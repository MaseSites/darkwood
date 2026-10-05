"""The panel's leak tests, which are the only ones that matter much.

Every other property here can be eyeballed from the code. Whether a feature at
day D is influenced by day D+1 cannot, and it is the failure that makes a
backtest look good and a live run disappoint. So the first test mutates the
future and demands the past not move.
"""

from __future__ import annotations

from itertools import pairwise

import numpy as np
import pandas as pd
import pytest

from traidingbrain.learn.panel import (
    DAY_MS,
    GROUPS,
    HOUR_MS,
    SOURCES,
    WARMUP_DAYS,
    Panel,
    Provenance,
    as_of,
    build_panel,
    check_provenance,
    common_window,
    daily_prices,
    label,
    price_features,
    walk_forward,
)

START_MS = 1_700_000_000_000 // DAY_MS * DAY_MS


def candles(days: int, *, seed: int = 7, drift: float = 0.0) -> pd.DataFrame:
    """Hourly candles on an exact grid, so a daily row exists for every day."""
    rng = np.random.default_rng(seed)
    hours = days * 24
    stamps = START_MS + np.arange(hours, dtype="int64") * HOUR_MS
    steps = rng.normal(loc=drift, scale=0.004, size=hours)
    close = 100.0 * np.exp(np.cumsum(steps))
    open_ = np.concatenate([[100.0], close[:-1]])
    spread = np.abs(rng.normal(scale=0.003, size=hours)) * close
    return pd.DataFrame(
        {
            "ts": stamps,
            "open": open_,
            "high": np.maximum(open_, close) + spread,
            "low": np.minimum(open_, close) - spread,
            "close": close,
            "volume": rng.uniform(50, 150, size=hours),
        }
    )


def test_features_do_not_move_when_the_future_changes() -> None:
    """The one test that catches repainting, leaked labels and bad rolling windows.

    Build the features, then replace every bar after a cut with noise and build
    them again. Rows up to the cut must be byte-identical. If any statistic
    reaches forward -- a centred window, a shift with the wrong sign, a
    normalisation over the whole series -- this fails and nothing else here
    would.
    """
    frame = candles(220)
    cut_day = 150
    cut_ms = START_MS + cut_day * DAY_MS

    before = price_features(daily_prices(frame))
    mutated = frame.copy()
    rng = np.random.default_rng(99)
    future = mutated["ts"] > cut_ms
    for column in ("open", "high", "low", "close", "volume"):
        mutated.loc[future, column] = rng.uniform(1.0, 5000.0, size=int(future.sum()))
    after = price_features(daily_prices(mutated))

    columns = [c for c in before.columns if c.startswith("%")]
    kept = before["decision_ms"] <= cut_ms
    pd.testing.assert_frame_equal(
        before.loc[kept, columns].reset_index(drop=True),
        after.loc[after["decision_ms"] <= cut_ms, columns].reset_index(drop=True),
        check_exact=True,
    )


def test_the_mutation_test_can_actually_fail() -> None:
    """A control: a deliberately forward-looking feature must be caught.

    Without this, the test above could be passing because the comparison is
    vacuous -- which is exactly how an earlier control test in this project
    gave a correlation of 1.0 whether the indexing was right or wrong.
    """
    frame = candles(120)
    cut_ms = START_MS + 80 * DAY_MS

    def leaky(daily: pd.DataFrame) -> pd.DataFrame:
        out = daily.copy()
        out["%tomorrow"] = out["open"].shift(-1) / out["open"] - 1.0
        return out

    before = leaky(daily_prices(frame))
    mutated = frame.copy()
    mutated.loc[mutated["ts"] > cut_ms, "open"] = 999.0
    after = leaky(daily_prices(mutated))

    kept = before["decision_ms"] <= cut_ms
    with pytest.raises(AssertionError):
        pd.testing.assert_frame_equal(
            before.loc[kept, ["%tomorrow"]].reset_index(drop=True),
            after.loc[after["decision_ms"] <= cut_ms, ["%tomorrow"]].reset_index(drop=True),
            check_exact=True,
        )


