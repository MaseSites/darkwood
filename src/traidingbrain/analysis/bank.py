"""The bank: every registered indicator, computed, in the unit it declared.

The registry says what each indicator is and how much it may count. This
produces the numbers. The two are kept apart because they fail differently --
a wrong weight is an argument, a wrong formula is a bug -- and because a test
can then assert the one property that matters here: **every registered spec has
a function, and every function has a spec.** An indicator registered without a
calculation would be a silent hole in the score; a calculation without a
registration would be a reading with no family, no lag and no failure mode.

**What each function returns is the reading, not the raw indicator.** A moving
average's level carries no direction -- what carries direction is how far above
or below it price is, and that distance is returned in ATR so it means the same
thing on BTC and on XRP. A cumulative total's absolute value depends on where
the file starts, so its change over the lookback is returned as a share of the
volume that traded in it. The declared `output_unit` is a promise about the
number that comes out of here, and `normalise` is written to it.

This module knows nothing about weighting. It produces numbers; `score.registry`
decides what they are worth. Keeping the direction one-way means the analysis
layer never has to import the scoring layer.

Built lazily by the caller. Several of these recurse bar by bar, and a backtest
that never asks for the score should not pay for them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from traidingbrain.analysis import formulas as f
from traidingbrain.analysis.indicators import bollinger, ema, macd, rsi, sma

#: Bars over which a cumulative series' change is read. Matches the lookback
#: registered for `obv`; a test pins the two together so the declared warm-up
#: cannot drift away from the real one.
CUMULATIVE_WINDOW = 20


def _distance_in_atr(close: pd.Series, level: pd.Series, atr: pd.Series) -> pd.Series:
    """How far price is above (positive) or below a level, in ATR."""
    return f.safe_ratio(close - level, atr)


def _share_of_volume(cumulative: pd.Series, volume: pd.Series) -> pd.Series:
    """A cumulative total's change over the window, as a share of its volume.

    Turns a number whose level depends on where the file begins into one that
    does not: "over the last twenty bars, this fraction of the volume traded
    was net in one direction". Bounded by construction at ±1.
    """
    traded = volume.rolling(CUMULATIVE_WINDOW, min_periods=CUMULATIVE_WINDOW).sum()
    return f.safe_ratio(cumulative.diff(CUMULATIVE_WINDOW), traded)


def compute_bank(frame: pd.DataFrame, atr: pd.Series) -> dict[str, pd.Series]:
    """Every registered indicator over one frame, keyed by its registered name.

    `atr` is passed in rather than recomputed because it is the scale unit of
    the whole system and the frame's own analysis has already built it -- two
    ATRs with different periods would make the same distance two numbers.
    """
    close = frame["close"]
    volume = frame["volume"]
    bands = bollinger(close, 20, 2.0)
    movement = f.directional_movement(frame, 14)
    volume_average = sma(volume, 20)
    previous_day = f.previous_period_levels(frame)
    previous_week = f.previous_period_levels(frame, weekly=True)

    def position_in(levels: f.PeriodLevels) -> pd.Series:
        span = levels.high - levels.low
        return 2.0 * f.safe_ratio(close - levels.low, span) - 1.0

    readings: dict[str, pd.Series] = {
        # -- trend ---------------------------------------------------------- #
        "sma_50": _distance_in_atr(close, sma(close, 50), atr),
        "sma_200": _distance_in_atr(close, sma(close, 200), atr),
        "ema_21": _distance_in_atr(close, ema(close, 21), atr),
        "ema_55": _distance_in_atr(close, ema(close, 55), atr),
        "macd_hist": f.safe_ratio(macd(close).histogram, atr),
        "adx_14": movement.adx,
        "dmi_14": movement.plus_di - movement.minus_di,
        "supertrend_10": _distance_in_atr(close, f.supertrend(frame, atr, 10, 3.0), atr),
        "psar": _distance_in_atr(close, f.parabolic_sar(frame), atr),
        "aroon_25": f.aroon_oscillator(frame, 25),
        "vortex_14": f.vortex(frame, 14),
        "trix_15": f.trix(close, 15),
        "ppo": f.percentage_price_oscillator(close),
        "hma_21": _distance_in_atr(close, f.hull_moving_average(close, 21), atr),
        "kama_20": _distance_in_atr(close, f.kaufman_adaptive(close, 20), atr),
        # -- momentum ------------------------------------------------------- #
        "rsi_14": rsi(close, 14),
        "stoch_14": f.stochastic_k(frame, 14),
        "stochrsi_14": f.stochastic_rsi(close, 14),
        # Shifted off its native -100..0 so that 50 is the midpoint here as it
        # is for every other bounded reading.
        "willr_14": f.williams_r(frame, 14) + 100.0,
        "cci_20": f.commodity_channel_index(frame, 20),
        "roc_12": close.pct_change(12),
        "cmo_14": f.chande_momentum(close, 14),
        "fisher_9": f.fisher_transform(frame, 9),
        "ultimate_osc": f.ultimate_oscillator(frame),
        # -- volatility ----------------------------------------------------- #
        "atr_14": f.safe_ratio(atr, close),
        "bb_width_20": f.safe_ratio(bands.upper - bands.lower, bands.middle),
        "bb_position_20": 2.0 * bands.percent_b(close) - 1.0,
        "keltner_pos_20": f.keltner_position(frame, atr, 20, 2.0),
        "donchian_pos_20": f.donchian_position(frame, 20),
        "hist_vol_30": f.historical_volatility(close, 30),
        "choppiness_14": f.choppiness(frame, 14),
        # -- volume --------------------------------------------------------- #
        "rvol_20": f.safe_ratio(volume, volume_average),
        "obv": _share_of_volume(f.on_balance_volume(frame), volume),
        "cmf_20": f.chaikin_money_flow(frame, 20),
        "mfi_14": f.money_flow_index(frame, 14),
        # Force index is price change times volume, so it carries both scales.
        # Dividing by ATR and by typical volume leaves a pure "how hard", which
        # is then scaled against its own history like any unbounded reading.
        "force_index_13": f.safe_ratio(f.force_index(frame, 13), atr * volume_average),
        "accum_dist": f.accumulation_divergence(frame, 50),
        "vwap_session": _distance_in_atr(close, f.session_vwap(frame), atr),
        # -- location ------------------------------------------------------- #
        "range_position_20": f.close_range_position(close, 20),
        "prev_day_position": position_in(previous_day),
        "prev_week_position": position_in(previous_week),
        "pivot_position": _distance_in_atr(close, f.classic_pivot(frame), atr),
    }
    return {name: series.replace([np.inf, -np.inf], np.nan) for name, series in readings.items()}
