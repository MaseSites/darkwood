"""Can anything predict the next 5-10 hours, and what would a 1-100 mean?

    python scripts/study_outlook.py --symbols BTCUSDT --hours 5
    python scripts/study_outlook.py --symbols BTCUSDT,ETHUSDT --hours 5,10 --permutations 50

Severin asked for a number from 1 to 100 that says how good it would be to buy
or sell right now, if he wants to be in profit in 5-10 hours. This script is
what has to pass before that number may exist.

**Why the measurement comes first.** The dashboard already shows a 1-100 figure
and it misled him today: ADA read "85/100, deutlich, Richtung aufwaerts" while
it ran +10.84% and the system took nothing. The 85 is a blend of clarity,
agreement, consensus and coverage -- how strongly the evidence agrees with
itself. Nothing in it was ever trained against what happened next. Shipping a
second confident number without checking it against the future would repeat the
same mistake with more arithmetic behind it.

**What is measured.** At every bar the features in `learn/outlook.py`, and as
the target the signed price move over the horizon with the round trip taken off
its magnitude. Direction is the sign of the prediction, so "buy or sell" is one
model rather than two: a short earns the negative of the move and pays the same
toll. Both sides are run through `learn.evaluate` unchanged -- once on the
target and once on its negative -- so the folds, the purging, the embargo and
the threshold-on-validation rule are the tested ones rather than new code.

**The trap this horizon walks into.** Neighbouring bars share almost all of a
5-10 hour window, so observations are near-duplicates. Three defences, all
required and none sufficient alone: the embargo is at least the horizon, the
block bootstrap gets a block of at least the horizon in bars, and `--step`
thins the pass. Thinning alone would not do -- a step below the horizon leaves
overlap behind -- and this is the exact fault that made `study_liquidity.py`
print a verdict it could not carry.

**What a score band will be allowed to mean.** The decile table at the end is
the calibration: for each band of the model's own prediction, what bars in that
band actually earned out of sample, with an interval. A 1-100 may only be
shipped with that table attached, because "85/100" is worth nothing and
"85/100, and such bars earned +0.21% over five hours, interval [+0.04, +0.38]"
is worth something.

**And the honest outcome.** If the real result sits inside the permutation
distribution, there is no score. That is a finding, not a reason to add
features.

**Measured on BTCUSDT on 05.10.2026: there is no score.** 34,394 cases, 18
folds, 1,435 days, both horizons, both directions.

    Rangkorrelation Vorhersage/Ergebnis   +0.0086 (5h)   +0.0069 (10h)

    5h  verkaufen   alle -0.0213%   gewaehlt -0.0279%   p 0.548
    10h kaufen      alle +0.0441%   gewaehlt +0.0223%   p 0.806
    10h verkaufen   alle -0.0441%   gewaehlt -0.0095%   p 0.194

At 10h the model's chosen subset earned *less* than every bar. The decile
table is flat and non-monotone with hit rates of 45-50% throughout; one row in
twenty excluded zero, and it was the fifth decile rather than the tenth, which
is what ten uncorrected comparisons produce on their own.

A separate number worth keeping from the same run: buying every bar and
holding ten hours earns +0.0441% of price against a round trip of 0.0750%. The
blind trade loses, over a period when BTC rose strongly.

**Then the level distances were added, and the answer is still no.** The first
run had no distance feature at all -- not to the nearest untouched zone, not to
the last swing, not to the nearest fair-value gap -- because
`ZoneTimeline.known_at` copies a list per call and goes quadratic over a full
pass. That was a compute reason, not a substantive one, and it removed exactly
the family the ADA reading pointed at. `learn/levels.py` makes the sweep linear
(2.3 s for 175,537 bars, 11,492 zones and 18,311 gaps), so the hypothesis
became testable. With 35 features instead of 28:

    Rangkorrelation   +0.0039 (5h)   +0.0045 (10h)

    5h  kaufen      alle +0.0213%   gewaehlt +0.0237%   p 0.516
    5h  verkaufen   alle -0.0213%   gewaehlt -0.0232%   p 0.581
    10h kaufen      alle +0.0441%   gewaehlt +0.0495%   p 0.484
    10h verkaufen   alle -0.0441%   gewaehlt -0.0099%   p 0.258

Slightly *worse* than without them, which is noise either way. The decile table
is flat with hit rates of 47-49% and its highest band is the fourth.

**The most convincing single observation is not a p-value.** Across the two
runs exactly one of ten decile rows excluded zero, and it moved -- the fifth
band without the level features, the fourth with them. A real effect does not
wander between adjacent runs; ten uncorrected comparisons produce one such row
by construction.

**Three facts about market structure fell out of the sweep itself**, before any
model ran, and they outlive this negative result:

* 93% of bars have no zone within one ATR. The median distance to the nearest
  untouched zone is 7.6 ATR up and 7.3 ATR down. ADA's "125 untouched, 0 in
  reach" is the normal state, so a zone-based entry structurally waits.
* A fair-value gap on M15 has a median lifetime of one bar and only 0.8% are
  never filled, which is why no gap is ever pending nearby. The column is kept
  because the standardiser already guards zero variance, and dropping it would
  be judgement placed above data.
* The median distance to the last confirmed swing is about 1.6 ATR, so swings
  are the only one of the three that is usually close enough to matter.

**What is left unexplored, honestly.** Ridge is linear, so interactions between
these features are invisible to it -- but the permutation null already measures
what fitting and thresholding manufacture, and a more flexible model would have
to clear a correspondingly wider null. At a rank correlation of 0.004 the
honest reading is that the information is not in these features at this
horizon, not that the model was too simple.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.learn.evaluate import evaluate, permutation_null, position
from traidingbrain.learn.outlook import (
    HOUR_MS,
    NAMES,
    OutlookCase,
    build_cases,
    horizon_bars,
)
from traidingbrain.learn.splits import DAY_MS, walk_forward
from traidingbrain.reporting.intervals import block_bootstrap

TRAIN_DAYS = 240.0
VALIDATE_DAYS = 60.0
TEST_DAYS = 60.0

#: Fewest cases before a walk-forward is attempted at all.
MIN_CASES = 400

#: Share of permutation runs at or above the real result that still counts as
#: lying inside the null.
INSIDE = 0.05

#: Bands for the calibration table.
DECILES = 10

#: Fewest observations before a rank correlation means anything at all.
MIN_FOR_RANK = 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument("--hours", default="5,10", help="Horizons in hours. Default 5,10.")
    parser.add_argument(
        "--step",
        type=int,
        default=4,
        help=(
            "Use every Nth bar. Neighbouring bars share nearly all of the "
            "horizon, so they cost time and add almost nothing. Not a "
            "substitute for the embargo."
        ),
    )
    parser.add_argument("--permutations", type=int, default=30)
    parser.add_argument("--max-bars", type=int, help="Tail of the signal frame. A transport check.")
    return parser.parse_args()


def load(symbols: list[str], hours: int, step: int, max_bars: int | None) -> list[OutlookCase]:
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    cases: list[OutlookCase] = []
    for symbol in symbols:
        frames = {}
        for timeframe in config.engine.timeframes.context:
            frame = store.read(symbol, timeframe)
            if max_bars and timeframe is config.engine.timeframes.signal:
                frame = frame.tail(max_bars)
            frames[timeframe] = frame
        if any(frame.empty for frame in frames.values()):
            print(f"{symbol}: keine Daten", flush=True)
            continue
        analysis = MultiFrameAnalysis(frames, config.engine)
        built, tally = build_cases(analysis, hours=hours, symbol=symbol, step=step)
        print(f"{symbol}: {tally.summary()}", flush=True)
        cases.extend(built)
    return sorted(cases, key=lambda case: case.opened_ts)


def flip(cases: list[OutlookCase]) -> list[OutlookCase]:
    """The same bars with the target negated: the short side.

    Ridge is linear, so a model fitted on the negative of a target is the
    negation of the model, and "kept" then means the bars it wants to sell. The
    realised return of selling them is the negated target, which is exactly
    what `evaluate` pools. So both directions come out of the tested path
    rather than out of a second implementation.
    """
    return [
        OutlookCase(
            opened_ts=case.opened_ts,
            closed_ts=case.closed_ts,
            target=-case.target,
            features=case.features,
            move=-case.move,
            symbol=case.symbol,
        )
        for case in cases
    ]


def line(name: str, values: list[float], block: int) -> str:
    if not values:
        return f"  {name:26s} keine"
    interval = block_bootstrap(values, block=block)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    hits = 100 * sum(1 for value in values if value > 0) / len(values)
    mean_pct = 100 * sum(values) / len(values)
    return f"  {name:26s} n={len(values):6d}  {mean_pct:+.4f}%  Treffer {hits:3.0f}%  {bounds}"


def calibration(predicted: list[float], actual: list[float], block: int) -> None:
    """What each band of the model's own PREDICTION actually earned.

    The bands come from `predicted` and the numbers reported come from
    `actual`, and that distinction is the whole table. The first version of
    this function bucketed by `actual` on both sides: it produced a perfectly
    monotone ladder from -1.47% to +1.65% with hit rates of 0% and 100% and
    "Null ausgeschlossen" on every row, which reads as an overwhelming finding
    and states only that the worst outcomes were bad.

    Built from pooled test folds only. This is the table a 1-100 has to be
    printed beside; without it the number is the ADA number again.
    """
    print("\n--- was jede Bandbreite der VORHERSAGE wirklich verdient hat ---")
    print("  (Testfenster, out-of-sample; ohne diese Tabelle darf keine 1-100 erscheinen)")
    if len(predicted) != len(actual) or len(predicted) < DECILES:
        print("  zu wenige Faelle")
        return
    scores = np.array(predicted, dtype="float64")
    outcomes = np.array(actual, dtype="float64")
    edges = np.quantile(scores, np.linspace(0.0, 1.0, DECILES + 1))
    print(f"  {'Band der Vorhersage':26s} {'n':>6s}  {'Ergebnis':>9s}  Intervall")
    for i in range(DECILES):
        low, high = edges[i], edges[i + 1]
        mask = (scores >= low) & ((scores < high) | (i == DECILES - 1))
        chosen = [float(value) for value in outcomes[mask]]
        print(line(f"{i + 1:2d}. Zehntel", chosen, block))
    rank = _spearman(scores, outcomes)
    print(
        f"\n  Rangkorrelation Vorhersage/Ergebnis: {rank:+.4f}\n"
        "  Das ist die eine Zahl, die sagt, ob eine Rangfolge von 1 bis 100 "
        "ueberhaupt\n  eine Bedeutung haette. Bei null ist jede Bandbreite gleich gut."
    )


def _spearman(left: np.ndarray, right: np.ndarray) -> float:
    """Rank correlation, written out so scipy is not a dependency."""
    if left.size < MIN_FOR_RANK:
        return float("nan")
    a = np.argsort(np.argsort(left)).astype("float64")
    b = np.argsort(np.argsort(right)).astype("float64")
    a -= a.mean()
    b -= b.mean()
    denom = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denom) if denom > 0 else float("nan")


def report(
    name: str,
    *,
    kept: list[float],
    everything: list[float],
    null: list[float],
    runs: int,
    block: int,
) -> None:
    print(f"\n{name}")
    print(line("alle Kerzen", everything, block))
    print(line("vom Modell gewaehlt", kept, block))
    if not kept or not null:
        print("  kein Ergebnis zum Vergleichen")
        return
    real = sum(kept) / len(kept)
    better, p_value = position(real, null)
    floor = 1 / (len(null) + 1)
    print(
        f"  gewuerfelt ({runs}x): Mittel {100 * float(np.mean(null)):+.4f}%, "
        f"Bandbreite [{100 * min(null):+.4f}%, {100 * max(null):+.4f}%]"
    )
    print(
        f"  {better} von {len(null)} Zufallslaeufen waren mindestens so gut "
        f"->  p ~ {p_value:.3f}  (kleinstmoeglich {floor:.3f})"
    )
    if better > INSIDE * len(null):
        print("  -> liegt in der Zufallsverteilung. Kein Vorhersagewert gefunden.")
    else:
        print("  -> liegt ausserhalb. Struktur gefunden; die Hoehe sagt die Tabelle unten.")


def main() -> int:
    args = parse_args()
    config = load_config()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )
    print(f"{len(NAMES)} Merkmale je Kerze, jede Kerze ein Fall -- kein Setup muss feuern.\n")

    for hours in [int(x) for x in args.hours.split(",")]:
        ahead = horizon_bars(hours, config.engine.timeframes.signal)
        print("=" * 78)
        print(f"Horizont {hours} h  ({ahead} Signalkerzen voraus)")
        cases = load(symbols, hours, args.step, args.max_bars)
        if len(cases) < MIN_CASES:
            print(f"Nur {len(cases)} Faelle -- zu wenig fuer Walk-forward")
            continue

        # The embargo is the horizon: a training case whose future runs into the
        # validation window has an outcome that overlaps it.
        plan = walk_forward(
            first_ts=cases[0].opened_ts,
            last_ts=cases[-1].closed_ts,
            train_days=TRAIN_DAYS,
            validate_days=VALIDATE_DAYS,
            test_days=TEST_DAYS,
            embargo_ms=hours * HOUR_MS,
        )
        span = (cases[-1].closed_ts - cases[0].opened_ts) / DAY_MS
        print(f"{len(cases)} Faelle, {len(plan.folds)} Fenster ueber {span:.0f} Tage")

        # Block length in observations, not in bars: `step` already thinned the
        # pass, so a 5h horizon spans ahead/step consecutive cases.
        block = max(2, ahead // max(1, args.step))
        print(f"Blocklaenge {block} Beobachtungen (Horizont {ahead} Kerzen / Schritt {args.step})")

        long_side = evaluate(plan.folds, cases)
        short_side = evaluate(plan.folds, flip(cases))
        if long_side.folds_used == 0:
            # Printed rather than left to show as empty rows. The first run of
            # this script reported "0 Fenster" and then three blank tables, and
            # a reader could easily take that for "nothing was found".
            needed = TRAIN_DAYS + VALIDATE_DAYS + TEST_DAYS
            print(
                f"\nKein Fenster passt: {span:.0f} Tage vorhanden, "
                f"{needed:.0f} gebraucht (Training {TRAIN_DAYS:.0f} + "
                f"Validierung {VALIDATE_DAYS:.0f} + Test {TEST_DAYS:.0f}).\n"
                "Das ist kein Befund, sondern zu wenig Historie -- "
                "--max-bars weglassen oder erhoehen."
            )
            continue
        report(
            "KAUFEN -- was das Modell long nehmen wollte",
            kept=long_side.kept,
            everything=long_side.everything,
            null=permutation_null(plan.folds, cases, runs=args.permutations),
            runs=args.permutations,
            block=block,
        )
        report(
            "VERKAUFEN -- was das Modell short nehmen wollte",
            kept=short_side.kept,
            everything=short_side.everything,
            null=permutation_null(plan.folds, flip(cases), runs=args.permutations),
            runs=args.permutations,
            block=block,
        )
        calibration(long_side.predicted, long_side.everything, block)
        print(
            "\nDie Null ist ein Modell, das auf gewuerfelten Labels trainiert und auf\n"
            "echte Ergebnisse angewandt wurde. Sie misst, wieviel scheinbaren Vorteil\n"
            "das Verfahren selbst erzeugt -- Anpassen, Alpha waehlen, Schwelle waehlen\n"
            "sind drei Chancen, in Rauschen Struktur zu finden."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
