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

#: Share of exits that actually pay the maker rate: the ones that reach a limit
#: target.
#:
#: This was wrong until 05.10.2026 and carried 0.386, the *hit rate*. The two
#: differ because a winning trade need not win at its target: of the champion's
#: 3,300 labelled signals, 1,118 exit at the target (33.879%) and 157 exit
#: positively on time -- and a time exit is a market order paying taker
#: (`learn/labels.py:424`). Using the hit rate therefore credited 157 trades
#: with a maker rebate they never earned, and made the toll 1.34% too low.
#:
#: An audit found the hit rate is also the wrong *kind* of number here: it comes
#: from barrier-labelled trades, while this script measures a barrier-free
#: directional bet whose exit has no limit target at all. The honest figure for
#: a pure directional bet is therefore taker on both sides; `--round-trip`
#: exists to price that, and the default below stays comparable with the rest of
#: the project's reporting.
TARGET_EXIT_SHARE = 0.33879

#: Whether the *entry* maker rate is earned is a separate and larger question.
#: `sim/broker.py:322-324` charges maker for every LIMIT entry, but 97.5% of
#: fills take the open branch and in 96.2% of those the open equals the limit
#: in the first minute the order is alive -- economically a market entry billed
#: as a resting one. Correcting it moves the system's measured expectancy from
#: -0.0340 R to -0.0615 R. That belongs in the simulator, not in this script's
#: constant, and `audit/ZIELRECHNUNG.md` section 3 is where it is recorded.
ENTRY_PAYS_MAKER = True

#: Hours in a day, for labelling horizons as days once they pass one.
DAY_HOURS = 24


def toll(slippage_bps: float) -> float:
    maker = float(DEFAULT_SPEC["maker_fee"])
    taker = float(DEFAULT_SPEC["taker_fee"])
    entry_fee = maker if ENTRY_PAYS_MAKER else taker
    exit_fee = TARGET_EXIT_SHARE * maker + (1.0 - TARGET_EXIT_SHARE) * taker
    return entry_fee + exit_fee + 2.0 * slippage_bps / 10_000.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument("--hours", help="Comma-separated horizons in hours.")
    parser.add_argument(
        "--round-trip",
        type=float,
        help=(
            "Override the toll with a round trip in percent, to price a venue "
            "this engine does not trade. Binance spot charges 0.1%% a side, so "
            "--round-trip 0.2 is a spot round trip before slippage -- nearly "
            "twice the 0.1215%% a USDT perpetual costs here. The move "
            "distribution is a property of the market and does not change, so "
            "the same table priced at a different toll is the honest way to "
            "ask what a different venue would demand."
        ),
    )
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
    cost = (
        args.round_trip / 100.0
        if args.round_trip is not None
        else toll(config.engine.simulation.slippage_bps)
    )
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
        "Horizont entscheidet -- eine Stunde verlangt rund 70%, eine Woche rund 51%.\n"
        "Jede bisher gescheiterte Familie arbeitete auf Stunden oder Minuten, wo 60\n"
        "bis 70% verlangt sind.\n"
        "\nWas dieses System dagegen *erreicht*, steht hier absichtlich nicht. Eine\n"
        "frueherere Fassung schrieb 'Rangkorrelation 0.004, also praktisch 50.0%' --\n"
        "das war eine Umformulierung und keine Messung. Die Richtungstreffsicherheit\n"
        "des Modells (sign(Vorhersage) == sign(Bewegung)) wird nirgends in diesem\n"
        "Repository berechnet; 0.004 ist eine Spearman-Korrelation ueber mautbereinigte\n"
        "signierte Renditen, und der Schritt von dort zu einer Prozentzahl ist einer,\n"
        "den niemand gerechnet hat. Die unbedingte Basisquote liegt bei 50.8%.\n"
        "Siehe audit/ZIELRECHNUNG.md, Abschnitt 2.\n"
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
