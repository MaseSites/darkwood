"""Every indicator, with the fields that decide how much it may count.

Severin asked for fifty indicators running at once. This is the inventory, and
the shape of each entry comes from `TRADING_ANALYSE_GRUNDLAGEN.md` chapter 12.7,
which says what to store and why:

    "Das Gehirn speichert daher für jeden Indikator die universellen Felder
     input_series, venue, lookback, formula_version, output_unit, lag, family,
     failure_modes und source, statt Namen als eigenständige Wahrheiten zu
     behandeln."

That last clause is the design. A name is not a truth. `family` is what stops
six moving averages from voting six times, `lag` is what stops a slow indicator
from being read as current, and `failure_modes` is what a person needs when a
reading looks wrong -- written down beside it rather than remembered.

**Why fifty is fine here and would not be in a sum.** Chapter 12.7 is blunt that
"neue Glättung ist keine neue Informationsquelle": a seventh moving average adds
no information. Fifty indicators are still worth having -- they disagree in
useful ways, and which of them disagrees is itself a reading -- but only because
`score.engine` reconciles them by family first. In a plain sum this inventory
would be a machine for reaching certainty about nothing.

**Every entry declares its lag honestly.** A 200-period average of an hourly
series is a statement about the last eight days, not about now. Anything reading
these has to be able to tell the difference, so the lag is a field rather than
folk knowledge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from traidingbrain.domain.enums import Bias, Timeframe
from traidingbrain.score.findings import Family, Finding


class Unit(StrEnum):
    """What an indicator's number actually is.

    Needed because the score has to turn a reading into a strength between zero
    and one, and doing that correctly depends entirely on the unit. An RSI of 70
    and a MACD of 70 have nothing in common, and a mapping that ignored the unit
    would treat them as if they did.
    """

    BOUNDED_100 = "bounded_0_100"
    BOUNDED_PM100 = "bounded_-100_100"
    PRICE = "price"
    RATIO = "ratio"
    SIGNED = "signed"
    ATR_UNITS = "atr_units"


@dataclass(frozen=True)
class Spec:
    """One indicator, with everything needed to weigh what it says.

    The fields are chapter 12.7's list. `formula_version` is there because the
    chapter asks the question directly -- "wechselt der Anbieter die Formel" --
    and a stored reading that cannot say which formula produced it cannot be
    compared with a later one.
    """

    name: str
    family: Family
    input_series: tuple[str, ...]
    lookback: int
    output_unit: Unit
    lag_bars: int
    """Bars before this means anything. Not the same as the lookback: an ATR
    over 14 bars needs 14 to warm up but describes now; a 200-period average
    needs 200 and describes the last 200."""

    failure_modes: tuple[str, ...]
    source: str
    formula_version: str = "1"
    venue_dependent: bool = False
    """True when the number changes with the data feed -- anything using volume.
    Chapter 11.2: "VWAP ist datenfeed- und sessionabhängig"."""

    def __post_init__(self) -> None:
        if not self.failure_modes:
            raise ValueError(
                f"{self.name}: an indicator with no stated failure mode is one "
                f"nobody has thought about hard enough to trust"
            )
        if self.lag_bars < 0 or self.lookback < 1:
            raise ValueError(f"{self.name}: lookback {self.lookback}, lag {self.lag_bars}")


#: How far a reading may sit from neutral before it counts as fully emphatic.
#:
#: Used to map a bounded oscillator onto the 0..1 strength scale: an RSI at 50
#: is neutral, at 50 ± this it is as emphatic as the scale allows. Twenty-five
#: puts the extremes at 25 and 75, which is inside the conventional 30/70 -- a
#: reading only reaches full strength once it is past where most people would
#: already call it stretched.
BOUNDED_FULL_SCALE = 25.0

#: Same idea for unbounded readings, in standard deviations of their own recent
#: history. Rolling rather than global, because a global scale would let a
#: quiet year decide what "extreme" means in a violent one.
SIGNED_FULL_SCALE_SIGMA = 2.0

#: How long the rolling window for that normalisation is.
#:
#: Comfortably longer than the slowest indicator's lookback, and that is a
#: requirement rather than a preference: scaling a 200-period average against
#: 200 bars of its own history is a z-score of noise about noise. A test pins
#: the relationship so a slower indicator cannot be added without widening this.
NORMALISE_WINDOW = 500

#: Fewest bars in that window before a normalised reading is trusted.
#: Below this the standard deviation is an estimate from too little, and the
#: honest answer is no reading rather than a confident one.
MIN_NORMALISE_SAMPLES = 20

#: Below this a reading takes no side. Not a threshold with an opinion -- it is
#: the float noise floor, so a reading of exactly neutral does not acquire a
#: direction from a rounding error.
NEUTRAL_EPSILON = 1e-9


@dataclass(frozen=True)
class Reading:
    """One indicator's value at one bar, before it becomes a finding."""

    spec: Spec
    value: float
    normalised: float
    """Signed, roughly -1..1. Positive argues up."""

    def to_finding(self, timeframe: Timeframe) -> Finding:
        strength = min(abs(self.normalised), 1.0)
        if strength < NEUTRAL_EPSILON:
            direction = Bias.NEUTRAL
        else:
            direction = Bias.BULLISH if self.normalised > 0 else Bias.BEARISH
        return Finding(
            key=f"{self.spec.name}_{timeframe.value.lower()}",
            family=self.spec.family,
            direction=direction,
            strength=round(strength, 4),
            timeframe=timeframe,
            source=self.spec.source,
            label=f"{self.spec.name} {self.value:.4g}",
        )


