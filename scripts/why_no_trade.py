"""What the analysis saw at a bar where you think a trade belonged.

    python scripts/why_no_trade.py --from "2026-10-01 08:00" --to "2026-10-01 13:00"
    python scripts/why_no_trade.py --symbol SOLUSDT --from "2026-09-28 00:00" --hours 12

Severin's complaint, and it is the right one: the screen almost never proposes
anything, yet the chart is full of places where a trade would obviously have
worked. One of the two is wrong and this says which, for a bar he can point at.

It prints the *ingredients* rather than a verdict. Each setup is a conjunction
of conditions over pools, structure, zones, gaps and candles; "setup A did not
fire" is useless, but "there was no pool for it to break" is a fact about the
market and "the pool was broken two bars ago" is a fact about the rule. The
first means the chart offered nothing the rules describe. The second means the
rules describe it and missed it, which is a different problem with a different
fix.

Times are UTC, like everything stored. A chart read in Swiss local time is two
hours ahead in summer and one in winter, which is exactly the kind of mismatch
that makes two people argue about different candles.
"""

from __future__ import annotations

import argparse
import calendar
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.analysis.liquidity import ZoneKind
from traidingbrain.analysis.pipeline import MultiFrameAnalysis
from traidingbrain.config.settings import load_config
from traidingbrain.data.store import ParquetStore
from traidingbrain.score.rating import rate
from traidingbrain.score.reading import score_at
from traidingbrain.strategy.setups import evaluate_all

#: How near a zone has to be to be worth mentioning, in ATR. Beyond this it is
#: a line on a chart rather than something the next hour can reach.
NEARBY_ATR = 3.0


def parse_utc(text: str) -> int:
    return calendar.timegm(time.strptime(text, "%Y-%m-%d %H:%M")) * 1000


def clock(ts: int) -> str:
    return time.strftime("%d.%m %H:%M", time.gmtime(ts / 1000))


def _describe_pools(liquidity: object, *, close: float, previous: float, unit: float) -> None:
    """The pools setup A breaks, and what this bar did to them.

    Split out because the three states it separates are the whole point:
    nothing to break, broken on this bar, or broken earlier. "Setup A did not
    fire" cannot tell them apart, and they are three different problems.
    """
    for kind, label in (
        (ZoneKind.EQUAL_HIGHS, "gleiche Hochs"),
        (ZoneKind.EQUAL_LOWS, "gleiche Tiefs"),
    ):
        pools = liquidity.zones_of(kind)  # type: ignore[attr-defined]
        if not pools:
            print(f"               keine {label} gefunden -- Setup A hat nichts zu brechen")
            continue
        for pool in pools:
            upward = kind is ZoneKind.EQUAL_HIGHS
            edge = pool.high if upward else pool.low
            now_beyond = close > edge if upward else close < edge
            was_beyond = previous > edge if upward else previous < edge
            state = (
                "diese Kerze gebrochen"
                if now_beyond and not was_beyond
                else "schon vorher gebrochen"
                if now_beyond
                else f"{abs(close - edge) / unit:.1f} ATR entfernt"
            )
            print(f"               {label} {pool.low:,.1f}-{pool.high:,.1f}: {state}")


