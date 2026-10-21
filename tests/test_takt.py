"""Takt-Balken (E24): der Erzeuger und die Schlusszeit im Motor.

Zwei Dinge werden hier eingefroren.

**Der Erzeuger buendelt richtig.** Jeder Balken traegt mindestens die Schwelle,
seine Hoch/Tief/Schluss sind die der Minuten, aus denen er besteht, und seine
`close_ts` ist die Schlusszeit seiner letzten Minute. Der angefangene Rest am
Ende wird verworfen.

**Die Pipeline liest `close_ts`, wenn es da ist.** Ein Takt-Rahmen mit
ungleich langen Balken richtet die Kontextebenen an der ECHTEN Schlusszeit
aus, nicht an `ts + timeframe_ms`. Ohne die Spalte bleibt alles beim Alten --
das friert `tests/test_backtest.py` mit dem goldenen Lauf ein, hier wird nur
der Zweig mit Spalte geprueft.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from traidingbrain.analysis.pipeline import close_times, index_at_or_before
from traidingbrain.data.takt import (
    DOLLAR,
    HIERARCHIE,
    MINUTE_MS,
    VOLUMEN,
    takt_balken,
    takt_hierarchie,
)
from traidingbrain.domain.enums import Timeframe

EPOCH = 1_700_000_000_000


def _minuten(n: int, volumen: list[float] | None = None) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    close = 100.0 + np.cumsum(rng.normal(0, 0.1, n))
    vol = np.array(volumen, dtype="float64") if volumen is not None else rng.uniform(1, 3, n)
    return pd.DataFrame(
        {
            "ts": EPOCH + np.arange(n, dtype="int64") * MINUTE_MS,
            "open": np.r_[100.0, close[:-1]],
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": vol,
        }
    )


def test_every_bar_carries_at_least_the_threshold_and_the_remainder_is_dropped() -> None:
    m1 = _minuten(10, volumen=[1, 1, 1, 2, 0.5, 0.5, 3, 1, 1, 0.5])
    bars = takt_balken(m1, VOLUMEN.groesse(m1), schwelle=3.0)
    # Summen: 1,2,3 | 5,5.5,6 | 9 | 10,11,11.5 -> der letzte (2.5) ist unfertig
    assert bars["minutes"].tolist() == [3, 3, 1]
    assert (bars["volume"] >= 3.0).all()
    assert bars["ts"].tolist() == [EPOCH, EPOCH + 3 * MINUTE_MS, EPOCH + 6 * MINUTE_MS]
    assert bars["close_ts"].tolist() == [
        EPOCH + 3 * MINUTE_MS,
        EPOCH + 6 * MINUTE_MS,
        EPOCH + 7 * MINUTE_MS,
    ]


def test_ohlc_is_the_ohlc_of_the_minutes_inside() -> None:
    m1 = _minuten(60)
    bars = takt_balken(m1, VOLUMEN.groesse(m1), schwelle=7.0)
    assert len(bars) > 3
    for _, b in bars.iterrows():
        inside = m1[(m1["ts"] >= b["ts"]) & (m1["ts"] < b["close_ts"])]
        assert len(inside) == b["minutes"]
        assert b["open"] == inside["open"].iloc[0]
        assert b["close"] == inside["close"].iloc[-1]
        assert b["high"] == inside["high"].max()
        assert b["low"] == inside["low"].min()
        assert np.isclose(b["volume"], inside["volume"].sum())


def test_dollar_bars_weigh_volume_by_price() -> None:
    m1 = _minuten(30)
    groesse = DOLLAR.groesse(m1)
    assert np.allclose(groesse, m1["close"] * m1["volume"])


def test_the_hierarchy_has_fewer_bars_on_higher_frames() -> None:
    m1 = _minuten(5_000)
    frames = takt_hierarchie(m1, VOLUMEN, basis_schwelle=20.0)
    counts = [len(frames[tf]) for tf in HIERARCHIE]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > 0


def test_the_pipeline_aligns_on_the_stored_close_not_on_the_clock() -> None:
    # Zwei Balken: einer dauert 3 Minuten, einer 50. Nach der Uhr (M15) waere
    # der erste erst nach 15 Minuten "geschlossen", nach close_ts nach 3.
    frame = pd.DataFrame(
        {
            "ts": [EPOCH, EPOCH + 3 * MINUTE_MS],
            "open": [1.0, 1.0],
            "high": [1.0, 1.0],
            "low": [1.0, 1.0],
            "close": [1.0, 1.0],
            "volume": [1.0, 1.0],
            "close_ts": [EPOCH + 3 * MINUTE_MS, EPOCH + 53 * MINUTE_MS],
        }
    )
    assert close_times(frame, Timeframe.M15).tolist() == frame["close_ts"].tolist()
    assert index_at_or_before(frame, Timeframe.M15, EPOCH + 3 * MINUTE_MS) == 0
    assert index_at_or_before(frame, Timeframe.M15, EPOCH + 2 * MINUTE_MS) is None
    assert index_at_or_before(frame, Timeframe.M15, EPOCH + 52 * MINUTE_MS) == 0
    assert index_at_or_before(frame, Timeframe.M15, EPOCH + 53 * MINUTE_MS) == 1
    # Ohne die Spalte: die Uhr.
    plain = frame.drop(columns=["close_ts"])
    assert index_at_or_before(plain, Timeframe.M15, EPOCH + 3 * MINUTE_MS) is None
    assert index_at_or_before(plain, Timeframe.M15, EPOCH + 15 * MINUTE_MS) == 0
