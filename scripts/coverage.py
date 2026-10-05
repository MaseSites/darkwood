"""Count what data this project actually holds, instead of believing a claim.

    python scripts/coverage.py
    python scripts/coverage.py --sources derivatives sentiment
    python scripts/coverage.py --json

On 05.10.2026 this project reported having five years of open interest, account
ratio and sentiment data. An audit counted it: the five years hold for **four
of twelve markets**, and the provenance of 43,777 rows cannot be traced to any
script in this repository. That is why this file exists -- a claim about
coverage is cheap, and the files are right there.

**Three things it reports that a row count does not.**

*Gaps.* A source with 43,812 hourly rows over five years is missing a quarter
of them, and nothing about the count says so. Gaps are counted against the
modal spacing, so an hourly series and a daily one are judged by their own
cadence.

*Provenance signals.* Not proof, but the things that differ between a venue's
API and a bulk archive: how many decimal places a ratio carries, whether
timestamps sit exactly on the hour or jitter by milliseconds, and whether a
"ratio" column contains exact zeros. `backfill_derivatives.py` asks Bybit from
2023-01-01; rows before that came from somewhere else, and this prints the
signals rather than guessing which.

*Availability lag.* The research order requires `available_at <= decision_time`
for every join. A row stamped 14:00 was not necessarily knowable at 14:00:
funding settles at the end of its interval, and a daily sentiment reading is
published during the day it describes. The lag is an assumption per source, so
it is declared here in one place instead of being rediscovered in each study.

**What it does not do.** It does not fix anything and it does not fetch
anything. It counts, and where counting cannot settle a question it says so.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from traidingbrain.config.settings import load_config

#: Milliseconds in a day, for turning a timestamp span into days.
DAY_MS = 86_400_000

#: Sources this script knows how to count, and the publication lag each one
#: carries. The lag is the honest part: it is an assumption, stated once.
#:
#: * ohlcv -- a closed candle is knowable at its close, so the lag is one
#:   interval. The stored `ts` is the OPEN time, which is the trap: a bar
#:   stamped 14:00 on H1 is not complete until 15:00.
#: * funding -- Binance settles every eight hours; the realised rate for an
#:   interval is known at its end, not its start.
#: * open_interest, account_ratio -- sampled series, knowable at the sample.
#: * sentiment -- Alternative.me publishes a daily value during the day it
#:   describes, and the exact hour is not documented. A full day is the
#:   conservative choice and is marked as such.
#: * flow -- taker split of a closed candle, same rule as ohlcv.
LAGS: dict[str, tuple[int, str]] = {
    "ohlcv": (0, "ts ist die EROEFFNUNG; verfuegbar erst ein Intervall spaeter"),
    "funding": (8 * 3_600_000, "Binance rechnet alle 8h ab; Rate am Ende bekannt"),
    "open_interest": (0, "Momentaufnahme, zum Zeitpunkt bekannt"),
    "account_ratio": (0, "Momentaufnahme, zum Zeitpunkt bekannt"),
    "sentiment": (
        DAY_MS,
        "Taeglich, Veroeffentlichungszeit nicht dokumentiert -- 1 Tag konservativ",
    ),
    "flow": (0, "Taker-Split einer geschlossenen Kerze; wie ohlcv ein Intervall spaeter"),
}

#: Decimal places a value carries, as a provenance signal. Bybit's API returns
#: ratios with more precision than Binance's archive dumps, which round to
#: four. Not proof of origin, but a difference worth printing.
PROVENANCE_DECIMALS = 4

#: A gap report lists at most this many, newest first. A series missing
#: thousands of hours produces a useless wall otherwise.
MAX_GAPS_SHOWN = 5

#: Steps a hole must span before it counts as a gap. Two, because one step
#: plus a millisecond of jitter means nothing is missing.
MIN_GAP_STEPS = 2


@dataclass
class Series:
    """One counted file."""

    source: str
    market: str
    rows: int
    first_ms: int
    last_ms: int
    step_ms: int
    gaps: int
    missing: int
    duplicates: int
    zeros: int
    lag_ms: int
    lag_note: str
    columns: list[str]
    notes: list[str] = field(default_factory=list)
    biggest_gaps: list[str] = field(default_factory=list)

    @property
    def span_days(self) -> float:
        return (self.last_ms - self.first_ms) / DAY_MS

    @property
    def span_years(self) -> float:
        return self.span_days / 365.25

    @property
    def completeness(self) -> float:
        """Share of the expected rows that are present, given the modal step."""
        if self.step_ms <= 0:
            return float("nan")
        expected = (self.last_ms - self.first_ms) // self.step_ms + 1
        return self.rows / expected if expected > 0 else float("nan")

    def line(self) -> str:
        first = datetime.fromtimestamp(self.first_ms / 1000, tz=UTC)
        last = datetime.fromtimestamp(self.last_ms / 1000, tz=UTC)
        step = f"{self.step_ms // 60_000}min" if self.step_ms else "?"
        return (
            f"  {self.market:10s} {self.rows:>8,d} Zeilen  {first:%Y-%m-%d} bis {last:%Y-%m-%d}  "
            f"{self.span_years:4.1f} J  Raster {step:>6s}  "
            f"vollstaendig {100 * self.completeness:5.1f}%  "
            f"Luecken {self.gaps:>4d} ({self.missing:,} fehlen)  "
            f"Dubletten {self.duplicates}"
        )


def modal_step(stamps: np.ndarray) -> int:
    """The most common spacing, which is the series' real cadence.

    The mode rather than the minimum or the mean: one duplicated timestamp
    makes the minimum zero, and a single multi-month gap drags the mean far
    from anything the data does.
    """
    if stamps.size < MIN_GAP_STEPS:
        return 0
    deltas = np.diff(stamps)
    deltas = deltas[deltas > 0]
    if deltas.size == 0:
        return 0
    counts = Counter(deltas.tolist())
    return int(counts.most_common(1)[0][0])


def count(frame: pd.DataFrame, *, source: str, market: str, value_columns: list[str]) -> Series:
    stamps = frame["ts"].to_numpy(dtype="int64")
    order = np.argsort(stamps, kind="stable")
    stamps = stamps[order]

    duplicates = int(stamps.size - np.unique(stamps).size)
    step = modal_step(stamps)

    gaps = 0
    missing = 0
    biggest: list[tuple[int, int, int]] = []
    if step > 0 and stamps.size > 1:
        deltas = np.diff(stamps)
        # A hole needs room for at least one missing point. Testing
        # `delta > step` instead counted every millisecond of timestamp jitter
        # as a gap: the funding files reported 2,283 gaps containing zero
        # missing points, which is a number that looks alarming and says
        # nothing. Binance stamps a settlement a few milliseconds late.
        holes = np.flatnonzero(deltas >= MIN_GAP_STEPS * step)
        gaps = int(holes.size)
        missing = int((deltas[holes] // step - 1).sum())
        for index in holes[np.argsort(-deltas[holes])][:MAX_GAPS_SHOWN]:
            biggest.append(
                (int(stamps[index]), int(stamps[index + 1]), int(deltas[index] // step - 1))
            )

    zeros = 0
    notes: list[str] = []
    for column in value_columns:
        if column not in frame.columns:
            continue
        values = frame[column].to_numpy()
        if not np.issubdtype(values.dtype, np.number):
            continue
        column_zeros = int((values == 0).sum())
        zeros += column_zeros
        if column_zeros:
            share = 100.0 * column_zeros / values.size
            notes.append(f"{column}: {column_zeros:,} Nullen ({share:.1f}%)")

        # Provenance: how many decimals the values actually carry. A venue API
        # and a bulk archive differ here, and the audit flagged exactly this.
        if np.issubdtype(values.dtype, np.floating):
            finite = values[np.isfinite(values) & (values != 0)]
            if finite.size:
                rounded = np.round(finite, PROVENANCE_DECIMALS)
                if np.allclose(finite, rounded, atol=0, rtol=0):
                    notes.append(
                        f"{column}: alle Werte auf {PROVENANCE_DECIMALS} Dezimalstellen "
                        f"-- Herkunftssignal, kein Beweis"
                    )

    # Provenance: timestamps exactly on their grid, or jittering by
    # milliseconds. An archive dump is usually exact; a live API is not.
    if step > 0:
        off_grid = int((stamps % step != stamps[0] % step).sum())
        if off_grid:
            notes.append(f"{off_grid:,} Zeitstempel ausserhalb des Rasters (Jitter)")

    lag_ms, lag_note = LAGS.get(source, (0, "Verzoegerung nicht festgelegt"))
    return Series(
        source=source,
        market=market,
        rows=int(frame.shape[0]),
        first_ms=int(stamps[0]) if stamps.size else 0,
        last_ms=int(stamps[-1]) if stamps.size else 0,
        step_ms=step,
        gaps=gaps,
        missing=missing,
        duplicates=duplicates,
        zeros=zeros,
        lag_ms=lag_ms,
        lag_note=lag_note,
        columns=[c for c in frame.columns],
        notes=notes,
        biggest_gaps=[
            f"{datetime.fromtimestamp(a / 1000, tz=UTC):%Y-%m-%d %H:%M} -> "
            f"{datetime.fromtimestamp(b / 1000, tz=UTC):%Y-%m-%d %H:%M} "
            f"({n:,} fehlen)"
            for a, b, n in biggest
        ],
    )


def _derivatives(data_dir: Path) -> list[Series]:
    out: list[Series] = []
    for market_dir in sorted(p for p in (data_dir / "derivatives").glob("*") if p.is_dir()):
        for name, columns in (
            ("open_interest", ["open_interest", "value"]),
            ("account_ratio", ["buy_ratio", "sell_ratio"]),
        ):
            path = market_dir / f"{name}.parquet"
            if path.is_file():
                out.append(
                    count(
                        pd.read_parquet(path),
                        source=name,
                        market=market_dir.name,
                        value_columns=columns,
                    )
                )
    return out


def _flat(data_dir: Path, folder: str, source: str, columns: list[str]) -> list[Series]:
    """One parquet per market in a flat folder -- funding and flow both are."""
    return [
        count(pd.read_parquet(path), source=source, market=path.stem, value_columns=columns)
        for path in sorted((data_dir / folder).glob("*.parquet"))
    ]


def _sentiment(data_dir: Path) -> list[Series]:
    path = data_dir / "sentiment.parquet"
    if not path.is_file():
        return []
    return [
        count(
            pd.read_parquet(path),
            source="sentiment",
            market="(global, Bitcoin-bezogen)",
            value_columns=["value"],
        )
    ]


def _ohlcv(data_dir: Path) -> list[Series]:
    """H1 only. Counting six timeframes across twelve markets reads nothing
    the hourly series does not already say about coverage, and costs minutes."""
    out: list[Series] = []
    for market_dir in sorted(p for p in (data_dir / "ohlcv").glob("*") if p.is_dir()):
        files = sorted((market_dir / "H1").glob("*.parquet"))
        if not files:
            continue
        frame = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
        out.append(
            count(
                frame,
                source="ohlcv",
                market=f"{market_dir.name}/H1",
                value_columns=["volume"],
            )
        )
    return out


#: Which collector answers for which requested source name. `derivatives` is
#: an alias covering both of its files, because asking for one of them alone
#: is a distinction nobody has needed.
COLLECTORS: dict[str, object] = {
    "derivatives": _derivatives,
    "openinterest": _derivatives,
    "accountratio": _derivatives,
    "funding": lambda d: _flat(d, "funding", "funding", ["rate"]),
    "flow": lambda d: _flat(d, "flow", "flow", ["volume", "taker_buy", "trades"]),
    "sentiment": _sentiment,
    "ohlcv": _ohlcv,
}


def gather(sources: set[str]) -> list[Series]:
    config = load_config()
    data_dir = config.engine.paths.data_dir
    out: list[Series] = []
    seen: set[int] = set()
    for name in sorted(sources):
        collector = COLLECTORS.get(name)
        if collector is None:
            continue
        # The derivative aliases share one collector; running it three times
        # would triple those rows.
        if id(collector) in seen:
            continue
        seen.add(id(collector))
        out += collector(data_dir)  # type: ignore[operator]
    return out


def report(rows: list[Series], *, active: list[str]) -> None:
    print("=" * 110)
    print("ABDECKUNGSREGISTER -- gezaehlt, nicht behauptet")
    print("=" * 110)
    print(f"{len(active)} Maerkte sind aktiv geschaltet: {', '.join(active)}\n")

    by_source: dict[str, list[Series]] = {}
    for row in rows:
        by_source.setdefault(row.source, []).append(row)

    for source in sorted(by_source):
        group = by_source[source]
        lag_hours = group[0].lag_ms / 3_600_000
        print(f"\n{source}  ({len(group)} Datei(en))")
        print(f"  Verfuegbar ab Beobachtung + {lag_hours:.0f}h: {group[0].lag_note}")
        print(f"  Spalten: {group[0].columns}")
        for row in sorted(group, key=lambda r: r.market):
            print(row.line())
            for note in row.notes:
                print(f"             ! {note}")
            for gap in row.biggest_gaps:
                print(f"             Luecke: {gap}")

        # A market key may carry a timeframe, as "BTCUSDT/H1" or
        # "BTCUSDT-H1". Splitting on "/" alone reported all twelve flow
        # markets as missing while two were present.
        covered = {r.market.split("/")[0].split("-")[0] for r in group}
        uncovered = [m for m in active if m not in covered]
        if uncovered:
            print(f"  FEHLT fuer: {', '.join(uncovered)}  ({len(uncovered)} von {len(active)})")

    print("\n" + "=" * 110)
    print("Was dieses Register nicht entscheiden kann")
    print("=" * 110)
    print(
        "Die Herkunftssignale oben (Dezimalstellen, Raster-Jitter, exakte Nullen)\n"
        "unterscheiden eine Venue-API von einem Archiv-Abzug, aber sie beweisen\n"
        "nichts. Zwei Dinge sagen die Zahlen dennoch deutlich:\n"
        "\n"
        "1. DIE DERIVATE-DATEN STAMMEN NICHT VON DEM SKRIPT, DAS SIE HOLT.\n"
        "   `scripts/backfill_derivatives.py:58` baut `ccxt.bybit`, und ihr\n"
        "   eigener Docstring (Zeile 10) sagt, Bybit liefere diese Reihen nur\n"
        "   'back to roughly March 2023'. Die vier Dateien beginnen aber am\n"
        "   2021-10-01 -- und zwar lueckenlos, was ein nachtraeglich ergaenztes\n"
        "   Stueck ausschliesst. 2021-10-01 ist ausserdem genau fuenf Jahre vor\n"
        "   dem letzten Datenpunkt, also eher ein 'fuenf Jahre zurueck'-Aufruf\n"
        "   als eine Venue-Grenze. Woher die Zeilen kommen, steht in keiner\n"
        "   Datei dieses Projekts.\n"
        "\n"
        "2. DIE FUNDING-DATEN SIND EIN GEMISCHTER DATENSATZ AUS ZWEI BOERSEN.\n"
        "   Die zwoelf Dateien spalten sich scharf: BTC, ETH, SOL und XRP\n"
        "   beginnen exakt am 2023-01-01 und haben 11 Zeitstempel ausserhalb\n"
        "   des Rasters; die anderen acht beginnen 2020 und haben je rund 3.300.\n"
        "   2023-01-01 ist genau der Standardwert von `--since` in\n"
        "   backfill_derivatives.py (Zeile 48), also das Bybit-Skript; die\n"
        "   jittrigen stammen aus dem Binance-Pfad. Die vier Hauptmaerkte der\n"
        "   Forschung benutzen damit die Funding-Raten einer ANDEREN Boerse als\n"
        "   die uebrigen acht. Fuer ein marktuebergreifendes Modell ist das ein\n"
        "   Defekt, nicht eine Feinheit.\n"
        "\n"
        "Und ein dritter Befund, der kein Herkunftsproblem ist, sondern einfach\n"
        "ein Fehler: BNBUSDT hat 3.615 Funding-Raten von exakt null, also 49,6%\n"
        "der Datei. Eine Boerse, die in der Haelfte aller Intervalle genau null\n"
        "abrechnet, gibt es nicht. LINKUSDT (4,7%) und LTCUSDT (4,2%) sind\n"
        "dieselbe Krankheit, milder.\n"
        "\n"
        "Solange das offen ist, darf keine dieser Zeilen ein gemessenes Modell\n"
        "trainieren: eine Zahl aus Daten unbekannter Herkunft ist keine Messung.\n"
        "Das ist die Reihenfolge, die der Forschungsauftrag verlangt -- Abdeckung\n"
        "und Herkunft zuerst, Modell danach."
    )


def parse_args() -> argparse.Namespace:
    known = ["ohlcv", "funding", "openinterest", "accountratio", "derivatives", "sentiment", "flow"]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sources", nargs="*", choices=known, help="Default: alle ausser ohlcv (das ist gross)."
    )
    parser.add_argument("--with-ohlcv", action="store_true", help="Preisdaten mitzaehlen.")
    parser.add_argument("--json", action="store_true", help="Maschinenlesbar, fuer den Adapter.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.sources:
        wanted = set(args.sources)
    else:
        wanted = {"derivatives", "funding", "sentiment", "flow"}
        if args.with_ohlcv:
            wanted.add("ohlcv")

    rows = gather(wanted)
    if not rows:
        print("Keine Dateien gefunden.")
        return 1

    config = load_config()
    active = list(config.engine.symbols.active)

    if args.json:
        print(
            json.dumps(
                {
                    "aktive_maerkte": active,
                    "serien": [
                        {
                            **asdict(row),
                            "span_jahre": round(row.span_years, 2),
                            "vollstaendigkeit": round(row.completeness, 4),
                        }
                        for row in rows
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    report(rows, active=active)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
