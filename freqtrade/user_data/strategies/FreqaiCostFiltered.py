"""The model, with the cost filter the test plan ranks first.

Everything about risk and execution is copied from `BaselineTrend` on purpose:
same timeframe, same stop, same ROI ladder, same protections, same stake. The
order requires the two be compared under identical costs, sizes and execution
assumptions, so the only thing that differs is *who decides to enter* -- a
rule, or a gradient-boosted model.

**The cost filter, and why it is not an afterthought.** The test plan derives
`k = c/d`: a trade's cost measured in R is the cost fraction divided by the
stop distance. Read forward instead of backward, it says a prediction is only
worth acting on if the move it predicts exceeds the toll. Binance spot charges
0.1% a side, so the round trip is 0.2% of price before slippage. Entering on a
prediction of +0.1% is paying 0.2% for it, and no stop width, position size or
leverage can change that sign -- all three live in the denominator.

So the entry threshold is set at 0.3%, which is 1.5x the round trip. That is
not a tuned number; it is the smallest multiple that leaves anything over, and
it is fixed before the first backtest.

**What the arithmetic demands of this model.** Break-even needs
`p = (1 + toll/move) / 2`. With a 0.2% round trip and a measured median
one-hour move of 0.306% (175,380 windows, four markets), that is **82.6%
directional accuracy**. This project has measured 50.0%. The model is not
expected to clear that bar on this timeframe, and running it is how that
becomes a recorded result instead of an opinion.

**Known limitation that the order asks to be named.** FreqAI has no purging
and no embargo -- checked, not assumed: the only `purge` in its source deletes
old model files. Labels are built with `.shift(-label_period_candles)`, so the
last `label_period_candles` rows of every training window have targets that
reach into the window being predicted. At 12 candles on 5m that is one hour of
overlap at each fold boundary. It inflates measured accuracy and cannot be
switched off from the configuration, which is why `freqtrade
lookahead-analysis` is part of the acceptance run and why its own
documentation's caveat about FreqAI applies here.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy
from pandas import DataFrame
from technical import qtpylib

#: Binance spot: 0.1% a side. The round trip before slippage.
ROUND_TRIP = 0.002

#: Minimum predicted move worth paying the toll for: 1.5x the round trip.
#: Fixed before measurement, so it is a rule and not a fitted parameter.
ENTRY_THRESHOLD = 1.5 * ROUND_TRIP

#: Exit when the model's view has fallen back to roughly the toll itself.
EXIT_THRESHOLD = 0.0

#: FreqAI sets `do_predict` to 1 when the point is inside the training
#: distribution and 0 (or -1 for outliers) when it is not. Acting on a
#: prediction the model itself flags as out-of-distribution is acting on
#: extrapolation.
IN_DISTRIBUTION = 1

ATR_PERIOD = 14
EMA_SLOW = 200


class FreqaiCostFiltered(IStrategy):
    INTERFACE_VERSION = 3

    can_short = False
    timeframe = "5m"

    #: Must cover the longest indicator any feature function builds. FreqAI
    #: expands `indicator_periods_candles` (max 50) across timeframes, and the
    #: 1h context multiplies the reach -- 200 candles of 5m is under a day,
    #: and the 1h features need 50 of those, which is why this is large.
    startup_candle_count: int = 800

    process_only_new_candles = True
    use_exit_signal = True

    #: Identical to BaselineTrend. Changing either here would turn the
    #: comparison into a comparison of risk settings.
    stoploss = -0.03
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

    plot_config = {
        "main_plot": {},
        "subplots": {
            "vorhersage": {"&-s_close": {"color": "steelblue"}},
            "do_predict": {"do_predict": {"color": "sienna"}},
        },
    }

    @property
    def protections_config(self) -> list[dict[str, Any]]:
        return self.protections

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        """Features expanded over every period, timeframe and shift.

        All price- and volume-derived, which is worth stating plainly: this
        project has already measured 35 such features ranking BTC's next
        5-10 hours at a rank correlation of 0.004. If a market is even weakly
        efficient, price-derived features should not predict price. These are
        here because the order asks for the standard FreqAI comparison, not
        because they are expected to carry information.
        """
        dataframe["%-rsi"] = ta.RSI(dataframe, timeperiod=period)
        dataframe["%-mfi"] = ta.MFI(dataframe, timeperiod=period)
        dataframe["%-adx"] = ta.ADX(dataframe, timeperiod=period)
        dataframe["%-cci"] = ta.CCI(dataframe, timeperiod=period)
        dataframe["%-roc"] = ta.ROC(dataframe, timeperiod=period)

        # Distance to a moving average, in price fractions rather than price:
        # an absolute distance is not comparable between BTC and SOL, and a
        # model trained on one scale would read the other as extreme.
        ema = ta.EMA(dataframe, timeperiod=period)
        dataframe["%-ema_distance"] = (dataframe["close"] - ema) / dataframe["close"]

        bollinger = qtpylib.bollinger_bands(
            qtpylib.typical_price(dataframe), window=period, stds=2.2
        )
        dataframe["%-bb_width"] = (bollinger["upper"] - bollinger["lower"]) / bollinger["mid"]
        dataframe["%-close_bb_lower"] = dataframe["close"] / bollinger["lower"]

        # Volatility as a fraction of price, for the same comparability reason.
        dataframe["%-atr_fraction"] = ta.ATR(dataframe, timeperiod=period) / dataframe["close"]

        # Volume relative to its own recent level. Raw volume is not
        # comparable across markets or across years.
        dataframe["%-volume_relative"] = dataframe["volume"] / (
            dataframe["volume"].rolling(period).mean() + 1e-12
        )
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """Features expanded over timeframes and shifts but not periods."""
        dataframe["%-price_change"] = dataframe["close"].pct_change()
        dataframe["%-volume_change"] = dataframe["volume"].pct_change()
        dataframe["%-candle_body"] = (dataframe["close"] - dataframe["open"]) / dataframe["close"]
        dataframe["%-candle_range"] = (dataframe["high"] - dataframe["low"]) / dataframe["close"]

        # Where the close sat inside the candle's own range: 1 is a close at
        # the high, 0 at the low. Undefined on a doji, hence the guard.
        span = dataframe["high"] - dataframe["low"]
        dataframe["%-close_position"] = np.where(
            span > 0, (dataframe["close"] - dataframe["low"]) / span, 0.5
        )
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        """Called once on the base timeframe, after everything else.

        Calendar features belong here rather than in the expanding functions:
        the hour of the day does not have a 10-, 20- and 50-period version,
        and expanding it would add correlated copies of one number.

        Encoded as sine and cosine so that hour 23 is adjacent to hour 0. A
        raw hour column tells a tree that 23 and 0 are maximally far apart,
        which is false and costs splits.
        """
        hour = dataframe["date"].dt.hour
        dataframe["%-hour_sin"] = np.sin(2 * np.pi * hour / 24)
        dataframe["%-hour_cos"] = np.cos(2 * np.pi * hour / 24)
        dataframe["%-day_of_week"] = dataframe["date"].dt.dayofweek / 6.0
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        """Mean return over the next `label_period_candles`, as a fraction.

        The mean of the window rather than its endpoint, which is the FreqAI
        convention: an endpoint target rewards the model for calling one
        candle exactly, and that single candle is mostly noise. The mean is
        also what a position held across the window actually experiences.

        This is the line that creates the overlap documented in the module
        docstring -- `shift(-n)` is future information, legitimate in a label
        and illegitimate in a feature. There is no `shift(-n)` in any of the
        feature functions above.
        """
        horizon = int(self.freqai_info["feature_parameters"]["label_period_candles"])
        dataframe["&-s_close"] = (
            dataframe["close"].shift(-horizon).rolling(horizon).mean() / dataframe["close"] - 1.0
        )
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Features are built by the feature_engineering_* functions above;
        # FreqAI assembles, trains and predicts here.
        dataframe = self.freqai.start(dataframe, metadata, self)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=ATR_PERIOD)
        dataframe["ema_slow"] = ta.EMA(dataframe, timeperiod=EMA_SLOW)
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["do_predict"] == IN_DISTRIBUTION)
            & (dataframe["&-s_close"] > ENTRY_THRESHOLD)
            & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "modell_ueber_maut")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe.loc[
            (dataframe["&-s_close"] < EXIT_THRESHOLD) & (dataframe["volume"] > 0),
            ["exit_long", "exit_tag"],
        ] = (1, "modell_gedreht")
        return dataframe
