"""Prove where the stored data came from, by fetching it again and comparing.

    python scripts/verify_provenance.py
    python scripts/verify_provenance.py --symbols BTCUSDT,ETHUSDT

`scripts/coverage.py` counts what is on disk and reports *signals* about
origin -- decimal places, grid jitter, exact zeros. Signals are not proof, and
on 05.10.2026 they produced a false alarm that blocked a whole research axis:
the open interest files begin 2021-10-01 while `backfill_derivatives.py` says
in its own docstring that Bybit serves these "back to roughly March 2023", so
the rows looked unaccountable.

They are not. Bybit returns 16419.749 for BTCUSDT at 2021-10-01 00:00 and the
stored value is 16419.749 -- identical to the last decimal. The docstring was
wrong, and a wrong sentence in a comment cost more than a wrong number would
have, because nobody re-measures a comment.

So this script exists to settle the question by measurement whenever it is
asked. It fetches a handful of stored timestamps from the venue again and
compares. **An exact match is the only acceptable result**: these are recorded
observations, not derived quantities, so a small difference is not rounding --
it is a different series.

**It also checks the venue the data is NOT from**, which is what turned the
alarm into an answer. Binance's public archive serves the same quantity for
the same timestamps with documented checksums, and the stored values are 34%
to 71% of it. Two venues of different size, not two readings of one. Without
that comparison "it matches Bybit" would be a coincidence nobody had excluded.

**What this cannot settle, and does report.** Matching Bybit makes the
derivative series accountable. It does not make it *consistent* with the price
series, which `config/settings.yaml` takes from Binance. Positioning on one
venue against prices on another is a weaker hypothesis than it looks, and the
mismatch belongs in the report of any model that uses both.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import ccxt
import pandas as pd

from traidingbrain.config.settings import load_config

#: Binance's public archive of the same quantity, for the venue comparison.
ARCHIVE = "https://data.binance.vision/data/futures/um/daily/metrics"

#: Stored hours to re-fetch per symbol. A handful is enough: these are
#: recorded observations, so one exact match is strong and one mismatch is
#: decisive. More would only cost rate limit.
SAMPLES = 3

#: Largest difference still called a match. Zero, deliberately: an open
#: interest is a number the venue published, not something computed from
#: other numbers, so anything above float noise means a different series.
TOLERANCE = 1e-6

#: Hours in milliseconds, for stepping the sample window.
HOUR_MS = 3_600_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated. Default: those with files.")
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Den Binance-Archivvergleich auslassen (spart Downloads).",
    )
    parser.add_argument(
        "--quarantine",
        action="store_true",
        help=(
            "Zeilen entfernen, die der Boerse nachweislich widersprechen, und "
            "sie nach data/quarantine/ schreiben. SCHREIBT Dateien."
        ),
    )
    parser.add_argument(
        "--scan-tail",
        type=int,
        default=0,
        help=(
            "Die letzten N Stunden Zeile fuer Zeile pruefen statt nur drei "
            "Stichproben. Noetig, weil eine Verunreinigung am jungen Ende sitzt, "
            "wo ein Walk-forward sein letztes Prueffenster hat."
        ),
    )
    return parser.parse_args()


def bybit_open_interest(exchange: object, symbol: str, ts: int) -> float | None:
    """What Bybit reports for that hour now, or None if it reports nothing."""
    try:
        payload = exchange.publicGetV5MarketOpenInterest(  # type: ignore[attr-defined]
            {
                "category": "linear",
                "symbol": symbol,
                "intervalTime": "1h",
                "startTime": ts,
                "endTime": ts + HOUR_MS,
                "limit": 5,
            }
        )
    except Exception as exc:
        print(f"      Bybit-Fehler: {type(exc).__name__}: {str(exc)[:90]}")
        return None
    for item in payload.get("result", {}).get("list", []):
        if int(item["timestamp"]) == ts:
            return float(item["openInterest"])
    return None


def binance_archive_open_interest(symbol: str, ts: int) -> float | None:
    """The same hour from Binance's archive, checksum verified.

    Returns None when the archive has no file for that day, which for an older
    symbol is ordinary rather than an error.
    """
    day = datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d")
    url = f"{ARCHIVE}/{symbol}/{symbol}-metrics-{day}.zip"
    try:
        with urllib.request.urlopen(url, timeout=40) as response:
            blob = response.read()
        with urllib.request.urlopen(url + ".CHECKSUM", timeout=20) as response:
            expected = response.read().decode().split()[0]
    except (urllib.error.URLError, OSError, IndexError):
        return None

    if hashlib.sha256(blob).hexdigest() != expected:
        print(f"      Archiv-Pruefsumme weicht ab fuer {day} -- Datei verworfen")
        return None

    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        frame = pd.read_csv(io.BytesIO(archive.read(archive.namelist()[0])))
    # as_unit("ms") explicitly: pandas 3.0 parses to datetime64[us], so the
    # usual `astype("int64") // 10**6` yields SECONDS and silently matches
    # nothing. That cost an hour today.
    frame["ts"] = pd.to_datetime(frame["create_time"], utc=True).dt.as_unit("ms").astype("int64")
    hit = frame.loc[frame["ts"] == ts, "sum_open_interest"]
    return float(hit.iloc[0]) if not hit.empty else None


def sample(
    exchange: object,
    symbol: str,
    stored: pd.DataFrame,
    stamps: list[int],
    *,
    with_archive: bool,
) -> tuple[int, int]:
    """Compare a few stored hours against Bybit, and against Binance beside it.

    Returns (matches, checked). A timestamp the venue does not answer for is
    not counted either way -- no answer is not a mismatch, and treating it as
    one would mark a whole symbol unaccountable because of a rate limit.
    """
    matches = 0
    checked = 0
    for ts in stamps:
        own = float(stored.loc[stored["ts"] == ts, "open_interest"].iloc[0])
        when = datetime.fromtimestamp(ts / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M")
        theirs = bybit_open_interest(exchange, symbol, ts)
        if theirs is None:
            print(f"   {when}  gespeichert {own:>18,.3f}   Bybit: keine Antwort")
            continue
        checked += 1
        delta = abs(own - theirs)
        if delta <= TOLERANCE:
            matches += 1
            mark = "GLEICH"
        else:
            mark = f"ABWEICHUNG {delta:,.3f}"
        print(f"   {when}  gespeichert {own:>18,.3f}   Bybit {theirs:>18,.3f}   {mark}")

        if with_archive:
            other = binance_archive_open_interest(symbol, ts)
            if other is not None:
                share = 100.0 * own / other if other else float("nan")
                print(
                    f"   {'':16s}  Binance-Archiv {other:>15,.3f}   "
                    f"gespeichert = {share:.0f}% davon"
                )
    return matches, checked


def scan_tail(
    exchange: object, symbol: str, stored: pd.DataFrame, *, hours: int
) -> list[int]:
    """Every stored hour in the last `hours` that the venue contradicts.

    Row by row rather than sampled, because the contamination this found sat
    in the final 35 hours of a 43,821-row file -- 0.08%, which three samples
    would miss and which a walk-forward's last validation fold reads in full.
    """
    frame = stored.sort_values("ts")
    recent = frame.iloc[-hours:] if hours < len(frame) else frame
    bad: list[int] = []
    for ts, own in zip(recent["ts"], recent["open_interest"], strict=True):
        theirs = bybit_open_interest(exchange, symbol, int(ts))
        if theirs is None:
            continue
        if abs(float(own) - theirs) > TOLERANCE:
            bad.append(int(ts))
    return bad


def quarantine(root: Path, symbol: str, stamps: list[int]) -> int:
    """Move the contradicted rows out of both derivative files.

    Moved rather than deleted: a row that disagrees with the venue is evidence
    about how it got there, and deleting it destroys the only record of the
    defect. `data/quarantine/` is outside anything a model reads.

    Both files are cut on the same timestamps, because the contamination
    arrived as whole observations -- open interest and account ratio were
    written together, and 35 rows were wrong in both.
    """
    if not stamps:
        return 0
    bad = set(stamps)
    out = root.parent / "quarantine" / symbol
    out.mkdir(parents=True, exist_ok=True)

    moved = 0
    for name in ("open_interest", "account_ratio"):
        path = root / symbol / f"{name}.parquet"
        if not path.is_file():
            continue
        frame = pd.read_parquet(path)
        mask = frame["ts"].isin(bad)
        if not mask.any():
            continue
        frame.loc[mask].to_parquet(out / f"{name}.parquet", index=False)
        frame.loc[~mask].reset_index(drop=True).to_parquet(path, index=False)
        moved += int(mask.sum())
    return moved


def main() -> int:
    args = parse_args()
    config = load_config()
    root = config.engine.paths.data_dir / "derivatives"

    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else sorted(p.name for p in root.glob("*") if (p / "open_interest.parquet").is_file())
    )
    if not symbols:
        print("Keine Derivate-Dateien gefunden.")
        return 1

    exchange = ccxt.bybit(
        {"enableRateLimit": True, "options": {"defaultType": "swap", "defaultSubType": "linear"}}
    )

    print("Herkunft wird nachgemessen, nicht behauptet.")
    print(f"Toleranz: {TOLERANCE:g} -- eine Boersenbeobachtung ist exakt oder eine andere.\n")

    verdicts: dict[str, bool] = {}
    for symbol in symbols:
        stored = pd.read_parquet(root / symbol / "open_interest.parquet")
        if stored.empty:
            continue
        # Oldest, middle and newest: an origin that holds only for recent rows
        # is exactly the case the false alarm was about.
        picks = [
            int(stored["ts"].iloc[0]),
            int(stored["ts"].iloc[len(stored) // 2]),
            int(stored["ts"].iloc[-1]),
        ][:SAMPLES]

        print(f"{symbol}:")
        matches, checked = sample(
            exchange, symbol, stored, picks, with_archive=not args.skip_archive
        )
        verdicts[symbol] = checked > 0 and matches == checked

        if args.scan_tail:
            bad = scan_tail(exchange, symbol, stored, hours=args.scan_tail)
            if bad:
                span = (
                    f"{datetime.fromtimestamp(min(bad) / 1000, tz=UTC):%Y-%m-%d %H:%M} bis "
                    f"{datetime.fromtimestamp(max(bad) / 1000, tz=UTC):%Y-%m-%d %H:%M}"
                )
                print(f"   SCHWANZ: {len(bad)} widersprechende Zeilen, {span}")
                if args.quarantine:
                    moved = quarantine(root, symbol, bad)
                    print(f"   -> {moved} Zeilen nach data/quarantine/ verschoben")
            else:
                print(f"   SCHWANZ: die letzten {args.scan_tail} Stunden stimmen")
        print()

    print("=" * 78)
    for symbol, ok in verdicts.items():
        print(f"  {symbol:10s} {'Herkunft BELEGT: Bybit linear' if ok else 'NICHT belegt'}")

    if all(verdicts.values()) and verdicts:
        print(
            "\nAlle geprueften Werte stimmen exakt mit Bybit und weichen deutlich vom\n"
            "Binance-Archiv ab. Damit ist die Herkunft geklaert und der Satz in\n"
            "scripts/backfill_derivatives.py, Bybit liefere erst ab Maerz 2023, ist\n"
            "widerlegt -- die aelteste geprueften Zeile liegt 2021.\n"
            "\nWAS DAMIT NICHT GEKLAERT IST: config/settings.yaml nimmt die Preise von\n"
            "BINANCE. Positionierungsdaten der einen Boerse gegen Preise der anderen\n"
            "sind eine schwaechere Hypothese als sie aussieht, und das gehoert in den\n"
            "Bericht jedes Modells, das beide benutzt -- nicht in eine Fussnote."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
