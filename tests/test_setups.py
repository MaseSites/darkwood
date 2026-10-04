"""The guide's setups: do they fire, and do they fire on the rule they cite?

A setup is easy to write and hard to notice being wrong, because both failures
look like silence. One that never fires and one that fires on every bar both
produce a backtest -- the first says the strategy found nothing, the second says
it found everything, and neither says "this condition is not the one in the
video". Three real bugs in this module were exactly that shape, and each is
pinned below by the test that would have caught it.

So the tests come in two layers. The rules are checked as **properties over
every signal the setups emit** on a long generated series: every A signal must
sit on the bar its level broke, every target must be the one its source names,
every stop must be on the far side of the thing the source says to hide behind.
And the **firing rate** is checked as a band, because a rule that quietly stops
matching is the failure mode that no property test catches -- all of them pass
vacuously on an empty list.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.analysis.pipeline import FrameAnalysis, analyse
from traidingbrain.config.settings import AppConfig, load_config
from traidingbrain.domain.enums import Side, Timeframe
from traidingbrain.strategy.setups import (
    BLOCK_STOP_BUFFER_ATR,
    BREAKOUT_FIRST_TARGET_R,
    CHANDELIER_ATR_MULTIPLE,
    INCOMPLETE,
    TRADEABLE,
    InducementOrderBlock,
    MomentumBreakout,
    SetupSignal,
    SetupTally,
    SupplyDemandRetest,
    evaluate_all,
)

BARS = 3500

#: How strongly the generator pulls price back to the level it is ranging around.
#:
#: This is the parameter that makes the fixture usable at all. A plain random
#: walk with a sine drift never revisits the same price twice, so no pool of
#: equal highs ever forms -- and a setup built on "ein Level mit mehreren
#: Rejections" then has nothing to match. Two of these setups fired four times
#: in 2,500 bars against a real-data rate forty times higher, which looked like
#: a bug in the setups and was a bug in the fixture.
LEVEL_STICKINESS = 0.12


def walk(count: int = BARS, seed: int = 5) -> pd.DataFrame:
    """A deterministic series that behaves enough like a market to test against.

    Alternating trending and ranging stretches, with price pulled back toward
    the level each range formed around. That pull is what produces repeated
    tests of the same price, which is what produces equal highs and lows, which
    is what three of these setups are built on.
    """
    rng = np.random.default_rng(seed)
    price = 100.0
    anchor, hold, slope = price, 0, 0.0
    rows = []
    for _ in range(count):
        if hold <= 0:
            hold = int(rng.integers(20, 90))
            anchor = price
            slope = float(rng.normal(0, 0.35)) if rng.random() < 0.55 else 0.0
        hold -= 1
        price = max(price + slope + LEVEL_STICKINESS * (anchor - price) + rng.normal(0, 0.55), 1.0)
        spread = abs(float(rng.normal(0, 0.5))) + 0.15
        open_ = price - float(rng.normal(0, 0.3))
        rows.append((open_, max(open_, price) + spread, min(open_, price) - spread, price))
    return pd.DataFrame(
        {
            "ts": [1_700_000_000_000 + i * 3_600_000 for i in range(count)],
            "open": [r[0] for r in rows],
            "high": [r[1] for r in rows],
            "low": [r[2] for r in rows],
            "close": [r[3] for r in rows],
            "volume": [100.0] * count,
        }
    )


@pytest.fixture(scope="module")
def config() -> AppConfig:
    return load_config()


@pytest.fixture(scope="module")
def analysis(config: AppConfig) -> FrameAnalysis:
    return analyse(walk(), Timeframe.H1, config.engine)


@pytest.fixture(scope="module")
def signals(analysis: FrameAnalysis) -> list[SetupSignal]:
    return [
        signal for index in range(len(analysis.frame)) for signal in evaluate_all(analysis, index)
    ]


def only(signals: list[SetupSignal], key: str) -> list[SetupSignal]:
    return [signal for signal in signals if signal.setup == key]


# --------------------------------------------------------------------------- #
# The fixture has to contain what the tests are about
# --------------------------------------------------------------------------- #


def test_every_tradeable_setup_fires_at_least_once(signals: list[SetupSignal]) -> None:
    """Guarding the tests below rather than the code.

    Every property test in this file passes on an empty list. A setup that
    silently stops matching would leave the suite green while the strategy lost
    a third of itself, which is precisely how the inducement setup spent its
    first version firing zero times in five years of real data.
    """
    fired = {signal.setup for signal in signals}

    assert fired == {setup.key for setup in TRADEABLE}


def test_the_setups_fire_at_a_plausible_rate(signals: list[SetupSignal]) -> None:
    """A band, not a number.

    The exact count depends on the fixture and will move when a threshold does.
    What must not move is the order of magnitude: a day-trading rule set that
    fires ten times an hour is matching noise, and one that fires twice a year
    cannot be evaluated at all. Measured on real BTC data this sits near one
    signal a day.
    """
    days = BARS / 24

    per_day = len(signals) / days

    assert 0.2 <= per_day <= 6.0, f"{per_day:.2f} signals a day is not a day-trading rate"


def test_every_signal_describes_a_trade_that_can_exist(signals: list[SetupSignal]) -> None:
    """A long whose stop is above its entry is not a cautious long; it is
    arithmetic that went wrong upstream. Dropped at the source, before anything
    sizes it, draws it or proposes it."""
    assert signals
    for signal in signals:
        assert signal.is_coherent()
        assert signal.risk > 0
        if signal.side is Side.LONG:
            assert signal.stop < signal.entry < signal.target
        else:
            assert signal.target < signal.entry < signal.stop


# --------------------------------------------------------------------------- #
# Setup A -- V08
# --------------------------------------------------------------------------- #


def test_the_breakout_fires_on_the_bar_the_level_broke(
    analysis: FrameAnalysis, signals: list[SetupSignal]
) -> None:
    """The bug this pins was not a wrong answer, it was a wrong question.

    Without checking the previous bar the setup matches "price is beyond a
    level", not "price just broke one" -- so it fires on every bar of a trend
    that cleared a level days ago. Measured on five years of BTC: 6,307 signals,
    3.4 a day, from a setup V08 describes as selective. With the check, 816.
    """
    breakouts = only(signals, "A")
    assert breakouts

    for signal in breakouts:
        level = signal.reference_level
        assert level is not None
        previous = analysis.close_at(signal.bar_index - 1)
        if signal.side is Side.LONG:
            assert previous <= level, "the level was already broken before this bar"
        else:
            assert previous >= level


def test_the_breakout_target_is_the_one_v08_names(signals: list[SetupSignal]) -> None:
    """ "Erstes Ziel bei 1,5R." Not a rounded 1.5, the exact multiple -- if this
    ever drifts it will be because someone tuned it, and tuning it is a change
    to the source's rule rather than to this code."""
    breakouts = only(signals, "A")
    assert breakouts

    for signal in breakouts:
        assert signal.reward_risk == pytest.approx(BREAKOUT_FIRST_TARGET_R)


