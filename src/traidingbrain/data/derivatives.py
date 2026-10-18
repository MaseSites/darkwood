"""Positioning data: how much is open, and which way the crowd leans.

Price says what happened. Open interest says whether it happened because someone
took on risk or because someone got out of it, and those are different markets
wearing the same candle.

The four combinations are the whole reason this is worth fetching:

| price | open interest | what it is                                  |
|-------|---------------|---------------------------------------------|
| up    | up            | new longs -- money arriving, trend supported |
| up    | down          | shorts covering -- a squeeze, not demand     |
| down  | up            | new shorts -- money arriving on the offer    |
| down  | down          | longs closing -- a flush, often exhaustion    |

A rally on falling open interest and a rally on rising open interest look
identical on a chart and are not the same trade. Nothing else in this system can
tell them apart.

**On lookahead.** Both series are timestamped at the close of the interval they
describe, exactly like a candle, and are read through the same
`index_at_or_before` discipline. Bybit serves them back to roughly March 2023,
which covers nearly the whole backfill window -- but not all of it, so a missing
reading has to stay missing rather than become a zero. "No data" and "open
interest did not change" are opposite claims.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from traidingbrain.data.venue import SUPPORTED, venue

#: Bybit returns at most this many rows per request.
MAX_PAGE = 200

#: Intervals Bybit accepts for these endpoints. Not the same set as for candles,
#: which is why this is spelled out rather than derived from Timeframe.
INTERVALS = {"5min", "15min", "30min", "1h", "4h", "1d"}

_COMPRESSION = "zstd"

#: Version 1 trug keine Venue. Eine Datei, aus ihrem Verzeichnis geloest, war
#: damit herkunftslos -- und `DerivativesStore.write` mischte zwei Boersen in
#: eine Datei, weil nichts sie unterscheiden konnte. Siehe
#: `audit/CHATGPT_BRIEFING_02.md` 5.1.
_OI_SCHEMA_V1 = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("open_interest", pa.float64(), nullable=False),
    ]
)

_RATIO_SCHEMA_V1 = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("buy_ratio", pa.float64(), nullable=False),
        pa.field("sell_ratio", pa.float64(), nullable=False),
    ]
)

#: Version 2: die Venue ist Pflichtfeld UND Verzeichnisebene.
#:
#: Beides, nicht eines von beiden. Eine Spalte allein schuetzt nicht, solange
#: weiterhin in denselben physischen Store geschrieben wird -- dann steht die
#: Herkunft daneben und die Zeilen liegen trotzdem zusammen. Ein getrennter
#: Pfad allein schuetzt nicht, weil eine verschobene Datei ihre Herkunft
#: verliert.
SCHEMA_VERSION = 2

_OI_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("open_interest", pa.float64(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
    ]
)

_RATIO_SCHEMA = pa.schema(
    [
        pa.field("ts", pa.int64(), nullable=False),
        pa.field("buy_ratio", pa.float64(), nullable=False),
        pa.field("sell_ratio", pa.float64(), nullable=False),
        pa.field("venue", pa.string(), nullable=False),
    ]
)

#: Das Manifest liegt NEBEN den Daten, nicht in ihnen.
#:
#: Die vier bestehenden Dateien tragen keine Venue-Spalte und werden nicht
#: umgeschrieben. Ihre Herkunft ist deshalb eine Aussage ueber sie, nicht in
#: ihnen -- und sie ist eine INFERENZ, die ihren Beleg mitfuehren muss.
PROVENANCE_FILE = "PROVENANCE.json"


class ForeignVenueError(RuntimeError):
    """Daten einer anderen Boerse wuerden mit diesen vermischt.

    `RuntimeError`, nicht `ValueError`: das ist kein ungueltiger Eingabewert,
    sondern ein Schreib- oder Lesevorgang, der nicht stattfinden darf.
    """


class DerivativesUnavailableError(RuntimeError):
    """The venue has no positioning data this far back.

    Raised rather than returning an empty frame, so a backfill that silently
    covered nothing is not mistaken for one that found nothing to add.
    """


@dataclass(frozen=True)
class FetchReport:
    """What a fetch actually retrieved, in terms worth printing."""

    symbol: str
    kind: str
    rows: int
    first_ts: int | None
    last_ts: int | None

    def summary(self) -> str:
        if not self.rows:
            return f"{self.symbol} {self.kind}: nothing returned"
        span = f"{_day(self.first_ts)} to {_day(self.last_ts)}"
        return f"{self.symbol} {self.kind}: {self.rows:,} rows, {span}"


def _day(ts: int | None) -> str:
    if ts is None:
        return "?"
    return datetime.fromtimestamp(ts / 1000, tz=UTC).date().isoformat()


class DerivativesSource:
    """Open interest and crowd positioning, read-only and credential-free.

    Through ccxt's unified methods rather than a venue's raw endpoints. The first
    version called Bybit's `/v5/market/open-interest` directly, which worked and
    quietly made the whole positioning factor Bybit-only -- a decision nobody
    made, buried in a URL. Both methods used here exist on Bybit and Binance and
    return the same two fields, which is exactly what unification is for.

    Separate from `MarketData` because these page differently and have a shorter
    history horizon, and folding them together would make one class whose failure
    modes have nothing to do with each other.
    """

    def __init__(self, exchange: Any, venue_name: str, *, max_retries: int = 4) -> None:
        # `venue_name` ist PFLICHT. Der Vorgabewert war "bybit", und
        # `backfill_derivatives.py` hat ihn benutzt, waehrend
        # `run_live.py:171` die konfigurierte Venue uebergab -- zwei
        # Boersen in einem Datensatz, ohne dass eine Zeile es sagte.
        self.exchange = exchange
        self.venue = venue(venue_name)
        self.max_retries = max_retries

    def open_interest(
        self, symbol: str, *, interval: str = "1h", since_ms: int, until_ms: int
    ) -> pd.DataFrame:
        """Total contracts outstanding, one row per interval."""
        rows = self._paged(
            "open interest",
            self.exchange.fetch_open_interest_history,
            symbol,
            interval=interval,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        return _tidy(
            pd.DataFrame(
                {
                    "ts": [int(r["timestamp"]) for r in rows],
                    "open_interest": [float(r["openInterestAmount"] or 0.0) for r in rows],
                }
            )
        )

    def account_ratio(
        self, symbol: str, *, interval: str = "1h", since_ms: int, until_ms: int
    ) -> pd.DataFrame:
        """The share of accounts positioned each way.

        Stored as a share rather than the ratio the venues report, because a share
        is bounded and a ratio is not: 0.6 and 1.5 say the same thing, but only one
        of them can be averaged, compared across venues, or shown on a bar.

        Accounts, not size -- a thousand small longs and one large short both read
        as crowded to the long side. That is the intended reading: this is a
        sentiment measure and the crowd is counted by head.
        """
        rows = self._paged(
            "long/short ratio",
            self.exchange.fetch_long_short_ratio_history,
            symbol,
            interval=interval,
            since_ms=since_ms,
            until_ms=until_ms,
        )
        shares = [_share_long(float(r["longShortRatio"] or 1.0)) for r in rows]
        return _tidy(
            pd.DataFrame(
                {
                    "ts": [int(r["timestamp"]) for r in rows],
                    "buy_ratio": shares,
                    "sell_ratio": [1.0 - share for share in shares],
                }
            )
        )

    # -- plumbing ----------------------------------------------------------- #

    def _paged(
        self,
        description: str,
        call: Any,
        symbol: str,
        *,
        interval: str,
        since_ms: int,
        until_ms: int,
    ) -> list[dict[str, Any]]:
        """Walk forward in windows until the range is covered.

        These endpoints stop at their own history horizon without saying so, so
        the loop ends on a page that returns nothing new -- never on a row count,
        which would spin forever once the venue runs out of history.
        """
        if interval not in INTERVALS:
            raise ValueError(f"{interval!r} is not an interval this endpoint accepts: {INTERVALS}")

        step = _interval_ms(interval)
        collected: list[dict[str, Any]] = []
        seen: set[int] = set()
        cursor = since_ms

        while cursor < until_ms:
            page = self._with_retry(
                description, call, self.venue.symbol(symbol), interval, cursor, MAX_PAGE
            )
            fresh = [
                row
                for row in page
                if row.get("timestamp") is not None
                and int(row["timestamp"]) not in seen
                and int(row["timestamp"]) <= until_ms
            ]
            if not fresh:
                break
            for row in fresh:
                seen.add(int(row["timestamp"]))
            collected.extend(fresh)
            newest = max(int(row["timestamp"]) for row in fresh)
            if newest <= cursor:
                break
            cursor = newest + step

        return collected

    def _with_retry(self, description: str, call: Any, *args: Any) -> list[dict[str, Any]]:
        delay = 1.0
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                result: list[dict[str, Any]] = call(*args)
                return result
            except Exception as exc:
                last = exc
                if attempt == self.max_retries - 1:
                    break
                time.sleep(delay)
                delay *= 2
        raise DerivativesUnavailableError(
            f"{description} failed after {self.max_retries} attempts: {last}"
        )


def _share_long(ratio: float) -> float:
    """Longs-to-shorts, as a share of accounts that are long.

    A ratio of 1.5 means three longs for every two shorts, which is a 0.6 share.
    Clamped, because a venue reporting an absurd ratio should produce a bounded
    number rather than one that fails a model constraint three layers later.
    """
    if ratio <= 0:
        return 0.5
    return max(0.0, min(1.0, ratio / (1.0 + ratio)))


def _interval_ms(interval: str) -> int:
    units = {"min": 60_000, "h": 3_600_000, "d": 86_400_000}
    for suffix, size in units.items():
        if interval.endswith(suffix):
            return int(interval[: -len(suffix)]) * size
    raise ValueError(f"cannot size the interval {interval!r}")


def _tidy(frame: pd.DataFrame) -> pd.DataFrame:
    """Sort, deduplicate and reset. The order these arrive in is not guaranteed."""
    if frame.empty:
        return frame
    return (
        frame.drop_duplicates(subset="ts", keep="last")
        .sort_values("ts")
        .reset_index(drop=True)
        .astype({"ts": "int64"})
    )


def _schema_for(kind: str) -> pa.Schema:
    return _OI_SCHEMA if kind == "open_interest" else _RATIO_SCHEMA


def _legacy_schema_for(kind: str) -> pa.Schema:
    return _OI_SCHEMA_V1 if kind == "open_interest" else _RATIO_SCHEMA_V1


def _tidy_by_venue(frame: pd.DataFrame) -> pd.DataFrame:
    """Sortieren und deduplizieren -- Schluessel ist (venue, ts), nicht ts.

    `_tidy` nahm `ts` allein. Innerhalb einer Partition genuegt das, weil dort
    nur eine Boerse liegt. Der Schluessel muss trotzdem die Venue enthalten:
    sonst verschluckt eine spaetere Zusammenfuehrung mehrerer Partitionen
    stillschweigend eine Boerse, und zwar die zuerst gelesene.
    """
    if frame.empty:
        return frame
    return (
        frame.drop_duplicates(subset=["venue", "ts"], keep="last")
        .sort_values(["venue", "ts"])
        .reset_index(drop=True)
        .astype({"ts": "int64"})
    )


class DerivativesStore:
    """Positionierungsreihen auf der Platte -- eine Boerse je Datei, erzwungen.

    **Was hier schiefging.** `LivePositioning.refresh` schrieb frisch geholte
    Zeilen in dieselbe Datei wie die Backfill-Historie. Die Live-Quelle kam
    aus `run_live.py:171` ueber `config.engine.exchange.name` (Binance), die
    Historie aus `backfill_derivatives.py` ueber hartkodiertes `ccxt.bybit`.
    Die Schemata trugen keine Venue, und `_tidy` deduplizierte auf `ts` allein
    -- bei Ueberlappung gewann die spaeter geschriebene Zeile.

    Die Groessenordnung ist gemessen: Bybit 16419.749 gegen Binance 47921.245
    fuer BTCUSDT am 2021-10-01 00:00, Faktor ~2.9 (`learn/panel.py:138`). Bei
    `MIN_OI_CHANGE = 0.004` (`analysis/positioning.py:48`) waere die Naht ein
    riesiges Open-Interest-Signal aus einem Datenfehler.

    **Zwei Schranken, nicht eine.** Die Venue ist Verzeichnisebene UND
    Pflichtspalte. Der Pfad trennt die Daten physisch; die Spalte macht eine
    einzelne Datei selbsterklaerend, auch wenn sie aus ihrem Verzeichnis
    geloest wird.

    **Das Erbe wird gelesen, niemals beschrieben.** Die vier bestehenden
    Dateien liegen unter `root/<SYMBOL>/<kind>.parquet` und bleiben
    byte-identisch -- der neue Pfad enthaelt die Venue, also kann `write` sie
    nicht treffen. Ihre Herkunft steht in einem Manifest daneben, als
    INFERENZ mit Beleg.
    """

    def __init__(
        self,
        root: Path,
        *,
        venue: str,
        on_foreign: str | None = None,
    ) -> None:
        """`venue` ist Pflicht, `on_foreign` beim Lesen.

        `on_foreign` hat absichtlich keinen Vorgabewert: was bei fremden Daten
        geschehen soll, ist eine Entscheidung des Aufrufers, und ein
        Vorgabewert waere genau die stille Entscheidung, die dieses Modul
        beseitigt. `"raise"` bricht ab, `"legacy"` liefert eine leere Reihe und
        laesst den Aufrufer das Fehlen berichten.

        Schreiben braucht die Angabe nicht -- dort ist die Antwort immer
        Abbruch.
        """
        if venue not in SUPPORTED:
            raise ValueError(
                f"Venue {venue!r} ist nicht unterstuetzt. Bekannt: "
                f"{sorted(SUPPORTED)}."
            )
        if on_foreign not in (None, "raise", "legacy"):
            raise ValueError(
                f"on_foreign {on_foreign!r} -- erlaubt sind 'raise' und 'legacy'."
            )
        self.root = root
        self.venue_name = venue
        self.on_foreign = on_foreign

    # -- Pfade -------------------------------------------------------------- #

    def path(self, symbol: str, kind: str) -> Path:
        """Der Schreibpfad. Enthaelt die Venue, darum trifft er kein Erbe."""
        return self.root / self.venue_name / symbol / f"{kind}.parquet"

    def legacy_path(self, symbol: str, kind: str) -> Path:
        """Das alte Layout ohne Venue-Ebene. Nur zum Lesen."""
        return self.root / symbol / f"{kind}.parquet"

    # -- Schreiben ---------------------------------------------------------- #

    def write(self, symbol: str, kind: str, frame: pd.DataFrame) -> int:
        """Zusammenfuehren und schreiben. Bricht bei fremden Zeilen ab."""
        if frame.empty:
            return 0

        if "venue" in frame.columns:
            fremd = sorted(set(frame["venue"].astype(str)) - {self.venue_name})
            if fremd:
                raise ForeignVenueError(
                    f"Der Rahmen traegt Zeilen von {fremd} und dieser Speicher "
                    f"ist {self.venue_name!r}. Zwei Boersen in einer Datei sind "
                    f"nachtraeglich nicht trennbar -- dieser Schreibvorgang "
                    f"findet nicht statt."
                )
            frame = frame.drop(columns=["venue"])

        schema = _schema_for(kind)
        frame = frame.copy()
        frame["venue"] = self.venue_name

        path = self.path(symbol, kind)
        if path.exists():
            stored: pd.DataFrame = pq.read_table(path).to_pandas()
            if "venue" in stored.columns:
                fremd = sorted(set(stored["venue"].astype(str)) - {self.venue_name})
                if fremd:
                    raise ForeignVenueError(
                        f"{path} enthaelt Zeilen von {fremd}, dieser Speicher "
                        f"ist {self.venue_name!r}. Die Datei wird nicht "
                        f"angefasst."
                    )
            else:
                raise ForeignVenueError(
                    f"{path} traegt keine Venue-Spalte, ist also Schema v1 "
                    f"unbekannter Herkunft. Eine Datei unbekannter Herkunft "
                    f"wird nicht fortgeschrieben."
                )
            frame = _tidy_by_venue(pd.concat([stored, frame], ignore_index=True))
        else:
            frame = _tidy_by_venue(frame)

        path.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(
            frame[schema.names], schema=schema, preserve_index=False
        )
        table = table.replace_schema_metadata(
            {"schema_version": str(SCHEMA_VERSION), "venue": self.venue_name}
        )
        pq.write_table(table, path, compression=_COMPRESSION)
        return len(frame)

    # -- Lesen -------------------------------------------------------------- #

    def _empty(self, kind: str) -> pd.DataFrame:
        schema = _schema_for(kind)
        return pd.DataFrame(
            {
                name: pd.Series(dtype="object" if name == "venue" else "float64")
                for name in schema.names
            }
        )

    def read(self, symbol: str, kind: str) -> pd.DataFrame:
        """Die eigene Partition, oder ein passendes Erbe, oder nichts."""
        path = self.path(symbol, kind)
        if path.exists():
            # Die eigene Partition stellt keine Fremddaten-Frage.
            loaded: pd.DataFrame = pq.read_table(path).to_pandas()
            return loaded

        legacy = self.legacy_path(symbol, kind)
        if not legacy.exists():
            return self._empty(kind)

        # Erst HIER wird die Entscheidung gebraucht: es liegt ein Erbe da,
        # dessen Herkunft nicht in ihm selbst steht. Die Angabe wird nicht
        # beim Konstruieren verlangt, weil ein Speicher, der nur schreibt
        # oder nur seine eigene Partition liest, sie nicht braucht -- eine
        # Pflichtangabe an dieser Stelle waere Zeremonie ohne Schutz.
        if self.on_foreign is None:
            raise TypeError(
                f"{legacy} liegt im alten Layout, und dieser Speicher wurde "
                "ohne on_foreign gebaut. Was mit Daten fremder oder "
                "unbekannter Herkunft geschehen soll, ist eine Entscheidung "
                "des Aufrufers: 'raise' bricht ab, 'legacy' liefert eine "
                "leere Reihe. Sie wird nicht stillschweigend getroffen."
            )

        manifest = self.read_provenance(self.root)
        herkunft = manifest.get("venue") if manifest else None

        if herkunft is None:
            if self.on_foreign == "raise":
                raise ForeignVenueError(
                    f"{legacy} liegt im alten Layout und die Herkunft ist "
                    f"unbekannt -- es gibt kein {PROVENANCE_FILE}. Unbekannte "
                    f"Herkunft wird KEINER Boerse zugeordnet."
                )
            return self._empty(kind)

        if herkunft != self.venue_name:
            if self.on_foreign == "raise":
                raise ForeignVenueError(
                    f"{legacy} ist laut Manifest {herkunft!r}, dieser Speicher "
                    f"ist {self.venue_name!r}. Kein stiller Ersatz mit einer "
                    f"anderen Boerse."
                )
            return self._empty(kind)

        loaded = pq.read_table(legacy).to_pandas()
        loaded["venue"] = herkunft
        return loaded[_schema_for(kind).names]

    # -- Das Manifest ------------------------------------------------------- #

    @staticmethod
    def read_provenance(root: Path) -> dict[str, Any] | None:
        path = root / PROVENANCE_FILE
        if not path.exists():
            return None
        loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return loaded

    @staticmethod
    def write_provenance(
        root: Path, *, venue: str, evidence: str
    ) -> dict[str, Any]:
        """Die Herkunft des Erbes festhalten -- als Inferenz, mit Beleg.

        Die vier bestehenden Dateien tragen keine Venue-Spalte. Ihre Herkunft
        ist deshalb eine Aussage UEBER sie, und sie muss ihren Beleg
        mitfuehren. `inferred` steht darum fest auf wahr: solange die Zeilen
        selbst es nicht sagen, ist es eine Schlussfolgerung.

        Nur lesend auf den Parquet-Dateien.
        """
        if venue not in SUPPORTED:
            raise ValueError(f"Venue {venue!r} ist nicht unterstuetzt.")
        if not evidence.strip():
            raise ValueError(
                "Eine Herkunftsangabe ohne Beleg ist in diesem Projekt keine "
                "Angabe -- siehe audit/P0A_LEGACY_FREEZE.md."
            )

        files: list[dict[str, Any]] = []
        for symbol_dir in sorted(d for d in root.iterdir() if d.is_dir()):
            if symbol_dir.name in SUPPORTED:
                continue  # eine Venue-Partition, kein Erbe
            for parquet in sorted(symbol_dir.glob("*.parquet")):
                digest = hashlib.sha256(parquet.read_bytes()).hexdigest()
                table = pq.read_table(parquet)
                ts = table.column("ts").to_pylist() if table.num_rows else []
                files.append(
                    {
                        "path": f"{symbol_dir.name}/{parquet.name}",
                        "sha256": digest,
                        "bytes": parquet.stat().st_size,
                        "rows": table.num_rows,
                        "first_ts": min(ts) if ts else None,
                        "last_ts": max(ts) if ts else None,
                        "columns": list(table.schema.names),
                        "carries_venue_column": "venue" in table.schema.names,
                    }
                )

        manifest: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "legacy_layout": "<SYMBOL>/<kind>.parquet",
            "venue": venue,
            "inferred": True,
            "evidence": evidence,
            "written_utc": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "files": files,
        }
        (root / PROVENANCE_FILE).write_text(
            json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8"
        )
        return manifest


class LivePositioning:
    """Keeps a symbol's positioning series current while a live loop runs.

    The backfill fetches years; this fetches the last day and stops. They write to
    the same store, so a long-running session drifts no further from the venue
    than one interval.

    It exists because the staleness rule in `analysis.positioning` is unforgiving
    by design: a reading older than a few hours is reported as unknown rather than
    carried forward, since a venue that stopped reporting is not a market that
    stopped moving. Correct -- and it means that without something topping the
    series up, every reading goes unknown a few hours after the last backfill and
    stays that way. Silent, permanent, and indistinguishable from a period the
    venue genuinely does not cover.
    """

    def __init__(
        self,
        source: DerivativesSource,
        store: DerivativesStore,
        *,
        interval: str = "1h",
        lookback_hours: int = 24,
    ) -> None:
        self.source = source
        self.store = store
        self.interval = interval
        self.lookback_hours = lookback_hours

    def refresh(self, symbol: str, now_ms: int) -> int:
        """Top up both series. Returns how many rows were written."""
        since = now_ms - self.lookback_hours * 3_600_000
        written = 0
        for kind, fetch in (
            ("open_interest", self.source.open_interest),
            ("account_ratio", self.source.account_ratio),
        ):
            frame = fetch(symbol, interval=self.interval, since_ms=since, until_ms=now_ms)
            if not frame.empty:
                written += self.store.write(symbol, kind, frame)
        return written
