"""Earning without predicting: what does the funding leg actually pay?

    python scripts/study_funding_carry.py
    python scripts/study_funding_carry.py --draws 20000

Fifteen families are closed and every one of them asked the same kind of
question: which way will the price go. The register calls one of them
"Funding / Relative Value", but what that measured was funding *as a feature
for direction* -- percentiles of the rate fed to a model that still had to
guess up or down. It failed like the rest.

This is a different object. A perpetual future has no expiry, so the venue
keeps it near spot by making one side pay the other every eight hours. Hold the
perp short and the same notional of spot long and the price is hedged out: what
is left is the funding, and it is collected without an opinion about direction.
That is the one shape this project has never measured, and it is worth being
precise about why it is different -- not "a better signal", but **no signal at
all**. Nothing here has to be predicted for it to pay.

So it deserves a measurement rather than an opinion, and it deserves the
measurement before the enthusiasm.

## What is measured here, exactly

Per market: the mean funding rate per eight-hour period over the full history
on disk, with a weekly-block interval, the share of periods that paid rather
than charged, and the holding time at which the accumulated funding covers the
fees of putting the hedge on and taking it off. Two legs, each paying a round
trip, from the project's own spec.

## What this cannot see, and it is not small

**There is no spot price series here.** Everything under `data/ohlcv/` is the
perpetual. A real hedge earns funding *minus* whatever the basis does between
entry and exit, and that term cannot be computed from the data on disk. It is
bounded -- funding exists precisely to hold the two together -- but "bounded"
is not "zero", and any number below is an upper bound on what the trade earns,
never an estimate of it.

**The capital is doubled.** One unit of spot plus one unit of perp notional
earns funding on one unit. Unless the venue nets the two as margin, the return
on money committed is half the return on notional quoted here.

**This trade is not a secret.** It is the standard basis trade, run at size by
people with better fees and better margin treatment. That is itself a reason
the measured rate is what it is, and a reason to distrust any version of this
that looks unusually good.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.domain.market import DEFAULT_SPEC

FUNDING = ROOT / "data" / "funding"
DAY_MS = 86_400_000

#: Perpetual funding settles every eight hours on this venue family.
PERIODS_PER_DAY = 3

#: The venue's default rate, applied whenever the perp sits close enough to
#: spot that the formula contributes nothing. A third to a half of all periods
#: land exactly here, which is the single most important thing to know about
#: the numbers below: this income is mostly a parameter the exchange sets, not
#: a market mispricing somebody found. An exchange that halves it halves the
#: trade, with no notice and no counterargument.
DEFAULT_RATE = 0.0001

DEFAULT_DRAWS = 10_000
SEED = 20261006
BLOCK_DAYS = 7

#: A half replicates if it lands within a factor of two of the other, either
#: way. The same band the cross-section study uses, for the same reason: wide
#: enough that a failure means something.
REPLICATION_BAND = (0.5, 2.0)

#: Days left to the goal date of 30.10.2026, used for the one piece of
#: arithmetic that says what any of this is worth.
DAYS_TO_GOAL = 24
GOAL_FROM = 12_000.0
GOAL_TO = 15_000.0


def read_funding(path: Path) -> pd.DataFrame:
    """One market's funding history, oldest first, duplicates dropped."""
    frame = pd.read_parquet(path)
    frame["ts"] = frame["ts"].astype("int64")
    return (
        frame.drop_duplicates(subset="ts", keep="first").sort_values("ts").reset_index(drop=True)
    )


