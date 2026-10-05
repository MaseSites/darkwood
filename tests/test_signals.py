"""The ledger of signals that never traded.

Two properties carry its purpose and both are asserted directly:

1. **A refusal and an occupied account are different rows.** Mixing them is the
   confound that made every journal-based filter result on 04.10.2026
   unreadable, and a schema that could not tell them apart would reproduce it.
2. **Writing is append-only.** The trade journal next door upserts, so
   re-running a replay silently rewrites the stored reason -- which section 6
   forbids. A re-run here under unchanged settings must be a no-op, and under
   changed settings must add rows beside the old ones rather than over them.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from traidingbrain.domain.enums import Rule, Side
from traidingbrain.journal.record import Source
from traidingbrain.journal.signals import Action, SignalRecord, SignalStore

EPOCH = 1_600_000_000_000
QUARTER = 900_000
SIGNATURE = "1000.0|['A', 'B', 'E', 'F', 'G']|0.15|M15"


def record(**overrides: object) -> SignalRecord:
    defaults: dict[str, object] = {
        "signal_id": "BTCUSDT-1600000000000-A",
        "run_signature": SIGNATURE,
        "decided_ts": EPOCH,
        "symbol": "BTCUSDT",
        "source": Source.REPLAY,
        "action": Action.REFUSED,
        "refused_by": Rule.COSTS,
        "detail": "Kosten 22.0% des Risikos, erlaubt sind 15.0%",
        "setup_key": "A",
        "setup_timeframe": "H4",
        "signal_timeframe": "M15",
        "side": Side.LONG,
        "entry": 100.0,
        "stop": 99.5,
        "target": 101.0,
        "reward_risk": 2.0,
        "cost_fraction": 0.22,
        "risk_amount": 10.0,
        "qty": 20.0,
        "leverage": 5.0,
    }
    return SignalRecord(**(defaults | overrides))  # type: ignore[arg-type]


@pytest.fixture
def store(tmp_path: Path) -> SignalStore:
    return SignalStore(tmp_path / "signals.sqlite")


# --------------------------------------------------------------------------- #
# What the ledger is for
# --------------------------------------------------------------------------- #


def test_a_refused_signal_survives_with_the_rule_that_refused_it(store: SignalStore) -> None:
    """The whole point. This used to be one increment of a counter."""
    assert store.record([record()]) == 1
    [back] = store.all()
    assert back.action is Action.REFUSED
    assert back.refused_by is Rule.COSTS
    assert back.cost_fraction == pytest.approx(0.22)
    assert "Kosten" in back.detail
    # And the plan is intact, so the signal can be labelled later.
    assert (back.entry, back.stop, back.target) == (100.0, 99.5, 101.0)
    assert back.side is Side.LONG
    assert back.stop_distance_pct == pytest.approx(0.5)


def test_refused_and_occupied_are_not_the_same_population(store: SignalStore) -> None:
    """A judgement the system made, against an accident of timing.

    `engine.py:201` only asks the strategy while the broker is flat, so a
    signal arriving during an open position is never examined at all. Counting
    that as a refusal would attribute it to a rule that never ran.
    """
    store.record(
        [
            record(signal_id="a", action=Action.REFUSED, refused_by=Rule.COSTS),
            record(signal_id="b", action=Action.OCCUPIED, refused_by=None, detail="Konto besetzt"),
            record(signal_id="c", action=Action.TAKEN, refused_by=None, detail="confidence 60"),
        ]
    )
    assert store.count(action=Action.REFUSED) == 1
    assert store.count(action=Action.OCCUPIED) == 1
    assert store.count(action=Action.TAKEN) == 1
    [occupied] = store.all(action=Action.OCCUPIED)
    assert occupied.refused_by is None, "no rule refused it; nothing looked at it"
    assert not occupied.tradeable


def test_the_rule_tally_says_which_hypothesis_to_test_first(store: SignalStore) -> None:
    store.record(
        [record(signal_id=f"cost-{i}", refused_by=Rule.COSTS) for i in range(7)]
        + [record(signal_id=f"rr-{i}", refused_by=Rule.REWARD_RISK) for i in range(3)]
        + [record(signal_id="taken", action=Action.TAKEN, refused_by=None)]
        + [record(signal_id="busy", action=Action.OCCUPIED, refused_by=None)]
    )
    tally = store.by_rule()
    assert tally == {"kosten": 7, "chance_risiko": 3, "genommen": 1, "besetzt": 1}
    # Sorted by size, so the first key is the rule worth asking about.
    assert next(iter(tally)) == "kosten"


# --------------------------------------------------------------------------- #
# Append-only
# --------------------------------------------------------------------------- #


def test_recording_the_same_run_twice_changes_nothing(store: SignalStore) -> None:
    """A replay re-run must be a no-op, not a rewrite."""
    assert store.record([record()]) == 1
    assert store.record([record()]) == 0, "the second write was not ignored"
    assert store.count() == 1


def test_a_verdict_is_never_amended_in_place(store: SignalStore) -> None:
    """Section 6: earlier decisions are not changed afterwards.

    The trade journal does upsert, which is how re-running a replay silently
    rewrote its own stored reasoning. Here the first verdict stands and a
    conflicting second write for the same configuration is dropped.
    """
    store.record([record(detail="erste Begruendung", cost_fraction=0.22)])
    store.record([record(detail="umgeschriebene Begruendung", cost_fraction=0.01)])
    [only] = store.all()
    assert only.detail == "erste Begruendung"
    assert only.cost_fraction == pytest.approx(0.22)


def test_a_changed_configuration_writes_beside_the_old_verdict(store: SignalStore) -> None:
    """Two eras, both readable.

    `journal/record.py` had to gain a field by hand when the cadence changed
    from hourly to fifteen minutes, and its docstring says the separation could
    not be reconstructed afterwards from anything else. The configuration is
    part of the key here so that never has to be done again.
    """
    store.record([record()])
    store.record([record(run_signature="1000.0|['A']|0.10|M15", refused_by=Rule.REWARD_RISK)])
    assert store.count() == 2
    assert store.count(run_signature=SIGNATURE) == 1
    assert store.by_rule(run_signature=SIGNATURE) == {"kosten": 1}


# --------------------------------------------------------------------------- #
# Shape
# --------------------------------------------------------------------------- #


def test_signals_come_back_in_decision_order(store: SignalStore) -> None:
    """Every interval in this project depends on the time order being right."""
    store.record(
        [
            record(signal_id="c", decided_ts=EPOCH + 2 * QUARTER),
            record(signal_id="a", decided_ts=EPOCH),
            record(signal_id="b", decided_ts=EPOCH + QUARTER),
        ]
    )
    assert [r.signal_id for r in store.all()] == ["a", "b", "c"]


def test_every_field_survives_the_round_trip(store: SignalStore) -> None:
    """Enums come back as enums, not as the strings they compare equal to.

    `journal/record.py:184` makes the same point: leaving a StrEnum as text
    works until the first `is` comparison or `match`, which is the bug that
    passes every test and fails once.
    """
    original = record(source=Source.LIVE, side=Side.SHORT, action=Action.TAKEN, refused_by=None)
    store.record([original])
    [back] = store.all()
    assert back == original
    assert back.source is Source.LIVE
    assert back.side is Side.SHORT
    assert back.action is Action.TAKEN


def test_replay_and_forward_signals_are_separable(store: SignalStore) -> None:
    """Never averaged together. The one rule the journal already enforces."""
    store.record(
        [record(signal_id="r", source=Source.REPLAY), record(signal_id="l", source=Source.LIVE)]
    )
    assert store.count(source=Source.LIVE) == 1
    assert store.count(source=Source.REPLAY) == 1


def test_an_empty_write_is_not_an_error(store: SignalStore) -> None:
    assert store.record([]) == 0
    assert store.count() == 0


def test_the_schema_has_nowhere_to_put_an_account_movement(tmp_path: Path) -> None:
    """A shadow case cannot be mistaken for a trade, structurally.

    Section 6 requires the shadow journal to be separate and to produce no real
    paper-account movements. Its own file and a schema with no equity, no fill
    and no profit field is what makes that a property rather than a promise.
    """
    path = tmp_path / "signals.sqlite"
    SignalStore(path)
    with sqlite3.connect(path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(signals)")}
    forbidden = {"equity", "net_pnl", "gross_pnl", "fees", "r_multiple", "exit_price", "balance"}
    assert not (columns & forbidden), (
        f"an outcome leaked into the signal ledger: {columns & forbidden}"
    )
