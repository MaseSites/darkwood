"""How far is the toll from the edge?

    python scripts/study_fees.py --symbols BTCUSDT

Run `scripts/study_refused.py` first; this reads the signal ledger it fills and
re-labels the signals the system actually took, changing one thing: the fee
schedule. Entry, stop, target and every price stay exactly as they were, so the
gross result cannot move -- a fee does not change where the market went. Only
the toll moves, and the net with it.

**Why this is worth its own script.** Seven levers have been measured and
rejected, and all of them tried to improve the *selection* of trades. Measured
on 05.10.2026 the selection is no longer the obvious place to look: the signals
the risk rules take are gross +0.048 R and net about zero, both refusal rules
are vindicated by labelled outcomes, and a learned filter trained with purging
and checked against a permutation null came out 0.069 R *worse* than the rules
it was meant to improve on. What remains is the toll, and the toll is not a
strategy question. It is `round_trip_fee / stop_fraction`, and the numerator is
a number somebody sets.

**What this is not.** Every interval here contains zero, it is per-signal
labelling without slot competition, and it is one market. It does not say the
system is profitable at a lower fee. It says something narrower and more
useful: the distance between this system and break-even is about the size of a
routine fee discount, which is a different kind of problem from needing to find
an edge.

**The arithmetic is exact, which is why it is worth stating despite the
intervals.** Gross is held fixed by construction and the toll is linear in the
fee rate, so the break-even fee can be read off two rows rather than searched
for. The uncertainty is all in the gross figure; the *difference* between rows
carries none of it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.frames import timeframe_ms
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.market import DEFAULT_SPEC, SymbolSpec
from traidingbrain.journal.signals import Action, SignalStore
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import block_bootstrap

HORIZON_MS = 48 * 3_600_000

#: Rows needed before the break-even fee can be interpolated.
NEEDED_FOR_SLOPE = 2

#: The schedules worth asking about, as multiples of the shipped fee.
#:
#: Not invented: Binance takes 10% off for paying fees in BNB and 25% off at
#: VIP 1 with BNB, both of which are settings rather than achievements. The
#: zero row is the ceiling -- what the system would earn if trading were free --
#: and it is worth printing because it is the gross figure and shows how much
#: of the result the toll is.
SCHEDULES: tuple[tuple[str, float], ...] = (
    ("heute (0.055/0.020%)", 1.00),
    ("-10% (BNB-Rabatt)", 0.90),
    ("-25% (VIP 1 + BNB)", 0.75),
    ("-50%", 0.50),
    ("0 (nur Slippage)", 0.00),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    return parser.parse_args()


def signature(config: object) -> str:
    engine = config.engine  # type: ignore[attr-defined]
    risk = config.risk  # type: ignore[attr-defined]
    return (
        f"{engine.simulation.initial_equity}|{engine.setups.enabled}|"
        f"{risk.limits.max_cost_fraction_of_risk}|{engine.timeframes.signal.value}|refused-v1"
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    funding_store = FundingStore(config.engine.paths.funding_dir)
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal
    )
    sig = signature(config)

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    work: list[tuple[SymbolSpec, list[object], Minutes, list[object]]] = []
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
                records,  # type: ignore[arg-type]
                Minutes.of(frame),
                funding_store.read(symbol),  # type: ignore[arg-type]
            )
        )

    if not work:
        print("Nichts zu rechnen -- erst scripts/study_refused.py laufen lassen")
        return 0

    total = sum(len(records) for _, records, _, _ in work)
    print(
        f"\nNur die {total} Signale, die das System genommen hat, ueber {len(work)} Markt/Maerkte."
    )
    print("Die Gebuehr ist der einzige veraenderte Wert; Einstieg, Stop und Ziel bleiben.\n")
    print(f"{'Gebuehr':>22s} {'brutto':>9s} {'Maut':>8s} {'netto':>9s}  Intervall auf netto")

    rows: list[tuple[float, float]] = []
    for label, factor in SCHEDULES:
        gross: list[float] = []
        cost: list[float] = []
        net: list[float] = []
        for base_spec, records, minutes, rates in work:
            spec = SymbolSpec(
                symbol=base_spec.symbol,
                **{
                    **DEFAULT_SPEC,
                    "taker_fee": DEFAULT_SPEC["taker_fee"] * factor,
                    "maker_fee": DEFAULT_SPEC["maker_fee"] * factor,
                },
            )
            for record in records:
                result = label_signal(
                    side=record.side,  # type: ignore[attr-defined]
                    entry=record.entry,  # type: ignore[attr-defined]
                    stop=record.stop,  # type: ignore[attr-defined]
                    target=record.target,  # type: ignore[attr-defined]
                    decision_ts=record.decided_ts,  # type: ignore[attr-defined]
                    minutes=minutes,
                    spec=spec,
                    config=config.engine.simulation,
                    horizon_ms=HORIZON_MS,
                    expiry_ms=expiry_ms,
                    funding=rates,  # type: ignore[arg-type]
                )
                if result.resolved:
                    gross.append(result.gross_r)
                    cost.append(result.cost_r)
                    net.append(result.net_r)
        if not net:
            continue
        interval = block_bootstrap(net)
        rows.append((factor, float(np.mean(net))))
        print(
            f"{label:>22s} {np.mean(gross):+9.4f} {np.mean(cost):8.4f} {np.mean(net):+9.4f}  "
            f"{interval.labelled() if interval is not None else 'zu wenige'}"
        )

    print("\nBrutto aendert sich nicht -- eine Gebuehr veraendert keinen Kursverlauf.")
    if len(rows) >= NEEDED_FOR_SLOPE:
        (f1, n1), (f2, n2) = rows[0], rows[1]
        if n2 != n1:
            # Linear in the fee rate, so two rows locate the crossing exactly.
            breakeven = f1 - n1 * (f2 - f1) / (n2 - n1)
            print(
                f"Die Null liegt bei {100 * breakeven:.1f}% der heutigen Gebuehr, "
                f"also {100 * (1 - breakeven):.1f}% Rabatt."
            )
    print(
        "\nJedes Intervall oben enthaelt die Null, es ist Signal-Ebene ohne\n"
        "Platzkonkurrenz, und es sind wenige Maerkte. Das hier sagt nicht, dass\n"
        "das System bei weniger Gebuehren profitabel ist. Es sagt, dass der\n"
        "Abstand zur Null die Groesse eines gewoehnlichen Rabatts hat -- und das\n"
        "ist eine andere Art von Problem als einen Vorteil finden zu muessen."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