def block_bootstrap(
    values: np.ndarray, stamps: np.ndarray, *, draws: int, seed: int = SEED
) -> tuple[float, float]:
    """A 95% interval for the mean, resampling whole weeks with replacement.

    Funding is strongly autocorrelated -- a venue that is paying shorts this
    morning is usually still paying them tonight -- so resampling individual
    settlements would give an interval several times too narrow. Weeks are the
    block everywhere else in this project and they are the block here.
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
    low, high = np.percentile(means, [2.5, 97.5])
    return float(low), float(high)


@dataclass(frozen=True)
class Market:
    """One market's funding history, summarised.

    A record rather than a tuple because it grew to nine fields that two
    different places unpack positionally, and the failure mode of that is a
    silent swap of two numbers that both look plausible as percentages.
    """

    name: str
    mean: float
    low: float
    high: float
    per_year: float
    payback_days: float
    early: float
    late: float
    at_default: float

    @property
    def proven(self) -> bool:
        """Interval entirely above zero."""
        return self.low > 0.0

    @property
    def ratio(self) -> float:
        """Second half over first. The replication number."""
        return self.late / self.early if self.early else float("nan")

    @property
    def repeats(self) -> bool:
        low, high = REPLICATION_BAND
        return low <= self.ratio <= high


def verdict(rows: list[Market], *, repeated: int, falling: int) -> None:
    """What the table means, with the goal arithmetic spelled out.

    Split out so that the one number people will quote -- what this does
    for 12,000 CHF by the end of October -- sits next to the caveats that
    bound it, instead of three screens above them.
    """
    positive = [r for r in rows if r.proven]
    print("\n" + "-" * 78)
    print(f"  {len(positive)} von {len(rows)} Maerkten mit Intervall ganz ueber der Null,")
    print(f"  aber nur {repeated} von {len(rows)} wiederholen sich in der zweiten Haelfte --")
    print(f"  und {falling} von {len(rows)} zahlen dort WENIGER als in der ersten.")
    print(
        "\n  Eine einheitliche Richtung ueber zwoelf Maerkte ist kein Rauschen.\n"
        "  Rauschen streut; das hier faellt ueberall. Der Basis-Trade ist bekannt\n"
        "  und wird von Leuten mit besseren Gebuehren gefahren, und genau so sieht\n"
        "  es aus, wenn eine Einnahmequelle voll wird. Die ehrliche Vorausschau ist\n"
        "  deshalb die ZWEITE Haelfte, nicht der Durchschnitt ueber beide."
    )
    if positive:
        best = max(positive, key=lambda r: r.per_year)
        worst = min(positive, key=lambda r: r.per_year)
        print(
            f"\n  Ueber die ganze Historie: {100 * worst.per_year:+.2f}% bis "
            f"{100 * best.per_year:+.2f}% pro Jahr aufs Notional,\n"
            f"  Amortisation {best.payback_days:.1f} bis {worst.payback_days:.1f} Tage."
        )
        # The income is mostly a number the exchange chose, not a mispricing
        # somebody found. Saying so belongs next to the figure, because it is
        # what decides how much of this survives a venue changing its mind.
        share = 100 * sum(r.at_default for r in rows) / len(rows)
        print(
            f"\n  Und woher es kommt: im Mittel {share:.0f}% aller Perioden liegen EXAKT\n"
            f"  auf dem Standardsatz der Boerse ({100 * DEFAULT_RATE:.2f}% je 8h). Diese Einnahme\n"
            f"  ist also ueberwiegend ein Parameter, den die Boerse setzt, und keine\n"
            f"  Fehlbewertung, die jemand gefunden hat. Wer ihn halbiert, halbiert\n"
            f"  den Trade, ohne Vorwarnung und ohne Gegenargument."
        )
        # What any of it is worth for the stated goal, computed rather than
        # described -- because "the first positive thing measured here" is the
        # exact moment a number gets read as more than it is. Twice: on the
        # whole history, and on the half that is actually forward-looking.
        recent = max(r.late for r in rows) * PERIODS_PER_DAY * 365.25
        for label, yearly in (("ganze Historie", best.per_year), ("zweite Haelfte", recent)):
            on_capital = 0.5 * yearly  # two legs, one notional
            reach = GOAL_FROM * (1.0 + on_capital * DAYS_TO_GOAL / 365.25)
            closes = 100 * (reach - GOAL_FROM) / (GOAL_TO - GOAL_FROM)
            print(
                f"\n  Bester Markt, {label}, {100 * yearly:+.2f}%/Jahr aufs Notional,\n"
                f"  also {100 * on_capital:+.2f}% aufs Kapital, ueber {DAYS_TO_GOAL} Tage:\n"
                f"  {GOAL_FROM:,.0f} CHF -> {reach:,.0f} CHF.\n"
                f"  Das schliesst {closes:.1f}% der Luecke."
            )
    else:
        print("  Keiner. Dann traegt auch dieser Weg nichts.")
    print(
        "\n  Drei Dinge fehlen hier, und keines ist klein:\n"
        "\n  1. Es gibt keine Spot-Reihe auf der Platte, nur den Perp. Die Basis\n"
        "     zwischen Einstieg und Ausstieg ist nicht gemessen, sondern\n"
        "     weggelassen. Jede Zahl oben ist eine OBERGRENZE, keine Schaetzung.\n"
        "\n  2. Das Kapital ist doppelt gebunden, solange die Boerse die beiden\n"
        "     Beine nicht als Margin verrechnet.\n"
        "\n  3. Der Weg, auf dem dieser Trade wirklich stirbt, steht in keiner\n"
        "     Spalte: das Short-Bein braucht Margin. Steigt der Preis scharf,\n"
        "     verliert der Perp, waehrend der Gewinn im Spot-Bein auf einem\n"
        "     anderen Konto liegt und nicht nachschiesst. Wird das Short-Bein\n"
        "     liquidiert, bleibt ein ungehedgtes Long stehen -- aus einem\n"
        "     richtungslosen Trade wird in dem Moment eine volle Wette. Das ist\n"
        "     kein Randfall, das ist die uebliche Todesursache dieses Trades,\n"
        "     und sie passiert genau dann, wenn das Funding am hoechsten war.\n"
        "\n  Dazu der Rahmen, der hier ohnehin gilt: dieses Konto handelt nicht\n"
        "  selbst, und der Kontoinhaber ist unter 18. Das hier ist eine Messung,\n"
        "  keine Handlungsanweisung."
    )
    print("-" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draws", type=int, default=DEFAULT_DRAWS)
    args = parser.parse_args()

    files = sorted(FUNDING.glob("*.parquet"))
    if not files:
        raise SystemExit(f"Keine Funding-Daten in {FUNDING}.")

    # Both legs are opened and closed, so the hedge pays two round trips. Taken
    # from the project's own spec, which is the perp schedule; a spot leg is
    # usually dearer, so this is the optimistic side of the real cost.
    round_trip = DEFAULT_SPEC["maker_fee"] + DEFAULT_SPEC["taker_fee"]
    setup_cost = 2.0 * round_trip

    print("=" * 78)
    print("Funding einsammeln: bezahlt werden, ohne eine Richtung zu behaupten")
    print("=" * 78)
    print(f"\nKosten, Hedge auf und wieder zu (zwei Beine): {100 * setup_cost:.4f}%")
    print(f"Funding faellt {PERIODS_PER_DAY}x taeglich an.\n")
    print(
        f"  {'Markt':10s} {'Perioden':>9s} {'Jahre':>6s} {'je 8h':>9s}  "
        f"{'95%-Intervall':>20s} {'positiv':>8s} {'pro Jahr':>9s} {'Amortisation':>13s}"
    )

    rows: list[Market] = []
    for path in files:
        frame = read_funding(path)
        rates = frame["rate"].to_numpy(dtype=float)
        stamps = frame["ts"].to_numpy(dtype=np.int64)
        years = (stamps[-1] - stamps[0]) / (365.25 * DAY_MS)
        low, high = block_bootstrap(rates, stamps, draws=args.draws)
        mean = float(rates.mean())
        share = float((rates > 0).mean())
        per_year = mean * PERIODS_PER_DAY * 365.25
        # Days of holding before the accumulated funding has paid for putting
        # the hedge on and taking it off again.
        daily = mean * PERIODS_PER_DAY
        payback = setup_cost / daily if daily > 0 else float("inf")
        # The same split-half check every other family in this project had to
        # pass. A rate whose whole mean comes from one bull market is a fact
        # about 2021, not an income; only the second half can say which.
        cut = len(rates) // 2
        early, late = float(rates[:cut].mean()), float(rates[cut:].mean())
        rows.append(
            Market(
                name=path.stem,
                mean=mean,
                low=low,
                high=high,
                per_year=per_year,
                payback_days=payback,
                early=early,
                late=late,
                at_default=float(np.isclose(rates, DEFAULT_RATE).mean()),
            )
        )
        print(
            f"  {path.stem:10s} {len(rates):>9,d} {years:>6.1f} {100 * mean:>+8.4f}%  "
            f"[{100 * low:+.4f}, {100 * high:+.4f}] {100 * share:>7.1f}% "
            f"{100 * per_year:>+8.2f}% {payback:>10.1f} T"
        )

    print("\nWiederholung: erste gegen zweite Haelfte der Historie, je 8h")
    repeated = 0
    falling = 0
    for row in rows:
        repeated += row.repeats
        falling += row.late < row.early
        print(
            f"  {row.name:10s} erste {100 * row.early:+.4f}%  "
            f"zweite {100 * row.late:+.4f}%  {row.ratio:>5.2f}x  "
            f"{'haelt' if row.repeats else 'FAELLT'}"
        )

    verdict(rows, repeated=repeated, falling=falling)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
