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
    NORMALISED = "normalised_-1_1"
    """Already on the scale the score wants: -1 fully bearish, +1 fully bullish.

    For the readings that are a position by construction -- where in a band,
    where in a channel, which share of volume went one way. Scaling those
    against their own history would discard the thing they measure: a close at
    the top of its range is at the top of its range, whether or not it has been
    there often lately."""


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

    full_scale: float | None = None
    """For an ATR-unit reading: the distance that counts as fully emphatic.

    One number does not fit all of them. Price sits within about an ATR of a
    21-period average and routinely six from a 200-period one, so a shared
    scale would leave the long averages pinned at the maximum in any trend --
    a gradation thrown away exactly where there is most of it to measure.
    `None` means the default."""

    depends_on: tuple[str, ...] = ()
    """Other indicators this one is not independent of.

    Only for shared causes that cross a family boundary -- within a family the
    median already handles it. The case that forced the field: the position of
    price in a twenty-bar channel is registered twice, once as a volatility
    reading and once as a location reading, and they are the same number. Two
    families agreeing is confluence, and this is how one thing is stopped from
    faking it."""

    directional: bool = True
    """False when the reading has a size but no side.

    ADX, ATR, Bollinger width, historical volatility, choppiness and relative
    volume all measure *how much*, never *which way*. Each one's registered
    failure mode says so in words -- "high ADX read as bullish", "volume is
    participation, never direction" -- and this field is that sentence made
    executable.

    Such a reading is context, not evidence, and `read_all` leaves it out of
    the findings. Letting it in as a neutral vote would be worse than dropping
    it: a family is reconciled by the median of its members, so four
    non-directional readings beside three directional ones would pull the
    family to neutral and erase the only part of it that had something to say.
    The number is still computed and still available to read -- it just does
    not get a vote on direction it does not have."""

    def __post_init__(self) -> None:
        if not self.failure_modes:
            raise ValueError(
                f"{self.name}: an indicator with no stated failure mode is one "
                f"nobody has thought about hard enough to trust"
            )
        if self.lag_bars < 0 or self.lookback < 1:
            raise ValueError(f"{self.name}: lookback {self.lookback}, lag {self.lag_bars}")
        if self.name in self.depends_on:
            raise ValueError(f"{self.name} depends on itself")


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

#: How many ATR a distance has to cover before it counts as fully emphatic.
#:
#: A fixed scale rather than a rolling one, and that is deliberate. Price two
#: ATR above its 200-period average is far above it, and it stays far above it
#: however long the trend lasts. Scaling that against its own history would
#: read a persistent trend as normal and therefore as neutral -- the trend
#: family would go quiet exactly when it has the clearest thing to say.
ATR_FULL_SCALE = 2.0

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
            # A dependency is between two indicators, but a finding's key also
            # carries the timeframe -- the hourly reading does not depend on
            # the daily one, only on its own timeframe's twin.
            depends_on=tuple(
                f"{name}_{timeframe.value.lower()}" for name in self.spec.depends_on
            ),
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
    directional: bool = True,
    depends_on: tuple[str, ...] = (),
    full_scale: float | None = None,
) -> Spec:
    return register(
        Spec(
            name=name,
            full_scale=full_scale,
            family=family,
            input_series=inputs,
            lookback=lookback,
            output_unit=unit,
            lag_bars=lag,
            failure_modes=fails,
            source=source,
            venue_dependent=venue,
            directional=directional,
            depends_on=depends_on,
        )
    )


CLOSE = ("close",)
HLC = ("high", "low", "close")
HLCV = ("high", "low", "close", "volume")
CV = ("close", "volume")

# -- trend and regime, chapter 12.1 ----------------------------------------- #
#
# Every moving average here is registered in ATR units, not in price. The
# reading is the *distance* from price to the average, because the level of a
# 200-period average carries no direction on its own -- what carries direction
# is whether price is above it and by how much. Measuring that gap in ATR makes
# it mean the same thing on BTC at 60,000 and on XRP at 0.50.

_add("sma_50", Family.TREND, inputs=CLOSE, lookback=50, unit=Unit.ATR_UNITS, lag=25,
     fails=("crossover read as a forecast", "lags every turn by half the lookback"),
     source="Z01", full_scale=2.5)
_add("sma_200", Family.TREND, inputs=CLOSE, lookback=200, unit=Unit.ATR_UNITS, lag=100,
     fails=("describes the last 200 bars, not now", "meaningless inside a range"),
     source="Z01", full_scale=6.0)
_add("ema_21", Family.TREND, inputs=CLOSE, lookback=21, unit=Unit.ATR_UNITS, lag=7,
     fails=("several EMAs counted as independent signals",), source="Z03", full_scale=1.5)
_add("ema_55", Family.TREND, inputs=CLOSE, lookback=55, unit=Unit.ATR_UNITS, lag=18,
     fails=("several EMAs counted as independent signals",), source="Z03", full_scale=2.5)
_add("macd_hist", Family.TREND, inputs=CLOSE, lookback=26, unit=Unit.SIGNED, lag=9,
     fails=("cross without regime context", "histogram sign flips on noise"),
     source="Z03")
