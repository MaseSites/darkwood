"""Daily feature rows across markets, joined so no row knows its own future.

The research order asks for a panel: one row per market per day, features from
what was knowable at the decision time, and a label reaching 24, 72 or 168
hours ahead. It also asks for several things that are easy to say and easy to
get wrong, so each one is a function here rather than a convention:

* **`available_at <= decision_time`.** Every join is backward-looking with a
  declared maximum staleness. A funding rate settles at the END of its
  interval, so the rate stamped 00:00 is knowable at 08:00 -- using it at
  00:00 is a leak of eight hours. `coverage.py` holds the lag per source and
  this module applies it.
* **No future backfill, and missing is not zero.** A forward fill reaches
  backward in time only; a gap stays `NaN` and the row is dropped or the
  column is absent. A zero would be a number the model learns from.
* **Split by timestamp, not by row.** Twelve markets on the same day belong on
  the same side of every boundary. Splitting a flat table by row index puts
  BTC's Tuesday in training and ETH's Tuesday in validation, which leaks
  across the panel through nothing more than cross-sectional correlation.
* **Purging.** A 168-hour label on the last training day reaches seven days
  into validation. Those rows are removed, plus an embargo, because a model
  that saw them has seen the answer.

**The provenance gate, and why it is code.** `scripts/coverage.py` found that
the open interest and account ratio files cannot have come from the script that
fetches them -- they predate what Bybit serves -- and that funding is a mixed
two-venue set. Training on rows whose origin is unknown produces a number that
cannot be interpreted, so `build_panel` refuses those sources unless the caller
passes `allow_unverified=True`, and then stamps the result so no report can
quietly omit it. A comment would have been forgotten by the next run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

DAY_MS = 86_400_000
HOUR_MS = 3_600_000


class Provenance(StrEnum):
    """Whether this project can say where a source's rows came from.

    `CROSS_VENUE` is the state that matters and that a two-value flag would
    have collapsed: the rows are fully accounted for, they are simply from a
    different exchange than the price series. That is a weaker hypothesis, not
    an unusable one, so it passes the gate and lands in the report. `MIXED` is
    worse -- the series contradicts *itself* across markets -- and `UNKNOWN`
    means nobody can say where the numbers came from at all.
    """

    VERIFIED = "belegt"
    CROSS_VENUE = "belegt, andere Boerse als die Preise"
    MIXED = "gemischte Boerse"
    UNKNOWN = "unbekannt"


#: States a feature group may be built from without an explicit override.
#:
#: `CROSS_VENUE` is in here deliberately. On 05.10.2026 the two derivative
#: sources were marked UNKNOWN because their files begin 2021-10-01 while
#: `backfill_derivatives.py` claimed in its docstring that Bybit serves only
#: back to March 2023. `scripts/verify_provenance.py` re-fetched the rows and
#: they match Bybit to the last decimal, 2021 included -- the docstring was
#: wrong, and a wrong sentence in a comment blocked a whole research axis for
#: a day, because nobody re-measures a comment.
USABLE: frozenset[Provenance] = frozenset({Provenance.VERIFIED, Provenance.CROSS_VENUE})


#: Where each source stands, and the lag before a row is knowable.
#:
#: The lags match `scripts/coverage.py`; keeping them in two places invites
#: them to disagree, so this table is the one the models use and that script
#: is what reports it.
SOURCES: dict[str, tuple[Provenance, int, str]] = {
    "ohlcv": (
        Provenance.VERIFIED,
        HOUR_MS,
        "Eigener Abruf ueber data/venue.py; ts ist die Eroeffnung, also erst "
        "ein Intervall spaeter vollstaendig.",
    ),
    "flow": (
        Provenance.VERIFIED,
        HOUR_MS,
        "backfill_flow.py gegen eine Live-Kerze geprueft (BTCUSDT 1h: Volumen "
        "3322.009, taker_buy_base 1626.267).",
    ),
    "sentiment": (
        Provenance.VERIFIED,
        DAY_MS,
        "Eigener Abruf bei api.alternative.me/fng/. Veroeffentlichungszeit "
        "nicht dokumentiert, daher ein Tag konservativ. Teilweise selbst "
        "preis- und volumenabhaengig -- kein reines Nicht-Preis-Merkmal.",
    ),
    "onchain": (
        Provenance.VERIFIED,
        DAY_MS,
        "Coin Metrics Community, eigener Abruf mit Pruefsumme und Roharchiv. "
        "Taegliche Kettenaktivitaet und Boersen-Zu-/Abfluesse, 9-11.8 Jahre je "
        "Markt. Verfuegbarkeit: ein voller Tag nach der Beobachtung -- die "
        "`status-time` des Dienstes ist eine Revalidierungszeit und keine "
        "Verfuegbarkeitszeit, was eine erste Fassung dieses Moduls falsch "
        "machte. Lizenz CC BY-NC 4.0: Forschung ja, kommerziell nicht ungeprueft.",
    ),
    "stablecoins": (
        Provenance.VERIFIED,
        DAY_MS,
        "DefiLlama, eigener Abruf. Stablecoin-Umlauf taeglich ab 2017-11-29. "
        "Angebot und USD-Bewertung sind getrennte Felder und werden getrennt "
        "gehalten; `totalUnreleased` wird verworfen, es meldet Billionen.",
    ),
    "funding": (
        Provenance.MIXED,
        8 * HOUR_MS,
        "BTC/ETH/SOL/XRP beginnen 2023-01-01 mit 11 Rasterabweichungen, die "
        "anderen acht 2020 mit je ~3.300: zwei verschiedene Boersen in einem "
        "Datensatz. Zusaetzlich BNBUSDT mit 49,6% exakten Nullen.",
    ),
    "open_interest": (
        Provenance.CROSS_VENUE,
        0,
        "Bybit linear, nachgemessen: Bybit liefert 16419.749 fuer BTCUSDT am "
        "2021-10-01 00:00 und genau das steht gespeichert. Gegengeprueft gegen "
        "das Binance-Archiv, das 47921.245 fuer dieselbe Stunde hat -- zwei "
        "Boersen verschiedener Groesse, nicht zwei Lesungen einer. Die Preise "
        "kommen laut config/settings.yaml von BINANCE, also ist das "
        "Positionierung der einen gegen Kurse der anderen Boerse.",
    ),
    "account_ratio": (
        Provenance.CROSS_VENUE,
        0,
        "Wie open_interest, dieselbe Pruefung. Die fehlende "
        "Vier-Dezimalstellen-Markierung bei BTC war echt und hatte eine "
        "Ursache: 35 Zeilen am Ende trugen sechs Dezimalstellen und "
        "widersprachen Bybit; sie liegen jetzt in data/quarantine/.",
    ),
}

#: Which sources each declared feature group needs. The order fixes these four
#: and the comparison is only meaningful if the groups are nested.
GROUPS: dict[str, tuple[str, ...]] = {
    "P": ("ohlcv",),
    "P+D": ("ohlcv", "open_interest", "account_ratio", "funding"),
    "P+D+M": ("ohlcv", "open_interest", "account_ratio", "funding", "macro"),
    "P+D+M+O": ("ohlcv", "open_interest", "account_ratio", "funding", "macro", "onchain"),
    # The axis the exhausted map does not cover, isolated from the derivative
    # sources so a difference cannot be attributed to the wrong one.
    "P+O": ("ohlcv", "onchain", "stablecoins"),
}

#: Lookbacks in days for the price baseline, as the order names them.
RETURN_DAYS: tuple[int, ...] = (1, 7, 28)

#: Window for realised volatility, in days.
VOL_DAYS = 28

#: Days of history a row needs before its features are complete. The longest
#: lookback plus the volatility window, so an incomplete rolling statistic
#: never reaches a model.
WARMUP_DAYS = max(RETURN_DAYS) + VOL_DAYS


@dataclass(frozen=True, slots=True)
class Panel:
    """Feature rows, labels and the provenance of what built them."""

    frame: pd.DataFrame
    features: list[str]
    horizon_hours: int
    group: str
    unverified: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def trustworthy(self) -> bool:
        return not self.unverified

    def describe(self) -> str:
        markets = self.frame["market"].nunique() if "market" in self.frame else 0
        days = self.frame["ts"].nunique() if "ts" in self.frame else 0
        stamp = (
            "HERKUNFT UNGEKLAERT: " + ", ".join(self.unverified)
            if self.unverified
            else "Herkunft aller Quellen belegt"
        )
        return (
            f"{self.group}, {self.horizon_hours}h: {len(self.frame):,} Zeilen, "
            f"{markets} Maerkte, {days} Tage, {len(self.features)} Merkmale. {stamp}"
        )


def check_provenance(
    group: str, *, allow_unverified: bool
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Which of a group's sources are not accounted for, and what is known.

    Raises unless the caller has explicitly accepted unverified data. The
    exception names the sources and points at the register, because "provenance
    failed" without the list is an error message nobody can act on.
    """
    needed = GROUPS.get(group)
    if needed is None:
        raise ValueError(f"Merkmalsgruppe '{group}' ist nicht angemeldet: {sorted(GROUPS)}")

    suspect: list[str] = []
    notes: list[str] = []
    for source in needed:
        entry = SOURCES.get(source)
        if entry is None:
            # macro and onchain have no connector yet; that is a different
            # problem from unknown provenance and is reported as absence.
            suspect.append(f"{source} (kein Connector)")
            continue
        state, _, note = entry
        if state not in USABLE:
            suspect.append(f"{source} ({state})")
        if state is not Provenance.VERIFIED:
            # A cross-venue source passes the gate and still earns a line in
            # the report: it is a real caveat about what the model can mean,
            # not a reason to refuse the measurement.
            notes.append(f"{source}: {note}")

    if suspect and not allow_unverified:
        raise ValueError(
            f"Gruppe {group} braucht Quellen ohne belegte Herkunft: {', '.join(suspect)}.\n"
            f"Das Register steht in scripts/coverage.py. Entweder die Herkunft klaeren\n"
            f"oder allow_unverified=True setzen -- dann traegt jedes Ergebnis den Stempel."
        )
    return tuple(suspect), tuple(notes)


