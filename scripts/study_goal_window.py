"""If there is no edge, what is left is a bet. How often has that bet paid?

    python scripts/study_goal_window.py
    python scripts/study_goal_window.py --days 24 --gain 0.25

The standing goal is 12,000 CHF to 15,000 by 30.10.2026. Sixteen families of
signal are measured and none is positive; the independent Freqtrade run has an
entry edge 1.8x smaller than the cheapest round trip this venue family can
charge; and the only non-directional income, funding carry, closes about one
percent of the gap even given perfect foresight.

Which leaves exactly one honest path to the number, and it is worth naming
rather than leaving implicit: **put the capital in and be right about
direction.** Not a system -- a bet. The purpose of this script is to say what
that bet has paid historically, because "that is just gambling" is a sentence,
and a base rate is a fact.

So: over every market on disk and every start day in its history, how often did
the next N days deliver the required gain? Reported per market and pooled, with
the median and the worst case beside the hit rate, because the number that
matters is not only how often it worked but what happened the rest of the time.

## Why this is not a recommendation

A base rate is not a probability for the next 24 days, and these twelve markets
are the ones that still exist. Whatever share of windows paid, the same series
contains the drawdowns, and a bet sized to reach +25% in 24 days is sized to
lose a comparable amount just as fast. The account holder is also under 18 and
this system places no orders of its own. This is a measurement of what the
remaining path has historically paid, nothing more -- which is precisely why it
belongs in the record next to the sixteen families that pay nothing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OHLCV = ROOT / "data" / "ohlcv"

#: The goal, as stated: 12,000 CHF to 15,000 by 30.10.2026.
DEFAULT_DAYS = 24
DEFAULT_GAIN = 0.25

#: The loss column's threshold. Fixed rather than tied to `--gain`, so the
#: "how often did it go badly" column keeps meaning the same thing when the
#: target is varied.
BAD_WINDOW = 0.20


def read_daily(symbol: str) -> np.ndarray:
    """Daily opens for one market, oldest first."""
    files = sorted((OHLCV / symbol / "D1").glob("*.parquet"))
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame["ts"] = frame["ts"].astype("int64")
    frame = frame.drop_duplicates(subset="ts", keep="first").sort_values("ts")
    return frame["open"].to_numpy(dtype=float)


def windows(opens: np.ndarray, *, days: int) -> np.ndarray:
    """Return of every `days`-long window, start to end.

    Overlapping on purpose. These are not treated as independent observations
    -- no interval is computed from them -- and overlapping windows are the
    right object for "how often did a stretch like this deliver", which is a
    question about stretches and not about a mean.
    """
    if opens.size <= days:
        return np.array([])
    return opens[days:] / opens[:-days] - 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS)
    parser.add_argument("--gain", type=float, default=DEFAULT_GAIN)
    args = parser.parse_args()

    symbols = sorted(d.name for d in OHLCV.iterdir() if (d / "D1").is_dir())
    print("=" * 78)
    print(f"Wie oft hat ein {args.days}-Tage-Fenster {100 * args.gain:+.0f}% gebracht?")
    print("=" * 78)
    print(
        "\nDas ist die Frage, die uebrig bleibt, wenn kein Vorteil messbar ist:\n"
        "nicht 'welches System', sondern 'wie oft zahlt die Wette'.\n"
    )
    print(
        f"  {'Markt':10s} {'Fenster':>8s} {'Treffer':>8s} {'Median':>9s} "
        f"{'schlechtestes':>14s} {'<= -20%':>9s}"
    )

    pooled: list[np.ndarray] = []
    rates: dict[str, float] = {}
    for symbol in symbols:
        rets = windows(read_daily(symbol), days=args.days)
        if rets.size == 0:
            continue
        pooled.append(rets)
        hit = float((rets >= args.gain).mean())
        rates[symbol] = hit
        print(
            f"  {symbol:10s} {rets.size:>8,d} {100 * hit:>7.1f}% "
            f"{100 * float(np.median(rets)):>+8.1f}% {100 * float(rets.min()):>+13.1f}% "
            f"{100 * float((rets <= -BAD_WINDOW).mean()):>8.1f}%"
        )

    every = np.concatenate(pooled)
    hit = float((every >= args.gain).mean())
    print("\n" + "-" * 78)
    print(
        f"  Ueber alle {len(pooled)} Maerkte und {every.size:,} Fenster: {100 * hit:.1f}% haben\n"
        f"  {100 * args.gain:+.0f}% oder mehr gebracht. Das ist etwa jedes "
        f"{1 / hit:.0f}. Fenster." if hit else "  Kein Fenster hat es gebracht."
    )
    loss = float((every <= -args.gain).mean())
    print(
        f"  Im selben Zeitraum haben {100 * loss:.1f}% der Fenster {100 * args.gain:.0f}% oder\n"
        f"  mehr VERLOREN. Das Verhaeltnis ist {hit / loss:.2f} zu 1."
        if loss
        else "  Kein Fenster hat ebenso viel verloren."
    )
    # Which market the bet would have to be on is the operative detail, and it
    # is visible in the table rather than in the pooled number: the big market
    # almost never does this, the small ones do -- and they are also the ones
    # with the deepest holes in the column beside it.
    calm, wild = min(rates, key=rates.get), max(rates, key=rates.get)  # type: ignore[arg-type]
    print(
        f"\n  Und auf WELCHEN Markt die Wette ginge, steht in der Tabelle, nicht in\n"
        f"  der Summe: {calm} schafft es in {100 * rates[calm]:.1f}% der Fenster, "
        f"{wild} in {100 * rates[wild]:.1f}%.\n"
        f"  Die Wette muesste also auf einen kleinen Markt gehen -- und das sind\n"
        f"  genau die mit den tiefsten Loechern in der Spalte daneben."
    )
    print(
        "\n  Eine Verzerrung, die diese Tabelle freundlicher macht, als sie ist:\n"
        "  diese zwoelf Maerkte existieren alle noch. Jeder, der in den letzten\n"
        "  Jahren verschwunden ist, fehlt hier samt seiner Fenster -- und das\n"
        "  waren ueberwiegend Verlustfenster. Die echte Trefferquote ist also\n"
        "  niedriger als die gezeigte, nicht hoeher."
    )
    print(
        "\n  Was daraus folgt, und es ist unbequem in beide Richtungen:\n"
        "\n  Das Ziel ist nicht unmoeglich -- es ist historisch oft genug passiert,\n"
        "  dass man es nicht wegdiskutieren kann. Es ist nur nichts, worauf ein\n"
        "  System hinarbeiten kann. Wer es will, kauft und hofft; die Trefferquote\n"
        "  oben ist der ganze Plan, und die Verlustquote daneben gehoert dazu.\n"
        "\n  Genau das unterscheidet es von dem, was hier gebaut wurde. Ein System\n"
        "  mit Vorteil macht aus vielen kleinen Entscheidungen eine verlaessliche;\n"
        "  eine Wette macht aus einer Entscheidung ein Ergebnis. Sechzehn Familien\n"
        "  sagen, dass der Vorteil nicht da ist. Sie sagen nicht, dass die Wette\n"
        "  nicht aufgehen kann -- nur, dass sie eine Wette bleibt, egal wie viel\n"
        "  Mechanik man darumherum baut."
    )
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
