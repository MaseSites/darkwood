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

**What this script found, and then unfound.** On BTC alone on 05.10.2026 the
answer was that break-even sits at 97.0% of today's fee -- a 3% discount, where
BNB alone gives 10%. That made the gap look like a setting rather than a
problem, and it was the one actionable conclusion of the day.

Run over all four markets the same afternoon, break-even is at 30.8% of
today's fee: a **69% discount**, which is not on offer. Gross expectancy across
4 markets and 3,324 taken signals is +0.0136 R against a toll of 0.0491 R, and
even at a fee of zero the net is +0.0151 R with an interval that still contains
zero. BTC's +0.0480 R gross was the best of four, and taking it for the system
was selection among four candidates -- which is exactly what the journal had
already warned, four markets in, with BTC the only positive one.

The lesson is cheap to state and was expensive to learn twice today: a number
measured on one market is a number about that market. The fix is not a better
estimate, it is refusing to quote the single-market figure at all.

**What this is still not.** Every interval contains zero, and it is per-signal
labelling without slot competition. It does not say the system is profitable at
any fee.

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
from traidingbrain.journal.version import run_signature
from traidingbrain.learn.labels import Minutes, label_signal
from traidingbrain.reporting.intervals import block_bootstrap

HORIZON_MS = 48 * 3_600_000

#: Rows needed before the break-even fee can be interpolated.
NEEDED_FOR_SLOPE = 2

#: The schedule factor that means "the fee we actually pay".
UNCHANGED = 1.00

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




def report_breakeven(rows: list[tuple[float, float]]) -> None:
    """Where the fee would have to be for the net to reach zero.

    Read off two rows rather than searched for: gross is held fixed by
    construction and the toll is linear in the fee rate, so the crossing is
    exact. The uncertainty is all in the gross figure, and the *difference*
    between rows carries none of it.
    """
    if len(rows) < NEEDED_FOR_SLOPE:
        return
    (f1, n1), (f2, n2) = rows[0], rows[1]
    if n2 == n1:
        return
    breakeven = f1 - n1 * (f2 - f1) / (n2 - n1)
    print(
        f"Die Null liegt bei {100 * breakeven:.1f}% der heutigen Gebuehr, "
        f"also {100 * (1 - breakeven):.1f}% Rabatt."
    )


def report_in_prices(
    gross: list[float], cost: list[float], stop_fractions: list[float]
) -> None:
    """The same result in percent of price, where the problem is one line long.

    `net_r = (captured move - fee - funding) / stop fraction`, and every term in
    that numerator is a fraction of the entry price. Stop width, position size
    and leverage appear only in the denominator, so they scale both sides
    equally and cannot change the sign -- only how large the R number is.

    That is why the widen-stop and target-cap levers failed and had to: both
    move the denominator, and the sign lives entirely in the numerator. Stated
    in R the result is "-0.0016", which sounds like a near miss of something
    unknown. Stated in price it is a specific quantity of movement the average
    trade does not capture, and there are exactly two ways to change it.

    The caveat: a stop also decides *which* trades are stopped out, so changing
    it does change the captured-move distribution. Widening a stop is not a
    no-op -- but it can only help by capturing more movement, never by making
    the toll cheaper.
    """
    if not stop_fractions or len(stop_fractions) != len(gross):
        return
    # From DEFAULT_SPEC, not from one market's spec: the round trip is a
    # property of the fee schedule, and taking it off whichever market came
    # first would quietly assume every market shares it.
    taker = float(DEFAULT_SPEC["taker_fee"])
    maker = float(DEFAULT_SPEC["maker_fee"])
    round_trip = 100.0 * (taker + maker)
    moves = sorted(100.0 * g * s for g, s in zip(gross, stop_fractions, strict=True))
    middle = moves[len(moves) // 2]
    pays = sum(1 for g, c in zip(gross, cost, strict=True) if g > c)

    print("\n--- dasselbe in Prozent des Preises, wo das Problem eine Zeile lang ist ---")
    print(f"  Runde Fahrt Gebuehr          {round_trip:.4f}% des Preises")
    print(f"  Erfasste Bewegung, Mittel    {sum(moves) / len(moves):+.4f}%")
    print(f"  Erfasste Bewegung, Median    {middle:+.4f}%")
    share = 100 * pays / len(gross)
    print(f"  Trades, die sich selbst bezahlen: {pays} von {len(gross)} ({share:.0f}%)")
    print(
        "\n  Stopweite, Groesse und Hebel stehen nur im Nenner von\n"
        "  (Bewegung - Gebuehr) / Stopanteil. Sie skalieren beide Seiten gleich und\n"
        "  koennen das Vorzeichen nicht drehen -- nur die R-Zahl groesser machen.\n"
        "  Deshalb mussten der weitere Stop und der Zieldeckel scheitern. Es bleiben\n"
        "  zwei Dinge: mehr Bewegung pro Trade erfassen, oder weniger Gebuehr zahlen."
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
    sig = run_signature(config)

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
    stop_fractions: list[float] = []
    today: tuple[list[float], list[float]] | None = None
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
                    if factor == UNCHANGED:
                        entry = float(record.entry)  # type: ignore[attr-defined]
                        stop = float(record.stop)  # type: ignore[attr-defined]
                        stop_fractions.append(abs(entry - stop) / entry if entry else 0.0)
        if not net:
            continue
        if factor == UNCHANGED:
            today = (list(gross), list(cost))
        interval = block_bootstrap(net)
        rows.append((factor, float(np.mean(net))))
        print(
            f"{label:>22s} {np.mean(gross):+9.4f} {np.mean(cost):8.4f} {np.mean(net):+9.4f}  "
            f"{interval.labelled() if interval is not None else 'zu wenige'}"
        )

    print("\nBrutto aendert sich nicht -- eine Gebuehr veraendert keinen Kursverlauf.")
    report_breakeven(rows)
    if today is not None:
        report_in_prices(today[0], today[1], stop_fractions)
    print(
        "\nJedes Intervall oben enthaelt die Null, und es ist Signal-Ebene ohne\n"
        "Platzkonkurrenz. Lies die Rabattzeile gegen das, was zu haben ist: BNB\n"
        "gibt 10%, VIP 1 mit BNB 25%. Verlangt die Null deutlich mehr als das,\n"
        "ist die Gebuehr nicht der Hebel, sondern nur der kleinere von zwei\n"
        "Abstaenden -- und der groessere ist die erfasste Bewegung selbst."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
