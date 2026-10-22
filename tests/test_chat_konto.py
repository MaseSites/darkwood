"""Kontostand des manuellen Papierkontos aus data/manual_paper.sqlite."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from traidingbrain.api.chat.konto import MANUELL_START, manuelles_konto

_SCHEMA = """CREATE TABLE IF NOT EXISTS positions (
        id TEXT PRIMARY KEY, symbol TEXT, side TEXT, qty REAL, entry REAL, leverage REAL,
        margin REAL, tp REAL, sl REAL, opened_ts INTEGER, status TEXT, exit REAL,
        closed_ts INTEGER, pnl REAL, fees REAL, reason TEXT, last_check_ts INTEGER)"""

JETZT = 1_800_000_000_000


def _db(tmp_path: Path, zeilen: list[tuple]) -> Path:
    pfad = tmp_path / "manual_paper.sqlite"
    with closing(sqlite3.connect(pfad)) as con:
        con.execute(_SCHEMA)
        con.executemany("INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", zeilen)
        con.commit()
    return pfad


def _zu(pid: str, pnl: float) -> tuple:
    return (pid, "BTCUSDT", "long", 0.01, 100.0, 5.0, 50.0, 110.0, 95.0,
            JETZT - 7_200_000, "closed", 101.0, JETZT - 3_600_000, pnl, 0.5, "tp", JETZT)


def _offen(pid: str, symbol: str, side: str) -> tuple:
    return (pid, symbol, side, 0.01, 100.0, 5.0, 50.0, None, None,
            JETZT - 60_000, "open", None, None, None, 0.1, None, JETZT)


def test_leeres_konto_steht_bei_1000(tmp_path):
    konto = manuelles_konto(_db(tmp_path, []), jetzt_ms=JETZT, bot_positionen=[])
    assert MANUELL_START == 1000.0
    assert konto.equity == 1000.0
    assert konto.open_positions == []


def test_geschlossene_pnl_zaehlt(tmp_path):
    db = _db(tmp_path, [_zu("a", 30.0), _zu("b", -12.5)])
    konto = manuelles_konto(db, jetzt_ms=JETZT, bot_positionen=[])
    assert konto.equity == 1017.5
    assert len(konto.recent_trades) == 2


def test_bot_positionen_zaehlen_mit(tmp_path):
    db = _db(tmp_path, [_offen("o", "BTCUSDT", "long")])
    konto = manuelles_konto(db, jetzt_ms=JETZT, bot_positionen=[("ETHUSDT", "short")])
    assert {(p.symbol, p.side.value) for p in konto.open_positions} == {
        ("BTCUSDT", "long"), ("ETHUSDT", "short")}


def test_bot_positionen_ohne_zustandsdatei_ist_leer(tmp_path):
    from traidingbrain.api.chat.konto import bot_positionen
    assert bot_positionen(tmp_path / "gibt_es_nicht.sqlite", ["BTCUSDT"]) == []


def test_bot_positionen_liest_echten_zustand_ohne_zu_schreiben(tmp_path):
    from traidingbrain.api.chat.konto import bot_positionen
    from traidingbrain.domain.enums import Side
    from traidingbrain.live.paperstate import PaperState, PaperStateStore
    from traidingbrain.sim.broker import OpenPosition

    pfad = tmp_path / "s.sqlite"
    speicher = PaperStateStore(pfad)
    short = OpenPosition(side=Side.SHORT, entry_price=100.0, qty=1.0, leverage=10.0,
                         stop=101.0, target=98.0, liq_price=109.0, opened_ts=1,
                         margin=10.0, risk_amount=1.0)
    speicher.save(PaperState(symbol="ETHUSDT", equity=1000.0, position=short))
    speicher.save(PaperState(symbol="BTCUSDT", equity=1000.0))
    vorher = (pfad.read_bytes(), pfad.stat().st_mtime_ns)

    assert bot_positionen(pfad, ["ETHUSDT", "BTCUSDT", "SOLUSDT"]) == [("ETHUSDT", "short")]
    assert (pfad.read_bytes(), pfad.stat().st_mtime_ns) == vorher