_add("adx_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=14,
     fails=("high ADX read as bullish -- it is strength, not direction",), source="Z03",
     directional=False)
_add("dmi_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.SIGNED, lag=14,
     fails=("DI cross alone taken as an entry",), source="Z03")
#: The Supertrend band is three ATR wide by construction, so the line sits
#: about that far away right after a flip. Scaling it to anything tighter would
#: report every fresh flip as maximally emphatic.
_add("supertrend_10", Family.TREND, inputs=HLC, lookback=10, unit=Unit.ATR_UNITS, lag=10,
     fails=("flips repeatedly in a sideways market",), source="Z03", full_scale=3.0)
_add("psar", Family.TREND, inputs=HLC, lookback=2, unit=Unit.ATR_UNITS, lag=2,
     fails=("every flip traded in a flat range",), source="Z16")
_add("aroon_25", Family.TREND, inputs=("high", "low"), lookback=25, unit=Unit.BOUNDED_PM100,
     lag=25, fails=("measures time since an extreme, not size of move",), source="Z16")
_add("vortex_14", Family.TREND, inputs=HLC, lookback=14, unit=Unit.SIGNED, lag=14,
     fails=("whipsaws when the range contracts",), source="Z16")
_add("trix_15", Family.TREND, inputs=CLOSE, lookback=15, unit=Unit.SIGNED, lag=15,
     fails=("triple smoothing makes it very late",), source="Z16")
_add("ppo", Family.TREND, inputs=CLOSE, lookback=26, unit=Unit.SIGNED, lag=9,
     fails=("same information as MACD, scaled",), source="Z16")
_add("hma_21", Family.TREND, inputs=CLOSE, lookback=21, unit=Unit.ATR_UNITS, lag=5,
     fails=("new smoothing is not a new information source",), source="Z01", full_scale=1.5)
_add("kama_20", Family.TREND, inputs=CLOSE, lookback=20, unit=Unit.ATR_UNITS, lag=10,
     fails=("adapts its own lag, so the lag field is an estimate",), source="Z01")

# -- momentum, chapter 12.2 -------------------------------------------------- #

_add("rsi_14", Family.MOMENTUM, inputs=CLOSE, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("overbought persists through a strong trend",), source="Z03")
#: The slow stochastic -- raw %K smoothed over three bars, which is what every
#: charting platform draws by default. Raw %K is registered separately as
#: Williams %R, because the two are the same number to the sign.
_add("stoch_14", Family.MOMENTUM, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("an extreme is not a reversal guarantee",), source="Z03")
_add("stochrsi_14", Family.MOMENTUM, inputs=CLOSE, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("a derivative of a derivative; noisier than either",), source="Z03")
#: Williams %R is native to -100..0; the bank shifts it onto 0..100 so that 50
#: is the midpoint here as it is for every other bounded reading.
_add("willr_14", Family.MOMENTUM, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("mirrors Stochastic; not independent confirmation",), source="Z03",
     depends_on=("stoch_14",))
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

_add("atr_14", Family.VOLATILITY, inputs=HLC, lookback=14, unit=Unit.RATIO, lag=1,
     fails=("no direction; rises in selloffs too",), source="Z02", directional=False)
_add("bb_width_20", Family.VOLATILITY, inputs=CLOSE, lookback=20, unit=Unit.RATIO, lag=1,
     fails=("width is expansion, not direction",), source="Z03", directional=False)
_add("bb_position_20", Family.VOLATILITY, inputs=CLOSE, lookback=20, unit=Unit.NORMALISED,
     lag=1, fails=("touching a band is not a reversal",), source="Z03")
_add("keltner_pos_20", Family.VOLATILITY, inputs=HLC, lookback=20, unit=Unit.NORMALISED, lag=1,
     fails=("whipsaws in flat markets",), source="Z17")
_add("donchian_pos_20", Family.VOLATILITY, inputs=("high", "low"), lookback=20,
     unit=Unit.NORMALISED, lag=1, fails=("late, and fakeout-prone in a range",), source="Z01")
_add("hist_vol_30", Family.VOLATILITY, inputs=CLOSE, lookback=30, unit=Unit.RATIO, lag=30,
     fails=("past dispersion does not price jump risk",), source="Z01", directional=False)
_add("choppiness_14", Family.VOLATILITY, inputs=HLC, lookback=14, unit=Unit.BOUNDED_100, lag=14,
     fails=("describes trendiness, not which way",), source="Z16", directional=False)

# -- volume and money flow, chapter 12.4 ------------------------------------- #

_add("rvol_20", Family.VOLUME, inputs=("volume",), lookback=20, unit=Unit.RATIO, lag=1,
     fails=("volume is participation, never direction",), source="Z12", venue=True,
     directional=False)
#: OBV and A/D are cumulative, so their level depends on where the file starts.
#: The bank reads their *change* over the lookback as a share of the volume
#: traded in it -- a number that means the same thing on any slice of history.
_add("obv", Family.VOLUME, inputs=CV, lookback=20, unit=Unit.NORMALISED, lag=1,
     fails=("assigns a whole bar's volume to one direction",), source="Z18", venue=True)