# --------------------------------------------------------------------------- #
# The inventory
# --------------------------------------------------------------------------- #

#: Every indicator this build knows, keyed by name.
#:
#: Grouped by family in source order so that adding one to the wrong family is
#: visible in a diff. The families are deliberately uneven: there are more ways
#: to measure momentum than to measure structure, and that imbalance is exactly
#: why the score reconciles by family instead of counting entries.
SPECS: dict[str, Spec] = {}


def register(spec: Spec) -> Spec:
    if spec.name in SPECS:
        raise ValueError(f"{spec.name} is registered twice")
    SPECS[spec.name] = spec
    return spec


def _add(
    name: str,
    family: Family,
    *,
    inputs: tuple[str, ...],
    lookback: int,
    unit: Unit,
    lag: int,
    fails: tuple[str, ...],
    source: str,
    venue: bool = False,
) -> Spec:
    return register(
        Spec(
            name=name,
            family=family,
            input_series=inputs,
            lookback=lookback,
            output_unit=unit,
            lag_bars=lag,
            failure_modes=fails,
            source=source,
            venue_dependent=venue,
        )
    )


CLOSE = ("close",)
HLC = ("high", "low", "close")
HLCV = ("high", "low", "close", "volume")
CV = ("close", "volume")

# -- trend and regime, chapter 12.1 ----------------------------------------- #

_add("sma_50", Family.TREND, inputs=CLOSE, lookback=50, unit=Unit.PRICE, lag=25,
     fails=("crossover read as a forecast", "lags every turn by half the lookback"),
     source="Z01")
_add("sma_200", Family.TREND, inputs=CLOSE, lookback=200, unit=Unit.PRICE, lag=100,
     fails=("describes the last 200 bars, not now", "meaningless inside a range"),
     source="Z01")
_add("ema_21", Family.TREND, inputs=CLOSE, lookback=21, unit=Unit.PRICE, lag=7,
     fails=("several EMAs counted as independent signals",), source="Z03")
_add("ema_55", Family.TREND, inputs=CLOSE, lookback=55, unit=Unit.PRICE, lag=18,
     fails=("several EMAs counted as independent signals",), source="Z03")
_add("macd_hist", Family.TREND, inputs=CLOSE, lookback=26, unit=Unit.SIGNED, lag=9,
     fails=("cross without regime context", "histogram sign flips on noise"),
     source="Z03")
_add("adx_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=14,
     fails=("high ADX read as bullish -- it is strength, not direction",), source="Z03")
_add("dmi_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.SIGNED, lag=14,
     fails=("DI cross alone taken as an entry",), source="Z03")
_add("supertrend_10", Family.TREND, inputs=HLC, lookback=10, unit=Unit.SIGNED, lag=10,
     fails=("flips repeatedly in a sideways market",), source="Z03")
_add("psar", Family.TREND, inputs=HLC, lookback=2, unit=Unit.SIGNED, lag=2,
     fails=("every flip traded in a flat range",), source="Z16")
_add("aroon_25", Family.TREND, inputs=("high", "low"), lookback=25, unit=Unit.BOUNDED_PM100,
     lag=25, fails=("measures time since an extreme, not size of move",), source="Z16")
_add("vortex_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.SIGNED, lag=14,
     fails=("whipsaws when the range contracts",), source="Z16")
_add("trix_15", Family.TREND, inputs=CLOSE, lookback=15, unit=Unit.SIGNED, lag=15,
     fails=("triple smoothing makes it very late",), source="Z16")
