"""Kontostand des manuellen Papierkontos, gebaut aus `data/manual_paper.sqlite`.

Die festen Regeln des Chats pruefen einen Vorschlag gegen einen `AccountState`.
Fuer das manuelle Konto gibt es keinen gespeicherten Stand -- er ergibt sich aus
Start plus den geschlossenen Zeilen, und das hier ist die einzige Stelle, die
das ausrechnet. Nur lesend: die Datenbank wird nie beschrieben.
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from traidingbrain.domain.enums import Side, TradeState
from traidingbrain.domain.proposal import ClosedTrade, Position
from traidingbrain.live.paperstate import _load_position
from traidingbrain.risk.limits import AccountState

#: Startkapital des manuellen Papierkontos in USD. Die Zahl steht nur hier.
MANUELL_START = 1000.0


def _geschlossene(con: sqlite3.Connection) -> list[ClosedTrade]:
    zeilen = con.execute(
        "SELECT * FROM positions WHERE status='closed' ORDER BY closed_ts").fetchall()
    raus: list[ClosedTrade] = []
    for r in zeilen:
        pnl = float(r["pnl"] or 0.0)
        fees = float(r["fees"] or 0.0)
        # Risiko wie in api/terminal.py:_manuell_geschlossen -- Abstand zum Stop,
        # ohne Stop die eingesetzte Marge.
        risiko = abs(float(r["entry"]) - float(r["sl"])) * float(r["qty"]) if r["sl"] else float(r["margin"])
        raus.append(ClosedTrade(
            proposal_id=str(r["id"]), symbol=r["symbol"], side=Side(r["side"]),
            state=TradeState.CLOSED_MANUAL,
            entry_price=float(r["entry"]), exit_price=float(r["exit"]), qty=float(r["qty"]),
            opened_ts=int(r["opened_ts"]), closed_ts=int(r["closed_ts"]),
            gross_pnl=pnl + fees, fees=fees, funding=0.0, net_pnl=pnl,
            r_multiple=round(pnl / risiko, 4) if risiko else 0.0,
            snapshot_hash="manuell",
        ))
    return raus


def _offene(con: sqlite3.Connection) -> list[Position]:
    zeilen = con.execute("SELECT * FROM positions WHERE status='open' ORDER BY opened_ts").fetchall()
    return [
        Position(
            symbol=r["symbol"], side=Side(r["side"]), qty=float(r["qty"]),
            entry_price=float(r["entry"]), leverage=float(r["leverage"]),
            liquidation_price=float(r["entry"]), opened_ts=int(r["opened_ts"]),
        )
        for r in zeilen
    ]


def manuelles_konto(db: Path, *, jetzt_ms: int, bot_positionen: list[tuple[str, str]]) -> AccountState:
    """Stand des manuellen Kontos. Fehlt die Datei, ist es das Startkapital."""
    historie: list[ClosedTrade] = []
    offen: list[Position] = []
    if db.exists():
        with closing(sqlite3.connect(db, timeout=10)) as con:
            con.row_factory = sqlite3.Row
            historie = _geschlossene(con)
            offen = _offene(con)
    # Die Bot-Positionen zaehlen fuer Limits wie max. gleichzeitige Positionen
    # und gleiche Richtung mit; Menge und Preis kennt dieses Konto nicht.
    jetzt_offen = offen + [
        Position(symbol=s, side=Side(seite), qty=1.0, entry_price=1.0, leverage=1.0,
                 liquidation_price=1.0, opened_ts=jetzt_ms)
        for s, seite in bot_positionen
    ]
    return AccountState.from_history(
        equity=MANUELL_START + sum(t.net_pnl for t in historie),
        history=historie, now_ms=jetzt_ms, open_positions=jetzt_offen,
    )


def bot_positionen(state_path: Path, symbole: list[str]) -> list[tuple[str, str]]:
    """`(symbol, side)` der offenen Positionen des Bots, aus dem Paper-Zustand.

    Nur lesend und ohne `PaperStateStore`: dessen Konstruktor legt Tabellen an,
    schaltet WAL und migriert Spalten -- ein Schreibzugriff auf die Datenbank
    des laufenden Traders. Fehlt Datei oder Tabelle, gibt es keine Positionen;
    jeder andere Fehler (gesperrt, kaputt) wird nicht verschluckt.
    """
    if not state_path.exists():
        return []
    raus: list[tuple[str, str]] = []
    with closing(sqlite3.connect(f"file:{state_path.as_posix()}?mode=ro", uri=True, timeout=10)) as con:
        for s in symbole:
            try:
                zeile = con.execute("SELECT position FROM accounts WHERE symbol = ?", (s,)).fetchone()
            except sqlite3.OperationalError as fehler:
                if "no such table" in str(fehler):
                    return []
                raise
            position = _load_position(zeile[0]) if zeile else None
            if position is not None:
                raus.append((s, position.side.value))
    return raus
