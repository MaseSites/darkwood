"""Das Chart-Urteil im Schatten: Claude sieht das Bild, der Haendler handelt weiter.

Jedes Mal, wenn der Haendler eine Order einreicht, wird der Chart gezeichnet
(Signal-Zeitebene plus zwei hoehere, nur Kerzen bis zur Entscheidung, Einstieg,
Stop und Ziel eingezeichnet) und Claude gefragt, ob es den Trade nehmen wuerde.
Die Antwort wird aufgeschrieben und sonst NICHTS: sie blockiert keine Order,
aendert keine Groesse und steht nicht in der Signatur.

Warum so und nicht gleich als Veto: ein Bild enthaelt keine Kerze, die der
Haendler nicht schon als Zahl hat. Ob Claude darin trotzdem etwas sieht, das
die Regeln nicht sehen, ist eine Messfrage -- `scripts/vision_report.py`
stellt sie, sobald genug Trades geschlossen sind. Ein Veto vor dieser Messung
wuerde die Trades veraendern, an denen es gemessen werden muesste.

Drei Dinge, die den Haendler schuetzen:

* Zeichnen geschieht im Haupt-Thread (Millisekunden, und die Parquet-Dateien
  werden nur dort gelesen); der Aufruf an Claude in EINEM Hintergrund-Thread,
  weil er eine Minute dauern kann.
* Jeder Fehler wird als Zeile mit `fehler` aufgeschrieben und nie geworfen.
  Die Beobachtung darf den Handel nicht anhalten.
* Je Order genau ein Urteil, ueber die `proposal_id`. Eine Order, die einen
  Neustart ueberlebt, wird nicht ein zweites Mal gefragt.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from traidingbrain.brain.subscription import SubscriptionUnavailableError, _extract_json
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.domain.enums import Timeframe
from traidingbrain.vision.render import Linie, Panel, nur_bis, preisformat, zeichne

#: Die Zeitebenen im Bild, von fein nach grob. Die Signal-Ebene kommt immer dazu.
EBENEN: tuple[Timeframe, ...] = (Timeframe.M15, Timeframe.H1, Timeframe.H4)

#: Wer bei einem Fehler wie oft nachgefragt wird: einmal, wie im Chat.
VERSUCHE = 2

SYSTEM_PROMPT_DATEI = Path(__file__).with_name("system_prompt.md")

#: Die Frage, die Claude bekommt. Ein Aufruf -> (Antwort, Sitzung).
Fragen = Callable[[str, list[bytes]], tuple[str | None, str | None]]


class Urteil(BaseModel):
    """Was Claude liefern soll; unbekannte Felder werden ignoriert."""

    urteil: Literal["nehmen", "auslassen"]
    konfidenz: int = Field(ge=0, le=100)
    begruendung: str
    muster: list[str] = []

    @field_validator("muster", mode="before")
    @classmethod
    def _null_ist_leer(cls, v: object) -> object:
        return [] if v is None else v


@dataclass(frozen=True)
class Auftrag:
    """Eine eingereichte Order, gezeichnet und bereit fuer die Frage."""

    proposal_id: str
    symbol: str
    side: str
    setup: str
    timeframe: str
    entry: float
    stop: float
    target: float
    decided_ts: int
    run_signature: str
    png: bytes

    @property
    def reward_risk(self) -> float:
        risiko = abs(self.entry - self.stop)
        return abs(self.target - self.entry) / risiko if risiko else 0.0


class SchattenSpeicher:
    """Die Urteile, eine Zeile je Order. SQLite, neben dem Journal."""

    def __init__(self, pfad: Path) -> None:
        self.pfad = pfad
        pfad.parent.mkdir(parents=True, exist_ok=True)
        with self._verbinde() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS urteile (
                    proposal_id TEXT NOT NULL,
                    symbol TEXT, side TEXT, setup TEXT, timeframe TEXT,
                    entry REAL, stop REAL, target REAL,
                    decided_ts INTEGER, run_signature TEXT,
                    judged_ts INTEGER, modell TEXT,
                    urteil TEXT, konfidenz INTEGER, begruendung TEXT, muster TEXT,
                    fehler TEXT, bild TEXT,
                    PRIMARY KEY (proposal_id, run_signature)
                )"""
            )

    def _verbinde(self) -> sqlite3.Connection:
        return sqlite3.connect(self.pfad, timeout=10)

    def kennt(self, proposal_id: str, run_signature: str) -> bool:
        with self._verbinde() as db:
            zeile = db.execute(
                "SELECT 1 FROM urteile WHERE proposal_id = ? AND run_signature = ?",
                (proposal_id, run_signature),
            ).fetchone()
        return zeile is not None

    def schreibe(self, zeile: dict[str, Any]) -> None:
        spalten = ", ".join(zeile)
        platz = ", ".join("?" for _ in zeile)
        with self._verbinde() as db:
            db.execute(
                f"INSERT OR REPLACE INTO urteile ({spalten}) VALUES ({platz})",  # noqa: S608
                tuple(zeile.values()),
            )

    def alle(self) -> list[dict[str, Any]]:
        with self._verbinde() as db:
            db.row_factory = sqlite3.Row
            return [dict(z) for z in db.execute("SELECT * FROM urteile ORDER BY decided_ts")]


