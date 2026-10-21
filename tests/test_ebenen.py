"""Die Ebenen-Aufzeichnung (E26): Definitionen mit festen Eingaben eingefroren."""

from __future__ import annotations

from pathlib import Path

from traidingbrain.data.calendar import MacroCalendar, ScheduledEvent
from traidingbrain.data.ebenen import (
    M15_MS,
    entscheidungszeit,
    kalender_abstand,
    oeffne,
    schreibe,
    strike_abstand,
)

T0 = 1_700_000_000_000


def test_decision_time_is_the_last_closed_quarter_hour() -> None:
    assert entscheidungszeit(T0) == (T0 // M15_MS) * M15_MS
    grenze = (T0 // M15_MS) * M15_MS
    assert entscheidungszeit(grenze + 20_000) == grenze
    assert entscheidungszeit(grenze + M15_MS) == grenze + M15_MS


def test_calendar_distance_per_impact_and_only_knowable_events() -> None:
    cal = MacroCalendar([
        ScheduledEvent("CPI", T0 + 90 * 60_000, "high", announced_ts=T0 - 1),
        ScheduledEvent("Speech", T0 + 30 * 60_000, "medium", announced_ts=T0 - 1),
        ScheduledEvent("Surprise", T0 + 10 * 60_000, "high", announced_ts=T0 + 1),  # noch unbekannt
        ScheduledEvent("Past", T0 - 5 * 60_000, "high", announced_ts=T0 - 1),
    ])
    k = kalender_abstand(cal, T0)
    assert k.min_high == 90
    assert k.min_medium == 30
    assert k.name == "Speech"


def test_calendar_without_events_in_horizon_is_null() -> None:
    cal = MacroCalendar([ScheduledEvent("Far", T0 + 30 * 86_400_000, "high", announced_ts=0)])
    k = kalender_abstand(cal, T0)
    assert k.min_high is None and k.min_medium is None and k.name is None


def test_nearest_big_strike_and_largest_strike() -> None:
    spot = 100.0
    strikes = [(95.0, 10.0), (101.0, 2.0), (110.0, 40.0), (120.0, 12.0)]
    s = strike_abstand(spot, strikes)
    # gross = oi >= 0.25 * 40 = 10 -> 95, 110, 120; naechster ist 95 (Abstand 5 < 10)
    assert s.naechst == 95.0 and s.abstand_pct == -5.0 and s.oi == 10.0
    assert s.max_strike == 110.0 and s.max_abstand_pct == 10.0 and s.max_oi == 40.0


def test_strike_without_data_is_null() -> None:
    s = strike_abstand(0.0, [(1.0, 1.0)])
    assert s.naechst is None
    s = strike_abstand(100.0, [])
    assert s.max_strike is None


def test_rows_are_unique_per_decision_and_symbol(tmp_path: Path) -> None:
    con = oeffne(tmp_path / "e.sqlite")
    zeile = {"ts": T0, "symbol": "BTCUSDT", "preis": 1.0, "geschrieben_utc": "x"}
    assert schreibe(con, zeile) is True
    assert schreibe(con, {**zeile, "preis": 2.0}) is False
    assert con.execute("SELECT preis FROM ebenen").fetchone()[0] == 1.0
