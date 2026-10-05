"""Walk a filter across the folds, and do it again with the labels shuffled.

This was inside `scripts/study_filter.py`, and it is here because the number it
produces -- zero of a hundred shuffled runs matched the real one, p ~ 0.010 --
is the only reason to believe a learned filter found anything at all. A claim
that load-bearing should not rest on untested code in a script, and there are
two specific ways it could be quietly wrong:

* **The test labels get shuffled too.** Then the null is a model trained on
  noise and scored against noise, whose expected performance is the base rate
  by construction, and every real result looks significant. The null that means
  something is a model trained on noise and applied to *real* outcomes, which
  measures how much apparent edge the fitting-and-thresholding procedure
  manufactures on its own.
* **The threshold is picked on the test fold.** Then there is no out-of-sample
  number anywhere and the whole walk-forward is decoration.

`tests/test_evaluate.py` asserts both directly, by comparing against the
unshuffled run and by checking that the realised outcomes reaching the pooled
result are untouched.

**The threshold floor.** Without one, the best mean on the validation fold is
always the single best signal in it, and the chosen threshold then keeps almost
nothing. A filter that trades twice a year is not what is being looked for, so
a threshold must keep at least a set share of the validation fold.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from traidingbrain.learn.model import Ridge, mean_squared_error
from traidingbrain.learn.splits import Fold

#: Regularisation strengths tried on the validation fold.
ALPHAS: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0)

#: Fewest signals a threshold may keep, as a share of the validation fold.
MIN_KEPT_SHARE = 0.15

#: Below these counts a fold is skipped rather than fitted.
#:
#: A fold with thirty training cases and a dozen features fits them exactly and
#: predicts nothing, and its test window would then enter the pooled result as
#: noise with a confident threshold attached.
MIN_TRAIN = 50
MIN_VALIDATE = 20


class Scorable(Protocol):
    """A labelled case: when it was decided, when it settled, and its numbers."""

    @property
    def opened_ts(self) -> int: ...

    @property
    def closed_ts(self) -> int: ...

    @property
    def target(self) -> float:
        """What the model predicts. Net R, not whether the trade won.

        Measured on 05.10.2026: the signals the reward-to-risk rule refuses hit
        58% of the time and still lose 0.13 R each, so a classifier trained on
        "did it win" would rank that population at the top."""

    @property
    def features(self) -> Sequence[float]: ...

    @property
    def taken(self) -> bool:
        """Did the system's own rules take this one?

        The baseline. Comparing a filter against every signal instead flatters
        it enormously, because most signals are ones the risk rules already
        refuse and which are measurably bad -- so a filter that avoids them
        only rediscovers the rules."""


@dataclass
class Outcome:
    """What one pass over the folds produced, pooled over test windows."""

    kept: list[float] = field(default_factory=list)
    taken: list[float] = field(default_factory=list)
    everything: list[float] = field(default_factory=list)
    errors: list[float] = field(default_factory=list)
    folds_used: int = 0

    @property
    def error(self) -> float:
        return float(np.mean(self.errors)) if self.errors else float("nan")

    def mean(self, which: list[float]) -> float:
        return sum(which) / len(which) if which else float("nan")

    @property
    def lift_over_taken(self) -> float:
        """The only comparison that decides anything."""
        return self.mean(self.kept) - self.mean(self.taken)


def _choose(
    train: Sequence[Scorable],
    validate: Sequence[Scorable],
    *,
    rng: np.random.Generator | None,
) -> tuple[Ridge, float] | None:
    """Fit on training, then pick alpha and threshold on validation.

    `rng` shuffles the training and validation targets and nothing else. The
    test fold is never passed in here, which is the structural half of the
    guarantee that the null is honest.
    """
    if len(train) < MIN_TRAIN or len(validate) < MIN_VALIDATE:
        return None

    y_train = np.array([case.target for case in train], dtype="float64")
    y_validate = np.array([case.target for case in validate], dtype="float64")
    if rng is not None:
        rng.shuffle(y_train)
        rng.shuffle(y_validate)

    x_train = np.array([list(case.features) for case in train], dtype="float64")
    x_validate = np.array([list(case.features) for case in validate], dtype="float64")
    names = tuple(f"f{i}" for i in range(x_train.shape[1]))

    floor = max(5, int(MIN_KEPT_SHARE * len(validate)))
    best: tuple[float, Ridge, float] | None = None
    for alpha in ALPHAS:
        model = Ridge.fit(x_train, y_train, names=names, alpha=alpha)
        predicted = model.predict(x_validate)
        for threshold in np.unique(predicted):
            kept = predicted >= threshold
            if int(kept.sum()) < floor:
                continue
            score = float(y_validate[kept].mean())
            if best is None or score > best[0]:
                best = (score, model, float(threshold))
    if best is None:
        return None
    return best[1], best[2]


def evaluate(
    folds: Sequence[Fold],
    cases: Sequence[Scorable],
    *,
    rng: np.random.Generator | None = None,
) -> Outcome:
    """One pass over every fold, pooling the test windows.

    The realised outcomes that reach the result are always the real ones, even
    when `rng` is given. That is the whole point: the null is a model that
    learned nothing, applied to what actually happened.
    """
    outcome = Outcome()
    for fold in folds:
        train, _purge = fold.training(cases)
        validate = fold.within(cases, fold.validate)
        test = fold.within(cases, fold.test)
        if not test:
            continue
        picked = _choose(train, validate, rng=rng)
        if picked is None:
            continue
        model, threshold = picked
        outcome.folds_used += 1

        x_test = np.array([list(case.features) for case in test], dtype="float64")
        predicted = model.predict(x_test)
        actual = np.array([case.target for case in test], dtype="float64")

        outcome.errors.append(mean_squared_error(predicted, actual))
        outcome.everything.extend(actual.tolist())
        outcome.kept.extend(actual[predicted >= threshold].tolist())
        outcome.taken.extend(case.target for case in test if case.taken)
    return outcome


def permutation_null(
    folds: Sequence[Fold], cases: Sequence[Scorable], *, runs: int, seed: int = 1000
) -> list[float]:
    """The mean kept result from `runs` shuffled-label passes.

    Each run gets its own seed so the distribution is reproducible and a single
    unlucky shuffle cannot be mistaken for the whole null.
    """
    out: list[float] = []
    for i in range(runs):
        shuffled = evaluate(folds, cases, rng=np.random.default_rng(seed + i))
        if shuffled.kept:
            out.append(shuffled.mean(shuffled.kept))
    return out


def position(real: float, null: Sequence[float]) -> tuple[int, float]:
    """How many of the null runs matched the real result, and the p-value.

    `(better + 1) / (n + 1)` rather than `better / n`, so a run where nothing
    matched reports `1/(n+1)` instead of zero. A p-value of exactly zero would
    claim more than a finite number of permutations can support, and the floor
    makes the resolution of the test visible: thirty runs cannot report better
    than 0.032 however strong the effect.
    """
    better = sum(1 for value in null if value >= real)
    return better, (better + 1) / (len(null) + 1)
