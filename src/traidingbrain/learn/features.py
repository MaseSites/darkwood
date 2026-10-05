"""What the model may look at, and the reason the list is a closed one.

Every feature here is computed from a `SignalRecord` and nothing else. That is
not a convention, it is the guarantee: a `SignalRecord` is written before the
market answers and has no outcome field to read, so a function whose only
argument is one cannot see the future even by accident. The alternative --
building features from a `Fill` and promising to use only the early fields --
is what went wrong on 04.10.2026.

**The trap, recorded because it nearly shipped.** A study here reported that
winners had a cost fraction of 3.35% against losers' 6.35%, with a tight
interval and +0.6513 R as a rule. The ratio 6.350/3.350 is 1.896 and the two
fee schedules differ by 1.875: a winner leaves at its target and pays maker, a
loser leaves at its stop and pays taker. "Winners had lower costs" was
"winners exited at the target" wearing a plausible name, and it was sitting in
the column labelled knowable-at-entry. The honest version -- the planned cost,
priced at taker on both legs before anything happened -- shows nothing at all:
-0.054 with [-0.713, +0.637].

So `cost_fraction` below is the planned estimate the risk layer computed at the
decision (`sim/plan.py`), never a realised fee. It is safe for the same reason
everything here is safe: it is already on the row, and the row predates the
outcome.

**Why no setup timeframe.** It would be one of the more interesting features --
the journal shows four-hour setups and hourly ones behaving differently -- and
the pool does not pass it out, so the ledger stores an empty string. A column
of empty strings one-hot encoded into nothing would look like a feature that
did not matter. It is left out until it is real.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import numpy as np

from traidingbrain.domain.enums import Side
from traidingbrain.journal.signals import SignalRecord

#: The setups that may appear, in the guide's own lettering.
#:
#: Fixed rather than discovered from the data, so the matrix has the same
#: columns in every fold. Discovering them per fold would silently change the
#: feature space whenever a rare setup happened not to fire in one window, and
#: the coefficients of two folds would stop being comparable.
SETUPS: tuple[str, ...] = ("A", "B", "C", "E", "F", "G")

#: Column names, in the order `row` produces them.
NAMES: tuple[str, ...] = (
    "stopweite_pct",
    "chance_risiko",
    "kosten_anteil",
    "hebel",
    "long",
    "stunde_sin",
    "stunde_cos",
    "wochentag",
    *(f"setup_{key}" for key in SETUPS),
)


def row(record: SignalRecord) -> list[float]:
    """One signal as numbers, from the record alone.

    The hour is split into a sine and a cosine rather than left as 0..23. A
    linear model given the raw hour can only say "later is better", which is
    the one shape a daily cycle cannot have -- and it would put midnight and
    23:00 at opposite ends of the scale when they are an hour apart. The
    weekday is left linear on purpose: the week is not a closed cycle for a
    market that trades through the weekend at a different character, so an
    ordering is a reasonable thing to let the model find.
    """
    when = datetime.fromtimestamp(record.decided_ts / 1000, tz=UTC)
    angle = 2.0 * np.pi * when.hour / 24.0
    return [
        record.stop_distance_pct,
        record.reward_risk,
        record.cost_fraction,
        record.leverage,
        1.0 if record.side is Side.LONG else 0.0,
        float(np.sin(angle)),
        float(np.cos(angle)),
        float(when.weekday()),
        *(1.0 if record.setup_key == key else 0.0 for key in SETUPS),
    ]


def matrix(records: Sequence[SignalRecord]) -> np.ndarray:
    """The feature matrix, one row per signal, columns in `NAMES` order."""
    if not records:
        return np.empty((0, len(NAMES)), dtype="float64")
    return np.array([row(record) for record in records], dtype="float64")