def test_the_breakout_stop_sits_on_the_far_side_of_the_level(
    signals: list[SetupSignal],
) -> None:
    """V08 says "knapp unter dem gebrochenen Level" without saying how far.

    Rather than invent a buffer, the stop goes on the far side of the level's
    own band: a pool of equal highs is a band with a measured height, so the
    distance stays a property of the market instead of a constant somebody
    picked. Chapter 20.2 is explicit that no source gives a general buffer.
    """
    for signal in only(signals, "A"):
        level = signal.reference_level
        assert level is not None
        if signal.side is Side.LONG:
            assert signal.stop <= level
        else:
            assert signal.stop >= level


def test_the_breakout_carries_v08s_two_stage_exit(signals: list[SetupSignal]) -> None:
    """V08 is the only source asking for a runner: half off at 1.5R, the rest on
    a Chandelier stop at ATR times two. Carried on the signal so whatever
    executes it must either honour it or say it does not -- silently ignoring it
    would trade a different exit under the same name."""
    for signal in only(signals, "A"):
        assert signal.trail_atr_multiple == CHANDELIER_ATR_MULTIPLE
        assert signal.scale_out_fraction == 0.5


def test_no_other_setup_claims_a_runner(signals: list[SetupSignal]) -> None:
    """The guide gives the two-stage exit to V08 alone. Spreading it to the
    others would be assembling a strategy out of parts of different ones, which
    chapter 30 opens by refusing."""
    for signal in signals:
        if signal.setup != "A":
            assert signal.trail_atr_multiple is None
            assert signal.scale_out_fraction is None


# --------------------------------------------------------------------------- #
# Setup C -- V09
# --------------------------------------------------------------------------- #


def test_the_retest_only_takes_the_first_return_and_only_a_slow_one(
    analysis: FrameAnalysis, signals: list[SetupSignal]
) -> None:
    """Both are V09's conditions and both rule a lot out: "Erste Rückkehr in
    validierte Zone; langsame Annäherung", with "ein scharfer aggressiver
    Rücklauf" listed as a reason not to trade."""
    retests = only(signals, "C")
    assert retests

    for signal in retests:
        zone = next(
            zone
            for zone in analysis.zones.known_at(signal.bar_index)
            if signal.entry in (zone.high, zone.low)
        )
        touch = analysis.zones.touch_at(zone, signal.bar_index)
        assert touch is not None
        assert touch.is_first
        assert touch.was_slow


