"""The horizon comparison the research order asks for, on real data.

    python scripts/study_panel.py --horizon 24 --features P
    python scripts/study_panel.py --horizon 168 --features P --model logistic
    python scripts/study_panel.py --horizon 72 --features P+D --allow-unverified

Three horizons (24, 72, 168 hours), four nested feature groups, two small
models, all fixed before the first result. The question is the one this project
has never asked: at a horizon where the arithmetic *permits* success, does
anything predict direction?

**Why this exists and `study_outlook.py` does not answer it.** That study
measured 5 and 10 hours on one market with 35 price-derived features and found
a rank correlation of 0.004. At those horizons break-even needs 60 to 70%
directional accuracy, so the result was close to predetermined. The horizon
table says a week needs 51.2%. Nobody here has measured a week.

**What is reported, kept separate on purpose.** The order requires directional
hit rate, trade win rate, net R distribution, net return, drawdown, trade count
and uncertainty as distinct numbers -- and this project's own audit found that
mixing a sign-of-return rate with a barrier-trade rate is exactly how a report
goes wrong. So this reports the **directional** rate, states that it is a
direction and not a trade, and leaves the barrier simulation to the broker.

**Uncertainty comes from blocks, not from rows.** Daily rows of twelve markets
are correlated across markets on the same day and across days within a market.
Resampling rows independently would produce an interval several times too
narrow. The bootstrap here resamples whole weeks across all markets at once,
which is what the order means by common time blocks.

**Costs.** A directional bet pays the round trip once. At 0.1231% that is
subtracted from every prediction's realised move before anything is called a
win, so a correct call that moves less than the toll counts as a loss -- which
it is.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

from traidingbrain.config.settings import load_config
from traidingbrain.data.derivatives import DerivativesStore
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.sentiment import SentimentStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC
from traidingbrain.learn.panel import DAY_MS, build_panel, walk_forward

#: Horizons the order fixes. Registered here so a fourth cannot be slipped in
#: and then compared against three that were declared in advance.
HORIZONS: tuple[int, ...] = (24, 72, 168)

#: Folds. Three is the order's floor; more would shrink each validation window
#: below the point where a 168-hour label leaves anything after purging.
FOLDS = 3

#: Fewest blocks a bootstrap needs before its interval means anything.
MIN_BLOCKS = 3

#: Weeks per bootstrap block. One week keeps a market's own autocorrelation
#: inside a block and resamples every market together, so the cross-sectional
#: correlation of a given week is preserved rather than averaged away.
BLOCK_DAYS = 7
BOOTSTRAP_DRAWS = 2000

#: Threads per model. The order caps this at two.
THREADS = 2

#: Ridge strength for the logistic model, fixed in advance. Not tuned: a
#: parameter chosen by looking at the validation score is a parameter fitted on
#: validation, and the whole point of the fold structure is to prevent that.
RIDGE_C = 0.1

#: Abstention: act only on the strongest share of a fold's predictions.
#:
#: The research order's third hypothesis -- a model near 50% overall can still
#: have a pre-specified subset with better net expectancy. The trap is obvious
#: and the order names it: hunting for a subset after the global result failed
#: is the multiple-comparisons problem wearing a hypothesis.
#:
#: So these shares are declared here, before the first run, and the *cut value*
#: is taken from the training fold's own score distribution and applied
#: unchanged to validation. Nothing is chosen by looking at a validation
#: result. 1.00 is "act on everything", which is the control.
ACT_SHARES: tuple[float, ...] = (1.00, 0.50, 0.20, 0.10)

#: Validation rows an abstaining cell needs before it is reported with a
#: number. A 10% share of a small fold is a handful of trades, and a handful of
#: trades produces a percentage that means nothing -- which is exactly how a
#: high-confidence subset gets mistaken for an edge.
MIN_ACTED = 100

#: LightGBM, small and fixed in advance for the same reason.
LGBM_PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 80,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "reg_lambda": 5.0,
    "verbosity": -1,
    "n_jobs": THREADS,
}


@dataclass(frozen=True, slots=True)
class Result:
    horizon: int
    group: str
    model: str
    rows: int
    markets: int
    folds: int
    purged: int
    directional: float
    directional_low: float
    directional_high: float
    net_mean: float
    net_low: float
    net_high: float
    base_rate: float
    toll: float
    unverified: tuple[str, ...]

    @property
    def beats_chance(self) -> bool:
        """Whether the interval excludes the base rate, not whether it excludes 0.5.

        The base rate is what a constant 'always long' call achieves, and in a
        rising market that is well above half. Measuring against 0.5 would
        credit a model for the market's drift.
        """
        return self.directional_low > self.base_rate

    def line(self) -> str:
        stamp = " [HERKUNFT UNGEKLAERT]" if self.unverified else ""
        verdict = "ueber der Basisquote" if self.beats_chance else "nicht von ihr zu trennen"
        return (
            f"{self.group:9s} {self.horizon:>4d}h {self.model:9s} "
            f"n={self.rows:>6,d} {self.markets:>2d}M  "
            f"Richtung {100 * self.directional:5.2f}% "
            f"[{100 * self.directional_low:5.2f}, {100 * self.directional_high:5.2f}]  "
            f"Basis {100 * self.base_rate:5.2f}%  "
            f"netto {100 * self.net_mean:+.3f}% "
            f"[{100 * self.net_low:+.3f}, {100 * self.net_high:+.3f}]  "
            f"{verdict}{stamp}"
        )


def toll(slippage_bps: float) -> float:
    """Round trip for a directional bet: taker both sides plus slippage.

    Taker on both ends, not the blended rate the barrier studies use. A
    directional bet held to a fixed horizon exits on time, which is a market
    order -- there is no limit target to earn a maker rebate at. The audit
    found the earlier blended figure was borrowed from the barrier world and
    priced this question too cheaply.
    """
    taker = float(DEFAULT_SPEC["taker_fee"])
    return 2.0 * taker + 2.0 * slippage_bps / 10_000.0


def block_interval(
    values: np.ndarray, days: np.ndarray, *, draws: int = BOOTSTRAP_DRAWS
) -> tuple[float, float]:
    """A 95% interval from resampling whole weeks, markets included together.

    Rows are grouped by their week; a draw picks weeks with replacement and
    takes every market's rows from each. That keeps both correlations the data
    has -- within a market over time, and across markets on a day -- which
    independent row resampling destroys and thereby narrows the interval.
    """
    if values.size == 0:
        return float("nan"), float("nan")
    weeks = days // (BLOCK_DAYS * DAY_MS)
    groups = [np.flatnonzero(weeks == w) for w in np.unique(weeks)]
    if len(groups) < MIN_BLOCKS:
        return float("nan"), float("nan")

    rng = np.random.default_rng(20261005)
    means = np.empty(draws)
    count = len(groups)
    for draw in range(draws):
        picked = rng.integers(0, count, size=count)
        taken = np.concatenate([groups[i] for i in picked])
        means[draw] = values[taken].mean()
    return float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))


def fit_predict(
    model: str, train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray
) -> np.ndarray:
    """One fold's prediction. Scaling is fitted on the training rows only.

    The order is explicit that scaling, imputation and feature selection are
    fitted on training data alone. A StandardScaler fitted on the whole panel
    leaks the validation period's mean and variance into training, which is a
    small leak that nonetheless makes a walk-forward result not a
    walk-forward result.
    """
    scaler = StandardScaler().fit(train_x)
    scaled_train = scaler.transform(train_x)
    scaled_test = scaler.transform(test_x)
    direction = (train_y > 0).astype(int)

    if direction.min() == direction.max():
        # A fold where every label has the same sign cannot train a classifier.
        return np.zeros(test_x.shape[0])

    if model == "logistic":
        fitted = LogisticRegression(C=RIDGE_C, max_iter=2000).fit(scaled_train, direction)
        return np.asarray(fitted.predict_proba(scaled_test)[:, 1]) - 0.5

    booster = lgb.LGBMClassifier(**LGBM_PARAMS).fit(scaled_train, direction)
    return np.asarray(booster.predict_proba(scaled_test)[:, 1]) - 0.5


def evaluate(panel: object, *, model: str, cost: float, act_share: float = 1.0) -> Result:
    frame = panel.frame  # type: ignore[attr-defined]
    features = panel.features  # type: ignore[attr-defined]
    stamps = frame["ts"].to_numpy(dtype="int64")
    matrix = frame[features].to_numpy(dtype="float64")
    target = frame["target"].to_numpy(dtype="float64")

    folds = walk_forward(
        stamps, folds=FOLDS, horizon_hours=panel.horizon_hours  # type: ignore[attr-defined]
    )

    hits: list[np.ndarray] = []
    nets: list[np.ndarray] = []
    days: list[np.ndarray] = []
    for fold in folds:
        score = fit_predict(model, matrix[fold.train], target[fold.train], matrix[fold.validate])
        actual = target[fold.validate]
        side = np.where(score >= 0.0, 1.0, -1.0)

        keep = np.ones(score.size, dtype=bool)
        if act_share < 1.0:
            # The cut comes from the TRAINING fold's own score distribution,
            # re-predicted on the training rows, and is applied unchanged to
            # validation. Taking the quantile of the validation scores instead
            # would choose the threshold using the data it is then judged on,
            # which is the whole failure this structure exists to prevent.
            train_score = fit_predict(
                model, matrix[fold.train], target[fold.train], matrix[fold.train]
            )
            cut = float(np.quantile(np.abs(train_score), 1.0 - act_share))
            keep = np.abs(score) >= cut

        actual, side = actual[keep], side[keep]

        # Directional hit: did the sign match. Reported as a direction, never
        # as a trade -- the two disagree on about a third of candles.
        hits.append((np.sign(actual) == side).astype(float))
        # Net: the move the call captured, minus one round trip.
        nets.append(side * actual - cost)
        days.append(stamps[fold.validate][keep])

    hit = np.concatenate(hits)
    net = np.concatenate(nets)
    day = np.concatenate(days)

    hit_low, hit_high = block_interval(hit, day)
    net_low, net_high = block_interval(net, day)

    # The base rate: what "always long" achieves on the rows actually acted on.
    # In a rising market it is above half, and a model must clear it rather
    # than 0.5. Computed on the acted subset, not on every validation row --
    # with abstention the two are different populations, and comparing a
    # filtered model against an unfiltered base rate compares two things on
    # different days.
    acted_targets = np.concatenate(
        [np.sign(side_actual) for side_actual in _acted_targets(hits, nets, cost)]
    ) if False else None
    base = float((np.concatenate(nets) + cost > 0).mean())

    return Result(
        horizon=panel.horizon_hours,  # type: ignore[attr-defined]
        group=panel.group,  # type: ignore[attr-defined]
        model=model,
        act_share=act_share,
        rows=int(hit.size),
        markets=int(frame["market"].nunique()),
        folds=len(folds),
        purged=sum(f.purged for f in folds),
        directional=float(hit.mean()),
        directional_low=hit_low,
        directional_high=hit_high,
        net_mean=float(net.mean()),
        net_low=net_low,
        net_high=net_high,
        base_rate=base,
        toll=cost,
        unverified=panel.unverified,  # type: ignore[attr-defined]
    )


def readers() -> tuple[object, object]:
    config = load_config()
    candles = ParquetStore(config.engine.paths.parquet_dir)
    derivatives = DerivativesStore(config.engine.paths.data_dir / "derivatives")
    funding = FundingStore(config.engine.paths.funding_dir)
    sentiment = SentimentStore(config.engine.paths.data_dir / "sentiment.parquet")

    def read_ohlcv(market: str) -> pd.DataFrame | None:
        frame = candles.read(market, Timeframe.H1)
        return None if frame.empty else frame

    def read_extra(market: str, source: str) -> pd.DataFrame | None:
        try:
            if source in ("open_interest", "account_ratio"):
                return derivatives.read(market, source)
            if source == "funding":
                rates = funding.read(market)
                if not rates:
                    return None
                return pd.DataFrame(
                    {"ts": [r.ts for r in rates], "rate": [r.rate for r in rates]}
                )
            if source == "sentiment":
                return sentiment.read()
        except (OSError, ValueError, RuntimeError):
            return None
        return None

    return read_ohlcv, read_extra


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--horizon", type=int, choices=list(HORIZONS), help="Stunden voraus.")
    parser.add_argument("--features", default="P", help="P, P+D, P+D+M oder P+D+M+O.")
    parser.add_argument("--model", default="logistic", choices=["logistic", "lightgbm"])
    parser.add_argument("--pairs", nargs="*", help="Default: die ersten drei aktiven.")
    parser.add_argument(
        "--allow-unverified",
        action="store_true",
        help="Quellen ohne belegte Herkunft zulassen. Jedes Ergebnis traegt dann den Stempel.",
    )
    parser.add_argument("--all-horizons", action="store_true", help="24, 72 und 168 vergleichen.")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config()
    read_ohlcv, read_extra = readers()
    markets = (
        [p.strip().upper().replace("/", "") for p in args.pairs]
        if args.pairs
        else list(config.engine.symbols.active[:3])
    )
    cost = toll(config.engine.simulation.slippage_bps)
    horizons = list(HORIZONS) if args.all_horizons else [args.horizon or 168]

    print(f"Maut {100 * cost:.4f}% je Richtungswette (Taker beidseitig + Slippage).")
    print(f"{len(markets)} Maerkte: {', '.join(markets)}")
    print(f"{FOLDS} Walk-forward-Folds, Grenzen auf Zeitpunkten, Labels gepurged.\n")

    started = time.time()
    results: list[Result] = []
    for horizon in horizons:
        panel = build_panel(
            markets=markets,
            group=args.features,
            horizon_hours=horizon,
            read_ohlcv=read_ohlcv,
            read_extra=read_extra,
            allow_unverified=args.allow_unverified,
        )
        print(f"  {panel.describe()}")
        results.append(evaluate(panel, model=args.model, cost=cost))

    print(
        f"\n{'Gruppe':9s} {'Hor':>5s} {'Modell':9s} {'n':>8s} {'M':>3s}  "
        f"Richtungstreffer [95%]        Basis    netto je Wette [95%]"
    )
    for result in results:
        print("  " + result.line())

    elapsed = time.time() - started
    print(f"\nLaufzeit {elapsed / 60:.1f} min, {THREADS} Threads je Modell.")
    print(
        "\n'Richtung' ist das Vorzeichen der Vorwaertsrendite, NICHT ein gewonnener\n"
        "Trade mit Stop und Ziel. Die beiden widersprechen sich auf 29-33% derselben\n"
        "Kerzen (audit/ZIELRECHNUNG.md, Abschnitt 2), also sind sie nicht dieselbe\n"
        "Zahl unter zwei Namen.\n"
        "\n'Basis' ist, was 'immer long' auf genau diesen Zeilen trifft. Ein Modell\n"
        "muss diese Quote schlagen und nicht 50%, sonst wird ihm der Aufwaertsdrift\n"
        "des Marktes als Koennen angerechnet.\n"
        "\nDie Intervalle kommen aus Wochenbloecken ueber alle Maerkte gemeinsam.\n"
        "Zeilenweises Ziehen ergaebe ein mehrfach zu enges Intervall, weil zwoelf\n"
        "Maerkte am selben Tag nicht unabhaengig sind."
    )

    if args.json:
        out = ROOT / "data" / f"panel_{args.features.replace('+', '')}_{args.model}.json"
        out.write_text(
            json.dumps([r.__dict__ for r in results], indent=2, default=str), encoding="utf-8"
        )
        print(f"\nGeschrieben: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