_add("ppo", Family.TREND, inputs=CLOSE, lookback=26, unit=Unit.SIGNED, lag=9,
     fails=("same information as MACD, scaled",), source="Z16")
_add("hma_21", Family.TREND, inputs=CLOSE, lookback=21, unit=Unit.PRICE, lag=5,
     fails=("new smoothing is not a new information source",), source="Z01")
_add("kama_20", Family.TREND, inputs=CLOSE, lookback=20, unit=Unit.PRICE, lag=10,
     fails=("adapts its own lag, so the lag field is an estimate",), source="Z01")

# -- momentum, chapter 12.2 -------------------------------------------------- #

_add("rsi_14", Family.MOMENTUM, inputs=CLOSE, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("overbought persists through a strong trend",), source="Z03")
_add("stoch_14", Family.MOMENTUM, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("an extreme is not a reversal guarantee",), source="Z03")
_add("stochrsi_14", Family.MOMENTUM, inputs=CLOSE, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("a derivative of a derivative; noisier than either",), source="Z03")
_add("willr_14", Family.MOMENTUM, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("mirrors Stochastic; not independent confirmation",), source="Z03")
_add("cci_20", Family.MOMENTUM, inputs=HLC, lookback=20, unit=Unit.SIGNED, lag=1,
     fails=("fixed thresholds are market and lookback dependent",), source="Z03")
_add("roc_12", Family.MOMENTUM, inputs=CLOSE, lookback=12, unit=Unit.RATIO, lag=1,
     fails=("dominated by outliers in the lookback",), source="Z03")
_add("cmo_14", Family.MOMENTUM, inputs=CLOSE, lookback=14, unit=Unit.BOUNDED_PM100, lag=1,
     fails=("same family as RSI; agreement is not evidence",), source="Z16")
_add("fisher_9", Family.MOMENTUM, inputs=("high", "low"), lookback=9, unit=Unit.SIGNED, lag=1,
     fails=("transform exaggerates extremes by construction",), source="Z16")
_add("ultimate_osc", Family.MOMENTUM, inputs=HLC, lookback=28, unit=Unit.BOUNDED_100, lag=1,
     fails=("three lookbacks blended; no single timescale",), source="Z16")

# -- volatility, chapter 12.3 ------------------------------------------------ #

_add("atr_14", Family.VOLATILITY, inputs=HLC, lookback=14, unit=Unit.ATR_UNITS, lag=1,
     fails=("no direction; rises in selloffs too",), source="Z02")
_add("bb_width_20", Family.VOLATILITY, inputs=CLOSE, lookback=20, unit=Unit.RATIO, lag=1,
     fails=("width is expansion, not direction",), source="Z03")
_add("bb_position_20", Family.VOLATILITY, inputs=CLOSE, lookback=20, unit=Unit.SIGNED, lag=1,
     fails=("touching a band is not a reversal",), source="Z03")
_add("keltner_pos_20", Family.VOLATILITY, inputs=HLC, lookback=20, unit=Unit.SIGNED, lag=1,
     fails=("whipsaws in flat markets",), source="Z17")
_add("donchian_pos_20", Family.VOLATILITY, inputs=("high", "low"), lookback=20,
     unit=Unit.SIGNED, lag=1, fails=("late, and fakeout-prone in a range",), source="Z01")
_add("hist_vol_30", Family.VOLATILITY, inputs=CLOSE, lookback=30, unit=Unit.RATIO, lag=30,
     fails=("past dispersion does not price jump risk",), source="Z01")
_add("choppiness_14", Family.VOLATILITY, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=14,
     fails=("describes trendiness, not which way",), source="Z16")

# -- volume and money flow, chapter 12.4 ------------------------------------- #

_add("rvol_20", Family.VOLUME, inputs=("volume",), lookback=20, unit=Unit.RATIO, lag=1,
     fails=("volume is participation, never direction",), source="Z12", venue=True)
_add("obv", Family.VOLUME, inputs=CV, lookback=20, unit=Unit.SIGNED, lag=1,
     fails=("assigns a whole bar's volume to one direction",), source="Z18", venue=True)
_add("cmf_20", Family.VOLUME, inputs=HLCV, lookback=20, unit=Unit.BOUNDED_PM100, lag=1,
     fails=("close position is a proxy, not real order flow",), source="Z19", venue=True)
_add("mfi_14", Family.VOLUME, inputs=HLCV, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("extremes persist in trends, like RSI",), source="Z19", venue=True)
_add("force_index_13", Family.VOLUME, inputs=CV, lookback=13, unit=Unit.SIGNED, lag=1,
     fails=("price change times volume; dominated by gaps",), source="Z18", venue=True)
