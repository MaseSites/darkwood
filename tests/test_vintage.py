"""Revisions: the leak the mutation test cannot see.

`test_no_lookahead.py` rewrites every bar after the decision point and demands
an identical snapshot. That catches a model reading forward in time. It cannot
catch the other direction, because it never happens to a price file: these
external services **restate history**. Coin Metrics marks recent rows `flash`
and revises them; FRED's `DTWEXBGS` is computed and can be restated. And
`ExternalStore.write` merges a restated row *over* its predecessor, newest
write winning.

So the same code, the same configuration, the same date range, run twice a
month apart, can produce two different panels. Nothing looks wrong. Both are
honest readings of what the file said at the time.

The research order asks for three things, and they have three different
answers:

**A future price cannot reach back.** Assertable, and asserted: mutate the
candles after a cut and the earlier feature rows are byte-identical.

**A macro value dated after the cut cannot reach back.** Also assertable. This
is the as-of join's whole job -- `available_ms = ts + lag_ms`, matched
backwards -- and it is worth a test of its own because a join written with
`direction="nearest"` would pass every other test in this file.

**A revision to a value dated BEFORE the cut does change the feature.** Not
assertable away, and pretending otherwise would be the lie. One vintage is
stored; the value that was published is gone unless the raw archive holds it.
What *is* assertable is that the two runs are never confused: the panel now
carries a fingerprint of the rows that built it, so a restated source produces
a visibly different `vintage_id`. The limitation stays. Silence about it does
not.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from traidingbrain.learn.panel import (
    DAY_MS,
    HOUR_MS,
    Panel,
    build_panel,
    source_fingerprint,
)

#: Long enough that rows survive `WARMUP_DAYS` (56) and still leave a usable
#: window on both sides of the cut.
DAYS = 160

#: The decision day the assertions are made at, in days from the start. Well
#: past the warmup so the row exists, well before the end so a mutation after
#: it has somewhere to live.
CUT_DAY = 120

HORIZON_HOURS = 24


def candles(*, mutate_from_day: int | None = None, seed: int = 7) -> pd.DataFrame:
    """Hourly candles with a deterministic random walk.

    `daily_prices` keeps only the 00:00 candle of each day, so a mutation that
    skipped those would be invisible and the test would be vacuous. This
    mutates every hour of the affected days.
    """
    rng = np.random.default_rng(seed)
    hours = DAYS * 24
    steps = rng.normal(0.0, 0.004, hours)
    price = 30_000.0 * np.exp(np.cumsum(steps))

    frame = pd.DataFrame(
        {
            "ts": np.arange(hours, dtype="int64") * HOUR_MS,
            "open": price,
            "high": price * 1.003,
            "low": price * 0.997,
            "close": price * (1.0 + steps * 0.5),
            "volume": 100.0 + rng.random(hours) * 10.0,
        }
    )

    if mutate_from_day is not None:
        cut_ms = mutate_from_day * DAY_MS
        after = frame["ts"] >= cut_ms
        assert after.any(), "the mutation window must contain rows"
        # A different world, not a nudge: a leak of any size shows up.
        shift = np.linspace(1.5, 4.0, int(after.sum()))
        for column in ("open", "high", "low", "close"):
            frame.loc[after, column] = frame.loc[after, column].to_numpy() * shift
        frame.loc[after, "volume"] = frame.loc[after, "volume"].to_numpy() * 9.0

    return frame


def macro(*, revise_day: int | None = None, seed: int = 11) -> pd.DataFrame:
    """A daily macro series with the per-row checksum the store writes.

    `revise_day` restates exactly one observation and gives it a new `sha256`,
    which is what a second fetch does to a row the service has changed.
    """
    rng = np.random.default_rng(seed)
    values = 100.0 + np.cumsum(rng.normal(0.0, 0.3, DAYS))
    frame = pd.DataFrame(
        {
            "ts": np.arange(DAYS, dtype="int64") * DAY_MS,
            "dollar_index": values,
            "sha256": ["fetch-one"] * DAYS,
        }
    )
    if revise_day is not None:
        row = frame["ts"] == revise_day * DAY_MS
        assert row.any(), f"day {revise_day} is not in the series"
        frame.loc[row, "dollar_index"] = float(frame.loc[row, "dollar_index"].iloc[0]) + 25.0
        frame.loc[row, "sha256"] = "fetch-two"
    return frame


def panel_from(prices: pd.DataFrame, series: pd.DataFrame | None) -> Panel:
    group = "P" if series is None else "P+M"

    def read_ohlcv(_market: str) -> pd.DataFrame:
        return prices

    def read_extra(_market: str, source: str) -> pd.DataFrame:
        if source == "macro" and series is not None:
            return series
        return pd.DataFrame()

    return build_panel(
        markets=["TESTUSDT"],
        group=group,
        horizon_hours=HORIZON_HOURS,
        read_ohlcv=read_ohlcv,
        read_extra=read_extra,
    )


def features_before_cut(panel: Panel) -> pd.DataFrame:
    """Feature rows strictly before the cut, in a comparable order.

    The emptiness check is not decoration. Two empty frames compare equal,
    so a panel that produced no rows before the cut would make every
    assertion in this file pass while testing nothing.
    """
    frame = panel.frame
    kept = frame.loc[frame["ts"] < CUT_DAY * DAY_MS]
    assert len(kept) > 20, f"only {len(kept)} rows before the cut -- nothing is being compared"
    assert panel.features, "the panel carries no features"
    return kept.loc[:, panel.features].reset_index(drop=True)


# --------------------------------------------------------------------------
# A. a future price cannot reach back
# --------------------------------------------------------------------------


def test_prices_after_the_cut_do_not_move_earlier_features() -> None:
    clean = panel_from(candles(), macro())
    mutated = panel_from(candles(mutate_from_day=CUT_DAY), macro())

    pd.testing.assert_frame_equal(
        features_before_cut(clean),
        features_before_cut(mutated),
        check_exact=True,
    )


def test_that_mutation_actually_changed_the_panel() -> None:
    """Without this, the test above passes on a panel that ignored the data."""
    clean = panel_from(candles(), macro())
    mutated = panel_from(candles(mutate_from_day=CUT_DAY), macro())

    # The label of a row shortly before the cut looks forward into the
    # mutated region, so it must differ. That is the same forward reach the
    # features are forbidden.
    late = CUT_DAY * DAY_MS - DAY_MS
    clean_target = clean.frame.loc[clean.frame["ts"] == late, "target"]
    mutated_target = mutated.frame.loc[mutated.frame["ts"] == late, "target"]
    assert not clean_target.empty, "the row before the cut must exist"
    assert float(clean_target.iloc[0]) != pytest.approx(float(mutated_target.iloc[0])), (
        "the mutation did not even change the forward label, so nothing was tested"
    )


# --------------------------------------------------------------------------
# B. a macro value dated after the cut cannot reach back
# --------------------------------------------------------------------------


def test_a_macro_revision_after_the_cut_does_not_reach_back() -> None:
    prices = candles()
    clean = panel_from(prices, macro())
    revised = panel_from(prices, macro(revise_day=CUT_DAY + 10))

    pd.testing.assert_frame_equal(
        features_before_cut(clean),
        features_before_cut(revised),
        check_exact=True,
    )


def test_the_as_of_join_respects_the_publication_lag() -> None:
    """A same-day macro value is not readable on that day.

    `macro` carries `lag_ms = DAY_MS`, so the observation dated D becomes
    available at D+1. Revising the observation dated exactly at the cut must
    therefore leave the cut row itself untouched -- and change the next day.
    """
    prices = candles()
    clean = panel_from(prices, macro())
    revised = panel_from(prices, macro(revise_day=CUT_DAY))

    at_cut = CUT_DAY * DAY_MS
    next_day = at_cut + DAY_MS
    column = next(c for c in clean.features if c.startswith("%macro_"))

    def value(panel: Panel, ts: int) -> float:
        row = panel.frame.loc[panel.frame["ts"] == ts, column]
        assert not row.empty, f"row {ts} missing"
        return float(row.iloc[0])

    assert value(clean, at_cut) == pytest.approx(value(revised, at_cut)), (
        "an observation dated today was read today -- the lag is not applied"
    )
    assert value(clean, next_day) != pytest.approx(value(revised, next_day)), (
        "the revision never arrived at all, so the join is not reading the series"
    )


# --------------------------------------------------------------------------
# C. a revision to the past does change the feature, and must be visible
# --------------------------------------------------------------------------


def test_a_past_revision_changes_the_feature_and_this_is_not_hidden() -> None:
    """The honest half. One vintage is stored, so the old value is gone.

    What must hold is that the two panels are distinguishable. Before the
    `vintages` field they were not: same group, same notes, same row count,
    different numbers.
    """
    prices = candles()
    original = panel_from(prices, macro())
    restated = panel_from(prices, macro(revise_day=CUT_DAY - 40))

    column = next(c for c in original.features if c.startswith("%macro_"))
    before = original.frame.loc[:, column].to_numpy()
    after = restated.frame.loc[:, column].to_numpy()
    assert not np.allclose(before, after), (
        "a restated past observation left the features identical, which would "
        "mean the macro series is not reaching the model at all"
    )

    assert original.vintage_id != restated.vintage_id, (
        "two panels built from different vintages carry the same id -- a result "
        "recorded under it cannot be reproduced"
    )


def test_the_same_data_twice_gives_the_same_vintage_id() -> None:
    """Otherwise the field above reports a change on every single run."""
    first = panel_from(candles(), macro())
    second = panel_from(candles(), macro())
    assert first.vintage_id == second.vintage_id
    assert first.vintages == second.vintages


def test_a_restated_price_file_also_changes_the_vintage() -> None:
    """Candles carry no checksum, so they take the content-hash path."""
    original = panel_from(candles(), macro())
    restated = panel_from(candles(mutate_from_day=CUT_DAY), macro())
    assert original.vintage_id != restated.vintage_id


def test_the_vintage_names_every_contributing_source() -> None:
    panel = panel_from(candles(), macro())
    assert [source for source, _ in panel.vintages] == ["macro", "ohlcv"]
    assert "Datenstand" in panel.describe()


def test_a_panel_without_a_recorded_vintage_says_so() -> None:
    """The default is empty, and an empty one must not read as a clean bill."""
    bare = Panel(frame=pd.DataFrame(), features=[], horizon_hours=24, group="P")
    assert "UNBEKANNT" in bare.describe()


# --------------------------------------------------------------------------
# the fingerprint itself
# --------------------------------------------------------------------------


def test_the_fingerprint_prefers_the_stored_checksum_over_the_content() -> None:
    """Provenance, not a restatement of the bytes.

    Two frames whose values differ but whose `sha256` is the same came from
    the same fetch; one of them has been edited after the fact. The
    fingerprint reports the fetch, because that is the question it answers.
    """
    one = pd.DataFrame({"ts": [0, DAY_MS], "v": [1.0, 2.0], "sha256": ["a", "a"]})
    two = pd.DataFrame({"ts": [0, DAY_MS], "v": [1.0, 99.0], "sha256": ["a", "a"]})
    assert source_fingerprint(one) == source_fingerprint(two)

    three = pd.DataFrame({"ts": [0, DAY_MS], "v": [1.0, 2.0], "sha256": ["a", "b"]})
    assert source_fingerprint(one) != source_fingerprint(three)


def test_the_fingerprint_falls_back_to_content_without_a_checksum() -> None:
    one = pd.DataFrame({"ts": [0, DAY_MS], "v": [1.0, 2.0]})
    two = pd.DataFrame({"ts": [0, DAY_MS], "v": [1.0, 99.0]})
    assert source_fingerprint(one) != source_fingerprint(two)
    assert source_fingerprint(one) == source_fingerprint(one.copy())


def test_column_order_does_not_change_the_fingerprint() -> None:
    """A reordered read is the same data, and must not look like a revision."""
    one = pd.DataFrame({"ts": [0, DAY_MS], "a": [1.0, 2.0], "b": [3.0, 4.0]})
    two = one.loc[:, ["b", "a", "ts"]]
    assert source_fingerprint(one) == source_fingerprint(two)
