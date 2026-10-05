"""How big is the move available at each horizon, against a fixed toll?

    python scripts/study_horizon.py
    python scripts/study_horizon.py --symbols BTCUSDT,ETHUSDT --hours 1,4,24,168,720

Three strategy families were measured and closed on 05.10.2026, and together
they said something none of them said alone: the gross edge findable at short
horizons is between two and eighty times smaller than the cost of trading it.
Every one of those measurements was monotone in horizon -- 0.17 basis points at
fifteen minutes, 37.5 at four hours over thirty-two.

So the question worth asking before building another strategy is not "which
rule" but "where is there room for one at all". The toll is fixed at about
0.1215% of price per round trip; the move available grows with the horizon. This
measures where the second overtakes the first.

**This is a ceiling, not an edge, and the distinction is the whole point.** A
move of 2% does not mean 2% can be earned -- earning it requires knowing the
direction, which is exactly what three families failed to do. What a large move
does mean is that the toll stops being the binding constraint. A horizon where
the typical move is below the toll cannot be traded profitably by anyone,
however good their model; a horizon where it is ten times the toll might be, by
someone who can call direction a little better than chance.

So read this as a filter on where to look, never as a promise about what is
there. Necessary, not sufficient.

**Measured open-to-open**, one candle after the decision, like everything else
here -- a window that begins at a close already seen is not a window anyone
could trade.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC

#: Horizons in hours, from one candle to a month.
#:
#: Measured on H1 candles throughout, so a horizon is a candle count and the
#: comparison across horizons is not also a comparison of data sources.
HOURS: tuple[int, ...] = (1, 2, 4, 8, 16, 24, 48, 96, 168, 336, 720)

#: Blended round trip at the measured hit rate: limit entry pays maker, a target
#: exit pays maker, a stop or time exit pays taker, plus slippage both sides.
#:
#: Not the worst case. Checked rather than assumed -- `sim/broker.py:323` takes
#: the maker rate for a LIMIT entry and `sim/plan.py:297` is what submits one,
#: so a winning trade already costs maker twice.
HIT_RATE = 0.386

#: Hours in a day, for labelling horizons as days once they pass one.
DAY_HOURS = 24


def toll(slippage_bps: float) -> float:
    maker = float(DEFAULT_SPEC["maker_fee"])
    taker = float(DEFAULT_SPEC["taker_fee"])
    exit_fee = HIT_RATE * maker + (1.0 - HIT_RATE) * taker
    return maker + exit_fee + 2.0 * slippage_bps / 10_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument("--hours", help="Comma-separated horizons in hours.")
    return parser.parse_args()


def moves(opens: np.ndarray, ahead: int) -> np.ndarray:
    """Absolute open-to-open move over `ahead` candles, starting one candle on.

    Explicit indices rather than slice arithmetic: the same shape of mistake
    made the reversal study measure a candle against itself, and the slices
    were what hid it.
    """
    n = opens.size
    if n < ahead + 3:
        return np.empty(0)
    at = np.arange(1, n - 1 - ahead)
    return np.abs(opens[at + 1 + ahead] / opens[at + 1] - 1.0)


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    cost = toll(config.engine.simulation.slippage_bps)
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )
    horizons = [int(h) for h in args.hours.split(",")] if args.hours else list(HOURS)

    frames = {}
    for symbol in symbols:
        frame = store.read(symbol, Timeframe.H1)
        if not frame.empty:
            frames[symbol] = frame["open"].to_numpy(dtype="float64")
    if not frames:
        print("Keine H1-Daten.")
        return 1

    print(f"Maut {100 * cost:.4f}% des Preises je runde Fahrt, fix.")
    print(f"{len(frames)} Maerkte, H1-Kerzen, Bewegung Eroeffnung zu Eroeffnung.\n")
    print(
        f"{'Horizont':>10s} {'n':>8s} {'Median':>9s} {'Mittel':>9s} "
        f"{'oberstes Zehntel':>17s} {'Median/Maut':>12s} {'ueber Maut':>11s} "
        f"{'Treffer noetig':>14s}"
    )

    for hours in horizons:
        pooled = [moves(opens, hours) for opens in frames.values()]
        pooled = [m for m in pooled if m.size]
        if not pooled:
            continue
        values = np.concatenate(pooled)
        median = float(np.median(values))
        top = float(np.median(values[values >= np.quantile(values, 0.9)]))
        share = 100.0 * float((values > cost).mean())
        label = f"{hours}h" if hours < DAY_HOURS else f"{hours // DAY_HOURS}d"
        # The number that matters, and it took measuring the moves to see it:
        # expectancy = (2p - 1) * move - toll, so break-even sits at
        # p = (1 + toll/move) / 2. One hour demands 69.9% directional accuracy
        # and a week demands 51.2% -- the same arithmetic as the toll, read the
        # right way round.
        needed = 0.5 * (1.0 + cost / median) if median > 0 else float("nan")
        print(
            f"{label:>10s} {values.size:>8d} {100 * median:>8.3f}% {100 * values.mean():>8.3f}% "
            f"{100 * top:>16.3f}% {median / cost:>11.1f}x {share:>10.1f}% "
            f"{100 * needed:>13.2f}%"
        )

    print(
        "\n'Treffer noetig' ist die Richtungstreffsicherheit, bei der eine Wette die\n"
        "Maut genau bezahlt: p = (1 + Maut/Bewegung) / 2. Das ist die Zahl, die den\n"
        "Horizont entscheidet -- eine Stunde verlangt 69.9%, eine Woche 51.2%.\n"
        "Gemessen hat dieses System eine Rangkorrelation von 0.004, also praktisch\n"
        "50.0%, und jede bisher gescheiterte Familie arbeitete auf Stunden oder\n"
        "Minuten, wo 60 bis 70% verlangt sind. Dass sie scheiterten, war fast\n"
        "vorbestimmt.\n"
        "\n'ueber Maut' ist der Anteil der Fenster, deren Bewegung die runde Fahrt\n"
        "uebersteigt -- also die, die sich ueberhaupt bezahlen KOENNTEN, wenn die\n"
        "Richtung bekannt waere. Sie ist nicht bekannt: drei Familien haben heute\n"
        "genau daran gescheitert.\n\n"
        "Das hier ist eine Decke, kein Vorteil. Ein Horizont, dessen typische\n"
        "Bewegung unter der Maut liegt, ist fuer niemanden profitabel handelbar,\n"
        "wie gut das Modell auch sei. Ein Horizont mit zehnfacher Bewegung koennte\n"
        "es sein -- fuer jemanden, der die Richtung etwas besser als zufaellig\n"
        "trifft. Notwendig, nicht hinreichend."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