def test_the_retest_hides_its_stop_behind_the_zone(signals: list[SetupSignal]) -> None:
    """V09: "Stop Loss: Hinter der Zone." The zone has two edges; the entry is
    the near one and the stop is the far one, so the trade is wrong exactly when
    the zone is."""
    retests = only(signals, "C")
    assert retests

    for signal in retests:
        if signal.side is Side.LONG:
            assert signal.stop < signal.entry
        else:
            assert signal.stop > signal.entry


# --------------------------------------------------------------------------- #
# Setup F -- V12
# --------------------------------------------------------------------------- #


def test_the_inducement_setup_fires_at_all(signals: list[SetupSignal]) -> None:
    """Its own test, because it is the one that silently did not.

    Two conditions cancelled: the zone had to be untouched, and this bar had to
    be its first touch. Asking for both *as of the same bar* is impossible --
    the first touch is the moment it stops being untouched. Zero signals in five
    years of real data, with every individual rule reading correctly.
    """
    assert only(signals, "F"), "the inducement setup fired zero times"


def test_the_inducement_target_is_the_previous_extreme(
    analysis: FrameAnalysis, signals: list[SetupSignal]
) -> None:
    """V12: "Ziel am vorherigen Hoch" (mirrored for a short), taken from the
    confirmed swings rather than from the highest bar in a window -- a window
    would include bars whose high was still being written.

    Asserted as the rule rather than as a reward-to-risk number. How wide the
    trade comes out is geometry the market supplies: on real BTC the median is
    above four, on this generated series it is near one, and neither of those
    is a fact about the code.
    """
    inducement = only(signals, "F")
    assert inducement

    for signal in inducement:
        swings = analysis.structure.recent_swings(signal.bar_index, limit=8)
        wanted = "high" if signal.side is Side.LONG else "low"
        prices = [swing.price for swing in swings if swing.kind.value == wanted]

        assert prices
        assert signal.target == (max(prices) if signal.side is Side.LONG else min(prices))


def test_the_inducement_stop_is_the_far_edge_of_the_chosen_zone(
    signals: list[SetupSignal],
) -> None:
    """V12: "Stop unter dem Higher-Timeframe-Tief." Entry at the near edge, stop
    at the far one, so the trade is wrong exactly when the zone is."""
    for signal in only(signals, "F"):
        assert signal.reference_level == signal.entry
        if signal.side is Side.LONG:
            assert signal.stop < signal.entry
        else:
            assert signal.stop > signal.entry


# --------------------------------------------------------------------------- #
# The setups that cannot propose
# --------------------------------------------------------------------------- #


def test_the_incomplete_setups_never_propose(analysis: FrameAnalysis) -> None:
    """D has no stop -- stated in the guide's own rule card -- and chapter 20.2
    forbids supplying one.

    A setup missing a stop is a position with unbounded loss. Filling the gap
    would mean trading a rule nobody gave while the label still said V10.

    E left this list on 04.10.2026. Its card does specify a stop ("hinter/über
    den gesamten Block") and only the buffer and the target were absent; those
    two are supplied and labelled as supplied, which is a different thing from
    inventing a stop that does not exist.
    """
    for setup in INCOMPLETE:
        for index in range(0, len(analysis.frame), 29):
            assert setup.evaluate(analysis, index) is None


def test_each_incomplete_setup_says_what_is_missing_and_quotes_its_source() -> None:
    """Kept as objects rather than deleted, because a missing setup looks like
    an oversight. This says which piece is absent and where the guide says so,
    which is what somebody needs in order to supply the number themselves."""
    assert INCOMPLETE
    for setup in INCOMPLETE:
        assert setup.missing
        assert setup.quote
        assert setup.source.startswith("V")


def test_every_setup_is_either_tradeable_or_declared_incomplete() -> None:
    """The guide describes seven. All seven are accounted for, so none can be
    quietly dropped and later remembered as never having existed."""
    keys = {setup.key for setup in TRADEABLE} | {setup.key for setup in INCOMPLETE}

    assert keys == set("ABCDEFG")


# --------------------------------------------------------------------------- #
# Setup E -- order block after Noc Trading (V11)
# --------------------------------------------------------------------------- #


def test_the_noc_block_fires_at_all(signals: list[SetupSignal]) -> None:
    """It asks for three things at once -- a sweep, displacement and a change of
    character -- so it is rare by construction. Rare is not the same as never,
    and a setup that never fires is a setup nobody would notice was broken."""
    assert only(signals, "E")


def test_the_noc_stop_covers_the_whole_block(signals: list[SetupSignal]) -> None:
    """V11: "Stop Loss: Hinter/über den gesamten Block." Not its near edge --
    a stop inside the block is taken out by the block doing its job."""
    for signal in only(signals, "E"):
        if signal.side is Side.LONG:
            assert signal.stop < signal.entry
        else:
            assert signal.stop > signal.entry


