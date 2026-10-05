"""Every value that crosses from a tool argument into a process, checked here.

The order is explicit: no arbitrary shell commands and no free file paths from
tool arguments. That is not satisfied by passing a list to `subprocess.run`
instead of a string -- a list stops shell injection, but it does nothing about
a `--strategy` argument naming a file outside the project, or a pair name that
makes a request to a market nobody configured.

So the rule here is **allowlist, not sanitise**. Nothing is cleaned up and
passed on; a value either matches something the project already declares or it
is refused. The allowlists come from the configuration and the strategy
directory, so they cannot drift from what actually exists.

**Why every function raises instead of returning a default.** A validator that
silently substitutes a safe value turns an attack into a surprising result,
and a caller cannot tell the difference between "I asked for BTC" and "I asked
for something refused and got BTC". `ArgumentRefusedError` carries the reason to the tool
caller, which is the only useful outcome.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

#: Freqtrade's own pair spelling: BASE/QUOTE, upper case, optional settle
#: suffix for futures. Deliberately narrow -- this is a gate, not a parser.
PAIR = re.compile(r"^[A-Z0-9]{2,15}/[A-Z0-9]{2,10}(?::[A-Z0-9]{2,10})?$")

#: A timerange as Freqtrade accepts it: YYYYMMDD, either side optional.
#: `20250301-`, `-20261001` and `20250301-20261001` are all valid.
TIMERANGE = re.compile(r"^(\d{8})?-(\d{8})?$|^(\d{8})$")

#: Python identifier rules, which is what a strategy class name must be. The
#: name is additionally checked against the strategies actually on disk, so
#: this only rejects the obviously malformed early with a clearer message.
CLASS_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

#: Timeframes this project stores. Not every timeframe Freqtrade supports --
#: only the ones the configuration names, because asking for one we have no
#: data for is a slow way to learn nothing.
TIMEFRAMES: frozenset[str] = frozenset({"1m", "5m", "15m", "1h", "4h", "1d", "1w"})

#: Horizons the research order fixes: 24, 72 and 168 hours. Registered as an
#: allowlist so an experiment cannot quietly be run on a fourth horizon and
#: then be compared against the three that were declared in advance.
HORIZON_HOURS: frozenset[int] = frozenset({24, 72, 168})

#: Feature groups the research order fixes, in order of inclusion.
FEATURE_GROUPS: tuple[str, ...] = ("P", "P+D", "P+D+M", "P+D+M+O")

#: Models the research order permits this round. No deep learning, no RL.
MODELS: frozenset[str] = frozenset({"logistic", "lightgbm"})

#: Most markets one call may ask for. The limit exists because the order caps
#: the first research round at five hours of compute and a request for every
#: market at every horizon is how that budget disappears in one call.
MAX_PAIRS = 12

#: Earliest date any argument may name. Before this there is no perpetual
#: market to speak of, so a date here is a typo rather than a request.
EPOCH = datetime(2017, 1, 1, tzinfo=UTC)


class ArgumentRefusedError(ValueError):
    """An argument was not on an allowlist. Carries the reason to the caller.

    Named for the project convention every other exception here follows --
    `UnsupportedVenueError`, `ExecutionRefusedError` and nine more. A bare
    `Refused` read better in isolation and worse in a traceback beside them.
    """


def pair(value: str, *, allowed: frozenset[str]) -> str:
    """One market, matching the spelling rules and the configured whitelist."""
    if not isinstance(value, str):
        raise ArgumentRefusedError(f"Marktname muss Text sein, nicht {type(value).__name__}.")
    candidate = value.strip().upper()
    if not PAIR.match(candidate):
        raise ArgumentRefusedError(f"'{value}' ist keine Marktschreibweise wie BTC/USDT.")
    if candidate not in allowed:
        listing = ", ".join(sorted(allowed))
        raise ArgumentRefusedError(
            f"'{candidate}' steht nicht in der Whitelist. Erlaubt: {listing}"
        )
    return candidate


def pairs(values: list[str] | None, *, allowed: frozenset[str]) -> list[str]:
    """Several markets, deduplicated, order preserved, count capped.

    An empty or absent list means "all configured", which is the useful
    default and keeps callers from having to restate the whitelist.
    """
    if not values:
        return sorted(allowed)
    if len(values) > MAX_PAIRS:
        raise ArgumentRefusedError(
            f"Hoechstens {MAX_PAIRS} Maerkte pro Aufruf, nicht {len(values)}."
        )

    out: list[str] = []
    for value in values:
        checked = pair(value, allowed=allowed)
        if checked not in out:
            out.append(checked)
    return out


def timeframe(value: str) -> str:
    if value not in TIMEFRAMES:
        listing = ", ".join(sorted(TIMEFRAMES))
        raise ArgumentRefusedError(f"'{value}' ist keine bekannte Zeitebene. Erlaubt: {listing}")
    return value


def timeframes(values: list[str] | None, *, default: list[str]) -> list[str]:
    if not values:
        return list(default)
    out: list[str] = []
    for value in values:
        checked = timeframe(value)
        if checked not in out:
            out.append(checked)
    return out


def timerange(value: str | None) -> str | None:
    """A date window, checked for shape and for being a real date.

    The regex alone accepts `20250231`, which is not a date. `strptime` is
    what actually settles it, and getting that wrong means a job runs for
    minutes before Freqtrade rejects the argument.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not TIMERANGE.match(value.strip()):
        raise ArgumentRefusedError(f"'{value}' ist kein Zeitraum wie 20250301-20261001.")

    text = value.strip()
    for part in text.split("-"):
        if not part:
            continue
        try:
            moment = datetime.strptime(part, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError as exc:
            raise ArgumentRefusedError(f"'{part}' ist kein gueltiges Datum: {exc}") from exc
        if moment < EPOCH:
            raise ArgumentRefusedError(
                f"'{part}' liegt vor {EPOCH:%Y-%m-%d}; dort gibt es keine Daten."
            )

    if "-" in text:
        start, _, end = text.partition("-")
        if start and end and start >= end:
            raise ArgumentRefusedError(f"Zeitraum laeuft rueckwaerts: {start} bis {end}.")
    return text


def strategy(value: str, *, directory: Path) -> str:
    """A strategy class name that exists as a file in the strategies directory.

    Checked against the directory rather than against a hard-coded list, so
    adding a strategy file is all it takes -- and so a name that is not a file
    in that one directory cannot be reached at all. This is the check that
    makes `--strategy` incapable of pointing somewhere else: the name never
    becomes a path, it is only ever compared against names found by scanning.
    """
    if not isinstance(value, str) or not CLASS_NAME.match(value):
        raise ArgumentRefusedError(f"'{value}' ist kein Klassenname.")
    available = known_strategies(directory)
    if value not in available:
        listing = ", ".join(sorted(available)) or "(keine gefunden)"
        raise ArgumentRefusedError(f"Strategie '{value}' gibt es nicht. Vorhanden: {listing}")
    return value


def known_strategies(directory: Path) -> frozenset[str]:
    """Class names of the .py files directly in the strategies directory.

    Deliberately non-recursive and deliberately by filename: Freqtrade
    resolves a strategy by class name and finds it by scanning this
    directory, so the filename stem is the name to offer. Reading the class
    out of the file would mean parsing it, and a mismatch between stem and
    class is a project error worth surfacing rather than papering over.
    """
    if not directory.is_dir():
        return frozenset()
    return frozenset(
        path.stem
        for path in directory.glob("*.py")
        if path.is_file() and not path.stem.startswith("_")
    )


def horizon(value: int) -> int:
    if value not in HORIZON_HOURS:
        listing = ", ".join(str(h) for h in sorted(HORIZON_HOURS))
        raise ArgumentRefusedError(
            f"Horizont {value}h ist nicht angemeldet. Festgelegt: {listing} Stunden."
        )
    return value


def feature_group(value: str) -> str:
    if value not in FEATURE_GROUPS:
        listing = ", ".join(FEATURE_GROUPS)
        raise ArgumentRefusedError(
            f"Merkmalsgruppe '{value}' ist nicht angemeldet. Festgelegt: {listing}"
        )
    return value


def model(value: str) -> str:
    if value not in MODELS:
        listing = ", ".join(sorted(MODELS))
        raise ArgumentRefusedError(
            f"Modell '{value}' ist in dieser Runde nicht zugelassen. Erlaubt: {listing}"
        )
    return value


def job_id(value: str) -> str:
    """A job identifier, which must look like one this adapter issued.

    Checked because a job id is used to look up a record and read its log, and
    an unchecked one is the file-path argument the order rules out.
    """
    if not isinstance(value, str) or not re.match(r"^[a-z]+-[0-9a-f]{12}$", value):
        raise ArgumentRefusedError(f"'{value}' ist keine Job-Kennung dieses Adapters.")
    return value


def whitelist_from_config(*paths: Path) -> frozenset[str]:
    """The pair whitelist, read from the merged Freqtrade configuration.

    Read from the files rather than taken as an argument so the allowlist and
    the thing Freqtrade will actually trade cannot disagree. Later files win,
    which is Freqtrade's own merge order.
    """
    found: frozenset[str] = frozenset()
    for path in paths:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ArgumentRefusedError(
                f"Konfiguration {path.name} ist nicht lesbar: {exc}"
            ) from exc
        listed = data.get("exchange", {}).get("pair_whitelist")
        if listed:
            found = frozenset(str(p).upper() for p in listed)
    if not found:
        raise ArgumentRefusedError("Keine pair_whitelist in der Konfiguration gefunden.")
    return found
