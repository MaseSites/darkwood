"""Does a learned filter find anything a shuffled one would not?

    python scripts/study_filter.py --symbols BTCUSDT
    python scripts/study_filter.py --symbols BTCUSDT --permutations 50

Section 8 of the masterplan, measured the way section 11 insists on. Run
`scripts/study_refused.py` first: this reads the signal ledger it fills.

**The one number that matters.** Not whether the filter looks good -- it will.
With 2,861 signals and a dozen features, a procedure that fits a model, picks a
regularisation strength and then picks a threshold has three chances to find
structure in noise, and section 11 is blunt about what many attempts do to a
backtest. So the whole pipeline is run again with the training and validation
targets **shuffled**, several times, and the real result is reported as its
position in that distribution. A model trained on noise, selected on noise and
applied to real data is exactly the right null: whatever apparent edge the
*procedure* manufactures shows up there too.

If the real test result sits inside the shuffled distribution, there is nothing
here, and that is the finding. It is also the likeliest outcome and the reason
this script exists before any filter is wired into the engine.

**What it predicts.** Net R, not whether the trade wins. Measured on
05.10.2026: the signals the reward-to-risk rule refuses hit 58% of the time --
far more than the 41% the system trades -- and still lose 0.13 R each. A
classifier trained on "did it win" would put that population at the top. Hit
rate is printed here only as a diagnostic.

**Where the folds come from.** `learn/splits.py`, with purging and an embargo
over the real label horizon, because a label covers an interval and a case
settled inside the evaluation window carries that window in its answer. The
threshold is chosen on the validation fold and the test fold is read once.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import Action, SignalRecord, SignalStore
from traidingbrain.learn.features import NAMES, matrix
from traidingbrain.learn.labels import Label, Minutes, label_signal
from traidingbrain.learn.model import Ridge, mean_squared_error
from traidingbrain.learn.splits import DAY_MS, Fold, walk_forward
from traidingbrain.reporting.intervals import block_bootstrap

#: Regularisation strengths tried on the validation fold.
#:
#: Wide and coarse. A fine grid is more chances to fit the validation fold, and
#: the permutation null below would absorb that -- but it would also make the
#: whole run slower for a choice the data cannot support anyway.
ALPHAS: tuple[float, ...] = (0.1, 1.0, 10.0, 100.0, 1000.0)

#: Fewest signals a threshold may keep, as a share of the validation fold.
#:
#: Without a floor the best validation mean is always the single best signal,
#: and the chosen threshold would keep almost nothing in the test fold. A
#: filter that trades twice a year is not the thing being looked for.
MIN_KEPT_SHARE = 0.15

#: Fewest cases a fold needs before it is worth fitting anything.
#:
#: A fold with thirty training cases and a dozen features produces a model that
#: fits them exactly and predicts nothing, and its test fold would then enter
#: the pooled result as noise with a confident threshold attached.
MIN_TRAIN = 50
MIN_VALIDATE = 20

#: Fewest resolved cases in total before a walk-forward is attempted.
MIN_CASES = 200

#: Share of permutation runs at or above the real result that still counts as
#: lying inside the null distribution.
INSIDE = 0.05

#: The horizon, the same one the labeller and the embargo use.
HORIZON_HOURS = 48
HOUR_MS = 3_600_000

TRAIN_DAYS = 360.0
VALIDATE_DAYS = 90.0
TEST_DAYS = 90.0


@dataclass(frozen=True)
class Case:
    """A labelled signal, with the two timestamps the splitter needs."""

    record: SignalRecord
    label: Label

    @property
    def opened_ts(self) -> int:
        return self.record.decided_ts

    @property
    def closed_ts(self) -> int:
        return self.label.closed_ts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument(
        "--permutations",
        type=int,
        default=30,
        help=(
            "How many shuffled-label runs form the null. Thirty gives a "
            "resolution of about three percent on the position, which is "
            "enough to tell inside from outside."
        ),
    )
    return parser.parse_args()


def signature(config: object) -> str:
    engine = config.engine  # type: ignore[attr-defined]
    risk = config.risk  # type: ignore[attr-defined]
    return (
        f"{engine.simulation.initial_equity}|{engine.setups.enabled}|"
        f"{risk.limits.max_cost_fraction_of_risk}|{engine.timeframes.signal.value}|refused-v1"
    )


def load_cases(symbols: list[str], config: object) -> list[Case]:
    """Every signal in the ledger, labelled against the three barriers."""
    store = ParquetStore(config.engine.paths.parquet_dir)  # type: ignore[attr-defined]
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")  # type: ignore[attr-defined]
    funding_store = FundingStore(config.engine.paths.funding_dir)  # type: ignore[attr-defined]
    simulation = config.engine.simulation  # type: ignore[attr-defined]
    expiry_ms = simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal  # type: ignore[attr-defined]
    )
    sig = signature(config)

    cases: list[Case] = []
    for symbol in symbols:
        records = signals.all(symbol=symbol, run_signature=sig)
        if not records:
            print(f"{symbol}: keine Signale im Protokoll -- study_refused.py zuerst", flush=True)
            continue
        frame = store.read(symbol, config.engine.timeframes.execution)  # type: ignore[attr-defined]
        if frame.empty:
            print(f"{symbol}: keine Minutendaten", flush=True)
            continue
        minutes = Minutes.of(frame)
        rates = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        for record in records:
            label = label_signal(
                side=record.side,
                entry=record.entry,
                stop=record.stop,
                target=record.target,
                decision_ts=record.decided_ts,
                minutes=minutes,
                spec=spec,
                config=simulation,
                horizon_ms=HORIZON_HOURS * HOUR_MS,
                expiry_ms=expiry_ms,
                funding=rates,
            )
            if label.resolved:
                cases.append(Case(record=record, label=label))
        print(f"{symbol}: {len(records)} Signale, {len(cases)} aufgeloest", flush=True)
    return sorted(cases, key=lambda c: c.opened_ts)


def choose(
    train: list[Case], validate: list[Case], target: np.ndarray, rng: np.random.Generator | None
) -> tuple[Ridge, float] | None:
    """Fit on training, then pick alpha and the threshold on validation.

    `rng` shuffles the training and validation targets, which is what makes the
    null. The test fold is never touched by it: the null is a model that learned
    nothing, applied to real outcomes.
    """
    if len(train) < MIN_TRAIN or len(validate) < MIN_VALIDATE:
        return None

    y = target[: len(train)].copy()
    y_validate = target[len(train) : len(train) + len(validate)].copy()
    if rng is not None:
        rng.shuffle(y)
        rng.shuffle(y_validate)

    x_train = matrix([case.record for case in train])
    x_validate = matrix([case.record for case in validate])

    best: tuple[float, Ridge, float] | None = None
    floor = max(5, int(MIN_KEPT_SHARE * len(validate)))
    for alpha in ALPHAS:
        model = Ridge.fit(x_train, y, names=NAMES, alpha=alpha)
        predicted = model.predict(x_validate)
        # Every observed prediction is a candidate threshold. Keeping the ones
        # at or above it, the score is the mean realised net R of what is kept --
        # subject to keeping enough of them to be a strategy rather than an
        # anecdote.
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


def run_once(
    folds: tuple[Fold, ...], cases: list[Case], *, rng: np.random.Generator | None
) -> tuple[list[float], list[float], list[float], float]:
    """One pass over every fold.

    Returns the filter's kept net R, the system's own taken net R, every net R,
    and the prediction error -- all restricted to the test windows, because a
    baseline measured over a different period is not a baseline.
    """
    kept_net: list[float] = []
    taken_net: list[float] = []
    all_net: list[float] = []
    errors: list[float] = []

    for fold in folds:
        train, _purge = fold.training(cases)
        validate = fold.within(cases, fold.validate)
        test = fold.within(cases, fold.test)
        if not test:
            continue
        ordered = [*train, *validate]  # type: ignore[list-item]
        target = np.array([case.label.net_r for case in ordered], dtype="float64")
        picked = choose(train, validate, target, rng)  # type: ignore[arg-type]
        if picked is None:
            continue
        model, threshold = picked

        x_test = matrix([case.record for case in test])
        predicted = model.predict(x_test)
        actual = np.array([case.label.net_r for case in test], dtype="float64")
        errors.append(mean_squared_error(predicted, actual))
        all_net.extend(actual.tolist())
        kept_net.extend(actual[predicted >= threshold].tolist())
        taken_net.extend(case.label.net_r for case in test if case.record.action is Action.TAKEN)

    return (
        kept_net,
        taken_net,
        all_net,
        float(np.mean(errors)) if errors else float("nan"),
    )


def report(
    kept: list[float],
    taken: list[float],
    everything: list[float],
    *,
    mse: float,
    null: list[float],
    runs: int,
) -> None:
    print("\n" + "=" * 78)
    if not everything:
        print("Keine Testfaelle -- zu wenig Historie fuer die Fenster")
        return

    def row(name: str, values: list[float]) -> str:
        if not values:
            return f"  {name:22s} keine"
        hits = 100 * sum(1 for v in values if v > 0) / len(values)
        interval = block_bootstrap(values)
        bounds = interval.labelled() if interval is not None else "zu wenige"
        return (
            f"  {name:22s} n={len(values):5d}  netto {sum(values) / len(values):+.4f} R  "
            f"Treffer {hits:3.0f}%  {bounds}"
        )

    print("Nur Testfenster, jedes einmal gelesen, Schwelle auf der Validierung gewaehlt.\n")
    print(row("alle Signale", everything))
    print(row("vom System genommen", taken))
    print(row("vom Filter behalten", kept))

    if kept:
        share = 100 * len(kept) / len(everything)
        over_all = sum(kept) / len(kept) - sum(everything) / len(everything)
        print(f"\n  behalten {share:.0f}% der Signale")
        print(f"  gegen alle Signale        {over_all:+.4f} R pro Trade")
        if taken:
            over_taken = sum(kept) / len(kept) - sum(taken) / len(taken)
            print(f"  gegen die heutigen Regeln {over_taken:+.4f} R pro Trade", end="")
            print("  <- die einzige Zeile, die zaehlt" if over_taken > 0 else "  <- schlechter")
    print(f"  mittlerer quadratischer Fehler der Vorhersage {mse:.4f}")

    print(
        "\n  'Alle Signale' enthaelt die 80%, die die Risikoregeln ohnehin ablehnen,\n"
        "  und die sind messbar schlecht. Ein Filter, der sie vermeidet, entdeckt\n"
        "  nur die Regeln neu. Die Vergleichslinie ist deshalb die mittlere Zeile."
    )

    print(f"\n--- und derselbe Ablauf mit gewuerfelten Labels, {runs} mal ---")
    if not null:
        print("  kein einziger Durchlauf lieferte Testfaelle")
        return
    real = sum(kept) / len(kept) if kept else float("nan")
    better = sum(1 for value in null if value >= real)
    print(
        f"  gewuerfelt: Mittel {np.mean(null):+.4f} R, "
        f"Bandbreite [{min(null):+.4f}, {max(null):+.4f}]"
    )
    print(f"  echt:       {real:+.4f} R")
    p_value = (better + 1) / (len(null) + 1)
    print(
        f"  {better} von {len(null)} Zufallslaeufen waren mindestens so gut  ->  p ~ {p_value:.3f}"
    )
    if better > INSIDE * len(null):
        print(
            "\n  Das echte Ergebnis liegt in der Zufallsverteilung. Dann hat das\n"
            "  Verfahren nichts gefunden, und das ist der Befund -- nicht ein\n"
            "  Grund, mehr Merkmale oder ein groesseres Modell zu probieren."
        )
    else:
        print(
            "\n  Das echte Ergebnis liegt ausserhalb der Zufallsverteilung. Das ist\n"
            "  ein Kandidat: als naechstes derselbe Filter als Backtest-Arm mit\n"
            "  Belegung, gemessen wie die anderen sieben Hebel."
        )


def main() -> int:
    args = parse_args()
    config = load_config()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    cases = load_cases(symbols, config)
    if len(cases) < MIN_CASES:
        print(f"Nur {len(cases)} aufgeloeste Faelle -- zu wenig fuer Walk-forward")
        return 0

    plan = walk_forward(
        first_ts=cases[0].opened_ts,
        last_ts=cases[-1].closed_ts,
        train_days=TRAIN_DAYS,
        validate_days=VALIDATE_DAYS,
        test_days=TEST_DAYS,
        embargo_ms=HORIZON_HOURS * HOUR_MS,
    )
    span = (cases[-1].closed_ts - cases[0].opened_ts) / DAY_MS
    print(f"\n{len(plan.folds)} Fenster ueber {span:.0f} Tage")
    for fold in plan.folds:
        _train, purge = fold.training(cases)
        print(f"  {fold.describe()}\n  {purge.summary()}")

    kept, taken, everything, mse = run_once(plan.folds, cases, rng=None)

    null: list[float] = []
    for i in range(args.permutations):
        shuffled_kept, _t, _a, _m = run_once(plan.folds, cases, rng=np.random.default_rng(1000 + i))
        if shuffled_kept:
            null.append(sum(shuffled_kept) / len(shuffled_kept))

    report(
        kept,
        taken,
        everything,
        mse=mse,
        null=null,
        runs=args.permutations,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
