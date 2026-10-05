"""The first candidate from a family this project had never tested.

Nine hypotheses fell on 05.10.2026 and all nine lay inside one family of nine:
every shipped setup is continuation logic waiting for a return to a zone. This
rule claims something different -- that a sharp range expansion out of a quiet
stretch continues far enough to pay for itself.

Four properties have to hold before any measurement of it means anything:

1. **It must not see the future.** The expansion is judged from the bar that
   closed, and a later bar must not change what it proposes.
2. **It must fire once per candle**, not once per signal bar the candle spans.
   Without that guard an H4 rule is proposed sixteen times on M15 and a
   backtest trades sixteen times what the rule describes.
3. **Quiet is judged on the bar before the expansion.** Asking whether the
   expanding bar itself sits in a quiet regime is close to a contradiction, and
   it is the off-by-one that makes a rule fire almost never while looking right.
4. **The stop sits beyond the bar, not inside it.** The claim is continuation,
   so the trade is wrong exactly when price comes back through the bar that
   started it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.strategies.vol_breakout import EXPANSION, LOOKBACK, VolBreakout

MINUTE_MS = 60_000
WEEK_MS = 10080 * MINUTE_MS
END_MS = (1_700_000_000_000 // WEEK_MS) * WEEK_MS
STEPS = {Timeframe.W1: 10080, Timeframe.D1: 1440, Timeframe.H4: 240, Timeframe.H1: 60}


def quiet_then_expand(
    timeframe: Timeframe,
    count: int,
    *,
    expand_at: int | None = None,
    upward: bool = True,
    seed: int = 3,
) -> pd.DataFrame:
    """A calm series with one deliberately huge bar near the end.

    Calm is built as a tight random walk so the rolling volatility percentile
    is genuinely low; the expanding bar is then unmistakable rather than
    marginal, so a test that fails is failing on the rule and not on whether
    one bar happened to clear a threshold.
    """
    rng = np.random.default_rng(seed)
    step = STEPS.get(timeframe, 15) * MINUTE_MS

    # Ranges from a narrow band rather than a random walk. The first version
    # drew a walk at sigma=0.0004 and the "calm" fixture fired the rule on its
    # own noise -- correctly, because in a walk a bar at twice the recent
    # average *range* is an ordinary event, range being noisy itself. That told
    # us something real about the rule (see the module docstring: the expansion
    # threshold alone is a weak filter and the quiet-regime gate does the work)
    # but it made every test here test the fixture instead of the rule.
    #
    # Here the widest bar is about 1.25x the band and the trailing average sits
    # mid-band, so nothing in the calm stretch can approach the 2x threshold.
    # A *calming* market, not merely a narrow one. The second version used a
    # near-constant range and nothing fired: `rolling_percentile_rank` ranks
    # ties upward, so a flat ATR sits near the 90th percentile, not the
    # middle, and the quiet gate never opened. Quiet has to mean quiet
    # *relative to its own recent history*, which needs the range to fall.
    jitter = rng.uniform(1.0, 1.25, size=count)
    decay = np.exp(-2.0 * np.arange(count) / max(count, 1))
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.0002, size=count)))
    opens = np.concatenate([[100.0], closes[:-1]])
    half = closes * 0.0015 * jitter * decay
    highs = np.maximum(opens, closes) + half
    lows = np.minimum(opens, closes) - half

    if expand_at is not None and 0 <= expand_at < count:
        i = expand_at
        base = float(opens[i])
        reach = base * 0.05 * (EXPANSION / 2.0)
        if upward:
            closes[i] = base + reach * 0.9
            highs[i] = base + reach
            lows[i] = base - reach * 0.05
        else:
            closes[i] = base - reach * 0.9
            lows[i] = base - reach
            highs[i] = base + reach * 0.05

    first = END_MS - (count - 1) * step
    return pd.DataFrame(
        {
            "ts": first + np.arange(count, dtype="int64") * step,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": rng.uniform(10.0, 100.0, size=count),
        }
    )


def build(*, expand_at: int | None = None, upward: bool = True) -> MultiFrameAnalysis:
    config = load_config()
    counts = {
        Timeframe.W1: 120,
        Timeframe.D1: 400,
        Timeframe.H4: 900,
        Timeframe.H1: 1800,
        Timeframe.M15: 4000,
    }
    frames = {}
    for timeframe in config.engine.timeframes.context:
        at = expand_at if timeframe is Timeframe.H4 else None
        frames[timeframe] = quiet_then_expand(
            timeframe, counts.get(timeframe, 1000), expand_at=at, upward=upward
        )
    return MultiFrameAnalysis(frames, config.engine)


def proposals(analysis: MultiFrameAnalysis, arm: VolBreakout) -> list[tuple[int, object]]:
    out = []
    for index in range(len(analysis.signal)):
        intent = arm.propose_at(analysis, index)
        if intent is not None:
            out.append((index, intent))
    return out


# --------------------------------------------------------------------------- #
# The four properties
# --------------------------------------------------------------------------- #


def test_it_does_not_see_the_future() -> None:
    """Randomising every later bar must not change what it proposes.

    The one test that makes a measurement of this arm worth running. A rule
    that peeks produces a beautiful backtest, and the walk-forward, the
    purging and the permutation null would all faithfully report the leak as
    skill.
    """
    analysis = build(expand_at=700)
    arm = VolBreakout()
    found = proposals(analysis, arm)
    assert found, "the fixture never triggered, so this test proves nothing"
    index, intent = found[0]

    config = load_config()
    rng = np.random.default_rng(11)
    frames = {}
    for timeframe, existing in analysis.analyses.items():
        frame = existing.frame.copy()
        if timeframe is Timeframe.H4:
            later = frame.index > 700
            for column in ("open", "high", "low", "close"):
                frame.loc[later, column] = frame.loc[later, column] * rng.uniform(
                    0.5, 2.0, size=int(later.sum())
                )
        frames[timeframe] = frame

    after = VolBreakout().propose_at(MultiFrameAnalysis(frames, config.engine), index)
    assert after == intent, "the proposal changed when only later bars changed"


def test_it_fires_once_per_candle_not_once_per_signal_bar() -> None:
    """An H4 candle spans sixteen M15 bars.

    Without the just-closed guard the same expansion is proposed sixteen times,
    and a backtest takes sixteen entries where the rule describes one.
    """
    analysis = build(expand_at=700)
    found = proposals(analysis, VolBreakout())

    assert found, "nothing fired"
    # One expanding candle in the fixture, so at most one proposal from it.
    assert len(found) == 1, f"one candle produced {len(found)} proposals"


def test_quiet_is_judged_on_the_bar_before_the_expansion() -> None:
    """Otherwise the condition nearly contradicts itself.

    The expanding bar raises its own volatility, so asking whether *it* sits in
    a quiet regime is asking for a bar that is both calm and not. Checked by
    its consequence: the rule fires at all on a fixture whose expansion is
    unmistakable.
    """
    analysis = build(expand_at=700)
    arm = VolBreakout()
    proposals(analysis, arm)

    assert arm.quiet_bars > 0, "no bar was ever judged quiet"
    assert arm.fired == 1, f"the expansion fired {arm.fired} times"


def test_the_stop_sits_beyond_the_bar_that_started_it() -> None:
    """The claim is continuation, so that is where the claim is wrong."""
    analysis = build(expand_at=700)
    [(_index, intent)] = proposals(analysis, VolBreakout())
    frame = analysis.analyses[Timeframe.H4]

    low = float(frame.column("low")[700])
    high = float(frame.column("high")[700])
    assert intent.side is Side.LONG
    assert intent.stop < low, "the stop is inside the expanding bar"
    assert intent.entry <= high


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_a_downward_expansion_is_traded_short() -> None:
    """Direction comes from the bar, not from the trend.

    A bar that expanded and closed down is a downward expansion however bullish
    the higher timeframes look -- the hypothesis is about the expansion itself.
    """
    analysis = build(expand_at=700, upward=False)
    found = proposals(analysis, VolBreakout())

    assert found, "nothing fired on a downward expansion"
    _index, intent = found[0]
    assert intent.side is Side.SHORT
    assert intent.stop > intent.entry > intent.target


def test_every_proposal_is_coherent_and_carries_its_reason() -> None:
    analysis = build(expand_at=700)
    [(_index, intent)] = proposals(analysis, VolBreakout())

    assert intent.is_coherent
    assert intent.reward_risk == pytest.approx(2.0, abs=0.01)
    assert "Spanne" in intent.reason and "Perzentil" in intent.reason


def test_a_calm_market_produces_nothing() -> None:
    """A rule that fires on ordinary noise is measuring noise."""
    analysis = build(expand_at=None)

    assert proposals(analysis, VolBreakout()) == []


def test_it_refuses_before_it_has_enough_history() -> None:
    """The lookback average is meaningless over a handful of bars."""
    analysis = build(expand_at=LOOKBACK - 2)

    assert proposals(analysis, VolBreakout()) == []


def test_the_counters_separate_a_result_from_a_bug() -> None:
    """Zero trades and a rule that never fired are different things.

    Without the counters a run with no trades cannot be told apart from a
    broken condition, and the second would be reported as a finding.
    """
    arm = VolBreakout()
    proposals(build(expand_at=None), arm)

    assert arm.fired == 0
    assert arm.quiet_bars > 0, "the quiet condition itself never matched"