def frage_text(a: Auftrag) -> str:
    """Die Zahlen zum Bild; das Bild selbst geht als eigener Block."""
    return (
        f"Markt: {a.symbol}\n"
        f"Das Regelsystem will eroeffnen: {a.side.upper()} (Setup {a.setup or '?'}"
        f"{', ' + a.timeframe if a.timeframe else ''})\n"
        f"Einstieg {preisformat(a.entry)}, Stop {preisformat(a.stop)}, "
        f"Ziel {preisformat(a.target)} ({a.reward_risk:.2f}R)\n\n"
        "Das Bild zeigt nur Kerzen bis zur Entscheidung. Wuerdest du diesen Trade "
        "nach dem Chart nehmen? Antworte nur mit dem JSON-Objekt."
    )


def lies_urteil(roh: str) -> Urteil:
    return Urteil.model_validate_json(_extract_json(roh))


def zeichne_auftrag(
    *,
    lies: Callable[[Timeframe], Any],
    pending: Any,
    symbol: str,
    signal: Timeframe,
    run_signature: str,
) -> Auftrag:
    """Den Chart einer eingereichten Order zeichnen: nur Kerzen bis zur Entscheidung.

    `pending.created_ts` ist der Schluss der Signalkerze, also der Moment der
    Entscheidung. Alles danach bleibt aus dem Bild.
    """
    seite = getattr(pending.side, "value", str(pending.side))
    linien = [
        Linie(pending.limit_price, "Einstieg", "entry"),
        Linie(pending.stop, "Stop", "stop"),
        Linie(pending.target, "Ziel", "target"),
    ]
    ebenen = [signal, *(tf for tf in EBENEN if tf is not signal)]
    ebenen.sort(key=timeframe_ms)
    panels = [
        Panel(
            f"{symbol} {tf.value}",
            nur_bis(lies(tf), pending.created_ts, bar_ms=timeframe_ms(tf)),
            linien,
        )
        for tf in ebenen
    ]
    titel = (
        f"{symbol}  {seite.upper()}  Einstieg {preisformat(pending.limit_price)}  "
        f"Stop {preisformat(pending.stop)}  Ziel {preisformat(pending.target)}"
    )
    return Auftrag(
        proposal_id=pending.proposal_id,
        symbol=symbol,
        side=seite,
        setup=getattr(pending, "setup", "") or "",
        timeframe=getattr(pending, "timeframe", "") or "",
        entry=float(pending.limit_price),
        stop=float(pending.stop),
        target=float(pending.target),
        decided_ts=int(pending.created_ts),
        run_signature=run_signature,
        png=zeichne(panels, titel=titel),
    )


