"""The one family the research order never named: one market against another.

    python scripts/study_cross_section.py
    python scripts/study_cross_section.py --draws 20000

Fourteen families are closed and none is positive. Before concluding that the
space is empty it is worth saying precisely what the space *was*, because the
register makes it visible: every arm so far measured a market against its own
future, and every baseline was "always long" on the same rows.

That shares one property across all 87 arms. The twelve markets here move
together -- when BTC rises most of them rise -- so a model asked "will market m
go up" is largely asked "will crypto go up", twelve times. And "always long" is
made of exactly that same common movement. The search has been asking a model
to beat the common factor at being the common factor.

A cross-sectional arm asks a different question: given today's twelve markets,
which of them will outperform the others? Hold the top third long and the
bottom third short in equal weight and the common factor cancels by
construction. What is left is the part nobody here has looked at.

**It is a harder bar, not an easier one, and that is said first.** Two legs pay
two tolls. A spread that would be a fine directional edge can still lose money
here. So this is not a hopeful arm; it is the last unexamined direction in the
natural space, and measuring it is what makes "the space is empty" a finding
rather than an assumption.

## Declared before any number was read

Rankings, each from price alone and observable at the moment of execution:

  mom_30   return over the last 30 days
  mom_7    return over the last 7 days
  vol_30   realised volatility over the last 30 days (ranked low-to-high)

Horizons: 1 day and 7 days. Periods are **non-overlapping** -- a trade that is
still open cannot also be the next observation. Overlapping windows produce
intervals far too narrow, which this project has already published once and
had to withdraw.

That is **6 cells**, so the threshold is 0.05/6 = 0.0083, not 0.05, and a 95%
interval excluding zero is not on its own a result. The replication rule is the
same as everywhere else: a surviving cell is a candidate for the held-back
window, never a verdict from this one.

## What this cannot see, stated rather than buried

All twelve markets exist today. A market that was delisted or collapsed in the
five-year window is not here, and its absence flatters exactly the arm that
buys past winners. The bias has a known direction -- toward a positive result --
and no free data fixes it, so any positive cell has to be read with it in mind.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.domain.market import DEFAULT_SPEC

OHLCV = ROOT / "data" / "ohlcv"
DAY_MS = 86_400_000

#: Declared above, and the count that sets the correction threshold.
RANKINGS = ("mom_30", "mom_7", "vol_30")
HORIZON_DAYS = (1, 7)

#: Equal-weight thirds of twelve markets: four long, four short.
BUCKET = 4

DEFAULT_DRAWS = 10_000
SEED = 20261006

#: A replication counts if the second half lands within a factor of two of the
#: first, either way. Wide on purpose: a real effect of this size will not be
#: measured twice to the decimal, and a band this generous makes a failure
#: mean something. The project's register already carries failures at 0.16x,
#: 0.26x and 0.29x, so the band has never been the thing doing the rejecting.
REPLICATION_BAND = (0.5, 2.0)

#: Weeks per bootstrap block. Daily spreads of a basket are correlated across
#: adjacent days; weeks are the unit this project uses everywhere else.
BLOCK_DAYS = 7


def read_daily(symbol: str) -> pd.DataFrame:
    """Daily opens for one market, oldest first, one row per day."""
    files = sorted((OHLCV / symbol / "D1").glob("*.parquet"))
    if not files:
        raise SystemExit(f"Keine Tagesdaten fuer {symbol}.")
    frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    frame["ts"] = frame["ts"].astype("int64")
    return (
        frame.drop_duplicates(subset="ts", keep="first")
        .sort_values("ts")
        .reset_index(drop=True)
        .loc[:, ["ts", "open"]]
    )


def panel(symbols: list[str]) -> pd.DataFrame:
    """Opens for every market on a shared daily index, days with gaps dropped.

    A cross-section needs every market priced on the same day or the ranking
    compares different moments. Dropping an incomplete day is the conservative
    choice: carrying a stale price forward would invent a return of zero for a
    market that simply was not observed.
    """
    joined: pd.DataFrame | None = None
    for symbol in symbols:
        daily = read_daily(symbol).rename(columns={"open": symbol}).set_index("ts")
        joined = daily if joined is None else joined.join(daily, how="inner")
    assert joined is not None
    return joined.sort_index()


def ranking_values(opens: pd.DataFrame, *, kind: str) -> pd.DataFrame:
    """The quantity markets are sorted by on each day, high = bought.

    Every column reaches backwards only. `vol_30` is negated so that in all
    three cases the top of the ranking is the side the arm goes long, which
    keeps the direction of a result unambiguous instead of depending on which
    feature produced it.
    """
    if kind == "mom_30":
        return opens / opens.shift(30) - 1.0
    if kind == "mom_7":
        return opens / opens.shift(7) - 1.0
    if kind == "vol_30":
        returns = opens / opens.shift(1) - 1.0
        return -returns.rolling(30).std()
    raise ValueError(f"Unbekannte Rangfolge: {kind}")


def spread_series(
    opens: pd.DataFrame, *, kind: str, horizon: int
) -> tuple[np.ndarray, np.ndarray, float]:
    """Return of long-top-third minus short-bottom-third, per non-overlapping period.

    Also reports turnover: the share of the basket that has to be traded at each
    rebalance, which is what the toll is charged on. Measuring it beats assuming
    a full turnover, and it is the number that decides whether a gross spread
    can survive two legs of fees.
    """
    values = ranking_values(opens, kind=kind)
    forward = opens.shift(-horizon) / opens - 1.0

    starts = range(0, len(opens) - horizon)
    spreads: list[float] = []
    stamps: list[int] = []
    previous: set[str] = set()
    turnovers: list[float] = []

    cursor = 0
    index = opens.index.to_numpy()
    for at in starts:
        if at < cursor:
            continue
        row = values.iloc[at]
        if row.isna().any() or forward.iloc[at].isna().any():
            continue
        order = row.sort_values(ascending=False)
        longs, shorts = list(order.index[:BUCKET]), list(order.index[-BUCKET:])
        held = set(longs) | set(shorts)

        ahead = forward.iloc[at]
        spreads.append(float(ahead[longs].mean() - ahead[shorts].mean()))
        stamps.append(int(index[at]))
        turnovers.append(len(held - previous) / len(held) if previous else 1.0)
        previous = held
        cursor = at + horizon  # non-overlapping: the next period starts at the exit

    return np.array(spreads), np.array(stamps), float(np.mean(turnovers))


def block_bootstrap(
    values: np.ndarray, stamps: np.ndarray, *, draws: int, level: float = 0.95, seed: int = SEED
) -> tuple[float, float]:
    """An interval for the mean at `level`, resampling whole weeks with replacement.

    `level` is a parameter and not a constant because this study looks at six
    cells, and a 95% interval read six times is not a 95% statement. The
    corrected level is passed in by the caller that knows the cell count.
    """
    rng = np.random.default_rng(seed)
    blocks = stamps // (BLOCK_DAYS * DAY_MS)
    unique = np.unique(blocks)
    index = {b: np.flatnonzero(blocks == b) for b in unique}
    target = values.size
    per_draw = int(np.ceil(target / np.mean([index[b].size for b in unique]))) + 2

    means = np.empty(draws)
    for d in range(draws):
        taken = np.concatenate(
            [index[b] for b in rng.choice(unique, size=per_draw, replace=True)]
        )
        while taken.size < target:
            extra = rng.choice(unique, size=per_draw, replace=True)
            taken = np.concatenate([taken, *(index[b] for b in extra)])
        means[d] = values[taken[:target]].mean()
    tail = 100.0 * (1.0 - level) / 2.0
    low, high = np.percentile(means, [tail, 100.0 - tail])
    return float(low), float(high)


def replication(
    opens: pd.DataFrame, *, kind: str, horizon: int, draws: int
) -> tuple[float, float, float]:
    """The same cell measured in the first and second half of the window.

    Selection on all the data and verification on the same data is how every
    one of the seven false findings in this project got as far as it did. A
    pattern that is real repeats at roughly the same size in a half it did not
    help choose; one that is noise shrinks. The ratio is reported rather than a
    pass/fail, because "replicated at 0.2x" is the useful sentence and "failed"
    is not.
    """
    cut = len(opens) // 2
    early, late = opens.iloc[:cut], opens.iloc[cut:]
    first, _, _ = spread_series(early, kind=kind, horizon=horizon)
    second, _, _ = spread_series(late, kind=kind, horizon=horizon)
    del draws  # the halves are reported as point estimates; the ratio is the signal
    ratio = float(second.mean() / first.mean()) if first.mean() else float("nan")
    return float(first.mean()), float(second.mean()), ratio


def judge_survivors(
    opens: pd.DataFrame,
    survivors: list[tuple[str, int, float, float, float, bool]],
    *,
    cells: int,
    corrected: float,
    draws: int,
) -> None:
    """The two gates every candidate here has to pass, reported one by one.

    Neither gate is new and neither is optional. Seven findings in this project
    have died at exactly these two -- three of them mine, two in code I had
    written minutes earlier -- which is why a surviving cell is printed with
    both answers attached rather than announced and then qualified.
    """
    low, high = REPLICATION_BAND
    print(f"  {len(survivors)} von {cells} Zellen ohne Null im 95%-Intervall.")
    print("  Zwei Pruefungen entscheiden, ob das mehr ist als eine Zelle in einem")
    print("  Raster -- und an genau diesen beiden sind hier schon sieben Funde")
    print("  gestorben, drei davon meine eigenen.\n")
    for kind, horizon, mean, cost, net, holds in survivors:
        early, late, ratio = replication(opens, kind=kind, horizon=horizon, draws=draws)
        repeats = low <= ratio <= high
        print(f"    {kind} / {horizon}T")
        print(
            f"      brutto {100 * mean:+.4f}%, Maut {100 * cost:.4f}%, "
            f"netto {100 * net:+.4f}%"
        )
        print(
            f"      Mehrfachkorrektur ({100 * corrected:.2f}%): "
            f"{'haelt' if holds else 'FAELLT'}"
        )
        print(
            f"      Wiederholung: erste Haelfte {100 * early:+.4f}%, "
            f"zweite {100 * late:+.4f}%, Verhaeltnis {ratio:.2f}x "
            f"({'haelt' if repeats else 'FAELLT'})"
        )
        passed = holds and repeats
        print(f"      -> {'Kandidat fuers Prueffenster' if passed else 'nicht belegt'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args()

    symbols = sorted(d.name for d in OHLCV.iterdir() if (d / "D1").is_dir())
    opens = panel(symbols)
    if len(symbols) < 3 * BUCKET:
        raise SystemExit(f"{len(symbols)} Maerkte reichen nicht fuer Drittel von {BUCKET}.")

    first = pd.Timestamp(int(opens.index[0]), unit="ms", tz="UTC").date()
    last = pd.Timestamp(int(opens.index[-1]), unit="ms", tz="UTC").date()
    print("=" * 78)
    print("Querschnitt: ein Markt gegen die anderen, nicht gegen seine eigene Zukunft")
    print("=" * 78)
    print(f"\n{len(symbols)} Maerkte, gemeinsames Fenster {first} bis {last} ({len(opens)} Tage)")
    print(f"  {', '.join(symbols)}")
    print(f"\nJe Periode long {BUCKET} / short {BUCKET}, gleichgewichtet, nicht ueberlappend.")

    # The toll a two-legged basket pays per rebalance, from the project's own
    # spec: every position that changes is closed and another opened, and both
    # legs pay. Turnover is measured, not assumed.
    round_trip = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"]
    print(f"Maut je gehandelter Position (maker/taker): {100 * round_trip:.4f}%")

    cells = len(RANKINGS) * len(HORIZON_DAYS)
    corrected = 1.0 - 0.05 / cells
    print(f"Korrigiertes Niveau bei {cells} Zellen: {100 * corrected:.2f}% statt 95%.")

    print(f"\n  {'Rangfolge':>8s} {'Horizont':>9s} {'Perioden':>9s} {'Umschlag':>9s} "
          f"{'Spanne':>9s}  {'95%-Intervall':>22s}  {'netto':>9s}  korr.")

    survivors = []
    for kind in RANKINGS:
        for horizon in HORIZON_DAYS:
            spreads, stamps, turnover = spread_series(opens, kind=kind, horizon=horizon)
            low, high = block_bootstrap(spreads, stamps, draws=args.draws)
            c_low, c_high = block_bootstrap(
                spreads, stamps, draws=args.draws, level=corrected
            )
            # Both legs pay, and only the part of the basket that changed.
            cost = 2.0 * turnover * round_trip
            net = float(spreads.mean()) - cost
            naive = low > 0.0 or high < 0.0
            holds = c_low > 0.0 or c_high < 0.0
            print(
                f"  {kind:>8s} {horizon:>7d} T {len(spreads):>9d} {100 * turnover:>8.1f}% "
                f"{100 * spreads.mean():>+8.4f}%  [{100 * low:+.4f}, {100 * high:+.4f}]"
                f"{' *' if naive else '  '} {100 * net:>+8.4f}%  {'ja' if holds else 'nein'}"
            )
            if low > 0.0:
                survivors.append((kind, horizon, float(spreads.mean()), cost, net, holds))

    print("\n" + "-" * 78)
    if not survivors:
        print(f"  Keine der {cells} Zellen hat ein Intervall ohne die Null.")
        print("  Damit faellt auch die letzte unbeobachtete Richtung des natuerlichen")
        print("  Raums: nicht nur sagt kein Merkmal die eigene Zukunft eines Marktes")
        print("  voraus, es sagt auch keines voraus, WELCHER Markt die anderen schlaegt.")
        print("  Der gemeinsame Faktor war also nicht das, was die Suche verdeckt hat.")
    else:
        judge_survivors(opens, survivors, cells=cells, corrected=corrected, draws=args.draws)
    print(
        "\n  Und was dieser Lauf nicht sehen kann: die zwoelf Maerkte existieren\n"
        "  alle noch. Ein in diesen fuenf Jahren verschwundener Markt fehlt hier,\n"
        "  und sein Fehlen schmeichelt genau dem Arm, der vergangene Gewinner\n"
        "  kauft. Die Verzerrung zeigt in Richtung eines positiven Ergebnisses."
    )
    print("-" * 78)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