def test_as_of_respects_the_publication_lag() -> None:
    """A funding rate settling at the end of its interval is not readable at the start."""
    base = pd.DataFrame({"decision_ms": [START_MS + 2 * DAY_MS]})
    # Stamped exactly at the decision time, but it settles eight hours later.
    other = pd.DataFrame({"ts": [START_MS + 2 * DAY_MS], "rate": [0.01]})

    without_lag = as_of(
        base, other, column="rate", name="%f", lag_ms=0, max_stale_ms=10 * DAY_MS
    )
    with_lag = as_of(
        base, other, column="rate", name="%f", lag_ms=8 * HOUR_MS, max_stale_ms=10 * DAY_MS
    )

    assert without_lag["%f"].iloc[0] == pytest.approx(0.01)
    assert np.isnan(with_lag["%f"].iloc[0]), "Die Rate war zur Entscheidungszeit nicht bekannt"


def test_as_of_never_reaches_forward() -> None:
    """Only values already available may be matched, for every decision point."""
    decisions = START_MS + np.arange(10) * DAY_MS
    base = pd.DataFrame({"decision_ms": decisions})
    other = pd.DataFrame(
        {"ts": decisions, "value": np.arange(10, dtype="float64")}
    )
    joined = as_of(
        base, other, column="value", name="%v", lag_ms=DAY_MS, max_stale_ms=30 * DAY_MS
    )
    # With a one-day lag, row i may see at most value i-1.
    for i, value in enumerate(joined["%v"]):
        if np.isnan(value):
            continue
        assert value <= i - 1 + 1e-9, f"Zeile {i} sah Wert {value}"


def test_as_of_drops_a_value_that_is_too_old() -> None:
    """A series that stopped must not keep supplying its last value forever."""
    base = pd.DataFrame({"decision_ms": [START_MS + 100 * DAY_MS]})
    other = pd.DataFrame({"ts": [START_MS], "value": [1.0]})
    joined = as_of(
        base, other, column="value", name="%v", lag_ms=0, max_stale_ms=3 * DAY_MS
    )
    assert np.isnan(joined["%v"].iloc[0])


def test_label_is_open_to_open_and_forward() -> None:
    daily = daily_prices(candles(60))
    got = label(daily, horizon_hours=72)
    opens = daily["open"].to_numpy()
    assert got.iloc[0] == pytest.approx(opens[3] / opens[0] - 1.0)
    # The last three rows cannot have a 72h label.
    assert got.iloc[-3:].isna().all()


def test_label_refuses_a_horizon_shorter_than_a_row() -> None:
    daily = daily_prices(candles(30))
    with pytest.raises(ValueError, match="kuerzer als eine Tageszeile"):
        label(daily, horizon_hours=12)


def test_walk_forward_purges_rows_whose_label_crosses_the_boundary() -> None:
    stamps = START_MS + np.arange(400) * DAY_MS
    folds = walk_forward(stamps, folds=3, horizon_hours=168, embargo_days=1)

    assert len(folds) == 3
    for fold in folds:
        assert fold.purged > 0, "Ein 168h-Label muss an jeder Grenze Zeilen kosten"
        # Every training row's label must close at or before the boundary.
        latest = stamps[fold.train].max()
        assert latest + 168 * HOUR_MS <= fold.boundary_ms
        # And validation must start after the embargo.
        assert stamps[fold.validate].min() > fold.boundary_ms


def test_a_longer_horizon_purges_more() -> None:
    stamps = START_MS + np.arange(400) * DAY_MS
    purged = [
        sum(f.purged for f in walk_forward(stamps, folds=3, horizon_hours=h))
        for h in (24, 72, 168)
    ]
    assert purged == sorted(purged)
    assert purged[0] < purged[-1]