def daily_prices(frame: pd.DataFrame) -> pd.DataFrame:
    """Hourly candles reduced to one decision point a day, at 00:00 UTC.

    The row for day D carries the OPEN of the 00:00 candle, which is the first
    price a decision taken at the end of D-1 could actually reach. Taking the
    close of D-1 instead would price an entry at a level already in the past --
    the same mistake `study_horizon.py` documents and avoids.
    """
    out = frame.copy()
    out["ts"] = out["ts"].astype("int64")
    out["day"] = (out["ts"] // DAY_MS) * DAY_MS
    midnight = out[out["ts"] == out["day"]]
    if midnight.empty:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    return (
        midnight.drop_duplicates(subset="day", keep="first")
        .rename(columns={"day": "decision_ms"})
        .loc[:, ["decision_ms", "open", "high", "low", "close", "volume"]]
        .sort_values("decision_ms")
        .reset_index(drop=True)
    )


def price_features(daily: pd.DataFrame) -> pd.DataFrame:
    """Group P: returns over 1/7/28 days and realised volatility.

    Every statistic is backward-looking by construction -- `shift(n)` reaches
    into the past, and the rolling window ends at the current row. There is no
    `shift(-n)` in this function, which is the property that matters.
    """
    out = daily.copy()
    opens = out["open"]
    for days in RETURN_DAYS:
        out[f"%ret_{days}d"] = opens / opens.shift(days) - 1.0

    step = opens.pct_change()
    out["%vol_28d"] = step.rolling(VOL_DAYS).std()
    # Volatility of the last week against the last month: a regime reading
    # that needs no threshold and no fitted parameter.
    out["%vol_ratio"] = step.rolling(7).std() / (step.rolling(VOL_DAYS).std() + 1e-12)
    out["%range_1d"] = (out["high"] - out["low"]) / out["open"]
    out["%volume_ratio"] = out["volume"] / (out["volume"].rolling(VOL_DAYS).mean() + 1e-12)
    return out


def as_of(
    base: pd.DataFrame,
    other: pd.DataFrame,
    *,
    column: str,
    name: str,
    lag_ms: int,
    max_stale_ms: int,
) -> pd.DataFrame:
    """Join `other` onto `base` backwards, respecting the source's lag.

    The row's own timestamp is pushed forward by `lag_ms` before matching, so a
    funding rate settling at the end of its interval cannot be read at the
    start of it. `max_stale_ms` bounds how old a matched value may be: without
    it, a series that stopped two years ago keeps supplying its last value
    forever, which looks like data and is not.
    """
    if other.empty or column not in other.columns:
        return base

    right = other.copy()
    right["ts"] = right["ts"].astype("int64")
    right["available_ms"] = right["ts"] + lag_ms
    right = right.sort_values("available_ms")[["available_ms", column]].rename(
        columns={column: name}
    )

    merged = pd.merge_asof(
        base.sort_values("decision_ms"),
        right,
        left_on="decision_ms",
        right_on="available_ms",
        direction="backward",
        allow_exact_matches=True,
    )
    stale = merged["decision_ms"] - merged["available_ms"] > max_stale_ms
    merged.loc[stale, name] = np.nan
    return merged.drop(columns=["available_ms"])


def label(daily: pd.DataFrame, *, horizon_hours: int) -> pd.Series:
    """Forward return from this row's entry to `horizon_hours` later.

    Open to open: the entry is the 00:00 open of day D and the exit is the
    00:00 open of the day the horizon lands on. Both are prices a decision made
    before D could reach.

    This is a *direction* label and not a trade result. The order is explicit
    that the two must not be mixed, and `audit/ZIELRECHNUNG.md` section 2
    measures how far apart they are: barrier labels and sign labels disagree on
    29-33% of the same candles.
    """
    steps = horizon_hours * HOUR_MS // DAY_MS
    if steps < 1:
        raise ValueError(f"Horizont {horizon_hours}h ist kuerzer als eine Tageszeile.")
    return daily["open"].shift(-steps) / daily["open"] - 1.0


@dataclass
class Fold:
    """One walk-forward split, by timestamp, purged and embargoed."""

    train: np.ndarray
    validate: np.ndarray
    boundary_ms: int
    purged: int = 0
    embargoed: int = 0
    note: str = ""


def walk_forward(
    stamps: np.ndarray, *, folds: int, horizon_hours: int, embargo_days: int = 1
) -> list[Fold]:
    """Expanding-window folds over unique timestamps, with purging.

    Boundaries fall on timestamps, never on rows, so every market's Tuesday
    lands on the same side. Training rows whose label window crosses the
    boundary are purged; `embargo_days` more are dropped after it, because a
    row just before the boundary shares most of its path with one just after.
    """
    unique = np.unique(stamps)
    if unique.size < folds + 1:
        raise ValueError(f"{unique.size} Zeitpunkte reichen nicht fuer {folds} Folds.")

    horizon_ms = horizon_hours * HOUR_MS
    embargo_ms = embargo_days * DAY_MS
    edges = np.linspace(0, unique.size, folds + 2).astype(int)[1:]

    out: list[Fold] = []
    for index in range(folds):
        split = unique[edges[index] - 1]
        end = unique[edges[index + 1] - 1]

        # A training row is usable only if its own label closes before the
        # boundary. This is the purge, and it is why a 168h horizon loses a
        # week of training data at every fold.
        train_mask = (stamps <= split) & (stamps + horizon_ms <= split)
        dropped = int(((stamps <= split) & (stamps + horizon_ms > split)).sum())

        validate_mask = (stamps > split + embargo_ms) & (stamps <= end)
        held = int(((stamps > split) & (stamps <= split + embargo_ms)).sum())

        if not train_mask.any() or not validate_mask.any():
            continue
        out.append(
            Fold(
                train=np.flatnonzero(train_mask),
                validate=np.flatnonzero(validate_mask),
                boundary_ms=int(split),
                purged=dropped,
                embargoed=held,
                note=f"Fold {index + 1}/{folds}",
            )
        )
    if not out:
        raise ValueError("Kein Fold hat nach Purging und Embargo noch Daten.")
    return out


def build_panel(
    *,
    markets: list[str],
    group: str,
    horizon_hours: int,
    read_ohlcv: object,
    read_extra: object | None = None,
    allow_unverified: bool = False,
    max_stale_days: int = 3,
) -> Panel:
    """Assemble the panel for one group and horizon.

    `read_ohlcv(market)` returns hourly candles; `read_extra(market, source)`
    returns a two-column frame for a non-price source, or an empty one. Passed
    in rather than imported so a test can supply fixtures without a data
    directory, which is the only way the leak tests can be fast.
    """
    unverified, notes = check_provenance(group, allow_unverified=allow_unverified)
    needed = GROUPS[group]
    max_stale_ms = max_stale_days * DAY_MS

    blocks: list[pd.DataFrame] = []
    for market in markets:
        candles = read_ohlcv(market)  # type: ignore[operator]
        if candles is None or candles.empty:
            continue
        daily = daily_prices(candles)
        if len(daily) < WARMUP_DAYS + 2:
            continue
        block = price_features(daily)

        if read_extra is not None:
            for source in needed:
                if source == "ohlcv":
                    continue
                entry = SOURCES.get(source)
                if entry is None:
                    continue
                _, lag_ms, _ = entry
                extra = read_extra(market, source)  # type: ignore[operator]
                if extra is None or extra.empty:
                    continue
                # Every numeric column the source offers, not just the first.
                # An on-chain fetch carries active addresses, transaction
                # count, supply, market cap, issuance and both exchange flow
                # directions, and taking one of them would discard the
                # measurement this group exists for.
                skip = {"ts", "available_ms", "validated_ms", "status", "sha256", "fetched_ms"}
                values = [
                    c
                    for c in extra.columns
                    if c not in skip and pd.api.types.is_numeric_dtype(extra[c])
                ]
                for value in values:
                    name = f"%{source}_{value}"
                    block = as_of(
                        block,
                        extra,
                        column=value,
                        name=name,
                        lag_ms=lag_ms,
                        max_stale_ms=max_stale_ms,
                    )
                    # Change rather than level: a supply of 19.5 million means
                    # nothing across markets or across years, its weekly change
                    # does. Computed after the join so it uses only joined,
                    # lag-respecting values.
                    if name in block.columns:
                        block[f"{name}_chg7"] = block[name] / block[name].shift(7) - 1.0
                        # And the level itself is dropped: it trends over a
                        # decade, so a model fitted on early folds reads a
                        # later level as an extreme it has never seen.
                        block = block.drop(columns=[name])

        block["target"] = label(block, horizon_hours=horizon_hours)
        block["market"] = market
        block = block.rename(columns={"decision_ms": "ts"})
        blocks.append(block.iloc[WARMUP_DAYS:])

    if not blocks:
        raise ValueError(f"Keine Marktdaten fuer {markets}.")

    frame = pd.concat(blocks, ignore_index=True)
    features = sorted(c for c in frame.columns if c.startswith("%"))

    # Missing stays missing. Rows without a complete feature vector or without
    # a label are dropped rather than imputed, because an imputed value fitted
    # on the whole panel is itself a leak.
    frame = frame.dropna(subset=[*features, "target"]).reset_index(drop=True)
    frame = frame.sort_values(["ts", "market"]).reset_index(drop=True)

    return Panel(
        frame=frame,
        features=features,
        horizon_hours=horizon_hours,
        group=group,
        unverified=unverified,
        notes=notes,
    )


def common_window(panels: list[Panel]) -> list[Panel]:
    """Restrict several panels to the rows every one of them has.

    The order requires feature groups be compared on a common observation
    window. Without this, a group that adds a source starting in 2023 is
    measured on a different era than the baseline, and the difference reads as
    information when it is coverage.
    """
    if not panels:
        return []
    keys = None
    for panel in panels:
        own = set(zip(panel.frame["ts"], panel.frame["market"], strict=True))
        keys = own if keys is None else (keys & own)
    if not keys:
        raise ValueError("Die Gruppen haben kein gemeinsames Beobachtungsfenster.")

    out: list[Panel] = []
    for panel in panels:
        mask = [
            (ts, market) in keys
            for ts, market in zip(panel.frame["ts"], panel.frame["market"], strict=True)
        ]
        trimmed = panel.frame.loc[mask].reset_index(drop=True)
        out.append(
            Panel(
                frame=trimmed,
                features=panel.features,
                horizon_hours=panel.horizon_hours,
                group=panel.group,
                unverified=panel.unverified,
                notes=(
                    *panel.notes,
                    f"auf gemeinsames Fenster beschnitten: {len(trimmed):,} Zeilen",
                ),
            )
        )
    return out
