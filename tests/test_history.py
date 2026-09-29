"""The similarity index, and the two time bounds that keep it honest.

A leaking similarity index is the most flattering bug in this whole system,
because it does not produce an error or an implausible number -- it produces
"similar setups won 68% of the time", which raises confidence, which raises
position size, and none of it survives a market that has not happened yet.

Two bounds, tested directly rather than inferred from a backtest looking
reasonable:

**Purging** -- a case is only admissible once its own outcome is known.

**Embargo** -- stricter, and the one that gets forgotten. A case whose outcome
window overlaps the present bar was partly determined by the very price action
being judged, so it is not independent evidence about this setup.
"""

from __future__ import annotations

import numpy as np
import pytest

from tests.factories import make_snapshot, make_timeframe_view
from traidingbrain.config.settings import HistoryConfig, load_config
from traidingbrain.domain.enums import Bias, RegimeKind, Timeframe, VolBucket
from traidingbrain.history.engine import HOUR_MS, HistoryEngine
from traidingbrain.history.fingerprint import dimension, feature_names, fingerprint
from traidingbrain.history.index import Case, Neighbour, SimilarityIndex
from traidingbrain.history.stats import MIN_SEPARATION_MS, deduplicate, summarise

DAY = 86_400_000
NOW = 1_700_000_000_000
EMBARGO = 48 * HOUR_MS


def vector(seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0, 0.3, size=dimension())


def case(*, entry_days_ago: float, resolved_days_ago: float, outcome: float, seed: int = 0) -> Case:
    return Case(
        fingerprint=vector(seed),
        entry_ts=NOW - int(entry_days_ago * DAY),
        resolved_ts=NOW - int(resolved_days_ago * DAY),
        outcome_r=outcome,
        symbol="BTCUSDT",
    )


# --------------------------------------------------------------------------- #
# Purging and embargo
# --------------------------------------------------------------------------- #


def test_a_case_that_has_not_resolved_is_invisible() -> None:
    """Its outcome has not happened yet. Consulting it is consulting the future."""
    index = SimilarityIndex(dimension(), embargo_ms=0)
    index.add(case(entry_days_ago=2, resolved_days_ago=-1, outcome=1.0))

    assert index.query(vector(), k=5, as_of_ms=NOW) == []


def test_a_case_inside_the_embargo_window_is_invisible() -> None:
    """It resolved, but its outcome overlaps the bar being judged.

    With a 48-hour outcome horizon, a case that resolved twelve hours ago had its
    result decided by the same price action currently under consideration. It is a
    partial copy of the present, not evidence about it.
    """
    index = SimilarityIndex(dimension(), embargo_ms=EMBARGO)
    index.add(case(entry_days_ago=3, resolved_days_ago=0.5, outcome=1.0))

    assert index.query(vector(), k=5, as_of_ms=NOW) == []

    older = SimilarityIndex(dimension(), embargo_ms=EMBARGO)
    older.add(case(entry_days_ago=10, resolved_days_ago=5, outcome=1.0))
    assert len(older.query(vector(), k=5, as_of_ms=NOW)) == 1


def test_the_admissible_mask_moves_with_time() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=EMBARGO)
    index.add(case(entry_days_ago=6, resolved_days_ago=4, outcome=1.0))

    assert not index.admissible(NOW - 5 * DAY).any(), "visible before it resolved"
    assert not index.admissible(NOW - 3 * DAY).any(), "visible inside the embargo"
    assert index.admissible(NOW).any()


def test_a_query_needs_an_explicit_as_of() -> None:
    """No default, on purpose: an optional time bound is a forgettable one, and
    forgetting it is a silent leak rather than an error."""
    index = SimilarityIndex(dimension(), embargo_ms=EMBARGO)
    with pytest.raises(TypeError):
        index.query(vector(), k=5)  # type: ignore[call-arg]


def test_neighbours_come_back_nearest_first() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=0)
    target = np.zeros(dimension())
    for i, scale in enumerate((0.1, 0.5, 2.0)):
        index.add(
            Case(
                fingerprint=np.full(dimension(), scale / np.sqrt(dimension())),
                entry_ts=NOW - 100 * DAY,
                resolved_ts=NOW - 99 * DAY,
                outcome_r=float(i),
                symbol="BTCUSDT",
            )
        )

    found = index.query(target, k=3, as_of_ms=NOW)

    assert [n.outcome_r for n in found] == [0.0, 1.0, 2.0]
    assert found[0].distance < found[1].distance < found[2].distance