def test_folds_split_on_timestamps_so_markets_stay_together() -> None:
    """Twelve markets on one day must land on the same side of every boundary.

    This is the panel leak: a flat table split by row index puts BTC's Tuesday
    in training and ETH's Tuesday in validation, and the two are correlated
    enough that the model simply reads the answer across.
    """
    days = START_MS + np.arange(200) * DAY_MS
    markets = 12
    stamps = np.repeat(days, markets)

    for fold in walk_forward(stamps, folds=3, horizon_hours=24):
        train_days = set(stamps[fold.train].tolist())
        validate_days = set(stamps[fold.validate].tolist())
        assert not (train_days & validate_days), "Ein Tag liegt auf beiden Seiten"
        # And every market of a training day is present, not a subset.
        for day in train_days:
            assert int((stamps[fold.train] == day).sum()) == markets


def test_walk_forward_refuses_too_few_timestamps() -> None:
    with pytest.raises(ValueError, match="reichen nicht"):
        walk_forward(START_MS + np.arange(3) * DAY_MS, folds=5, horizon_hours=24)


def test_provenance_gate_blocks_the_derivative_group() -> None:
    """P+D needs sources whose origin this project cannot state."""
    with pytest.raises(ValueError, match="ohne belegte Herkunft"):
        check_provenance("P+D", allow_unverified=False)

    suspect, notes = check_provenance("P+D", allow_unverified=True)
    assert any("open_interest" in s for s in suspect)
    assert any("account_ratio" in s for s in suspect)
    assert any("funding" in s for s in suspect)
    assert notes, "Der Stempel muss sagen, was bekannt ist"


def test_provenance_gate_lets_the_price_group_through() -> None:
    suspect, notes = check_provenance("P", allow_unverified=False)
    assert suspect == ()
    assert notes == ()


def test_provenance_gate_reports_a_missing_connector_separately() -> None:
    """macro and onchain are absent, which is not the same as unexplained."""
    suspect, _ = check_provenance("P+D+M", allow_unverified=True)
    assert any("kein Connector" in s for s in suspect)


def test_unknown_group_is_refused() -> None:
    with pytest.raises(ValueError, match="nicht angemeldet"):
        check_provenance("P+X", allow_unverified=True)


def test_every_group_is_nested_in_the_next() -> None:
    """A comparison across groups only means something if they are nested."""
    order = ["P", "P+D", "P+D+M", "P+D+M+O"]
    # pairwise, not zip(xs, xs[1:], strict=True) -- offset slices have
    # different lengths by construction, so strict always raises. This
    # project has made that exact mistake before, in backfill_flow.py.
    for smaller, larger in pairwise(order):
        assert set(GROUPS[smaller]) <= set(GROUPS[larger])


def test_build_panel_produces_rows_and_drops_the_warmup() -> None:
    frames = {"BTCUSDT": candles(260, seed=1), "ETHUSDT": candles(260, seed=2)}
    panel = build_panel(
        markets=["BTCUSDT", "ETHUSDT"],
        group="P",
        horizon_hours=72,
        read_ohlcv=frames.get,
    )
    assert panel.trustworthy
    assert panel.frame["market"].nunique() == 2
    assert panel.features
    assert all(f.startswith("%") for f in panel.features)
    # The warmup rows are gone, so no partially-warm statistic survives.
    first_day = (panel.frame["ts"].min() - START_MS) // DAY_MS
    assert first_day >= WARMUP_DAYS
    # And no feature or label is missing.
    assert not panel.frame[[*panel.features, "target"]].isna().to_numpy().any()


def test_build_panel_keeps_markets_aligned_on_timestamps() -> None:
    frames = {"BTCUSDT": candles(260, seed=1), "ETHUSDT": candles(260, seed=2)}
    panel = build_panel(
        markets=["BTCUSDT", "ETHUSDT"], group="P", horizon_hours=24, read_ohlcv=frames.get
    )
    counts = panel.frame.groupby("ts").size()
    assert set(counts.unique()) == {2}, "Jeder Zeitpunkt muss beide Maerkte tragen"


def test_build_panel_refuses_unverified_sources_by_default() -> None:
    frames = {"BTCUSDT": candles(260)}
    with pytest.raises(ValueError, match="ohne belegte Herkunft"):
        build_panel(
            markets=["BTCUSDT"], group="P+D", horizon_hours=24, read_ohlcv=frames.get
        )