_add("accum_dist", Family.VOLUME, inputs=HLCV, lookback=20, unit=Unit.SIGNED, lag=1,
     fails=("no direct identification of institutional flow",), source="Z18", venue=True)
_add("vwap_session", Family.VOLUME, inputs=HLCV, lookback=24, unit=Unit.SIGNED, lag=1,
     fails=("anchor and feed change the number",), source="Z03", venue=True)

# -- location, chapter 12.5 -------------------------------------------------- #

_add("range_position_20", Family.LOCATION, inputs=("high", "low", "close"), lookback=20,
     unit=Unit.SIGNED, lag=1, fails=("a range must be chosen before the position means anything",),
     source="Z13")
_add("prev_day_position", Family.LOCATION, inputs=HLC, lookback=24, unit=Unit.SIGNED, lag=1,
     fails=("loses relevance as distance grows",), source="P10")
_add("prev_week_position", Family.LOCATION, inputs=HLC, lookback=168, unit=Unit.SIGNED, lag=1,
     fails=("loses relevance as distance grows",), source="P10")
_add("pivot_position", Family.LOCATION, inputs=HLC, lookback=24, unit=Unit.SIGNED, lag=1,
     fails=("many pivot formulas; no level is guaranteed",), source="Z03")


def specs_by_family() -> dict[Family, list[Spec]]:
    grouped: dict[Family, list[Spec]] = {}
    for spec in SPECS.values():
        grouped.setdefault(spec.family, []).append(spec)
    return grouped


# --------------------------------------------------------------------------- #
# Turning a value into a strength
# --------------------------------------------------------------------------- #


def normalise(spec: Spec, series: pd.Series, index: int) -> float:
    """Map a reading onto roughly -1..1, according to what its unit is.

    This is the only place the unit matters, and it matters completely: an RSI
    of 70 and a MACD histogram of 70 have nothing in common, and a shared
    mapping that ignored the unit would treat them as if they did.

    Unbounded readings are scaled against their own recent history -- rolling,
    never global. A global scale lets a quiet year decide what counts as extreme
    in a violent one, which is the same lookahead that ruins a regime filter.
    """
    values = series.to_numpy(dtype="float64")
    if index < 0 or index >= len(values):
        return 0.0
    value = float(values[index])
    if not np.isfinite(value):
        return 0.0

    if spec.output_unit is Unit.BOUNDED_100:
        return float(np.clip((value - 50.0) / BOUNDED_FULL_SCALE, -1.0, 1.0))
    if spec.output_unit is Unit.BOUNDED_PM100:
        return float(np.clip(value / 100.0, -1.0, 1.0))
    if spec.output_unit in (Unit.SIGNED, Unit.RATIO, Unit.PRICE, Unit.ATR_UNITS):
        return _rolling_z(values, index)
    return 0.0


def _rolling_z(values: np.ndarray, index: int) -> float:
    """How unusual this reading is against its own recent history.

    Uses only bars up to and including `index`, which is what makes it safe to
    call inside a backtest loop. A window that reached forward would make every
    indicator look prescient in exactly the way that cannot be spotted by
    reading the output.
    """
    start = max(0, index - NORMALISE_WINDOW + 1)
    window = values[start : index + 1]
    window = window[np.isfinite(window)]
    if len(window) < MIN_NORMALISE_SAMPLES:
        return 0.0
    spread = float(np.std(window))
    if spread <= 0:
        return 0.0
    z = (float(values[index]) - float(np.mean(window))) / spread
    return float(np.clip(z / SIGNED_FULL_SCALE_SIGMA, -1.0, 1.0))


def read_all(
    computed: dict[str, pd.Series], index: int, timeframe: Timeframe
) -> list[Finding]:
    """Every registered indicator that has a value here, as findings.

    An indicator absent from `computed` is skipped rather than defaulted. A
    missing indicator and one reading zero are different states, and folding
    them together would let a detector that failed to run look like one that
    found nothing.
    """
    findings: list[Finding] = []
    for name, spec in SPECS.items():
        series = computed.get(name)
        if series is None or not spec.lookback <= index < len(series):
            continue
        value = float(series.to_numpy(dtype="float64")[index])
        if not np.isfinite(value):
            continue
        findings.append(
            Reading(spec=spec, value=value, normalised=normalise(spec, series, index)).to_finding(
                timeframe
            )
        )
    return findings


#: Signature every compute function follows: a frame in, one series out.
Compute = Callable[[pd.DataFrame], pd.Series]
