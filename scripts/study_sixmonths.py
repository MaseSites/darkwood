"""Where 1,000 CHF ends up in six months, resampled from trades we measured.

    python scripts/study_sixmonths.py
    python scripts/study_sixmonths.py --trades 300 --paths 50000

The research order asks whether 1,000 CHF can become 20,000 in six months, and
asks for it answered with a table: target rate, median, loss rate, severe
losses, max drawdown, and the number of trades and independent periods behind
it. This is that table.

**What makes this different from the simulation in the order.** That one assumes
a payoff of +2R gross on a win and -1R on a loss at an assumed hit rate -- and
says so plainly, calling itself "keine profitable Echtgeldstrategie". The
assumption is the weak point: a take-profit placed at 2R does not mean the
average realised win is 2R. Trades end early, gap through their stop, pay
funding, and exit on time barriers.

So this resamples the **measured** net-R series instead of assuming a shape.
Every path is a draw from trades this system actually produced, with their real
wins, real losses, real fees and real funding.

**In blocks, not independently.** The order asks for resampling that preserves
time dependence, and it is right to: a losing streak is what decides whether a
path survives, and independent draws scatter streaks that the market clusters.
Block length comes from the series' own autocorrelation via `suggested_block`.

**What this cannot tell you.** It cannot tell you the probability of reaching
20,000. It resamples a measured past, so it inherits every property of that
past and assumes the next six months resemble it. Overlapping windows are not
independent evidence and neither are bootstrap paths. The honest reading of a
target rate here is "the measured trade distribution, recombined, reaches the
goal this often" -- which is a statement about the distribution, not a forecast.

**And the headline, measured on 05.10.2026.** The system's own trades have a
net expectancy of about -0.034 R. Compounding a negative expectancy cannot
reach a 20x target at any risk fraction, and raising the risk fraction makes
every path worse rather than widening the chance of a good one. The table below
says so numerically, which is more useful than saying so in prose.
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
from traidingbrain.reporting.intervals import suggested_block

HORIZON_MS = 48 * 3_600_000

#: The target the research order sets, and the stake it starts from.
START_CHF = 1_000.0
TARGET_CHF = 20_000.0

#: Risk fractions the order asks to be compared, as fractions of the account.
RISKS: tuple[float, ...] = (0.0025, 0.005, 0.01, 0.02, 0.03)

#: Trades in six months. The order's own example uses 300.
TRADES = 300

#: Paths per risk fraction.
PATHS = 50_000

#: Fewest measured trades before resampling says anything.
MIN_TRADES = 50


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument("--trades", type=int, default=TRADES)
    parser.add_argument("--paths", type=int, default=PATHS)
    parser.add_argument("--seed", type=int, default=20261005)
    return parser.parse_args()


def measured_net_r(symbols: list[str]) -> list[float]:
    """Net R of every trade the system actually took, in time order.

    Taken signals only. The refused ones are a different population and
    including them would simulate a system nobody runs.
    """
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    signals = SignalStore(config.engine.paths.data_dir / "signals.sqlite")
    funding_store = FundingStore(config.engine.paths.funding_dir)
    expiry_ms = config.engine.simulation.entry_expiry_bars * timeframe_ms(
        config.engine.timeframes.signal
    )
    signature = run_signature(config)

    rows: list[tuple[int, float]] = []
    for symbol in symbols:
        records = [
            record
            for record in signals.all(symbol=symbol, run_signature=signature)
            if record.action is Action.TAKEN
        ]
        frame = store.read(symbol, config.engine.timeframes.execution)
        if not records or frame.empty:
            print(f"{symbol}: keine genommenen Signale", flush=True)
            continue
        minutes = Minutes.of(frame)
        rates = funding_store.read(symbol)
        spec = SymbolSpec(symbol=symbol, **DEFAULT_SPEC)
        kept = 0
        for record in records:
            label = label_signal(
                side=record.side,
                entry=record.entry,
                stop=record.stop,
                target=record.target,
                decision_ts=record.decided_ts,
                minutes=minutes,
                spec=spec,
                config=config.engine.simulation,
                horizon_ms=HORIZON_MS,
                expiry_ms=expiry_ms,
                funding=rates,
            )
            if label.resolved:
                rows.append((record.decided_ts, label.net_r))
                kept += 1
        print(f"{symbol}: {kept} aufgeloeste Trades", flush=True)

    rows.sort(key=lambda row: row[0])
    return [net for _ts, net in rows]


def paths_for(
    series: np.ndarray, *, risk: float, trades: int, paths: int, block: int, seed: int
) -> tuple[np.ndarray, np.ndarray]:
    """Compound block-resampled trades, and track the worst drawdown of each path.

    Blocks rather than independent draws, because a losing streak is what
    decides whether a path survives and independent draws scatter the streaks
    the market clusters. Built by sampling block starts and laying them end to
    end, the same circular scheme `reporting.intervals` uses.
    """
    rng = np.random.default_rng(seed)
    n = series.size
    count = int(np.ceil(trades / block))
    starts = rng.integers(0, n, size=(paths, count))
    offsets = np.arange(block)
    picks = (starts[:, :, None] + offsets[None, None, :]) % n
    draws = series[picks.reshape(paths, count * block)[:, :trades]]

    # Each trade moves the account by risk * net_r of the *current* balance,
    # which is what compounding means and what the order's own formula does.
    steps = 1.0 + risk * draws
    # A path that loses more than everything is dead, not negative: clip so a
    # single catastrophic draw cannot produce a nonsensical sign flip.
    steps = np.clip(steps, 0.0, None)
    equity = START_CHF * np.cumprod(steps, axis=1)

    peak = np.maximum.accumulate(equity, axis=1)
    drawdown = np.max(1.0 - equity / np.maximum(peak, 1e-12), axis=1)
    return equity[:, -1], drawdown


def main() -> int:
    args = parse_args()
    config = load_config()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    series = np.array(measured_net_r(symbols), dtype="float64")
    if series.size < MIN_TRADES:
        print(f"Nur {series.size} Trades -- zu wenig zum Resampeln.")
        return 0

    block = suggested_block(series)
    hits = 100.0 * float((series > 0).mean())
    wins = series[series > 0]
    losses = series[series <= 0]
    print("\n" + "=" * 78)
    print(
        f"{series.size} gemessene Trades, {len(symbols)} Maerkte. "
        f"Blocklaenge {block} (aus der eigenen Autokorrelation)."
    )
    print(
        f"Erwartung {series.mean():+.4f} R   Treffer {hits:.1f}%   "
        f"mittlerer Gewinn {wins.mean():+.3f} R   mittlerer Verlust {losses.mean():+.3f} R"
    )
    print(
        "\nDer Auftrag rechnet mit +2R brutto je Gewinn. Gemessen sind es "
        f"{wins.mean():+.3f} R netto --\nein gesetztes Ziel von 2R ist nicht der "
        "durchschnittlich realisierte Gewinn."
    )

    print(f"\n{args.paths:,} Pfade je Risikostufe, {args.trades} Trades je Pfad.".replace(",", "'"))
    print(
        f"\n{'Risiko':>8s} {'Median':>10s} {'5%':>9s} {'95%':>11s} "
        f"{'Ziel 20k':>9s} {'unter 1k':>9s} {'>=50% weg':>10s} {'DD 95%':>8s}"
    )
    for risk in RISKS:
        final, drawdown = paths_for(
            series,
            risk=risk,
            trades=args.trades,
            paths=args.paths,
            block=block,
            seed=args.seed,
        )
        print(
            f"{100 * risk:7.2f}% {np.median(final):10,.0f} {np.quantile(final, 0.05):9,.0f} "
            f"{np.quantile(final, 0.95):11,.0f} "
            f"{100 * float((final >= TARGET_CHF).mean()):8.2f}% "
            f"{100 * float((final < START_CHF).mean()):8.1f}% "
            f"{100 * float((final <= 0.5 * START_CHF).mean()):9.1f}% "
            f"{100 * float(np.quantile(drawdown, 0.95)):7.1f}%".replace(",", "'")
        )

    print(
        "\nWas diese Tabelle NICHT ist: eine Wahrscheinlichkeit, 20.000 zu erreichen.\n"
        "Sie mischt eine gemessene Vergangenheit neu und erbt damit jede ihrer\n"
        "Eigenschaften. Bootstrap-Pfade sind keine unabhaengigen Belege, genauso\n"
        "wenig wie ueberlappende Fenster. Die ehrliche Lesart ist: so oft erreicht\n"
        "die gemessene Verteilung, neu kombiniert, das Ziel."
    )
    if series.mean() <= 0:
        print(
            "\nUnd solange die Erwartung negativ ist, verschiebt mehr Risiko die\n"
            "Verteilung nicht nach oben, sondern streckt sie nach unten. Das ist in\n"
            "der Tabelle an den Spalten 'unter 1k' und 'DD 95%' direkt ablesbar."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
