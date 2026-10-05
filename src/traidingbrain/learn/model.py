"""The numeric filter: ridge regression on net R, fitted in closed form.

Section 8 of the masterplan asks for a trainable model that scores whether a
signal from the existing strategy is worth taking, and suggests starting with
something small -- logistic regression against a tree method -- rather than
reaching for a complicated method because of its name.

**Why it predicts net R and not whether the trade wins.** Section 8 offers both
targets and warns about the first: a model with many small wins and a few large
losses can be unprofitable. On 05.10.2026 that stopped being a caution and
became a measurement. The signals the reward-to-risk rule refuses hit **58% of
the time** -- far more often than the 41% the system actually trades -- and
still lose 0.13 R each, because every win is too small to pay the toll. A
classifier trained on "did it win" would rank that population at the top. So
the target here is the quantity that decides the account, and the hit rate is
only ever a diagnostic.

**Why ridge and not logistic.** The target is continuous, so a classifier would
have to throw the magnitude away first. Ridge also has a closed-form solution,
which matters more than it sounds: there is no optimiser, no learning rate, no
convergence criterion and no seed, so the same data gives bit-identical
coefficients on every machine and every run. The decision cache exists in this
project because sampling parameters were removed from the model API and
reproducibility had to come from somewhere; here it comes for free.

**Why no scikit-learn.** It is not installed, and `pyproject.toml` carries a
comment about what an undeclared dependency did to the first fresh install.
Ridge is one linear solve. Pulling in scikit-learn and scipy -- about a hundred
megabytes, on a project that hand-writes its indicators against TA-Lib as a dev
oracle -- to avoid writing `solve` is the wrong trade.

**The regularisation is not optional.** With 2,861 signals and a dozen features
an unregularised fit will find structure in noise, and section 11 is blunt about
what many attempts do to a backtest. `alpha` is chosen on the validation fold
and never on the test fold, which `learn/splits.py` keeps separate for exactly
this.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise

import numpy as np

#: Added to the diagonal before solving, on top of `alpha`.
#:
#: Guards the solve itself rather than the fit: two perfectly correlated
#: features make the matrix singular, and `np.linalg.solve` raises. A feature
#: set that collinear is a bug worth seeing, but it should not take a whole
#: walk-forward run down with it.
RIDGE_FLOOR = 1e-10

#: A feature matrix has rows and columns and nothing else.
MATRIX_DIMS = 2


@dataclass(frozen=True)
class Standardiser:
    """Per-feature mean and scale, fitted on one set of rows only.

    Section 8 requires normalisation to be fitted on the permitted data alone.
    It is easy to get wrong in a way no test notices: standardising the whole
    matrix before splitting lets the test fold's mean and variance into the
    training set, which is a leak that leaves the features looking perfectly
    honest one by one.
    """

    mean: np.ndarray
    scale: np.ndarray

    @classmethod
    def fit(cls, rows: np.ndarray) -> Standardiser:
        matrix = np.asarray(rows, dtype="float64")
        mean = matrix.mean(axis=0)
        scale = matrix.std(axis=0)
        # A feature that never varies carries no information and would divide by
        # zero. Left at 1 so it contributes a constant that the intercept
        # absorbs, rather than a column of nan that poisons every coefficient.
        scale = np.where(scale > 0, scale, 1.0)
        return cls(mean=mean, scale=scale)

    def apply(self, rows: np.ndarray) -> np.ndarray:
        scaled: np.ndarray = (np.asarray(rows, dtype="float64") - self.mean) / self.scale
        return scaled


@dataclass(frozen=True)
class Ridge:
    """A fitted linear model over standardised features.

    Frozen, and it holds its own standardiser. A model separated from the
    scaling it was fitted under is a model that will be applied to differently
    scaled data at some point, and the result will look like a bad model rather
    than a mistake.
    """

    coef: np.ndarray
    intercept: float
    scaler: Standardiser
    names: tuple[str, ...]
    alpha: float

    @classmethod
    def fit(
        cls, rows: np.ndarray, target: np.ndarray, *, names: tuple[str, ...], alpha: float = 1.0
    ) -> Ridge:
        """Solve `(X'X + alpha I) b = X'y` on standardised, centred data.

        Standardising first is what makes one `alpha` meaningful across
        features measured in percent, in hours and in multiples of risk --
        without it the penalty would fall almost entirely on whichever feature
        happened to have the smallest units.

        The intercept is the training mean of the target and is not penalised.
        Shrinking it would pull every prediction towards zero R, which is not a
        prior anybody holds: the honest prior is the average outcome of the
        signals the model was shown.
        """
        matrix = np.asarray(rows, dtype="float64")
        y = np.asarray(target, dtype="float64")
        if matrix.ndim != MATRIX_DIMS:
            raise ValueError(f"expected a 2-D feature matrix, got shape {matrix.shape}")
        if matrix.shape[0] != y.size:
            raise ValueError(f"{matrix.shape[0]} rows against {y.size} targets")
        if matrix.shape[1] != len(names):
            raise ValueError(f"{matrix.shape[1]} columns against {len(names)} names")
        if alpha < 0:
            raise ValueError("alpha cannot be negative")

        scaler = Standardiser.fit(matrix)
        x = scaler.apply(matrix)
        intercept = float(y.mean())
        centred = y - intercept

        gram = x.T @ x + (alpha + RIDGE_FLOOR) * np.eye(x.shape[1])
        coef = np.linalg.solve(gram, x.T @ centred)
        return cls(coef=coef, intercept=intercept, scaler=scaler, names=tuple(names), alpha=alpha)

    def predict(self, rows: np.ndarray) -> np.ndarray:
        """Expected net R for each row, in the units the target was given in."""
        predicted: np.ndarray = self.scaler.apply(rows) @ self.coef + self.intercept
        return predicted

    def weights(self) -> dict[str, float]:
        """Coefficients by name, largest first.

        On standardised features these are comparable to each other: each is the
        change in expected net R for one standard deviation of its feature. That
        is the only reading under which "which feature matters most" is a
        question with an answer.
        """
        pairs = zip(self.names, (float(value) for value in self.coef), strict=True)
        return dict(sorted(pairs, key=lambda kv: -abs(kv[1])))

    def describe(self, limit: int = 6) -> str:
        head = [f"{name} {value:+.4f}" for name, value in list(self.weights().items())[:limit]]
        return f"Achsenabschnitt {self.intercept:+.4f} R  |  " + ", ".join(head)


def mean_squared_error(predicted: np.ndarray, actual: np.ndarray) -> float:
    residual = np.asarray(predicted, dtype="float64") - np.asarray(actual, dtype="float64")
    return float(residual @ residual / residual.size)


def brier_score(probability: np.ndarray, outcome: np.ndarray) -> float:
    """Mean squared error of a probability against a 0/1 outcome.

    Kept here because section 8 asks for calibration to be checked whenever
    probabilities are used, and because a ridge prediction can be turned into
    one. It is a diagnostic rather than the objective: a model can be perfectly
    calibrated about win probability and still lose money, which is what the
    58%-hit-rate population at the top of this module demonstrates.
    """
    error = np.asarray(probability, dtype="float64") - np.asarray(outcome, dtype="float64")
    return float(error @ error / error.size)


def reliability(
    probability: np.ndarray, outcome: np.ndarray, *, bins: int = 10
) -> list[tuple[float, float, int]]:
    """Predicted against realised frequency, per bin.

    Returns `(mean predicted, observed rate, count)`. Empty bins are left out
    rather than reported as zero, because a bin with nothing in it is not a
    place where the model was wrong.
    """
    p = np.asarray(probability, dtype="float64")
    y = np.asarray(outcome, dtype="float64")
    edges = np.linspace(0.0, 1.0, bins + 1)
    out: list[tuple[float, float, int]] = []
    for low, high in pairwise(edges):
        # The last bin takes its upper edge, or a prediction of exactly 1 would
        # fall outside every bin and vanish from the curve.
        inside = (p >= low) & (p < high) if high < 1.0 else (p >= low) & (p <= high)
        if not inside.any():
            continue
        out.append((float(p[inside].mean()), float(y[inside].mean()), int(inside.sum())))
    return out
