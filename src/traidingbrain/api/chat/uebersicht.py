"""Marktuebersicht des Chats: alle beobachteten Maerkte nebeneinander.

Nur lesend und nur fuer den Sprecher -- das Urteil (`pruefe`) liest sie nicht.
Wie im Lagebild wird jede ausgefallene Quelle `None` und steht in `quellen`
als `"unbekannt: <Grund>"`; ein Ersatzwert kommt nie hinein. Die Quellen laufen
parallel unter einem gemeinsamen Zeitlimit, denn der Marktscore braucht kalt
rund 17 s je Markt; was bis dahin nicht fertig ist, heisst "nicht rechtzeitig
berechnet". Ein vollstaendiger Lauf bleibt 60 s im Zwischenspeicher.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from traidingbrain.api import terminal
from traidingbrain.api.chat.lagebild import _grund, _journal_zeilen, _markt_standard
from traidingbrain.api.chat.modelle import MarktZeile, Setup
from traidingbrain.api.chat.pruefung import _ALLE_EBENEN

#: Wie viele der letzten Journal-Trades je Markt in die Uebersicht gehen.
_LETZTE_TRADES = 3

#: So lange gilt ein vollstaendiger Lauf.
SPEICHER_S = 60.0

_ZU_SPAET = "unbekannt: nicht rechtzeitig berechnet"

#: Marktscore-Richtung -> Seite; alles andere ist neutral.
_RICHTUNG = {"aufwärts": "long", "abwärts": "short"}

#: Schluessel: Tupel der Symbole; Wert: (Zeitpunkt, Zeilen).
_ZWISCHENSPEICHER: dict[tuple[str, ...], tuple[float, list[MarktZeile]]] = {}
_SPERRE = threading.Lock()


def _kopf_standard(symbol: str) -> Any:
    return terminal.kopf(symbol)  # erst beim Aufruf nachgeschlagen


def _score_standard(services: Any, symbol: str) -> dict:
    # Der schnelle Marktscore, nicht `terminal_score` (kalt ~17 s mehr je Markt).
    from traidingbrain.api.app import _score_read_dict  # spaet, gegen Zirkel

    return _score_read_dict(services, symbol)


@dataclass
class UebersichtHoler:
    """Die Quellen der Uebersicht; Standard sind die echten Funktionen, Tests reichen Attrappen."""

    kopf: Callable[[str], Any] = _kopf_standard
    score: Callable[[Any, str], dict] = _score_standard
    markt: Callable[[Any, str, str], Any] = _markt_standard


def _auftraege(
    services: Any, symbole: tuple[str, ...], ebenen: list[str], h: UebersichtHoler
) -> list[tuple[str, str, Callable[[], Any]]]:
    """(Symbol, Quelle, Aufruf); die Umrechnung laeuft mit, damit auch sie ausfallen darf.

    Reihenfolge: schnelle Quellen zuerst, der Score zuletzt -- so fuellt ein
    kalter Score nicht die Arbeiter, waehrend Kurse und Setups warten.
    """

    def kurs(s: str) -> tuple[float, float]:
        k = h.kopf(s)
        return float(k.last), float(k.change_pct)

    def setups(s: str, tf: str) -> list[Setup]:
        return [
            Setup(timeframe=tf, side=x.side, entry=x.entry, stop=x.stop, target=x.target)
            for x in h.markt(services, s, tf).setups
        ]

    def journal(s: str) -> list[dict]:
        return _journal_zeilen(services, s)[:_LETZTE_TRADES]

    def score(s: str) -> tuple[str, int, str]:
        d = h.score(services, s)
        return _RICHTUNG.get(d["direction"], "neutral"), int(d["rating"]), str(d["regime"])

    raus: list[tuple[str, str, Callable[[], Any]]] = []
    raus += [(s, "kurs", lambda s=s: kurs(s)) for s in symbole]
    raus += [
        (s, f"setups:{tf}", lambda s=s, tf=tf: setups(s, tf)) for s in symbole for tf in ebenen
    ]
    raus += [(s, "journal", lambda s=s: journal(s)) for s in symbole]
    raus += [(s, "score", lambda s=s: score(s)) for s in symbole]
    return raus


def _zeile(
    symbol: str, ebenen: list[str], ergebnis: dict[tuple[str, str], tuple[bool, Any]]
) -> MarktZeile:
    """Eine Zeile aus den Ergebnissen; (False, Grund) heisst ausgefallen."""
    quellen: dict[str, str] = {}

    def wert(quelle: str) -> Any:
        ok, w = ergebnis[(symbol, quelle)]
        if ok:
            return w
        quellen[quelle] = w
        return None

    kurs = wert("kurs")
    score = wert("score")

    # Setups: dieselbe Regel wie im Lagebild -- fehlt eine Ebene, teilweise
    # unbekannt; fehlen alle, unbekannt.
    setups: list[Setup] = []
    ausgefallen: list[str] = []
    for tf in ebenen:
        ok, w = ergebnis[(symbol, f"setups:{tf}")]
        if ok:
            setups += w
        else:
            ausgefallen.append(f"{tf} ({w.replace('unbekannt: ', '')})")
    alle_ausgefallen = bool(ebenen) and len(ausgefallen) == len(ebenen)
    if ausgefallen:
        kopf = "unbekannt: " if alle_ausgefallen else "teilweise unbekannt: "
        quellen["setups"] = kopf + "; ".join(ausgefallen)

    trades = wert("journal")
    return MarktZeile(
        symbol=symbol,
        preis=kurs[0] if kurs else None,
        veraenderung_pct=kurs[1] if kurs else None,
        richtung=score[0] if score else None,
        rating=score[1] if score else None,
        regime=score[2] if score else None,
        setups=None if alle_ausgefallen else setups,
        letzte_trades=trades if trades is not None else [],
        quellen=quellen,
    )


def baue_uebersicht(
    services: Any,
    *,
    holer: UebersichtHoler | None = None,
    zeitlimit_s: float = 45.0,
    jetzt: Callable[[], float] = time.monotonic,
) -> list[MarktZeile]:
    """Eine Zeile je beobachtetem Markt, in der Reihenfolge der Konfiguration."""
    from traidingbrain.api.app import _followed_symbols  # spaet, gegen Zirkel

    symbole = tuple(_followed_symbols(services))
    with _SPERRE:
        gespeichert = _ZWISCHENSPEICHER.get(symbole)
        if gespeichert is not None and jetzt() - gespeichert[0] < SPEICHER_S:
            return list(gespeichert[1])

    h = holer or UebersichtHoler()
    zeitebenen = services.config.engine.setups.timeframes
    ebenen = _ALLE_EBENEN if zeitebenen is None else [t.value for t in zeitebenen]

    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="uebersicht")
    try:
        laeufe = {pool.submit(f): (s, q) for s, q, f in _auftraege(services, symbole, ebenen, h)}
        fertig, _ = wait(laeufe, timeout=zeitlimit_s)
    finally:
        # Nicht warten: was noch laeuft, laeuft im Hintergrund zu Ende, der Rest entfaellt.
        pool.shutdown(wait=False, cancel_futures=True)

    ergebnis: dict[tuple[str, str], tuple[bool, Any]] = {}
    zu_spaet = False
    for lauf, schluessel in laeufe.items():
        if lauf not in fertig:
            ergebnis[schluessel] = (False, _ZU_SPAET)
            zu_spaet = True
        elif (fehler := lauf.exception()) is not None:
            ergebnis[schluessel] = (False, _grund(fehler))
        else:
            ergebnis[schluessel] = (True, lauf.result())

    zeilen = [_zeile(s, ebenen, ergebnis) for s in symbole]
    # Ein Lauf mit Zeitueberschreitung wird nicht gespeichert, sonst stuenden
    # seine "nicht rechtzeitig"-Zeilen eine Minute lang.
    if not zu_spaet:
        with _SPERRE:
            _ZWISCHENSPEICHER[symbole] = (jetzt(), zeilen)
    return list(zeilen)
