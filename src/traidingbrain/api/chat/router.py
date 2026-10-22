"""Endpunkte des Chats unter `/api/terminal/chat`.

Das Urteil einer Karte kommt allein aus `pruefe`; was Claude dazu schreibt,
erreicht es nie. Der einzige Weg zu einer (Papier-)Order ist `ausfuehren`:
nur fuer eine angenommene Karte, nur einmal, und erst nach einer Neupruefung
mit frischem Lagebild. Bot-Dateien werden nur gelesen; geschrieben wird
`chat.sqlite` und, ueber `order_oeffnen`, `manual_paper.sqlite`.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from traidingbrain.api import terminal
from traidingbrain.api.terminal import OrderWunsch
from traidingbrain.api.chat.lagebild import Holer, LageNichtVerfuegbar, baue_lage
from traidingbrain.api.chat.modelle import Lage, Regelwerte, Urteil, Vorschlag
from traidingbrain.api.chat.pruefung import pruefe, regelwerte_aus
from traidingbrain.api.chat.speicher import ChatSpeicher
from traidingbrain.api.chat.sprecher import VERLAUF_ZEILEN, ClaudeSprecher, Sprecher
from traidingbrain.risk.limits import RiskLimits

#: So viele Nachrichten liefert `/verlauf`.
VERLAUF_ANZEIGE = 50

#: `pruefe` liest die Zeitebene der Lage nicht; beim Ausfuehren und im Formular
#: steht hier nur ein Name, damit die Lage vollstaendig ist.
_ZEITEBENE_OHNE_ANGABE = "H4"

_PLAN_FEHLT = "config_offen/plan.yaml fehlt oder ist unvollstaendig"

#: Platzhalter, mit dem `ausfuehren` die Karte beansprucht, bevor die Order steht.
_ORDER_AUSSTEHEND = "ausstehend"

#: Gezeigte und frisch gepruefte Order gelten als gleich bis auf diese Abstaende.
_REL_TOLERANZ = 1e-9
_MARGIN_TOLERANZ_USD = 0.01

_GEAENDERT = "Vorschlag hat sich geaendert - bitte neu pruefen"


class NachrichtAnfrage(BaseModel):
    text: str = Field(min_length=1)
    symbol: str
    timeframe: str


class PruefAnfrage(Vorschlag):
    """Formular-Modus: ein Vorschlag ohne Claude."""

    timeframe: str = _ZEITEBENE_OHNE_ANGABE


def _karte_json(karte_id: str, karte: dict) -> dict:
    return {
        "id": karte_id,
        "vorschlag": karte["vorschlag"].model_dump(mode="json"),
        "urteil": karte["urteil"].model_dump(mode="json"),
        "preis": karte["preis"],
        "laeuft_ab_ts": karte["laeuft_ab_ts"],
        "ausgefuehrt_ts": karte["ausgefuehrt_ts"],
        "order_id": karte["order_id"],
    }


def _grund(urteil: Urteil) -> str:
    """Die erste Regel, die nicht erfuellt ist, mit ihrem Wert."""
    r = next(r for r in urteil.regeln if r.status != "erfuellt")
    return f"{r.name}: {r.wert}"


def _gleich(a: float | None, b: float | None) -> bool:
    """None nur gleich None; Zahlen gleich bis auf 1e-9 relativ."""
    if a is None or b is None:
        return a is b
    return math.isclose(a, b, rel_tol=_REL_TOLERANZ, abs_tol=0.0)


def _geaenderte_felder(gezeigt: OrderWunsch, neu: OrderWunsch) -> list[str]:
    """Worin die frisch gepruefte Order von der gezeigten abweicht.

    Kam der Stop vom Setup oder die Margin aus dem Plan, kann die Neupruefung
    andere Werte liefern (etwa nach einem H1/H4-Schluss) -- dann waere die
    Order nicht mehr die Karte, die der Nutzer angeklickt hat.
    """
    felder = [
        f for f in ("sl", "tp", "leverage") if not _gleich(getattr(gezeigt, f), getattr(neu, f))
    ]
    if abs(gezeigt.margin_usd - neu.margin_usd) > _MARGIN_TOLERANZ_USD:
        felder.append("margin_usd")
    if (gezeigt.symbol, gezeigt.side) != (neu.symbol, neu.side):
        felder.append("symbol/side")
    return felder


def _order_id_setzen(speicher: ChatSpeicher, karte_id: str, order_id: str) -> None:
    """Traegt die Order-ID nach; die Karte ist zu diesem Zeitpunkt schon beansprucht.

    `ChatSpeicher` kennt nur das einmalige `als_ausgefuehrt` -- das Nachtragen
    gehoert spaeter als eigene Methode dorthin.
    """
    with speicher._db() as db:
        db.execute("UPDATE karten SET order_id = ? WHERE id = ?", (order_id, karte_id))


def router(
    services: Any,
    *,
    sprecher: Sprecher | None = None,
    speicher: ChatSpeicher | None = None,
    holer: Holer | None = None,
    jetzt: Callable[[], float] = time.time,
) -> APIRouter:
    """Die fuenf Endpunkte der Spec (Abschnitt 7).

    Sprecher und Speicher entstehen erst beim ersten Aufruf: das Einhaengen in
    `create_app` soll weder eine Datei anlegen noch die CLI suchen.
    """
    r = APIRouter(prefix="/api/terminal/chat", tags=["chat"])
    sperre = threading.Lock()  # eine Nachricht an Claude zur Zeit
    aufbau = threading.Lock()
    geteilt: dict[str, Any] = {"sprecher": sprecher, "speicher": speicher}

    def _sprecher() -> Any:
        with aufbau:
            if geteilt["sprecher"] is None:
                geteilt["sprecher"] = ClaudeSprecher()
            return geteilt["sprecher"]

    def _speicher() -> ChatSpeicher:
        with aufbau:
            if geteilt["speicher"] is None:
                geteilt["speicher"] = ChatSpeicher(
                    services.config.engine.paths.data_dir / "chat.sqlite"
                )
            return geteilt["speicher"]

    def _jetzt_ms() -> int:
        return int(jetzt() * 1000)

    def _werte() -> Regelwerte:
        try:
            return regelwerte_aus(services.config, terminal._lese_plan_yaml())
        except (KeyError, ValueError, TypeError, yaml.YAMLError):
            # fehlt, kein YAML, oder ein Wert wie `risk_cap_share: null` / "viel"
            raise HTTPException(503, _PLAN_FEHLT) from None

    def _limits() -> RiskLimits:
        return RiskLimits(services.config.risk.limits, getattr(services, "kill_switch", None))

    def _lage(symbol: str, timeframe: str, jetzt_ms: int) -> Lage:
        try:
            return baue_lage(services, symbol, timeframe, jetzt_ms=jetzt_ms, holer=holer)
        except LageNichtVerfuegbar as fehler:
            raise HTTPException(503, str(fehler)) from fehler

    def _karte(v: Vorschlag, lage: Lage, werte: Regelwerte, ts: int) -> dict:
        """Pruefen und als Karte ablegen -- angenommen oder abgelehnt."""
        urteil = pruefe(v, lage, werte, _limits())
        ttl = services.config.risk.execution.proposal_ttl_seconds
        karte_id = _speicher().karte_anlegen(v, urteil, ts=ts, ttl_s=ttl)
        return {
            "id": karte_id,
            "vorschlag": v.model_dump(mode="json"),
            "urteil": urteil.model_dump(mode="json"),
            "laeuft_ab_ts": ts + ttl * 1000,
        }

    @r.post("/nachricht")
    def _nachricht(a: NachrichtAnfrage) -> dict:
        if not sperre.acquire(blocking=False):
            raise HTTPException(409, "Claude antwortet noch")
        try:
            ts = _jetzt_ms()
            symbol = Vorschlag(symbol=a.symbol, side="long").symbol  # gleich normalisiert
            werte = _werte()
            lage = _lage(symbol, a.timeframe, ts)
            sp = _speicher()
            verlauf = [(z["rolle"], z["text"]) for z in sp.verlauf(VERLAUF_ZEILEN)]
            sp.nachricht("nutzer", a.text, ts=ts)
            # Ab hier steht die Nutzerzeile: jeder Fehler bekommt eine Bot-Zeile,
            # damit keine Frage unbeantwortet im Verlauf bleibt.
            try:
                antwort = _sprecher().sprich(a.text, lage, verlauf)
            except Exception as fehler:  # Anmeldefehler faengt der Sprecher selbst ab
                grund = f"{type(fehler).__name__}: {fehler}"[:300]
                sp.nachricht("bot", f"Konnte nicht antworten: {grund}", ts=_jetzt_ms())
                return {"antwort": "", "bedenken": [], "karte": None, "fehler": grund}
            karte = None
            if antwort.vorschlag is not None:
                v = antwort.vorschlag
                # Ein Vorschlag fuer einen anderen Markt bekommt dessen Lage.
                try:
                    lage_v = lage if v.symbol == lage.symbol else _lage(v.symbol, a.timeframe, ts)
                except HTTPException as fehler:
                    sp.nachricht("bot", f"Konnte nicht antworten: {fehler.detail}", ts=_jetzt_ms())
                    raise
                karte = _karte(v, lage_v, werte, ts)
            sp.nachricht(
                "bot",
                antwort.text or antwort.fehler or "",
                ts=_jetzt_ms(),
                karte_id=karte["id"] if karte else None,
            )
            return {
                "antwort": antwort.text,
                "bedenken": antwort.bedenken,
                "karte": karte,
                "fehler": antwort.fehler,
            }
        finally:
            sperre.release()

    @r.post("/pruefen")
    def _pruefen(a: PruefAnfrage) -> dict:
        """Formular-Modus: dieselbe Pruefung, Claude wird nie gefragt."""
        ts = _jetzt_ms()
        werte = _werte()
        v = Vorschlag.model_validate(a.model_dump(exclude={"timeframe"}))
        karte = _karte(v, _lage(v.symbol, a.timeframe, ts), werte, ts)
        return {"antwort": "", "bedenken": [], "karte": karte, "fehler": None}

    @r.post("/ausfuehren/{karte_id}")
    def _ausfuehren(karte_id: str) -> dict:
        """Die einzige Stelle, die eine Order aufgibt -- hoechstens eine je Karte.

        Reihenfolge: 404 unbekannt, 409 schon ausgefuehrt, 410 abgelaufen, 409
        abgelehnt; dann Lage neu und `pruefe` neu, die neue Order muss der Order
        der Karte gleichen (sl, tp, Hebel; Margin bis 0.01 USD), Kursdrift gegen
        den Kurs der Karte. Aufgegeben wird die gespeicherte Order -- die, die der
        Nutzer gesehen hat. Erst danach wird die Karte atomar beansprucht (`als_ausgefuehrt`)
        und ERST DANN `order_oeffnen` gerufen -- so kann auch ein Doppelklick
        nur eine Order erzeugen. Scheitert die Order nach der Beanspruchung,
        bleibt die Karte markiert und es kommt 502: kein automatischer zweiter
        Versuch, denn ob die Order nicht doch geschrieben wurde, weiss hier niemand.
        """
        sp = _speicher()
        karte = sp.karte(karte_id)
        if karte is None:
            raise HTTPException(404, "Karte unbekannt")
        if karte["ausgefuehrt_ts"] is not None:
            raise HTTPException(409, "Karte wurde schon ausgefuehrt")
        ts = _jetzt_ms()
        if ts > karte["laeuft_ab_ts"]:
            raise HTTPException(410, "Karte ist abgelaufen")
        if not karte["urteil"].angenommen:
            raise HTTPException(409, "Karte war abgelehnt")

        v: Vorschlag = karte["vorschlag"]
        lage = _lage(v.symbol, _ZEITEBENE_OHNE_ANGABE, ts)
        urteil = pruefe(v, lage, _werte(), _limits())
        if not urteil.angenommen or urteil.order is None:
            return {"ausgefuehrt": False, "grund": _grund(urteil)}
        # Aufgegeben wird die Order der Karte, nicht die frisch berechnete -- also
        # nur, wenn beide (bis auf Rundung) dieselbe sind.
        gezeigt: OrderWunsch | None = karte["urteil"].order
        if gezeigt is None:
            return {"ausgefuehrt": False, "grund": _GEAENDERT, "felder": ["order"]}
        felder = _geaenderte_felder(gezeigt, urteil.order)
        if felder:
            return {"ausgefuehrt": False, "grund": _GEAENDERT, "felder": felder}

        alt, neu = karte["preis"], lage.preis
        if not alt or neu is None:
            return {"ausgefuehrt": False, "grund": "Kurs bei Pruefung unbekannt"}
        drift_bp = abs(neu - alt) / alt * 10_000
        if drift_bp > services.config.risk.execution.max_price_drift_bps:
            return {"ausgefuehrt": False, "grund": f"Kurs hat sich um {drift_bp:.1f} bp bewegt"}

        if not sp.als_ausgefuehrt(karte_id, _ORDER_AUSSTEHEND, ts=ts):
            raise HTTPException(409, "Karte wurde schon ausgefuehrt")
        try:
            order = terminal.order_oeffnen(gezeigt)
        except Exception as fehler:  # jeder Fehler: melden, nie wiederholen
            text = fehler.detail if isinstance(fehler, HTTPException) else str(fehler)
            _order_id_setzen(sp, karte_id, f"fehlgeschlagen: {text}"[:200])
            raise HTTPException(502, f"Order nicht aufgegeben: {text}") from fehler
        _order_id_setzen(sp, karte_id, order["id"])
        return {"ausgefuehrt": True, "order": order}

    @r.get("/verlauf")
    def _verlauf() -> list[dict]:
        sp = _speicher()
        raus = []
        for z in sp.verlauf(VERLAUF_ANZEIGE):
            karte = sp.karte(z["karte_id"]) if z["karte_id"] else None
            raus.append({**z, "karte": _karte_json(z["karte_id"], karte) if karte else None})
        return raus

    @r.get("/status")
    def _status() -> dict:
        s = _sprecher()
        return {"claude": s.status() if hasattr(s, "status") else "unbekannt"}

    return r
