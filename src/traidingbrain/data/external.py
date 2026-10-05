"""Data from outside the exchange: on-chain activity and stablecoin liquidity.

The declared map of strategy families is exhausted -- twelve measured, none
positive -- and everything on it lived inside the exchange: price, volume,
volatility, range, time of day, order flow, positioning, funding, regime,
horizon. This module is the first source that does not.

**Two connectors, both keyless and both checked against the live service
before a line of this was written.**

* **Coin Metrics Community** (`community-api.coinmetrics.io/v4`). Daily asset
  metrics from 2015. `api.coinmetrics.io/v4` answers 401 without a key; the
  community host answers 200, and the difference is not documented in one
  place, so it is recorded here. Available keyless: `AdrActCnt`, `TxCnt`,
  `SplyCur`, `HashRate`, `CapMrktCurUSD`, `IssTotUSD` and -- the one that
  matters -- **`FlowInExUSD` / `FlowOutExUSD`, exchange inflow and outflow in
  USD.** The research order's own source table called reliable free exchange
  netflow unconfirmed. It is available. Metrics behind the paywall answer 403
  and are listed so nobody retries them: `TxTfrValAdjUSD`, `FeeTotUSD`,
  `NVTAdj`, `SplyAct1yr`.
* **DefiLlama** (`stablecoins.llama.fi`). 3,233 daily rows from 2017-11-29.

**The availability rule, which this source makes unusually concrete.** Every
Coin Metrics row carries `<metric>-status` and `<metric>-status-time`. Recent
rows come back as `status=flash` -- preliminary -- with a status time on the
**following day between 02:00 and 03:45 UTC**. So a flow value stamped for day
D was not knowable at D 00:00; it was knowable about 26 hours later. Using the
stamp as the availability time would leak more than a day into every feature
built from it. `available_ms` is therefore taken from `status-time` when the
service gives one, and falls back to a conservative full day otherwise.

**The revision problem, named rather than solved.** `flash` means the value
may be restated. The API serves whatever it believes today, so a backtest run
now reads *revised* numbers for old days while a live system would have seen
the flash ones. That is a point-in-time gap this connector cannot close --
Coin Metrics Community exposes no vintage query -- and any model using these
features carries it. `status` is stored per row so a study can at least
exclude the ones still marked preliminary.

**Licence.** Coin Metrics Community data is CC BY-NC 4.0. Research and paper
trading are inside that; a later commercial use is not, and must not be
assumed from this file.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

#: The community host. The documented `api.coinmetrics.io/v4` answers 401
#: without a key; this one answers 200. Checked, not assumed.
COINMETRICS = "https://community-api.coinmetrics.io/v4"

#: DefiLlama's public stablecoin history. No key, no rate limit documented.
DEFILLAMA = "https://stablecoins.llama.fi/stablecoincharts/all"

#: Metrics the community tier serves. Verified one by one against the live
#: service -- the catalog endpoint answers 400 on this host, so asking for the
#: metric is the only reliable way to know.
COMMUNITY_METRICS: tuple[str, ...] = (
    "AdrActCnt",
    "TxCnt",
    "SplyCur",
    "CapMrktCurUSD",
    "IssTotUSD",
    "FlowInExUSD",
    "FlowOutExUSD",
)

#: Metrics that answer 403 on the community tier. Listed so the next person
#: does not spend a request discovering it again.
PAYWALLED: frozenset[str] = frozenset(
    {"TxTfrValAdjUSD", "FeeTotUSD", "NVTAdj", "SplyAct1yr"}
)

#: Availability lag applied to every row: one full day after the observation.
#:
#: Measured on rows the service still annotates meaningfully, a daily metric
#: for day D carries a status time on D+1 between 02:00 and 03:45 UTC -- about
#: 26 hours. A full day is the round number just under that, and the direction
#: of the rounding is the point: a feature that arrives late is merely weaker,
#: a feature that arrives early is wrong.
#:
#: Applied as a constant rather than read per row, because `status-time` turned
#: out to mean "last revalidated" rather than "first available" -- see the note
#: in `coinmetrics`.
FALLBACK_LAG_MS = 86_400_000

DAY_MS = 86_400_000
REQUEST_TIMEOUT = 40.0
PAGE_SIZE = 10_000
MAX_RETRIES = 4
BACKOFF_SECONDS = 2.0
USER_AGENT = "traidingbrain-research/0.1"


class ExternalUnavailableError(RuntimeError):
    """A source did not answer. Carries which one and why."""


@dataclass(frozen=True, slots=True)
class Fetched:
    """A response plus what is needed to say where it came from."""

    frame: pd.DataFrame
    source: str
    url: str
    sha256: str
    fetched_ms: int

    def describe(self) -> str:
        return (
            f"{self.source}: {len(self.frame):,} Zeilen, sha256 {self.sha256[:16]}, "
            f"geholt {pd.Timestamp(self.fetched_ms, unit='ms', tz='UTC'):%Y-%m-%d %H:%M}"
        )


def _get(url: str) -> bytes:
    """One GET with bounded retries and backoff.

    Retries only what is worth retrying: a timeout, a 5xx, or a 429. A 403 is
    the paywall and a 400 is a wrong request -- repeating either just spends
    the rate limit on a certainty.
    """
    last = ""
    for attempt in range(MAX_RETRIES):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as error:
            retryable = error.code == 429 or error.code >= 500  # noqa: PLR2004
            last = f"HTTP {error.code}"
            if not retryable:
                raise ExternalUnavailableError(f"{url} antwortete {last}") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = type(error).__name__
        if attempt < MAX_RETRIES - 1:
            time.sleep(BACKOFF_SECONDS * (2**attempt))
    raise ExternalUnavailableError(f"{url} nach {MAX_RETRIES} Versuchen nicht erreichbar: {last}")


def _stamp(text: str) -> int:
    """An ISO timestamp from either service, in epoch milliseconds.

    `.value` on a scalar Timestamp returns NANOSECONDS, and keeps returning
    them after `as_unit("ms")` -- that call changes the resolution, not the
    unit of `.value`. Reading it as milliseconds produced a year of 45,002,209
    and a crash in the coverage report, which is the lucky version: a silent
    off-by-a-million in an availability time is a leak nobody would see.

    `//  1_000_000` rather than `timestamp() * 1000`, because the float
    multiply loses sub-millisecond precision on stamps this large and these
    values are compared for ordering.
    """
    return int(pd.Timestamp(text).tz_convert("UTC").value // 1_000_000)


def coinmetrics(
    asset: str, metrics: tuple[str, ...] = COMMUNITY_METRICS, *, since: str = "2015-01-01"
) -> Fetched:
    """Daily metrics for one asset, with each row's availability time.

    `available_ms` comes from the service's own `status-time` where it exists.
    That is the honest number: a flow value stamped for day D carries a status
    time on D+1 at about 02:00-03:45 UTC, so treating the stamp as the
    availability would leak over a day.
    """
    wanted = tuple(m for m in metrics if m not in PAYWALLED)
    if not wanted:
        raise ExternalUnavailableError(
            "Alle angefragten Metriken liegen hinter der Bezahlschranke."
        )

    url = (
        f"{COINMETRICS}/timeseries/asset-metrics?assets={asset.lower()}"
        f"&metrics={','.join(wanted)}&start_time={since}&page_size={PAGE_SIZE}"
    )
    blob = _get(url)
    payload = json.loads(blob)
    rows = payload.get("data", [])
    if not rows:
        raise ExternalUnavailableError(f"Coin Metrics lieferte keine Zeilen fuer {asset}.")

    records: list[dict[str, object]] = []
    for row in rows:
        observed = _stamp(row["time"])
        # `status-time` is NOT a point-in-time availability stamp, which cost
        # a wrong first version of this function. Every one of them falls in
        # the last six months, even for rows observed in 2015 -- it reports
        # when Coin Metrics last revalidated the value, not when it first
        # existed. Using it would have marked every pre-2026 feature
        # unavailable and silently emptied every model built on this source,
        # which reads as thin coverage rather than as a bug.
        #
        # So availability is the conservative constant the research order
        # prescribes for exactly this case, and the revalidation time is kept
        # beside it under its own name rather than discarded.
        validated = [
            _stamp(str(row[f"{m}-status-time"])) for m in wanted if row.get(f"{m}-status-time")
        ]
        record: dict[str, object] = {
            "ts": observed,
            "available_ms": observed + FALLBACK_LAG_MS,
            "validated_ms": max(validated) if validated else 0,
            "status": str(row.get(f"{wanted[0]}-status", "")),
        }
        for metric in wanted:
            value = row.get(metric)
            record[metric] = float(value) if value not in (None, "") else float("nan")
        records.append(record)

    frame = pd.DataFrame(records).sort_values("ts").reset_index(drop=True)
    return Fetched(
        frame=frame,
        source=f"coinmetrics:{asset.lower()}",
        url=url,
        sha256=hashlib.sha256(blob).hexdigest(),
        fetched_ms=int(time.time() * 1000),
    )


def stablecoins() -> Fetched:
    """Total stablecoin circulation per day, supply and USD valuation kept apart.

    The research order warns to distinguish them and the payload shows why:
    `totalCirculating` is units of the peg and `totalCirculatingUSD` is their
    dollar valuation, and for a de-pegged coin those diverge. Both are kept.

    `totalUnreleased` is deliberately dropped. It reports figures in the tens
    of trillions, which is not a quantity any model should see.
    """
    blob = _get(DEFILLAMA)
    payload = json.loads(blob)
    if not isinstance(payload, list) or not payload:
        raise ExternalUnavailableError("DefiLlama lieferte keine Liste.")

    records = []
    for row in payload:
        try:
            observed = int(row["date"]) * 1000
        except (KeyError, TypeError, ValueError):
            continue
        circulating = row.get("totalCirculating") or {}
        valued = row.get("totalCirculatingUSD") or {}
        records.append(
            {
                "ts": observed,
                # A daily aggregate is complete only once the day is over.
                # DefiLlama documents no publication time, so a full day is
                # the conservative choice and is stated rather than hidden.
                "available_ms": observed + FALLBACK_LAG_MS,
                "supply_usd_peg": float(circulating.get("peggedUSD", float("nan"))),
                "valued_usd_peg": float(valued.get("peggedUSD", float("nan"))),
            }
        )

    frame = pd.DataFrame(records).sort_values("ts").reset_index(drop=True)
    return Fetched(
        frame=frame,
        source="defillama:stablecoins",
        url=DEFILLAMA,
        sha256=hashlib.sha256(blob).hexdigest(),
        fetched_ms=int(time.time() * 1000),
    )


class ExternalStore:
    """Parquet per source, with the raw response kept beside it.

    The raw archive is not redundancy. These services restate their history --
    Coin Metrics marks recent rows `flash` and revises them -- so the file that
    was actually fetched is the only record of what a run could have seen.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def path(self, source: str) -> Path:
        return self._root / f"{source.replace(':', '_')}.parquet"

    def write(self, fetched: Fetched, *, keep_raw: bool = True) -> Path:
        target = self.path(fetched.source)
        frame = fetched.frame.copy()
        frame["sha256"] = fetched.sha256
        frame["fetched_ms"] = fetched.fetched_ms

        if target.is_file():
            # Merge on the observation stamp, newest write winning: a restated
            # row should replace its predecessor rather than sit beside it.
            previous = pd.read_parquet(target)
            frame = (
                pd.concat([previous, frame], ignore_index=True)
                .drop_duplicates(subset="ts", keep="last")
                .sort_values("ts")
                .reset_index(drop=True)
            )
        frame.to_parquet(target, index=False)

        if keep_raw:
            archive = self._root / "raw"
            archive.mkdir(exist_ok=True)
            name = f"{fetched.source.replace(':', '_')}-{fetched.fetched_ms}.json"
            (archive / name).write_text(
                json.dumps({"url": fetched.url, "sha256": fetched.sha256}, indent=2),
                encoding="utf-8",
            )
        return target

    def read(self, source: str) -> pd.DataFrame:
        target = self.path(source)
        if not target.is_file():
            return pd.DataFrame(columns=["ts", "available_ms"])
        return pd.read_parquet(target)

    def coverage(self, source: str) -> str:
        frame = self.read(source)
        if frame.empty:
            return f"{source}: nichts gespeichert"
        first = pd.Timestamp(int(frame["ts"].min()), unit="ms", tz="UTC")
        last = pd.Timestamp(int(frame["ts"].max()), unit="ms", tz="UTC")
        span = (frame["ts"].max() - frame["ts"].min()) / DAY_MS
        expected = int(span) + 1
        lag_hours = float((frame["available_ms"] - frame["ts"]).median()) / 3_600_000
        revalidated = (
            int((frame.get("validated_ms", pd.Series(dtype="int64")) > 0).sum())
            if "validated_ms" in frame
            else 0
        )
        flash = int((frame.get("status", pd.Series(dtype=str)) == "flash").sum())
        return (
            f"{source}: {len(frame):,} Zeilen, {first:%Y-%m-%d} bis {last:%Y-%m-%d} "
            f"({span / 365.25:.1f} J), {100 * len(frame) / expected:.1f}% vollstaendig, "
            f"Verfuegbarkeit +{lag_hours:.1f}h, {flash} vorlaeufig, "
            f"{revalidated} mit Revalidierungszeit"
        )