def test_a_distance_ceiling_keeps_strangers_out() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=0)
    index.add(
        Case(
            fingerprint=np.full(dimension(), 5.0),
            entry_ts=NOW - 100 * DAY,
            resolved_ts=NOW - 99 * DAY,
            outcome_r=1.0,
            symbol="BTCUSDT",
        )
    )
    assert index.query(np.zeros(dimension()), k=5, as_of_ms=NOW, max_distance=1.0) == []


def test_one_symbol_can_be_excluded() -> None:
    """Supports the strictest question: does a pattern learned elsewhere transfer?"""
    index = SimilarityIndex(dimension(), embargo_ms=0)
    for symbol in ("BTCUSDT", "ETHUSDT"):
        index.add(
            Case(
                fingerprint=vector(1),
                entry_ts=NOW - 100 * DAY,
                resolved_ts=NOW - 99 * DAY,
                outcome_r=1.0,
                symbol=symbol,
            )
        )

    found = index.query(vector(1), k=5, as_of_ms=NOW, exclude_symbol="BTCUSDT")

    assert [n.symbol for n in found] == ["ETHUSDT"]


def test_a_case_cannot_resolve_before_it_started() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=0)
    with pytest.raises(ValueError, match="resolve before"):
        index.add(case(entry_days_ago=1, resolved_days_ago=2, outcome=1.0))


def test_a_wrongly_shaped_fingerprint_is_refused() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=0)
    with pytest.raises(ValueError, match="features"):
        index.add(
            Case(
                fingerprint=np.zeros(3),
                entry_ts=NOW,
                resolved_ts=NOW,
                outcome_r=0.0,
            )
        )


def test_the_index_grows_past_its_first_allocation() -> None:
    index = SimilarityIndex(dimension(), embargo_ms=0)
    for i in range(5000):
        index.add(
            case(
                entry_days_ago=500 - i * 0.05,
                resolved_days_ago=499 - i * 0.05,
                outcome=1.0,
                seed=i,
            )
        )
    assert len(index) == 5000
    assert len(index.query(vector(3), k=10, as_of_ms=NOW)) == 10


# --------------------------------------------------------------------------- #
# Not counting the same episode twice
# --------------------------------------------------------------------------- #


