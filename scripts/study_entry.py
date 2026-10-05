"""Does a resting order placed better than the market earn its keep?

    python scripts/study_entry.py
    python scripts/study_entry.py --symbols BTCUSDT,ETHUSDT

An audit on 05.10.2026 found something the simulator had been hiding in plain
sight: **3,219 of 3,300 fills (97.5%) take the open branch, and in 96.2% of
those the bar's open is numerically identical to the limit price, in the first
minute the order is alive.** The limit therefore sits at the market. It fills
almost always, it gains nothing on price, and it is nevertheless charged the
maker fee -- a market entry billed as a resting one.

That is a defect, and it is also a lead. `stop-width-cannot-flip-the-sign` says
net R is `(captured move - fee) / stop fraction`, and that stop, size and
leverage cancel. Only two things can change the sign: a lower fee, or **more
captured movement per trade**. An entry placed away from the market is the one
untested way to get the second, and it fixes the first as a side effect, because
a price that has to come to the order earns the maker rebate honestly.

**The arithmetic of moving the entry, which is why this is worth measuring.**
Hold the stop and the target prices fixed and move a long's entry down by `k`
of its stop distance `D`:

* stop distance becomes `D(1-k)` -- the denominator shrinks
* distance to target becomes `(T-E) + kD` -- the numerator grows
* so a 1.5:1 plan at k=0.2 becomes `(1.5 + 0.2) / 0.8 = 2.125:1`

And the cost: the fill is no longer certain. The price must retrace to the
order, which is a different population of trades -- a pullback, not a breakout
continuation. Whether better terms on fewer trades beats worse terms on all of
them is not something the arithmetic settles, which is the whole reason this
script runs rather than argues.

**The accounting trap this reports its way around.** Comparing the mean net R
of the *filled* trades across values of k is a selection comparison: a larger k
fills fewer and more favourable signals, so its mean improves even if the
account does worse. The honest column is the mean **per signal offered**, with
an unfilled signal counted as zero -- it is a non-event, earning nothing and
costing nothing.

**The confound that column still carries, named rather than hidden.** The
broker has one position slot (`sim/broker.py:245`). Fewer fills free that slot
for signals that are currently crowded out, so per-signal R understates a high
`k` by however much the freed slot is worth. `occupancy-shadow-measured` put
that shadow at 4,090 hidden signals against 1,666 visible, and measuring it
properly needs a broker rebuild. This script cannot settle it and says so.
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
from traidingbrain.domain.enums import Side
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import block_bootstrap

HORIZON_MS = 48 * 3_600_000

#: How far to move the entry toward the stop, as a fraction of the stop
#: distance. Zero is the shipped behaviour and serves as the control: it must
#: reproduce the champion's -0.0340 R, and if it does not then this script is
#: measuring something other than what it claims.
#:
#: Capped at 0.5 because the plan's reward-to-risk floor would reject most of
#: what lies beyond: at k=0.5 the stop distance halves, and the cost rule
#: (`max_cost_fraction_of_risk`) refuses a stop too tight to carry the fee.
#: That rule is not applied here -- this measures the labelling, not the
#: planner -- so beyond 0.5 the numbers would describe trades the live system
#: would never place.
OFFSETS: tuple[float, ...] = (0.0, 0.05, 0.1, 0.2, 0.3, 0.5)

#: Resolved trades needed before a cell is printed with a number.
MIN_RESOLVED = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated. Default: the first four.")
    return parser.parse_args()


def shifted(entry: float, stop: float, side: Side, offset: float) -> float:
    """The entry moved `offset` of the stop distance away from the market.

    For a long that is downward and for a short upward -- in both cases
    *toward the stop*, which is what shrinks the risk distance and lengthens
    the run to target.
    """
    distance = abs(entry - stop)
    if side is Side.LONG:
        return entry - offset * distance
    return entry + offset * distance


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    funding_store = FundingStore(config.engine.paths.funding_dir)
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal
    )
    sig = run_signature(config)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    work = []
    for symbol in symbols:
        records = [
            record
            for record in signals.all(symbol=symbol, run_signature=sig)
            if record.action is Action.TAKEN
        ]
        frame = store.read(symbol, config.engine.timeframes.execution)
        if not records or frame.empty:
            print(f"{symbol}: keine genommenen Signale im Protokoll", flush=True)
            continue
        work.append(
            (
                SymbolSpec(symbol=symbol, **DEFAULT_SPEC),
                records,
                Minutes.of(frame),
                funding_store.read(symbol),
            )
        )

    if not work:
        print("Nichts zu rechnen -- erst scripts/study_refused.py laufen lassen")
        return 1

    offered = sum(len(records) for _, records, _, _ in work)
    print(f"\n{offered} angebotene Signale ueber {len(work)} Markt/Maerkte.")
    print(
        "Nur der Einstiegspreis wird verschoben. Stop und Ziel bleiben, wo die\n"
        "Struktur sie hingelegt hat -- eine Verschiebung beider waere ein anderer\n"
        "Plan und nicht ein besserer Einstieg in denselben.\n"
    )
    print(
        f"{'Versatz':>8s} {'gefuellt':>9s} {'Quote':>7s} {'netto je Fill':>14s} "
        f"{'netto je Signal':>16s}  Intervall auf netto je Signal"
    )

    control: float | None = None
    for offset in OFFSETS:
        per_signal: list[float] = []
        filled: list[float] = []
        holds: list[float] = []
        for spec, records, minutes, rates in work:
            for record in records:
                entry = shifted(
                    float(record.entry), float(record.stop), record.side, offset
                )
                result = label_signal(
                    side=record.side,
                    entry=entry,
                    stop=float(record.stop),
                    target=float(record.target),
                    decision_ts=record.decided_ts,
                    minutes=minutes,
                    spec=spec,
                    config=config.engine.simulation,
                    horizon_ms=HORIZON_MS,
                    expiry_ms=expiry_ms,
                    funding=rates,
                )
                if result.resolved:
                    filled.append(result.net_r)
                    per_signal.append(result.net_r)
                    holds.append(result.minutes_held / 60.0)
                else:
                    # Never filled: a non-event. Zero, not a loss and not
                    # dropped -- dropping it is the selection this column
                    # exists to avoid.
                    per_signal.append(0.0)

        if len(filled) < MIN_RESOLVED:
            print(f"{offset:>8.2f} {len(filled):>9d} {'':>7s} {'zu wenige':>14s}")
            continue

        rate = len(filled) / len(per_signal)
        interval = block_bootstrap(per_signal)
        mark = ""
        if offset == 0.0:
            control = float(np.mean(per_signal))
        elif control is not None and np.mean(per_signal) > control:
            mark = "  <- besser als heute"
        hold = f"{np.mean(holds):.0f}h" if holds else "?"
        print(
            f"{offset:>8.2f} {len(filled):>9d} {100 * rate:>6.1f}% "
            f"{np.mean(filled):>+14.4f} {np.mean(per_signal):>+16.4f}  "
            f"{interval.labelled() if interval is not None else 'zu wenige':<28s} "
            f"Haltedauer {hold}{mark}"
        )

    print(
        "\n'netto je Fill' ist eine Auswahlzahl und steht hier nur zum Vergleich:\n"
        "ein groesserer Versatz fuellt weniger und guenstigere Signale, also\n"
        "verbessert sich diese Spalte auch dann, wenn das Konto schlechter laeuft.\n"
        "Entschieden wird auf 'netto je Signal', wo ein nicht gefuelltes Signal\n"
        "null zaehlt -- es verdient nichts und kostet nichts.\n"
        "\nWas diese Spalte dennoch unterschaetzt: der Broker hat EINEN Platz\n"
        "(sim/broker.py:245). Weniger Fuellungen machen ihn fuer Signale frei, die\n"
        "heute verdraengt werden, und dieser Gewinn steht in keiner Spalte. Der\n"
        "gemessene Schatten lag bei 4.090 verborgenen gegen 1.666 sichtbaren\n"
        "Signalen; ihn richtig zu verrechnen verlangt einen Umbau des Brokers.\n"
        "Ein Versatz, der hier gleich gut aussieht, ist dort also besser.\n"
        "\nUnd der Grund, warum das ueberhaupt gemessen wird: heute liegt das Limit\n"
        "praktisch am Markt (97,5% der Fuellungen am Eroeffnungspreis, 96,2% davon\n"
        "identisch mit dem Limit), fuellt fast immer, gewinnt nichts am Preis und\n"
        "wird trotzdem als Maker abgerechnet. Ein Kurs, der zur Order kommen muss,\n"
        "verdient die Maker-Gebuehr wirklich."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