class Schatten:
    """Beobachtet die Haendler, zeichnet jede neue Order und laesst sie beurteilen."""

    def __init__(
        self,
        speicher: SchattenSpeicher,
        bilder: Path,
        fragen: Fragen,
        *,
        modell: str,
        im_hintergrund: bool = True,
        uhr: Callable[[], float] = time.time,
    ) -> None:
        self.speicher = speicher
        self.bilder = bilder
        self.fragen = fragen
        self.modell = modell
        self.uhr = uhr
        self._gesehen: set[tuple[str, str]] = set()
        self._warteschlange: queue.Queue[Auftrag] = queue.Queue()
        self._faden: threading.Thread | None = None
        if im_hintergrund:
            self._faden = threading.Thread(target=self._arbeite, name="vision-schatten", daemon=True)
            self._faden.start()

    # -- Haupt-Thread ------------------------------------------------------- #

    def beobachte(self, traders: Iterable[Any]) -> int:
        """Neue Orders zeichnen und einreihen; gibt zurueck, wie viele. Wirft nie."""
        neu = 0
        for trader in traders:
            try:
                pending = trader.broker.pending
                if pending is None or not pending.proposal_id:
                    continue
                schluessel = (pending.proposal_id, trader.run_signature)
                if schluessel in self._gesehen:
                    continue
                self._gesehen.add(schluessel)
                if self.speicher.kennt(*schluessel):
                    continue
                auftrag = zeichne_auftrag(
                    lies=lambda tf, t=trader: t.store.read(t.symbol, tf),
                    pending=pending,
                    symbol=trader.symbol,
                    signal=trader.config.engine.timeframes.signal,
                    run_signature=trader.run_signature,
                )
            except Exception as problem:  # noqa: BLE001 -- Beobachtung haelt den Handel nie an
                print(f"  [Chart-Urteil] {getattr(trader, 'symbol', '?')}: nicht gezeichnet: "
                      f"{type(problem).__name__}: {problem}", flush=True)
                continue
            if self._faden is None:
                self.beurteile(auftrag)
            else:
                self._warteschlange.put(auftrag)
            neu += 1
        return neu

    # -- Hintergrund -------------------------------------------------------- #

    def _arbeite(self) -> None:
        while True:
            auftrag = self._warteschlange.get()
            try:
                self.beurteile(auftrag)
            except Exception as problem:  # noqa: BLE001
                print(f"  [Chart-Urteil] {auftrag.symbol}: {problem}", flush=True)

    def beurteile(self, auftrag: Auftrag) -> dict[str, Any]:
        """Fragen, lesen, aufschreiben. Jeder Ausgang wird eine Zeile."""
        bild = self.bilder / f"{auftrag.proposal_id}.png"
        try:
            self.bilder.mkdir(parents=True, exist_ok=True)
            bild.write_bytes(auftrag.png)
            bild_pfad = str(bild)
        except OSError:
            bild_pfad = ""

        urteil: Urteil | None = None
        fehler = ""
        text = frage_text(auftrag)
        for versuch in range(VERSUCHE):
            try:
                roh, _sitzung = self.fragen(text, [auftrag.png])
            except SubscriptionUnavailableError as problem:
                fehler = f"Claude nicht erreichbar: {str(problem)[:200]}"
                break
            if roh is None:
                fehler = "Claude hat nicht geantwortet"
                break
            try:
                urteil = lies_urteil(roh)
                fehler = ""
                break
            except (ValidationError, ValueError) as problem:
                fehler = f"Antwort nicht lesbar: {str(problem)[:300]}"
                if versuch == 0:
                    text += (
                        f"\n\nDeine letzte Antwort war nicht lesbar:\n{roh[:1500]}\n\n"
                        f"Fehler: {str(problem)[:500]}\nNur das korrigierte JSON-Objekt."
                    )

        zeile = {
            "proposal_id": auftrag.proposal_id,
            "symbol": auftrag.symbol,
            "side": auftrag.side,
            "setup": auftrag.setup,
            "timeframe": auftrag.timeframe,
            "entry": auftrag.entry,
            "stop": auftrag.stop,
            "target": auftrag.target,
            "decided_ts": auftrag.decided_ts,
            "run_signature": auftrag.run_signature,
            "judged_ts": int(self.uhr() * 1000),
            "modell": self.modell,
            "urteil": urteil.urteil if urteil else None,
            "konfidenz": urteil.konfidenz if urteil else None,
            "begruendung": urteil.begruendung if urteil else None,
            "muster": ", ".join(urteil.muster) if urteil else None,
            "fehler": fehler or None,
            "bild": bild_pfad,
        }
        try:
            self.speicher.schreibe(zeile)
        except sqlite3.Error as problem:
            print(f"  [Chart-Urteil] {auftrag.symbol}: nicht gespeichert: {problem}", flush=True)
        if urteil is not None:
            print(
                f"  [{auftrag.symbol}] Chart-Urteil (Schatten, ohne Wirkung): "
                f"{urteil.urteil} {urteil.konfidenz}% -- {urteil.begruendung[:160]}",
                flush=True,
            )
        else:
            print(f"  [{auftrag.symbol}] Chart-Urteil fehlgeschlagen: {fehler}", flush=True)
        return zeile


def fuer_haendler(config: Any, *, name: str = "vision_shadow") -> Schatten:
    """Der Schatten, wie der Haendler ihn startet: ueber die angemeldete Claude-CLI.

    Ueber das Abo und nicht die API, wie der Chat: keine Rechnung je Aufruf, und
    bei ein paar Orders am Tag ist die Latenz der CLI gleichgueltig.
    """
    import shutil
    import tempfile
    from functools import partial

    from traidingbrain.brain.subscription import _cli_environment
    from traidingbrain.vision.frage import frage_mit_bild

    daten = config.engine.paths.data_dir
    modell = config.engine.brain.model
    fragen = partial(
        frage_mit_bild,
        executable=shutil.which("claude") or "claude",
        model=modell,
        system_file=str(SYSTEM_PROMPT_DATEI),
        workspace=tempfile.mkdtemp(prefix="darkwood-vision-"),
        env=_cli_environment(),
    )
    return Schatten(
        SchattenSpeicher(daten / f"{name}.sqlite"),
        daten / name,
        fragen,
        modell=modell,
    )
