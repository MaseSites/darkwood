"""Does a learned filter find anything a shuffled one would not?

    python scripts/study_filter.py --symbols BTCUSDT
    python scripts/study_filter.py --symbols BTCUSDT --permutations 100

Section 8 of the masterplan, measured the way section 11 insists on. Run
`scripts/study_refused.py` first: this reads the signal ledger it fills.

**The number that matters is not whether the filter looks good.** It will. With
a few thousand signals and a dozen features, a procedure that fits a model,
picks a regularisation strength and then picks a threshold has three chances to
find structure in noise. So the whole pipeline runs again with the training and
validation targets **shuffled**, and the real result is reported as its position
in that distribution. A model trained on noise, selected on noise and applied to
real outcomes is the right null: whatever apparent edge the *procedure*
manufactures shows up there too.

**And the number that decides anything is the baseline.** The first run of this
study reported "+0.1578 R against all signals, p = 0.01", which was true and
badly misleading: "all signals" includes the roughly 80% the risk rules already
refuse, and those are measurably bad at net -0.25 R. A filter that avoids them
only rediscovers the rules. The comparison line is what the system actually
takes over the same test windows, and it is printed in the middle.

On BTC on 05.10.2026 the two answers came out opposite ways: zero of a hundred
shuffled runs matched the filter, so it is learning something real -- and it
still landed 0.069 R per trade *worse* than the rules it was meant to improve
on, having found a population with a higher hit rate to get there.

**What it predicts.** Net R, not whether the trade wins. The signals the
reward-to-risk rule refuses hit 58% of the time against the 41% the system
trades, and still lose 0.13 R each. Hit rate is printed only as a diagnostic.

The folds, the purging and the permutation machinery live in
`traidingbrain.learn.evaluate`, where they are tested -- a p-value this
load-bearing should not rest on untested code in a script.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from functools import cached_property
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
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.evaluate import Outcome, evaluate, permutation_null, position
from traidingbrain.learn.features import row
from traidingbrain.learn.labels import Label, Minutes, label_signal
from traidingbrain.learn.splits import DAY_MS, walk_forward
from traidingbrain.reporting.intervals import block_bootstrap

#: The horizon, the same one the labeller and the embargo use.
HORIZON_HOURS = 48
HOUR_MS = 3_600_000

#: Fewest resolved cases in total before a walk-forward is attempted.
MIN_CASES = 200

#: Share of permutation runs at or above the real result that still counts as
#: lying inside the null distribution.
INSIDE = 0.05

TRAIN_DAYS = 360.0
VALIDATE_DAYS = 90.0
TEST_DAYS = 90.0


@dataclass(frozen=True)
class Case:
    """A labelled signal, shaped the way `learn.evaluate` reads it."""

    record: SignalRecord
    label: Label

    @property
    def opened_ts(self) -> int:
        return self.record.decided_ts

    @property
    def closed_ts(self) -> int:
        return self.label.closed_ts

    @property
    def target(self) -> float:
        return self.label.net_r

    @cached_property
    def features(self) -> list[float]:
        """Cached because the permutation runs read every case many times."""
        return row(self.record)

    @property
    def taken(self) -> bool:
        return self.record.action is Action.TAKEN


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument(
        "--permutations",
        type=int,
        default=30,
        help=(
            "How many shuffled-label runs form the null. The smallest p it can "
            "report is 1/(runs+1), so thirty bottoms out at 0.032 and a hundred "
            "at 0.010 -- the resolution is a choice, not a result."
        ),
    )
    return parser.parse_args()




def load_cases(symbols: list[str], config: object) -> list[Case]:
    """Every signal in the ledger, labelled against the three barriers."""
    store = ParquetStore(config.engine.paths.parquet_dir)  # type: ignore[attr-defined]
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")  # type: ignore[attr-defined]
    funding_store = FundingStore(config.engine.paths.funding_dir)  # type: ignore[attr-defined]
    simulation = config.engine.simulation  # type: ignore[attr-defined]
    expiry_ms = simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal  # type: ignore[attr-defined]
    )
    sig = run_signature(config)

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
        before = len(cases)
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
        print(f"{symbol}: {len(records)} Signale, {len(cases) - before} aufgeloest", flush=True)
    return sorted(cases, key=lambda case: case.opened_ts)


def line(name: str, values: list[float]) -> str:
    if not values:
        return f"  {name:22s} keine"
    hits = 100 * sum(1 for value in values if value > 0) / len(values)
    interval = block_bootstrap(values)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    return (
        f"  {name:22s} n={len(values):5d}  netto {sum(values) / len(values):+.4f} R  "
        f"Treffer {hits:3.0f}%  {bounds}"
    )


def report(outcome: Outcome, null: list[float], runs: int) -> None:
    print("\n" + "=" * 78)
    if not outcome.everything:
        print("Keine Testfaelle -- zu wenig Historie fuer die Fenster")
        return

    print("Nur Testfenster, jedes einmal gelesen, Schwelle auf der Validierung gewaehlt.\n")
    print(line("alle Signale", outcome.everything))
    print(line("vom System genommen", outcome.taken))
    print(line("vom Filter behalten", outcome.kept))

    if outcome.kept:
        share = 100 * len(outcome.kept) / len(outcome.everything)
        over_all = outcome.mean(outcome.kept) - outcome.mean(outcome.everything)
        print(f"\n  behalten {share:.0f}% der Signale")
        print(f"  gegen alle Signale        {over_all:+.4f} R pro Trade")
        if outcome.taken:
            lift = outcome.lift_over_taken
            verdict = "  <- die einzige Zeile, die zaehlt" if lift > 0 else "  <- schlechter"
            print(f"  gegen die heutigen Regeln {lift:+.4f} R pro Trade{verdict}")
    print(f"  mittlerer quadratischer Fehler der Vorhersage {outcome.error:.4f}")

    print(
        "\n  'Alle Signale' enthaelt die rund 80%, die die Risikoregeln ohnehin\n"
        "  ablehnen, und die sind messbar schlecht. Ein Filter, der sie vermeidet,\n"
        "  entdeckt nur die Regeln neu. Die Vergleichslinie ist die mittlere Zeile."
    )

    print(f"\n--- und derselbe Ablauf mit gewuerfelten Labels, {runs} mal ---")
    if not null:
        print("  kein einziger Durchlauf lieferte Testfaelle")
        return
    real = outcome.mean(outcome.kept)
    better, p_value = position(real, null)
    print(
        f"  gewuerfelt: Mittel {np.mean(null):+.4f} R, "
        f"Bandbreite [{min(null):+.4f}, {max(null):+.4f}]"
    )
    print(f"  echt:       {real:+.4f} R")
    print(
        f"  {better} von {len(null)} Zufallslaeufen waren mindestens so gut"
        f"  ->  p ~ {p_value:.3f}  (kleinstmoeglich {1 / (len(null) + 1):.3f})"
    )
    if better > INSIDE * len(null):
        print(
            "\n  Das echte Ergebnis liegt in der Zufallsverteilung. Dann hat das\n"
            "  Verfahren nichts gefunden, und das ist der Befund -- nicht ein\n"
            "  Grund, mehr Merkmale oder ein groesseres Modell zu probieren."
        )
    else:
        print(
            "\n  Das echte Ergebnis liegt ausserhalb der Zufallsverteilung, das\n"
            "  Verfahren findet also Struktur. Ob die gefundene Struktur besser ist\n"
            "  als die Regeln, die wir schon haben, sagt allein die mittlere Zeile\n"
            "  oben. Das sind zwei verschiedene Fragen."
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

    outcome = evaluate(plan.folds, cases)
    null = permutation_null(plan.folds, cases, runs=args.permutations)
    report(outcome, null, args.permutations)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