def describe_bar(multi: MultiFrameAnalysis, index: int) -> None:
    analysis = multi.signal
    ts = analysis.ts_at(index)
    close = analysis.close_at(index)
    unit = analysis.atr_at(index)
    frame = analysis.frame
    high = float(frame["high"].to_numpy()[index])
    low = float(frame["low"].to_numpy()[index])
    previous = analysis.close_at(index - 1) if index else close

    print(f"\n{'=' * 74}")
    print(f"{clock(ts)} UTC   C {close:,.1f}   H {high:,.1f}   L {low:,.1f}   ATR {unit:,.1f}")

    structure = analysis.structure.state_at(index)
    print(f"  Struktur     Trend {structure.trend.value}, Folge [{structure.sequence_text()}]")
    breaks = []
    if structure.bos:
        breaks.append(f"Bruch vor {structure.bars_since_bos} Kerzen")
    if structure.choch:
        breaks.append(f"Charakterwechsel vor {structure.bars_since_choch} Kerzen")
    print(
        f"               {', '.join(breaks) if breaks else 'kein Bruch im Fenster'}"
        f"  (Richtung {structure.break_direction.value})"
    )

    liquidity = analysis.liquidity.state_at(index)
    sweeps = []
    if liquidity.sweep_up:
        sweeps.append("Hoch geholt")
    if liquidity.sweep_down:
        sweeps.append("Tief geholt")
    print(
        f"  Liquidität   {', '.join(sweeps) if sweeps else 'kein Sweep'}"
        + (f" (vor {liquidity.bars_since_sweep} Kerzen)" if liquidity.bars_since_sweep else "")
    )

    # The pools are what setup A breaks. Saying whether one exists, and whether
    # this bar or an earlier one crossed it, separates "nothing to break" from
    # "broken before, so the rule has already passed on it".
    _describe_pools(liquidity, close=close, previous=previous, unit=unit)

    zones = list(analysis.zones.unmitigated_at(index))
    near = [z for z in zones if abs(close - z.mid) / unit <= NEARBY_ATR]
    print(f"  Zonen        {len(zones)} unberührt, davon {len(near)} in Reichweite")
    for zone in near[:4]:
        print(
            f"               {zone.role.value} {zone.low:,.1f}-{zone.high:,.1f}"
            f"  {abs(close - zone.mid) / unit:.1f} ATR entfernt"
        )

    patterns = analysis.candles.at(index)
    print(
        f"  Kerzen       {', '.join(p.value for p in patterns) if patterns else 'kein Muster'}"
        f"  (Neigung {analysis.candles.bias_at(index).value})"
    )

    gaps = [g for g in analysis.fair_value_gaps if g.created_index <= index]
    live = [g for g in gaps[-6:] if abs(close - g.mid) / unit <= NEARBY_ATR]
    print(f"  Fair Value   {len(live)} Lücke(n) in Reichweite")

    reading = score_at(multi, index)
    if reading is None:
        print("  Bewertung    noch nicht bereit (eine Zeitebene wärmt auf)")
    else:
        rating = rate(reading.score)
        print(
            f"  Bewertung    {rating.value}/100 ({rating.band}), Richtung "
            f"{reading.score.direction.value}, schwächster Teil {rating.weakest}"
        )

    fired = evaluate_all(analysis, index)
    if fired:
        for signal in fired:
            print(
                f"  >>> SETUP {signal.setup} {signal.name}: {signal.side.value} "
                f"{signal.entry:,.1f} / Stop {signal.stop:,.1f} / Ziel {signal.target:,.1f}"
            )
    else:
        print("  Setups       keines ausgelöst")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--from", dest="start", required=True, help='UTC, "YYYY-MM-DD HH:MM"')
    parser.add_argument("--to", dest="end", help='UTC, "YYYY-MM-DD HH:MM"')
    parser.add_argument("--hours", type=int, default=6, help="window length when --to is absent")
    args = parser.parse_args()

    config = load_config().engine
    store = ParquetStore(config.paths.parquet_dir)
    frames = {tf: store.read(args.symbol, tf) for tf in config.timeframes.context}
    if any(frame.empty for frame in frames.values()):
        print(f"keine Daten für {args.symbol}", file=sys.stderr)
        return 1

    start = parse_utc(args.start)
    end = parse_utc(args.end) if args.end else start + args.hours * 3_600_000

    print(f"{args.symbol}: was die Analyse sah, {clock(start)} bis {clock(end)} UTC")
    multi = MultiFrameAnalysis(frames, config)
    stamps = multi.signal.column("ts")
    shown = 0
    for index in range(len(stamps)):
        if start <= int(stamps[index]) <= end:
            describe_bar(multi, index)
            shown += 1
    if not shown:
        print("keine Kerze in diesem Fenster", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
