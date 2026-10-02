"""Is the collector still collecting?

The failure this exists for is not a crash. A crash is loud. The failure is a
collector that stopped at 03:00 and was noticed at the next backtest, by which
time it has written a hole into the history -- and a hole is indistinguishable
from a quiet market unless something recorded that nobody was looking.

So this asks one question per series: when did it last succeed, and is that
longer ago than it should be? A non-zero exit makes systemd mark the unit
failed, which puts it in `systemctl --failed` and in the boot summary. That is
deliberately the ordinary mechanism rather than a bespoke alert: a warning that
only exists inside this project is a warning nobody sees.

Run it with `--quiet` from a timer and it prints only what is wrong.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from traidingbrain.config.settings import load_secrets
from traidingbrain.storage.postgres import PostgresUnavailableError, connect

MINUTE = 60_000

#: Where the age display switches unit. Seconds up to a minute and a half, then
#: minutes up to an hour and a half, then hours up to two days, then days --
#: each boundary a little past the unit's natural end so "95s" never appears
#: where "2min" reads better.
SHOW_SECONDS_BELOW = 90
SHOW_MINUTES_BELOW = 5_400
SHOW_HOURS_BELOW = 172_800
HOUR = 60 * MINUTE
DAY = 24 * HOUR

#: How stale a series may get before it counts as broken.
#:
#: Roughly three times its collection interval, not one. A single missed run is
#: a slow fetch or a timer that coalesced; three in a row is something that is
#: not coming back on its own. An alert that fires on the first miss is an alert
#: that gets ignored by the second week.
TOLERANCE_MS: dict[str, int] = {
    "M1": 20 * MINUTE,
    "M15": 20 * MINUTE,
    "H1": 3 * HOUR,
    "H4": 3 * HOUR,
    "D1": 3 * HOUR,
    "W1": 3 * HOUR,
    "funding": 3 * HOUR,
}

#: When the disk gets this full, a database that appends all day is a problem
#: that is weeks away rather than months -- which is the point at which it is
#: still cheap to fix.
DISK_WARN_PCT = 85


def _tolerance_for(series: str) -> int:
    """`ohlcv:BTCUSDT:M15` -> the M15 tolerance; `funding:BTCUSDT` -> funding."""
    kind = series.rsplit(":", 1)[-1] if series.startswith("ohlcv:") else series.split(":", 1)[0]
    return TOLERANCE_MS.get(kind, 3 * HOUR)


def _age(ms: int) -> str:
    seconds = ms / 1000
    if seconds < SHOW_SECONDS_BELOW:
        return f"{seconds:.0f}s"
    if seconds < SHOW_MINUTES_BELOW:
        return f"{seconds / 60:.0f}min"
    if seconds < SHOW_HOURS_BELOW:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def check_series(cur: Any, now_ms: int, quiet: bool) -> list[str]:
    cur.execute(
        "SELECT series, last_ok_ts, last_rows, last_error FROM collector_status ORDER BY series"
    )
    rows = cur.fetchall()
    if not rows:
        return ["collector_status is empty -- nothing has ever run"]

    problems: list[str] = []
    for series, last_ok_ts, last_rows, last_error in rows:
        age = now_ms - int(last_ok_ts)
        limit = _tolerance_for(series)
        stale = age > limit
        if stale:
            problems.append(f"{series}: last success {_age(age)} ago (limit {_age(limit)})")
        if last_error:
            problems.append(f"{series}: last run failed -- {last_error[:200]}")
        if not quiet:
            mark = "STALE" if stale else "ok"
            print(f"{mark:6s} {series:26s} {_age(age):>7s} ago, {last_rows} rows last run")
    return problems


def check_disk(quiet: bool) -> list[str]:
    usage = shutil.disk_usage("/")
    pct = 100 * usage.used / usage.total
    if not quiet:
        print(f"disk   {pct:.0f}% used, {usage.free / 1e9:.1f} GB free")
    if pct >= DISK_WARN_PCT:
        return [f"disk {pct:.0f}% full, {usage.free / 1e9:.1f} GB left"]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that the collector is still collecting.")
    parser.add_argument("--quiet", action="store_true", help="print only problems")
    args = parser.parse_args()

    url = load_secrets().postgres_url.get_secret_value()
    if not url:
        print("no TB_POSTGRES_URL -- nothing to check", file=sys.stderr)
        return 2

    now_ms = int(time.time() * 1000)
    try:
        with connect(url) as conn, conn.cursor() as cur:
            problems = check_series(cur, now_ms, args.quiet)
    except PostgresUnavailableError as error:
        # A database that cannot be reached *is* the health report, and the most
        # likely one: the collector runs on the Raspberry Pi and the Pi gets
        # switched off. A traceback here says "this script is broken" about a
        # situation in which it is working perfectly.
        print(f"database not reachable: {error}", file=sys.stderr)
        print(f"  {url.rsplit('@', 1)[-1]} -- is the Pi on and in this network?", file=sys.stderr)
        return 1
    problems += check_disk(args.quiet)

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    if not args.quiet:
        print("\nall series current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
