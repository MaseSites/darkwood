"""Where, if anywhere, is the edge?

    python scripts/study_edge.py
    python scripts/study_edge.py --source live

Severin's question, and the one the whole journal exists to answer: *when do we
make money and when do we lose it?* Every trade carries the case that was made
for it -- setup, chart, cadence, rating and its four parts, each of seven
information families, the regime, the side, the stop width, the reward-to-risk.
This cuts the record by each of those and asks which slices are different from
the whole.

**The danger is the method, not the data.** Slice two and a half thousand trades
fifty ways and some slices come back looking profitable because fifty coin
flips produce a run. At the usual five-percent threshold, *two or three* of
fifty slices are expected to look significant when nothing is there at all. A
report that printed the best few and called them findings would be a machine
for manufacturing false edges, and it would be convincing.

So every slice is tested, the number of tests is printed, and the threshold is
adjusted for how many were made (Bonferroni -- crude, conservative, and
impossible to argue with). A slice that survives is worth looking at. The
expected output, given everything measured in this project so far, is that
none do; that is a result and it is printed as one.

**What is not done here:** picking the best slice and trading it. A rule found
by searching the same data it is then justified by is not a rule, it is a
description of that data. Anything that survives goes to a forward test, which
is what `Source.LIVE` in the journal is for.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np

from traidingbrain.config.settings import load_config
from traidingbrain.journal.record import JournalEntry, Source
from traidingbrain.journal.store import JournalStore

BOOT = 4000

#: Fewest trades in a slice before it is tested at all.
#:
#: Below this the interval is wider than any effect worth having, and the slice
#: contributes nothing but another test to correct for -- which makes every
#: other slice harder to detect. Dropping it costs nothing and helps.
MIN_SLICE = 40

#: The threshold before correcting for how many slices were tested.
ALPHA = 0.05


@dataclass(frozen=True)
class Slice:
    """One cut of the journal, with its own numbers."""

    dimension: str
    name: str
    values: list[float]

    @property
    def n(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> float:
        return float(np.mean(self.values))

    @property
    def hit_rate(self) -> float:
        return 100.0 * sum(1 for v in self.values if v > 0) / self.n


def bootstrap_p(values: list[float], seed: int = 7) -> float:
    """How often a sample this size, drawn from this slice, lands the wrong side
    of zero.

    A two-sided bootstrap p-value: the share of resamples whose mean has the
    opposite sign to the observed one, doubled. Crude and assumption-free,
    which is what is wanted on a distribution of R multiples -- they are
    bounded below at roughly -1 and unbounded above, so nothing normal applies.
    """
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    observed = float(np.mean(sample))
    wrong_side = float(np.mean(draws <= 0.0) if observed > 0 else np.mean(draws >= 0.0))
    return min(1.0, 2.0 * wrong_side)


def interval(values: list[float], seed: int = 11) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    sample = np.array(values, dtype="float64")
    draws = rng.choice(sample, size=(BOOT, len(sample)), replace=True).mean(axis=1)
    return float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))


def _hour(entry: JournalEntry) -> str:
    return f"{datetime.fromtimestamp(entry.opened_ts / 1000, tz=UTC).hour:02d}h UTC"


def _weekday(entry: JournalEntry) -> str:
    return datetime.fromtimestamp(entry.opened_ts / 1000, tz=UTC).strftime("%A")


def _band(value: float, edges: tuple[float, ...], unit: str = "") -> str:
    for edge in edges:
        if value < edge:
            return f"< {edge}{unit}"
    return f">= {edges[-1]}{unit}"


def _family(entry: JournalEntry, name: str) -> str:
    for note in entry.reason.families:
        if note.family == name:
            if note.silent:
                return "schweigt"
            return note.direction
    return "fehlt"


#: Every way the record is cut. Each is one test, and the correction below is
#: driven by how many there turn out to be.
DIMENSIONS: dict[str, Callable[[JournalEntry], str]] = {
    "Setup": lambda e: e.reason.setup_key,
    "Chart des Setups": lambda e: e.reason.setup_timeframe,
    "Takt": lambda e: e.reason.signal_timeframe or "H1 (vor der Umstellung)",
    "Markt": lambda e: e.symbol,
    "Richtung": lambda e: e.reason.side,
    "Bewertungsband": lambda e: e.reason.rating_band,
    "Bild stimmt zu": lambda e: "ja" if e.reason.rating_agreed_with_setup else "nein",
    "Regime": lambda e: e.reason.regime,
    "Stunde": _hour,
    "Wochentag": _weekday,
    "Stopweite": lambda e: _band(e.reason.stop_distance_pct, (0.75, 1.25, 2.0), " %"),
    "CRV": lambda e: _band(e.reason.reward_risk, (1.75, 2.5, 3.5)),
    "Familien mit Meinung": lambda e: _band(float(e.reason.breadth), (5.0, 7.0)),
    "Streit (conflict)": lambda e: _band(e.reason.conflict, (0.2, 0.5)),
    "Trend-Familie": lambda e: _family(e, "trend"),
    "Struktur-Familie": lambda e: _family(e, "structure"),
    "Liquiditäts-Familie": lambda e: _family(e, "liquidity"),
    "Lage-Familie": lambda e: _family(e, "location"),
}


def cut(entries: list[JournalEntry]) -> list[Slice]:
    """Every slice of every dimension that is large enough to test."""
    out: list[Slice] = []
    for dimension, key in DIMENSIONS.items():
        groups: dict[str, list[float]] = {}
        for entry in entries:
            try:
                groups.setdefault(key(entry), []).append(entry.r_multiple)
            except Exception:  # a dimension missing from an older row
                continue
        for name, values in groups.items():
            if len(values) >= MIN_SLICE:
                out.append(Slice(dimension, name, values))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="replay", choices=[str(s) for s in Source])
    parser.add_argument("--min", type=int, default=MIN_SLICE, help="fewest trades per slice")
    args = parser.parse_args()

    config = load_config()
    store = JournalStore(config.engine.paths.data_dir / "journal.sqlite")
    entries = store.all(source=Source(args.source))
    if not entries:
        print(f"Keine Trades mit Quelle {args.source}.", file=sys.stderr)
        return 1

    whole = [e.r_multiple for e in entries]
    low, high = interval(whole)
    print(f"{len(entries)} Trades ({args.source})")
    print(f"Gesamt   {np.mean(whole):+.4f} R   [{low:+.3f}, {high:+.3f}]")
    print(f"Treffer  {100 * sum(1 for v in whole if v > 0) / len(whole):.0f} %\n")

    slices = cut(entries)
    tests = len(slices)
    threshold = ALPHA / tests if tests else ALPHA

    print(f"{tests} Teilmengen getestet (mindestens {args.min} Trades je Teilmenge).")
    print(
        f"Schwelle {ALPHA} / {tests} = {threshold:.5f} — so viele Tests bedeuten, dass "
        f"bei reinem Zufall\nrund {ALPHA * tests:.0f} Teilmengen die unkorrigierte "
        f"Schwelle reissen wuerden.\n"
    )

    scored = [(s, bootstrap_p(s.values)) for s in slices]
    scored.sort(key=lambda pair: pair[1])

    survivors = [(s, p) for s, p in scored if p < threshold]
    print("=" * 86)
    if survivors:
        print("Haelt der Korrektur stand:\n")
        for s, p in survivors:
            lo, hi = interval(s.values)
            print(
                f"  {s.dimension:22s} {s.name:26s} n={s.n:5d}  {s.mean:+.3f} R  "
                f"Treffer {s.hit_rate:3.0f}%  [{lo:+.3f}, {hi:+.3f}]  p={p:.5f}"
            )
    else:
        print("Keine einzige Teilmenge haelt der Korrektur stand.\n")
        print("Das ist ein Ergebnis und kein fehlendes: ueber achtzehn Dimensionen")
        print("hinweg gibt es keine Bedingung, unter der dieses Regelwerk nachweislich")
        print("Geld verdient. Wer hier trotzdem die beste Zeile nimmt, beschreibt den")
        print("Zufall in diesen Daten und nennt ihn eine Taktik.")

    print("\n" + "=" * 86)
    print("Die zehn auffaelligsten, korrigiert oder nicht — zum Anschauen, nicht zum Handeln:\n")
    for s, p in scored[:10]:
        lo, hi = interval(s.values)
        mark = "  <- haelt" if p < threshold else ""
        print(
            f"  {s.dimension:22s} {s.name:26s} n={s.n:5d}  {s.mean:+.3f} R  "
            f"Treffer {s.hit_rate:3.0f}%  [{lo:+.3f}, {hi:+.3f}]  p={p:.4f}{mark}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