_add("cmf_20", Family.VOLUME, inputs=HLCV, lookback=20, unit=Unit.NORMALISED, lag=1,
     fails=("close position is a proxy, not real order flow",), source="Z19", venue=True)
_add("mfi_14", Family.VOLUME, inputs=HLCV, lookback=14, unit=Unit.BOUNDED_100, lag=1,
     fails=("extremes persist in trends, like RSI",), source="Z19", venue=True)
_add("force_index_13", Family.VOLUME, inputs=CV, lookback=13, unit=Unit.SIGNED, lag=1,
     fails=("price change times volume; dominated by gaps",), source="Z18", venue=True)
#: Read as a divergence, not as a flow. The accumulation/distribution line
#: summed over a window *is* Chaikin money flow -- the same formula with the
#: same window -- so reading it that way would register one number twice. What
#: the line adds is where it sits in its own range against where price sits in
#: its: the two disagreeing is the reading people actually use it for.
_add("accum_dist", Family.VOLUME, inputs=HLCV, lookback=50, unit=Unit.NORMALISED, lag=1,
     fails=("no direct identification of institutional flow",
            "a divergence can persist for a long time without resolving"),
     source="Z18", venue=True)
_add("vwap_session", Family.VOLUME, inputs=HLCV, lookback=2, unit=Unit.ATR_UNITS, lag=1,
     fails=("anchor and feed change the number",), source="Z03", venue=True, full_scale=2.5)

# -- location, chapter 12.5 -------------------------------------------------- #
#
# The calendar readings warm up as soon as one period has closed, so their
# lookback is two bars rather than a bar count standing in for a day. A bar
# count would mean something different on every timeframe, and on the weekly
# frame "the previous day in 168 bars" is three years of warm-up for a number
# that was available in the second week.

#: Position in the range of *closes*, where Donchian uses the wicks. The
#: distinction is the point: a range drawn through the wicks includes every
#: rejected spike, and a range drawn through the closes is where value
#: actually settled. Related enough to declare the dependence all the same.
_add("range_position_20", Family.LOCATION, inputs=CLOSE, lookback=20,
     unit=Unit.NORMALISED, lag=1,
     fails=("a range must be chosen before the position means anything",),
     source="Z13", depends_on=("donchian_pos_20",))
_add("prev_day_position", Family.LOCATION, inputs=HLC, lookback=2, unit=Unit.NORMALISED, lag=1,
     fails=("loses relevance as distance grows",), source="P10")
_add("prev_week_position", Family.LOCATION, inputs=HLC, lookback=2, unit=Unit.NORMALISED,
     lag=1, fails=("loses relevance as distance grows",), source="P10")
_add("pivot_position", Family.LOCATION, inputs=HLC, lookback=2, unit=Unit.ATR_UNITS, lag=1,
     fails=("many pivot formulas; no level is guaranteed",), source="Z03", full_scale=2.5)


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
    return _scale(spec, value, values, index)


def _scale(spec: Spec, value: float, values: np.ndarray, index: int) -> float:
    """The unit-dependent half of `normalise`, split out so each branch is one line.

    Anything that is not bounded and not already a distance falls through to
    the rolling z-score, which is the only honest default for a number whose
    natural size nobody can state in advance.
    """
    if spec.output_unit is Unit.BOUNDED_100:
        return float(np.clip((value - 50.0) / BOUNDED_FULL_SCALE, -1.0, 1.0))
    if spec.output_unit is Unit.BOUNDED_PM100:
        return float(np.clip(value / 100.0, -1.0, 1.0))
    if spec.output_unit is Unit.NORMALISED:
        return float(np.clip(value, -1.0, 1.0))
    if spec.output_unit is Unit.ATR_UNITS:
        return float(np.clip(value / (spec.full_scale or ATR_FULL_SCALE), -1.0, 1.0))
    return _rolling_z(values, index)


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

    Non-directional indicators are left out too, for the reason set out on
    `Spec.directional`: a reading with a size but no side is context, and
    letting it vote neutral would drag its family's median towards nothing.
    `context_at` returns those instead.
    """
    findings: list[Finding] = []
    for name, spec in SPECS.items():
        if not spec.directional:
            continue
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


def context_at(computed: dict[str, pd.Series], index: int) -> dict[str, float]:
    """The non-directional readings at this bar, by name.

    How violent, how wide, how choppy, how busy. None of it argues a side, and
    all of it changes what a side is worth -- which is why it is kept and shown
    rather than quietly dropped at the point where it fails to be evidence.
    """
    out: dict[str, float] = {}
    for name, spec in SPECS.items():
        if spec.directional:
            continue
        series = computed.get(name)
        if series is None or not spec.lookback <= index < len(series):
            continue
        value = float(series.to_numpy(dtype="float64")[index])
        if np.isfinite(value):
            out[name] = value
    return out


#: Signature every compute function follows: a frame in, one series out.
Compute = Callable[[pd.DataFrame], pd.Series]
