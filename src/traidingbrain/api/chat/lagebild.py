"""Lagebild des Chats: was der Bot zu einem Markt gerade sieht.

Nur lesend. Jede Quelle, die ausfaellt, wird `None` und steht in `quellen` als
`"unbekannt: <Grund>"` -- nie ein Ersatzwert; die Regelpruefung zaehlt
`unbekannt` wie `verletzt`. Die Quellen sind dieselben Funktionen wie im
Terminal (Kopfzeile, Score, Marktansicht, Kalender), damit der Chat nichts
sieht, was die Oberflaeche nicht auch zeigt.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException

from traidingbrain.api.chat.konto import bot_positionen, manuelles_konto
from traidingbrain.api.chat.modelle import Lage, Setup
from traidingbrain.api.chat.pruefung import _ALLE_EBENEN
from traidingbrain.api.portfolio import build_ledger
from traidingbrain.api.terminal import (
    MANUELL_DB,
    Kalender,
    Kopf,
    Score,
    _lese_plan_yaml,
    kalender,
    kopf,
    terminal_score,
)
from traidingbrain.journal.record import Source

#: Wie viele der letzten Journal-Trades des Markts in den Kontext gehen.
_LETZTE_TRADES = 5


def _score_standard(services: Any, symbol: str) -> Score:
    from traidingbrain.api.app import _journal_path, _konto_signatur  # spaet, gegen Zirkel

    return terminal_score(services, symbol, _journal_path, _konto_signatur)


def _markt_standard(services: Any, symbol: str, timeframe: str) -> Any:
    from traidingbrain.api.app import _market_for  # spaet, gegen Zirkel

    return _market_for(services, symbol, timeframe)


@dataclass
class Holer:
    """Die Quellen des Lagebilds; Standard sind die echten Funktionen, Tests reichen Attrappen."""

    kopf: Callable[[str], Kopf] = kopf
    score: Callable[[Any, str], Score] = _score_standard
    markt: Callable[[Any, str, str], Any] = _markt_standard
    kalender: Callable[[], Kalender] = kalender


def _grund(fehler: Exception) -> str:
    text = fehler.detail if isinstance(fehler, HTTPException) else repr(fehler)
    return f"unbekannt: {text}"


def _journal_zeilen(services: Any, symbol: str) -> list[dict]:
    """Die letzten Trades des Markts aus dem Live-Journal; fehlt es, ist es leer."""
    from traidingbrain.api.app import _journal_path, _konto_signatur  # spaet, gegen Zirkel

    pfad = _journal_path(services)
    # `JournalStore` legt die Datei an, wenn sie fehlt -- hier wird nichts angelegt.
    if not pfad.exists():
        raise KeyError(f"kein Journal unter {pfad.name}")
    led = build_ledger(pfad, source=Source.LIVE, signature=_konto_signatur(services))
    eigene = [z for z in led.rows if z.symbol == symbol][:_LETZTE_TRADES]
    return [
        {
            "side": z.side,
            "setup": z.setup,
            "timeframe": z.setup_timeframe,
            "r_multiple": z.r_multiple,
            "net_pnl": z.net_pnl,
            "exit_reason": z.exit_reason,
            "closed_ts": z.closed_ts,
        }
        for z in eigene
    ]


def baue_lage(
    services: Any, symbol: str, timeframe: str, *, jetzt_ms: int, holer: Holer | None = None
) -> Lage:
    from traidingbrain.api.app import _followed_symbols, _state_path  # spaet, gegen Zirkel

    h = holer or Holer()
    quellen: dict[str, str] = {}
    kontext: dict = {}

    def hole(name: str, quelle: Callable[[], Any]) -> Any:
        try:
            return quelle()
        except (HTTPException, KeyError) as fehler:
            quellen[name] = _grund(fehler)
            return None

    k = hole("kurs", lambda: h.kopf(symbol))
    preis = float(k.last) if k is not None else None
    if k is not None:
        kontext["kopf"] = {"last": k.last, "mark": k.mark, "funding_rate": k.funding_rate}

    s = hole("bild", lambda: h.score(services, symbol))
    bild = s.direction if s is not None else None
    if s is not None:
        kontext["score"] = {
            "rating": s.rating,
            "band": s.band,
            "regime": s.regime,
            "headline": s.headline,
        }

    # Setups: Vereinigung ueber die Handelsebenen; eine Ebene ohne Ansicht wird
    # uebersprungen und vermerkt, fallen alle aus, ist die Antwort unbekannt.
    zeitebenen = services.config.engine.setups.timeframes
    ebenen = _ALLE_EBENEN if zeitebenen is None else [t.value for t in zeitebenen]
    setups: list[Setup] = []
    ausgefallen: list[str] = []
    for tf in ebenen:
        ansicht = hole(f"setups:{tf}", lambda tf=tf: h.markt(services, symbol, tf))
        if ansicht is None:
            ausgefallen.append(f"{tf} ({quellen.pop(f'setups:{tf}')})")
            continue
        setups += [
            Setup(timeframe=tf, side=x.side, entry=x.entry, stop=x.stop, target=x.target)
            for x in ansicht.setups
        ]
    if ausgefallen and len(ausgefallen) == len(ebenen):
        quellen["setups"] = "unbekannt: " + "; ".join(a.replace("unbekannt: ", "") for a in ausgefallen)
    elif ausgefallen:
        quellen["setups"] = "teilweise unbekannt: " + "; ".join(
            a.replace("unbekannt: ", "") for a in ausgefallen
        )
    alle_ausgefallen = bool(ebenen) and len(ausgefallen) == len(ebenen)

    kal = hole("kalender", h.kalender)
    kontext["kalender"] = (
        [
            {"country": e.country, "title": e.title, "impact": e.impact, "hours_away": e.hours_away}
            for e in kal.events
            if e.hours_away <= 24
        ]
        if kal is not None
        else None
    )

    try:
        kontext["plan"] = _lese_plan_yaml()
    except (OSError, ValueError) as fehler:
        quellen["plan"] = _grund(fehler)
        kontext["plan"] = None

    try:
        kontext["letzte_trades"] = _journal_zeilen(services, symbol)
    except (HTTPException, KeyError, OSError, sqlite3.Error) as fehler:
        quellen["journal"] = _grund(fehler)
        kontext["letzte_trades"] = None

    gefolgt = _followed_symbols(services)
    konto = manuelles_konto(
        MANUELL_DB,
        jetzt_ms=jetzt_ms,
        bot_positionen=bot_positionen(_state_path(services), gefolgt),
    )
    return Lage(
        symbol=symbol,
        timeframe=timeframe,
        preis=preis,
        bild=bild,
        setups=None if alle_ausgefallen else setups,
        folgt=symbol in gefolgt,
        konto=konto,
        quellen=quellen,
        kontext=kontext,
    )