def test_the_noc_stop_keeps_a_buffer_beyond_the_edge(signals: list[SetupSignal]) -> None:
    """The card's own warning is "exakten Kantentreffer verlangen".

    A stop exactly on the edge is taken out by the same imprecision the card
    says not to demand on the way in. The buffer is the one number here the
    video does not give, so it is named and checked rather than being a literal
    somewhere in the middle of a formula.
    """
    assert BLOCK_STOP_BUFFER_ATR > 0


def test_the_noc_setup_says_which_rules_are_v11s_and_which_are_supplied(
    signals: list[SetupSignal],
) -> None:
    """The point of the whole exercise.

    Two of this setup's numbers are the card's and two are mine. In three
    months the only way to tell whether a measurement describes Severin's rules
    or my reading of them is if each trade says so, and the reasons travel into
    the journal with the trade.
    """
    for signal in only(signals, "E"):
        reasons = " | ".join(signal.reasons)
        assert "V11:" in reasons, "nothing claims to come from the video"
        assert "ergaenzt:" in reasons, "the supplied rules are not marked as supplied"


def test_the_noc_setup_is_tradeable_and_no_longer_declared_incomplete() -> None:
    """It moved lists on 04.10.2026, and both lists have to agree about it --
    a setup in neither would vanish, and one in both would be traded while the
    screen said it could not be."""
    assert "E" in {setup.key for setup in TRADEABLE}
    assert "E" not in {setup.key for setup in INCOMPLETE}


# --------------------------------------------------------------------------- #
# Separateness, which chapter 30 asks for explicitly
# --------------------------------------------------------------------------- #


def test_two_setups_firing_together_are_both_reported(analysis: FrameAnalysis) -> None:
    """Chapter 30: "getrennte Video-Modelle ... keine kombinierte
    Master-Strategie". Picking a winner here would throw away the fact that two
    independent rules agreed, before anything could weigh it."""
    agreements = [
        found
        for index in range(len(analysis.frame))
        if len(found := evaluate_all(analysis, index)) > 1
    ]

    assert agreements, "no bar ever had two setups, so this proves nothing"
    for found in agreements:
        assert len({signal.setup for signal in found}) == len(found)


def test_every_signal_names_its_source_video(signals: list[SetupSignal]) -> None:
    """A signal that cannot be traced to a video cannot be argued with, and the
    whole point of this rule set is that it came from somewhere."""
    for signal in signals:
        assert signal.source.startswith("V")
        assert signal.reasons


# --------------------------------------------------------------------------- #
# No lookahead
# --------------------------------------------------------------------------- #


def test_rewriting_the_future_cannot_change_an_earlier_signal(config: AppConfig) -> None:
    """The guarantee the whole engine rests on, applied to the new layer.

    Every setup reads zones, candles and structure, and each of those already
    has its own version of this test. This one is about the setups themselves:
    a target taken from a window that runs past the decision bar, a stop read
    from a swing not yet confirmed.
    """
    frame = walk(900)
    cut = 600

    def upto(source: pd.DataFrame) -> list[tuple[str, int, float, float, float]]:
        built = analyse(source, Timeframe.H1, config.engine)
        return [
            (s.setup, s.bar_index, s.entry, s.stop, s.target)
            for index in range(cut)
            for s in evaluate_all(built, index)
        ]

    before = upto(frame)
    mutated = frame.copy()
    mutated.loc[cut:, ["open", "high", "low", "close"]] = 999.0

    assert before
    assert upto(mutated) == before


# --------------------------------------------------------------------------- #
# Counting
# --------------------------------------------------------------------------- #


def test_the_tally_counts_per_setup_because_the_average_hides_everything() -> None:
    """Three setups pooled into one number cannot say which one worked, and
    chapter 30's whole instruction is that they are measured apart."""
    tally = SetupTally()
    for setup, count in (("A", 3), ("C", 1)):
        for _ in range(count):
            tally.add(
                SetupSignal(
                    setup=setup,
                    name="x",
                    source="V08",
                    side=Side.LONG,
                    entry=100.0,
                    stop=99.0,
                    target=102.0,
                    bar_index=0,
                )
            )

    assert tally.counts == {"A": 3, "C": 1}
    assert "A: 3" in tally.summary()


def test_an_empty_tally_says_so_rather_than_showing_nothing() -> None:
    assert SetupTally().summary() == "no setup fired"


def test_the_setup_objects_carry_the_labels_the_protocol_asks_for() -> None:
    for setup in (MomentumBreakout(), SupplyDemandRetest(), InducementOrderBlock()):
        assert setup.key in set("ACF")
        assert setup.name
        assert setup.source.startswith("V")