def test_build_panel_stamps_a_run_on_unverified_data() -> None:
    frames = {"BTCUSDT": candles(260)}
    panel = build_panel(
        markets=["BTCUSDT"],
        group="P+D",
        horizon_hours=24,
        read_ohlcv=frames.get,
        read_extra=lambda _m, _s: pd.DataFrame(columns=["ts", "value"]),
        allow_unverified=True,
    )
    assert not panel.trustworthy
    assert "HERKUNFT UNGEKLAERT" in panel.describe()


def test_build_panel_refuses_an_empty_universe() -> None:
    with pytest.raises(ValueError, match="Keine Marktdaten"):
        build_panel(
            markets=["NOPE"], group="P", horizon_hours=24, read_ohlcv=lambda _m: None
        )


def test_common_window_restricts_to_shared_rows() -> None:
    frames = {"BTCUSDT": candles(260, seed=1)}
    wide = build_panel(
        markets=["BTCUSDT"], group="P", horizon_hours=24, read_ohlcv=frames.get
    )
    # A second panel covering half the days, as a source starting later would.
    half = wide.frame.iloc[: len(wide.frame) // 2].reset_index(drop=True)
    narrow = Panel(
        frame=half, features=wide.features, horizon_hours=24, group="P+D"
    )

    trimmed = common_window([wide, narrow])
    assert len({len(p.frame) for p in trimmed}) == 1
    assert len(trimmed[0].frame) == len(half)
    assert any("gemeinsames Fenster" in n for n in trimmed[0].notes)


def test_common_window_refuses_disjoint_panels() -> None:
    frames = {"BTCUSDT": candles(260, seed=1)}
    first = build_panel(
        markets=["BTCUSDT"], group="P", horizon_hours=24, read_ohlcv=frames.get
    )
    shifted = first.frame.copy()
    shifted["ts"] = shifted["ts"] + 10_000 * DAY_MS
    second = Panel(frame=shifted, features=first.features, horizon_hours=24, group="P+D")
    with pytest.raises(ValueError, match="kein gemeinsames Beobachtungsfenster"):
        common_window([first, second])


def test_daily_prices_takes_the_midnight_open() -> None:
    frame = candles(10)
    daily = daily_prices(frame)
    assert len(daily) == 10
    assert (daily["decision_ms"] % DAY_MS == 0).all()
    midnight = frame[frame["ts"] == START_MS]
    assert daily["open"].iloc[0] == pytest.approx(midnight["open"].iloc[0])


def test_daily_prices_survives_candles_off_the_grid() -> None:
    """A series with no midnight candle yields no rows rather than wrong ones."""
    frame = candles(10)
    frame["ts"] = frame["ts"] + 137  # nothing lands on a day boundary
    assert daily_prices(frame).empty


def test_the_register_marks_exactly_the_sources_coverage_questioned() -> None:
    """The gate must agree with what `scripts/coverage.py` actually found.

    Verified: our own OHLCV backfill, the flow fetch checked against a live
    candle, and the Alternative.me sentiment pull. Not verified: funding (two
    venues in one set) and the two derivative files (they predate what the
    script that fetches them can serve).
    """
    assert SOURCES["ohlcv"][0] is Provenance.VERIFIED
    assert SOURCES["flow"][0] is Provenance.VERIFIED
    assert SOURCES["sentiment"][0] is Provenance.VERIFIED
    assert SOURCES["funding"][0] is Provenance.MIXED
    assert SOURCES["open_interest"][0] is Provenance.UNKNOWN
    assert SOURCES["account_ratio"][0] is Provenance.UNKNOWN
    # Every unverified source carries a note saying what is known about it.
    for name, (state, _, note) in SOURCES.items():
        if state is not Provenance.VERIFIED:
            assert len(note) > 40, f"{name} hat keine brauchbare Begruendung"


def test_lags_are_declared_for_every_source_a_group_uses() -> None:
    """A source without a declared lag would be joined at zero staleness."""
    for sources in GROUPS.values():
        for source in sources:
            if source in ("macro", "onchain"):
                continue  # no connector yet; absence, not a missing lag
            assert source in SOURCES, f"{source} fehlt im Register"
            assert SOURCES[source][1] >= 0
