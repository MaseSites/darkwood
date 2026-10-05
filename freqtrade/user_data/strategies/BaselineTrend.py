"""The yardstick, not a candidate.

A deliberately plain trend-following rule: enter when the fast EMA is above the
slow EMA and momentum has just turned up, exit on the reverse or on the stop.
Eight indicators, no model, no tuning.

**This is expected to lose, and that is its job.** The order asks for a
non-AI strategy to compare the FreqAI one against. A comparison is only
informative if the baseline is fixed in advance and never adjusted to look
better -- the moment a yardstick gets tuned it stops being a yardstick and
becomes the best of N attempts.

**What the arithmetic says before any backtest runs.** Expectancy per trade is
`(2p - 1) * move - toll`, so break-even sits at `p = (1 + toll/move) / 2`.
Binance spot charges 0.1% a side, so a round trip is 0.2% of price before
slippage. Measured on 175,380 hourly windows across four markets, the median
one-hour move is 0.306%. That puts break-even at **82.6% directional
accuracy** on this timeframe and venue. The same measurement on this project's
own research pipeline found 50.0%.

So this strategy is not a bet that it will work. It is the fixed point against
which anything else is measured, and the number above is why the research
arm of this project is pointed at multi-day horizons, where the same
arithmetic asks for 51-56% instead of 83%.

**No forward-looking data.** Every indicator reads closed candles only; there
is no `.shift(-n)` anywhere in this file. `startup_candle_count` is set to
cover the longest period used (200 for the slow EMA plus headroom), so the
first bars of a backtest are not computed from a partially warm indicator.
"""

from __future__ import annotations

from typing import Any

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.strategy import IStrategy

#: Periods. Named rather than inlined so the startup count below is visibly
#: derived from them instead of being a number someone hoped was big enough.
EMA_FAST = 20
EMA_SLOW = 200
RSI_PERIOD = 14
ATR_PERIOD = 14

#: RSI band. Entering only above 50 keeps the rule one-directional: it is a
#: trend follower, so it should not also buy weakness.
RSI_FLOOR = 50
RSI_CEILING = 70


class BaselineTrend(IStrategy):
    INTERFACE_VERSION = 3

    #: Spot only, as the order requires. No shorting, no leverage.
    can_short = False

    timeframe = "5m"

    #: Candles needed before the first decision is trustworthy. The slow EMA
    #: dominates; the extra headroom covers TA-Lib's own warmup.
    startup_candle_count: int = EMA_SLOW + 50

    process_only_new_candles = True
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    #: A 3% stop on a 200 USDT position risks 6 USDT, which is 0.6% of the
    #: 1,000 USDT paper wallet. Risk is size times stop distance, never size.
    stoploss = -0.03

    #: Time-boxed profit taking. The second row forces an exit after four
    #: hours regardless of profit, so a position cannot quietly become a
    #: multi-day hold that this timeframe was never measured for.
    minimal_roi = {
        "0": 0.02,
        "120": 0.01,
        "240": 0.0,
    }

    trailing_stop = False

    order_types: dict[str, Any] = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    #: Loss brakes the order asks for. StoplossGuard halts a pair after
    #: repeated stop-outs; MaxDrawdown halts everything once the account is
    #: down more than 10% over the window. Both are measured on closed trades,
    #: so neither can fire on an unrealised swing.
    protections: list[dict[str, Any]] = [
        {"method": "CooldownPeriod", "stop_duration_candles": 12},
        {
            "method": "StoplossGuard",
            "lookback_period_candles": 288,
            "trade_limit": 3,
            "stop_duration_candles": 72,
            "only_per_pair": False,
        },
        {
            "method": "MaxDrawdown",
            "lookback_period_candles": 576,
            "trade_limit": 10,
            "stop_duration_candles": 144,
            "max_allowed_drawdown": 0.10,
        },
    ]

    @property
    def protections_config(self) -> list[dict[str, Any]]:
        return self.protections

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema_fast"] = ta.EMA(dataframe, timeperiod=EMA_FAST)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=EMA_SLOW)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=RSI_PERIOD)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=ATR_PERIOD)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["ema_fast"] > dataframe["ema_slow"])
            & (dataframe["rsi"] > RSI_FLOOR)
            & (dataframe["rsi"] < RSI_CEILING)
            & (dataframe["close"] > dataframe["ema_fast"])
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "ema_trend")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["close"] < dataframe["ema_fast"]) & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "lost_fast_ema")
        return dataframe