def test_neighbours_from_the_same_episode_collapse() -> None:
    """Consecutive hourly bars in one move look nearly identical.

    Counting twenty of them as twenty independent cases inflates the sample by an
    order of magnitude, and the sample size is what unlocks larger positions.
    """
    # Twenty bars half an hour apart: ten hours, inside the separation window.
    one_episode = [
        Neighbour(
            distance=0.1 + i * 0.01,
            outcome_r=1.0,
            ts=NOW - 100 * DAY + i * (HOUR_MS // 2),
            symbol="B",
        )
        for i in range(20)
    ]
    assert len(deduplicate(one_episode)) == 1

    # A run spanning several separation windows is several episodes, and counting
    # it as one would be the opposite mistake.
    longer = [
        Neighbour(
            distance=0.1 + i * 0.01,
            outcome_r=1.0,
            ts=NOW - 100 * DAY + i * HOUR_MS,
            symbol="B",
        )
        for i in range(48)
    ]
    kept = deduplicate(longer)
    assert 2 <= len(kept) <= 5, f"48 hours collapsed to {len(kept)} episodes"


def test_genuinely_separate_episodes_all_count() -> None:
    spread = [
        Neighbour(
            distance=0.2,
            outcome_r=1.0,
            ts=NOW - 100 * DAY + i * (MIN_SEPARATION_MS * 2),
            symbol="B",
        )
        for i in range(5)
    ]
    assert len(deduplicate(spread)) == 5


def test_the_closest_match_survives_a_collapse() -> None:
    cluster = [
        Neighbour(distance=0.9, outcome_r=-1.0, ts=NOW, symbol="B"),
        Neighbour(distance=0.1, outcome_r=+1.0, ts=NOW + HOUR_MS, symbol="B"),
    ]
    kept = deduplicate(cluster)
    assert len(kept) == 1
    assert kept[0].outcome_r == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Refusing to quote a rate that is not supported
# --------------------------------------------------------------------------- #


def test_a_thin_sample_reports_no_rate_at_all() -> None:
    """Four cases at 75% is three wins, not a 75% win rate."""
    thin = [
        Neighbour(distance=0.2, outcome_r=r, ts=NOW - (100 + i * 5) * DAY, symbol="B")
        for i, r in enumerate([1.0, 1.0, 1.0, -1.0])
    ]
    stats, _ = summarise(thin, min_samples=30)

    assert stats.similar_situations_found == 4
    assert stats.historical_winrate is None
    assert stats.mean_r_multiple is None
    assert stats.sample_is_sufficient is False


def test_a_sufficient_sample_reports_the_numbers() -> None:
    many = [
        Neighbour(
            distance=0.2,
            outcome_r=1.0 if i % 3 else -1.0,
            ts=NOW - (100 + i * 2) * DAY,
            symbol="B",
        )
        for i in range(40)
    ]
    stats, quality = summarise(many, min_samples=30)

    assert stats.sample_is_sufficient is True
    assert stats.historical_winrate is not None
    assert 0.0 < stats.historical_winrate < 1.0
    assert quality.independent == 40


def test_an_empty_neighbourhood_is_reported_as_empty() -> None:
    stats, quality = summarise([], min_samples=30, regime=RegimeKind.RANGE)
    assert stats.similar_situations_found == 0
    assert stats.sample_is_sufficient is False
    assert quality.independent == 0


# --------------------------------------------------------------------------- #
# Fingerprints
# --------------------------------------------------------------------------- #


def test_a_fingerprint_has_the_declared_shape() -> None:
    assert fingerprint(make_snapshot()).shape == (dimension(),)
    assert len(feature_names()) == dimension()


def test_a_fingerprint_carries_no_price_or_scale() -> None:
    """Otherwise it would only match the same instrument at the same level, which
    is almost never -- and four thin histories would never become one usable one."""
    cheap = make_snapshot(price=100.0, atr=1.0)
    dear = make_snapshot(price=100_000.0, atr=1000.0)

    np.testing.assert_allclose(fingerprint(cheap), fingerprint(dear), atol=1e-12)


def test_a_different_market_state_gives_a_different_fingerprint() -> None:
    calm = make_snapshot()
    wild = make_snapshot(
        frames=[
            make_timeframe_view(
                tf, trend=Bias.BEARISH, volatility=VolBucket.EXTREME, regime=RegimeKind.TREND_DOWN
            )
            for tf in (Timeframe.W1, Timeframe.D1, Timeframe.H4, Timeframe.H1, Timeframe.M15)
        ]
    )
    assert np.linalg.norm(fingerprint(calm) - fingerprint(wild)) > 1.0


# --------------------------------------------------------------------------- #
# The engine, walk-forward by construction
# --------------------------------------------------------------------------- #


@pytest.fixture
def history_config() -> HistoryConfig:
    return load_config().engine.history


def test_a_setup_enters_the_index_only_when_it_resolves(history_config: HistoryConfig) -> None:
    engine = HistoryEngine(history_config)
    snapshot = make_snapshot()

    engine.remember("trade-1", snapshot)
    assert engine.cases == 0, "an open trade was indexed before it had an outcome"
    assert engine.unresolved == 1

    engine.resolve("trade-1", outcome_r=1.5, resolved_ts=snapshot.ts + 4 * HOUR_MS)
    assert engine.cases == 1
    assert engine.unresolved == 0


def test_an_entry_that_never_filled_is_dropped(history_config: HistoryConfig) -> None:
    """It has no outcome. Recording it as a zero would put a trade that never
    happened into the evidence."""
    engine = HistoryEngine(history_config)
    engine.remember("trade-1", make_snapshot())
    engine.forget("trade-1")

    assert engine.cases == 0
    assert engine.unresolved == 0


def test_resolving_something_unknown_is_a_no_op(history_config: HistoryConfig) -> None:
    engine = HistoryEngine(history_config)
    assert engine.resolve("never-seen", outcome_r=1.0, resolved_ts=NOW) is False


def test_an_empty_index_reports_nothing_rather_than_guessing(
    history_config: HistoryConfig,
) -> None:
    stats, _ = HistoryEngine(history_config).lookup(make_snapshot())

    assert stats.similar_situations_found == 0
    assert stats.sample_is_sufficient is False
    assert stats.historical_winrate is None


def test_a_lookup_cannot_see_a_case_from_its_own_future(
    history_config: HistoryConfig,
) -> None:
    """The property the whole subsystem exists for.

    A case recorded with a later timestamp must be invisible to a lookup made
    earlier, no matter how similar it is.
    """
    engine = HistoryEngine(history_config)
    past = make_snapshot(ts=NOW - 400 * DAY)
    future = make_snapshot(ts=NOW + 100 * DAY)

    engine.remember("future", future)
    engine.resolve("future", outcome_r=3.0, resolved_ts=future.ts + DAY)

    stats, _ = engine.lookup(past)
    assert stats.similar_situations_found == 0
