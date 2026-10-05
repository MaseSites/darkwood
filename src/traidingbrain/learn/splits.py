"""Walk-forward windows, with the overlapping cases cut out.

Section 11 of the masterplan: train on the past, choose on the next stretch,
measure on the one after that, then roll the whole arrangement forward and do it
again. Four jobs, four disjoint periods, and they must stay disjoint for the
test number to mean anything.

**Why a plain date split is not enough.** A label is not an event at a point in
time; it covers the interval from the entry to whichever barrier closed it. A
signal opened two hours before the test window begins and closed six hours into
it has an outcome that is *partly made of the test period*. Train on it and the
model has seen the thing it is about to be scored on -- not through any bug in
the feature code, but through the label. That is the leak this module exists to
remove, and no amount of care in `analysis/` can catch it, because the features
were honest; it was the answer key that overlapped.

So a training case is kept only if it closed before the evaluation window, with
a gap. Purging removes the overlap; the embargo removes the stretch just before
it, where serial correlation makes a closed case still nearly the same event as
the first cases being scored. Both are measured in the units of the thing that
causes them -- the actual label horizon -- rather than picked.

**The holdout.** `walk_forward` reserves a final stretch that no fold touches.
Section 11 asks for a period used only once the candidates are settled, and is
blunt about what it costs: the moment its results are used to change something,
it is no longer an untouched test. Nothing here can enforce that. What it can do
is keep the period out of every fold so the choice remains available.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

DAY_MS = 86_400_000


def _day(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=UTC).date().isoformat()


class Case(Protocol):
    """Anything with a decision time and a resolution time.

    The two timestamps are the whole interface: purging is about when a label
    was *settled*, not about what it says or which features produced it.
    """

    @property
    def opened_ts(self) -> int: ...

    @property
    def closed_ts(self) -> int: ...


@dataclass(frozen=True)
class Window:
    """A half-open period, `[start, end)`."""

    start_ts: int
    end_ts: int

    def holds(self, ts: int) -> bool:
        return self.start_ts <= ts < self.end_ts

    @property
    def days(self) -> float:
        return (self.end_ts - self.start_ts) / DAY_MS

    def __str__(self) -> str:
        return f"{_day(self.start_ts)}..{_day(self.end_ts)}"


@dataclass(frozen=True)
class Purge:
    """What was dropped from a training set, and why.

    Returned rather than logged. A split that silently discarded a third of its
    training data would look like a split that had a third less data, and the
    two call for different decisions.
    """

    kept: int
    overlapped: int
    """Closed inside or after the evaluation window: the leak."""

    embargoed: int
    """Closed inside the gap before it: nearly the same event."""

    @property
    def considered(self) -> int:
        return self.kept + self.overlapped + self.embargoed

    def summary(self) -> str:
        if self.considered == 0:
            return "  keine Faelle im Trainingsfenster"
        lost = 100 * (self.overlapped + self.embargoed) / self.considered
        return (
            f"  {self.kept} von {self.considered} Faellen behalten "
            f"({self.overlapped} ueberlappend, {self.embargoed} in der Sperrfrist, "
            f"{lost:.1f}% verworfen)"
        )


@dataclass(frozen=True)
class Fold:
    """One step of the walk: train, choose, measure.

    `validate` is where thresholds and model choice are settled and `test` is
    where the settled thing is scored once. Collapsing them is the most common
    way a walk-forward result turns out to be in-sample: a threshold picked on
    the same data it is then reported on has been fitted to it.
    """

    index: int
    train: Window
    validate: Window
    test: Window
    embargo_ms: int

    def training[C: Case](self, cases: Iterable[C]) -> tuple[list[C], Purge]:
        """The training cases that may be used, and an account of the rest.

        A case has to have opened inside the training window and closed early
        enough that neither its outcome nor its immediate aftermath touches what
        comes next. The barrier is the start of `validate`, not of `test`:
        validation decides the threshold, so a case leaking into it is fitted on
        just as surely, one step further back.
        """
        cutoff = self.validate.start_ts - self.embargo_ms
        kept: list[C] = []
        overlapped = 0
        embargoed = 0
        for case in cases:
            if not self.train.holds(case.opened_ts):
                continue
            if case.closed_ts >= self.validate.start_ts:
                overlapped += 1
            elif case.closed_ts >= cutoff:
                embargoed += 1
            else:
                kept.append(case)
        return kept, Purge(kept=len(kept), overlapped=overlapped, embargoed=embargoed)

    def within[C: Case](self, cases: Iterable[C], window: Window) -> list[C]:
        """Cases decided inside a window, in time order.

        Evaluation windows are not purged. A case opened inside the test window
        whose outcome runs past its end is still a decision the system made in
        that period, and dropping it would quietly remove the trades that were
        still open -- which are disproportionately the losers somebody was
        sitting in. `sim/engine.py:244` refuses the same temptation.
        """
        return sorted((c for c in cases if window.holds(c.opened_ts)), key=lambda c: c.opened_ts)

    def describe(self) -> str:
        return (
            f"Fold {self.index}: Training {self.train}  Auswahl {self.validate}  Test {self.test}"
        )


@dataclass(frozen=True)
class Plan:
    """Every fold, plus the stretch deliberately left alone."""

    folds: tuple[Fold, ...]
    holdout: Window | None

    def describe(self) -> str:
        lines = [f.describe() for f in self.folds]
        if self.holdout is not None:
            lines.append(
                f"Zurueckbehalten (unberuehrt): {self.holdout} "
                f"-- erst nach der Kandidatenwahl lesen, und dann ist es verbraucht"
            )
        return "\n".join(lines)


def walk_forward(
    *,
    first_ts: int,
    last_ts: int,
    train_days: float,
    validate_days: float,
    test_days: float,
    embargo_ms: int,
    step_days: float | None = None,
    holdout_days: float = 0.0,
) -> Plan:
    """Lay out the folds across a period.

    `step_days` defaults to `test_days`, which makes consecutive test windows
    abut without overlapping -- so every fold scores a stretch no other fold
    scored, and the test results can be pooled. A smaller step gives more folds
    whose test windows share data, and then the pooled number counts the same
    days more than once.

    Returns whatever fits. A period too short for even one fold gives an empty
    plan rather than a fold with a two-week training window, because the second
    is the kind of thing that produces a number and no warning.
    """
    if min(train_days, validate_days, test_days) <= 0:
        raise ValueError("train, validate and test windows must all be positive")
    if embargo_ms < 0:
        raise ValueError("the embargo cannot be negative")

    step = test_days if step_days is None else step_days
    if step <= 0:
        raise ValueError("the step must be positive")

    usable_end = last_ts - int(holdout_days * DAY_MS)
    holdout = Window(usable_end, last_ts) if holdout_days > 0 else None

    span = int((train_days + validate_days + test_days) * DAY_MS)
    folds: list[Fold] = []
    start = first_ts
    while start + span <= usable_end:
        train_end = start + int(train_days * DAY_MS)
        validate_end = train_end + int(validate_days * DAY_MS)
        test_end = validate_end + int(test_days * DAY_MS)
        folds.append(
            Fold(
                index=len(folds) + 1,
                train=Window(start, train_end),
                validate=Window(train_end, validate_end),
                test=Window(validate_end, test_end),
                embargo_ms=embargo_ms,
            )
        )
        start += int(step * DAY_MS)

    return Plan(folds=tuple(folds), holdout=holdout)


def pooled_test_cases[C: Case](plan: Plan, cases: Sequence[C]) -> list[C]:
    """Every case scored in some fold's test window, each counted once.

    Pooling across folds is how a walk-forward produces one number, and it is
    only legitimate while the test windows are disjoint. With overlapping
    windows a case appears in several folds, and the pooled mean weights those
    days more heavily than the rest -- so this deduplicates by decision time and
    the caller gets a count it can compare against the sum of the folds.
    """
    seen: set[tuple[int, int]] = set()
    out: list[C] = []
    for fold in plan.folds:
        for case in fold.within(cases, fold.test):
            key = (case.opened_ts, case.closed_ts)
            if key in seen:
                continue
            seen.add(key)
            out.append(case)
    return sorted(out, key=lambda c: c.opened_ts)
