"""Does the next candle lean against the last one, and does it pay?

    python scripts/study_reversal.py
    python scripts/study_reversal.py --symbols BTCUSDT,ETHUSDT --timeframes M15,H1,H4

The simple comparison the test plan asks to keep regardless of what the
complicated models do: predict against the last closed candle's return. It
covers two things at once -- the plan's baseline D, and the "Mean Reversion"
strategy family, which this project had never tested while all five of its
shipped setups are continuation logic.

**It needs no backtest, which is the point.** A reversal claim is a statement
about conditional forward returns, so it can be measured on the price series
directly. No slots, no sizing, no strategy object: just "given the last candle
went up, what did the next hours do". That makes it cheap enough to run across
markets and timeframes in one pass, and it removes every confound a backtest
adds.

**Entry is the next candle's open, never the close just seen.** A signal from a
closed candle cannot be filled at a price that has already happened -- the test
plan says so explicitly and it is the most common way a reversal study invents
an edge it does not have.

**The prediction this is testing against.** A 2026 preprint reports measurable
15-minute reversal in crypto at a gross advantage of about 1.3 basis points
against an assumed 5 basis points of round-trip cost -- so the effect is real
and does not pay. Our own round trip is about 13.5 basis points including
slippage, nearly three times theirs. If that reading carries over, the gross
edge here should be small, positive, and swamped. A result much larger than a
basis point or two would be the surprise and should be treated as a bug
hypothesis before a finding.

**The one number that decides it.** Gross conditional return minus the round
trip, with an interval. Hit rates are printed as a diagnostic only: this
project has measured three separate times that a population with a better hit
rate can earn less.
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
from traidingbrain.reporting.intervals import block_bootstrap


#: Round trip as a fraction of price: fees plus slippage both ways.
#:
#: The fees are the published schedule; the slippage is what the simulator
#: assumes per side. Both belong here, because the question is whether a
#: measured edge survives what it actually costs to take.
def round_trip(slippage_bps: float) -> float:
    fees = float(DEFAULT_SPEC["taker_fee"]) + float(DEFAULT_SPEC["maker_fee"])
    return fees + 2.0 * slippage_bps / 10_000.0


#: How many candles ahead to measure, per timeframe.
#:
#: One is the plan's own question. The longer ones are here because the ratio of
#: movement to fee is the whole problem: a typical five-hour BTC move is about
#: 89 basis points against a 13.5 basis point round trip, and at fifteen minutes
#: it is a fraction of that. If reversal pays anywhere it should pay where the
#: moves are large relative to the toll.
HORIZONS: tuple[int, ...] = (1, 2, 4, 8)

#: Quantile edges for "how big was the last candle", fitted per market.
#:
#: A reversal claim is usually about *overextension*, so the interesting group
#: is the largest moves rather than all of them. Quantiles rather than fixed
#: thresholds, since an ATR-sized move means different things across eras.
BANDS = (0.0, 0.5, 0.8, 0.95, 1.0)

#: Fewest observations in a band before it is reported at all.
MIN_BAND = 30


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated markets. Default: the first four.")
    parser.add_argument("--timeframes", default="M15,H1,H4")
    return parser.parse_args()


def forward_returns(frame: object, ahead: int) -> tuple[np.ndarray, np.ndarray]:
    """The last candle's return, and the return of the `ahead` candles after it.

    Both measured open-to-open one candle later than the signal, so the entry
    price is one a decision taken at the close could actually reach. Using the
    close that produced the signal would be the lookahead this study exists to
    avoid.
    """
    opens = np.asarray(frame["open"], dtype="float64")  # type: ignore[index]
    closes = np.asarray(frame["close"], dtype="float64")  # type: ignore[index]
    n = closes.size
    if n < ahead + 4:
        return np.empty(0), np.empty(0)

    # Explicit index arrays rather than slice arithmetic, because the first
    # version got the offset wrong by one and the slices hid it. There, both
    # series ended up describing the SAME candle -- the signal as its
    # close-to-close return and the "forward" move as its open-to-open return --
    # so the contrarian result was just minus the absolute return, reading as
    # -0.40% on every candle and -2.02% on the largest, with a hit rate of 0%.
    #
    # The hit rate was the tell, not the size. A real effect, however bad, wins
    # sometimes; exactly zero means the two columns are the same number.
    at = np.arange(1, n - 1 - ahead)
    signal = closes[at] / closes[at - 1] - 1.0
    forward = opens[at + 1 + ahead] / opens[at + 1] - 1.0
    return signal, forward


def line(name: str, values: np.ndarray, cost: float) -> str:
    if values.size < MIN_BAND:
        return f"    {name:26s} n={values.size:6d}  zu wenige"
    net = values - cost
    interval = block_bootstrap(net * 100.0)
    bounds = interval.labelled() if interval is not None else "zu wenige"
    hits = 100.0 * float((net > 0).mean())
    return (
        f"    {name:26s} n={values.size:6d}  brutto {100 * values.mean():+.4f}%  "
        f"netto {100 * net.mean():+.4f}%  Treffer {hits:3.0f}%  {bounds}"
    )


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    cost = round_trip(config.engine.simulation.slippage_bps)
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )
    timeframes = [Timeframe(t.strip()) for t in args.timeframes.split(",")]

    print(f"Runde Fahrt {100 * cost:.4f}% des Preises (Gebuehr + Slippage beidseitig).")
    print("Einstieg zur Eroeffnung der NAECHSTEN Kerze, nie zum gesehenen Schluss.")
    print("Gegenbewegung = gegen das Vorzeichen der letzten Kerze handeln.\n")

    for timeframe in timeframes:
        for ahead in HORIZONS:
            pooled_signal: list[np.ndarray] = []
            pooled_forward: list[np.ndarray] = []
            for symbol in symbols:
                frame = store.read(symbol, timeframe)
                if frame.empty:
                    continue
                signal, forward = forward_returns(frame, ahead)
                if signal.size:
                    pooled_signal.append(signal)
                    pooled_forward.append(forward)
            if not pooled_signal:
                continue
            signal = np.concatenate(pooled_signal)
            forward = np.concatenate(pooled_forward)

            # Trading against the last candle: the realised return is the
            # forward move times the opposite of its sign.
            contrarian = -np.sign(signal) * forward
            print(f"  {timeframe.value}, {ahead} Kerzen voraus  ({signal.size} Beobachtungen)")
            print(line("alle Kerzen", contrarian, cost))

            # And by how large the last candle was, since a reversal claim is
            # usually about overextension rather than about every candle.
            magnitude = np.abs(signal)
            edges = np.quantile(magnitude, BANDS)
            for i in range(len(BANDS) - 1):
                low, high = edges[i], edges[i + 1]
                mask = (magnitude >= low) & ((magnitude < high) | (i == len(BANDS) - 2))
                label = f"Groesse {100 * BANDS[i]:.0f}-{100 * BANDS[i + 1]:.0f}%"
                print(line(label, contrarian[mask], cost))
            print()

    print(
        "Ein Preprint von 2026 berichtet messbare 15-Minuten-Gegenbewegung mit "
        "etwa\n1,3 Basispunkten brutto gegen 5 Basispunkte angenommene Kosten -- der "
        "Effekt\nist dort real und zahlt nicht. Unsere runde Fahrt ist fast dreimal "
        "so hoch.\nEin Bruttoergebnis deutlich ueber ein, zwei Basispunkten waere "
        "hier die\nUeberraschung und zuerst ein Fehlerverdacht, kein Befund."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
