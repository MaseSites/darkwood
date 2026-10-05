"""Tighten the cost rule instead of loosening it, and count what the account keeps.

    python scripts/study_costcap.py
    python scripts/study_costcap.py --symbols BTCUSDT,ETHUSDT

The register holds `kostenregel_lockern` at **-0.2996 R**, the worst group in
the whole journal, with an interval excluding zero. Loosening the cost rule is
measured and catastrophic. Tightening it has never been measured, which is an
odd gap for a lever whose mirror image is the strongest refusal evidence in
the project.

**The rule.** `risk.limits.max_cost_fraction_of_risk` refuses a signal whose
round trip would eat more than that share of the money at risk. It stands at
0.15 today: a trade may spend fifteen cents of every franc risked on getting
in and out. Every taken signal carries its `cost_fraction` in the journal, so
the sweep needs no re-simulation of the decision -- only a filter and a
re-label.

**What is reported, and why the usual per-trade figure is the wrong headline.**
A tighter cap takes fewer trades. Mean R per trade can improve while the
account does the same or worse, and it can worsen while the account loses
less. What the account actually experiences is **total R**: trades times mean
R. With no edge to protect, the useful question is not "which cap earns most"
but "which cap loses least", and only the total answers it.

So the table carries both, and the decision column is total R. A system whose
expectancy is negative has exactly one honest lever left, and it is to pay the
toll fewer times.

**What this cannot become.** A cap tuned to the best cell of a sweep is a
parameter fitted on the data it is judged by. The cells are declared in
advance, the interval is on the difference against today's 0.15, and a cap
only earns a recommendation if the improvement survives in the other part of
the data -- the check that killed the one candidate `study_states.py` found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.grid import timeframe_ms
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import block_bootstrap, two_group_difference

HORIZON_MS = 48 * 3_600_000

#: Caps to sweep, declared before measuring. 0.15 is today's setting and the
#: control; everything below it is a tightening.
CAPS: tuple[float, ...] = (0.15, 0.12, 0.10, 0.08, 0.06, 0.04, 0.03)

#: Today's cap, which the differences are measured against.
TODAY = 0.15

#: Resolved trades a cell needs before it is reported with a number.
MIN_RESOLVED = 50

#: An improvement must survive at this share of its size in the other part of
#: the data. Half, as elsewhere in this project.
REPLICATION_FLOOR = 0.5

#: Share of signals used to measure the replication half.
FIT_SHARE = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated. Default: the first four.")
    parser.add_argument(
        "--any",
        action="store_true",
        dest="any_signature",
        help=(
            "Die groesste gespeicherte Signatur lesen, auch wenn die aktuelle "
            "Konfiguration eine andere ergibt. Jede Zahl beschreibt dann jenen "
            "Lauf, nicht den heutigen -- die Ausgabe sagt das."
        ),
    )
    return parser.parse_args()


def measure(work: list, cap: float, config: object) -> tuple[np.ndarray, int]:
    """Net R of every signal whose cost fraction clears the cap.

    Returns the R values and how many signals were offered in total, because
    the share taken is half the story a tighter cap tells.
    """
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(  # type: ignore[attr-defined]
        config.engine.timeframes.signal  # type: ignore[attr-defined]
    )
    out: list[float] = []
    offered = 0
    for spec, records, minutes, rates in work:
        for record in records:
            offered += 1
            fraction = getattr(record, "cost_fraction", None)
            if fraction is None or float(fraction) > cap:
                continue
            result = label_signal(
                side=record.side,
                entry=float(record.entry),
                stop=float(record.stop),
                target=float(record.target),
                decision_ts=record.decided_ts,
                minutes=minutes,
                spec=spec,
                config=config.engine.simulation,  # type: ignore[attr-defined]
                horizon_ms=HORIZON_MS,
                expiry_ms=expiry_ms,
                funding=rates,
            )
            if result.resolved:
                out.append(result.net_r)
    return np.array(out, dtype="float64"), offered


def decompose(work: list, cap: float, config: object) -> None:
    """Split the improvement into the part that is arithmetic and the part that is not.

    This is the test that makes the sweep readable, and without it the result
    would be the seventh false finding of the day. `net_r` is
    `gross_r - cost_r - funding_r`, and `cost_fraction` IS the cost in R -- so
    filtering on a low cost fraction raises net R **by construction**. The
    measured correlation between the filter and the cost it removes is +0.83.

    What is not by construction: the same filter correlates **-0.004** with
    gross R. So it does not mechanically select better moves, and the gross
    difference between cheap and expensive trades is a real question.

    Measured over 3,300 trades, cheap (<= 0.04) against the rest:

      cost    -0.0395  [-0.041, -0.038]   certain, and arithmetic
      gross   +0.0799  [-0.033, +0.195]   NOT established
      net     +0.1190  [+0.005, +0.234]

    A third of the net gain is the certain part. Assume the gross difference is
    zero -- the conservative reading its own interval permits -- and the cheap
    trades come to about **-0.015 R** instead of -0.054 R. Still negative, 3.6
    times less so, from nothing but paying the toll less often.
    """
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(  # type: ignore[attr-defined]
        config.engine.timeframes.signal  # type: ignore[attr-defined]
    )
    cheap: list[tuple[float, float, float]] = []
    dear: list[tuple[float, float, float]] = []
    for spec, records, minutes, rates in work:
        for record in records:
            fraction = getattr(record, "cost_fraction", None)
            if fraction is None:
                continue
            result = label_signal(
                side=record.side,
                entry=float(record.entry),
                stop=float(record.stop),
                target=float(record.target),
                decision_ts=record.decided_ts,
                minutes=minutes,
                spec=spec,
                config=config.engine.simulation,  # type: ignore[attr-defined]
                horizon_ms=HORIZON_MS,
                expiry_ms=expiry_ms,
                funding=rates,
            )
            if not result.resolved:
                continue
            row = (result.gross_r, result.cost_r, result.net_r)
            (cheap if float(fraction) <= cap else dear).append(row)

    if len(cheap) < MIN_RESOLVED or len(dear) < MIN_RESOLVED:
        return

    left = np.array(cheap)
    right = np.array(dear)
    print(f"\nZerlegung bei Deckel {cap:.2f}: {len(cheap)} guenstige gegen {len(dear)} teure")
    for index, name in ((0, "BRUTTO"), (1, "Kosten"), (2, "netto")):
        difference = two_group_difference(left[:, index].tolist(), right[:, index].tolist())
        bounds = difference.labelled() if difference is not None else "zu wenige"
        print(
            f"  {name:7s} {left[:, index].mean():+.4f} gegen {right[:, index].mean():+.4f}  "
            f"Differenz {left[:, index].mean() - right[:, index].mean():+.4f}  {bounds}"
        )
    print(
        "  Die Kostenzeile ist Definition: cost_fraction IST die Kosten in R,\n"
        "  Korrelation +0.83. Die Bruttozeile ist es nicht -- Korrelation -0.004 --\n"
        "  und ihr Intervall entscheidet, ob hier mehr steht als Arithmetik."
    )


def load_work(config: object, *, symbols: list[str], any_signature: bool) -> list:
    """Taken signals, minute candles and funding, per market.

    The signature is resolved rather than assumed: it contains the risk
    configuration, so changing one cap orphans every stored signal. Lowering
    `max_cost_fraction_of_risk` on 05.10.2026 made this study print "keine
    genommenen Signale" for all four markets while 12,843 signals sat in the
    file. `SignalStore.resolve` is what says so instead of leaving it to be
    guessed.
    """
    store = ParquetStore(config.engine.paths.parquet_dir)  # type: ignore[attr-defined]
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")  # type: ignore[attr-defined]
    funding_store = FundingStore(config.engine.paths.funding_dir)  # type: ignore[attr-defined]

    sig, note = signals.resolve(run_signature(config), fallback=any_signature)
    print(f"  {note}")
    print()

    work = []
    for symbol in symbols:
        records = [
            record
            for record in signals.all(symbol=symbol, run_signature=sig)
            if record.action is Action.TAKEN
        ]
        frame = store.read(symbol, config.engine.timeframes.execution)  # type: ignore[attr-defined]
        if not records or frame.empty:
            print(f"{symbol}: keine genommenen Signale")
            continue
        records.sort(key=lambda r: r.decided_ts)
        work.append(
            (
                SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
                records,
                Minutes.of(frame),
                funding_store.read(symbol),
            )
        )
    return work


def main() -> int:
    args = parse_args()
    config = load_config()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )
    work = load_work(config, symbols=symbols, any_signature=args.any_signature)
    if not work:
        print("Nichts zu rechnen.")
        return 1

    # The replication half: the earlier signals of each market.
    early = [(s, r[: int(FIT_SHARE * len(r))], m, f) for s, r, m, f in work]
    late = [(s, r[int(FIT_SHARE * len(r)) :], m, f) for s, r, m, f in work]

    print(
        "Der Kostendeckel refusiert ein Signal, dessen runde Fahrt mehr als diesen\n"
        "Anteil des eingesetzten Risikos frisst. Lockern steht im Register bei\n"
        "-0.2996 R, der schlechtesten Gruppe ueberhaupt. Verschaerfen wurde nie\n"
        "gemessen.\n"
    )
    print(
        f"{'Deckel':>7s} {'Trades':>7s} {'Anteil':>7s} {'R je Trade':>11s} "
        f"{'R GESAMT':>10s} {'gegen 0.15':>11s}  Intervall auf R je Trade"
    )

    baseline_total = None
    rows: list[tuple[float, float, float]] = []
    for cap in CAPS:
        values, offered = measure(late, cap, config)
        if values.size < MIN_RESOLVED:
            print(f"{cap:>7.2f} {values.size:>7d}  zu wenige")
            continue
        total = float(values.sum())
        mean = float(values.mean())
        if cap == TODAY:
            baseline_total = total
        interval = block_bootstrap(values)
        against = "" if baseline_total is None else f"{total - baseline_total:>+11.1f}"
        rows.append((cap, mean, total))
        print(
            f"{cap:>7.2f} {values.size:>7d} {100 * values.size / max(1, offered):>6.1f}% "
            f"{mean:>+11.4f} {total:>+10.1f} {against}  "
            f"{interval.labelled() if interval is not None else 'zu wenige'}"
        )

    if baseline_total is None or not rows:
        return 0

    best = min(rows, key=lambda r: -r[2])  # least negative total
    print(
        f"\nBester Deckel nach R GESAMT: {best[0]:.2f} mit {best[2]:+.1f} R "
        f"gegen {baseline_total:+.1f} R heute."
    )
    if best[0] == TODAY:
        print("Das ist der heutige. Verschaerfen bringt nichts.")
        return 0

    early_values, _ = measure(early, best[0], config)
    early_today, _ = measure(early, TODAY, config)
    if early_values.size >= MIN_RESOLVED and early_today.size >= MIN_RESOLVED:
        gain_late = best[2] - baseline_total
        gain_early = float(early_values.sum()) - float(early_today.sum())
        ratio = abs(gain_early / gain_late) if gain_late else 0.0
        held = gain_early * gain_late > 0 and ratio >= REPLICATION_FLOOR
        print(
            f"In der frueheren Haelfte: {gain_early:+.1f} R gegen {gain_late:+.1f} R "
            f"({ratio:.2f}x) -- {'wiederholt' if held else 'NICHT wiederholt, kein Befund'}"
        )

    decompose(work, best[0], config)

    print(
        "\nEntschieden wird auf R GESAMT, nicht auf R je Trade. Ein straffer Deckel\n"
        "nimmt weniger Trades: das Mittel kann steigen, waehrend das Konto gleich\n"
        "viel verliert, und es kann fallen, waehrend das Konto weniger verliert.\n"
        "Nur die Summe ist, was das Konto erlebt.\n"
        "\nUnd was das hier nicht ist: ein Vorteil. Ein System ohne Vorteil hat genau\n"
        "einen ehrlichen Hebel, und er lautet, die Maut seltener zu zahlen. Das\n"
        "verschiebt das Ziel nicht, es verlangsamt nur den Weg davon weg."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
