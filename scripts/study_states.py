"""Do any of the declared market states predict direction? Five families at once.

    python scripts/study_states.py
    python scripts/study_states.py --symbols BTCUSDT,ETHUSDT --horizons 24,168

Seven strategy families sat open in the register with nothing against them but
"not measured yet". Five of them ask the same question in different words --
*when* should the system act -- and that question has one shape, so it has one
measurement:

| family | state measured here |
|---|---|
| Volatilitaetsausbruch | realised volatility, percentile banded |
| Handelsspannen-Ausbruch | position in the Donchian range |
| VWAP und Tageszeit | hour of day, in session bands |
| Momentum mit Volumen | recent return crossed with relative volume |
| Funding / Relative Value | funding rate, percentile banded |
| Regime-Umschaltung | trend against range, from the regime timeline |

**Why a state cannot be tested by its move size, which is the trap this
project already fell into.** `study_horizon.py` showed the typical hourly move
is 2.5x the toll, and three families still failed -- because a large move is
not a captured move, and the gap is direction. So a state that merely marks
bigger moves marks bigger losses just as readily. What is measured here is the
**signed** outcome of acting long in that state, net of the round trip,
against the same quantity in the state's complement. A significantly negative
cell is a finding too: it says act short.

**The multiple-comparison accounting, stated before the first number.** Six
states, up to three bands each, three horizons: about 54 cells. At 95%
confidence roughly **2.7 of them fire by chance**, so a single interval
excluding zero is not news -- it is the expected yield of asking 54 questions.
The threshold printed is therefore Bonferroni-corrected to the cell count, and
the uncorrected count is printed beside it so the difference is visible rather
than asserted. This project has already shipped and withdrawn five false
findings, and four of them had exactly this shape.

**Intervals come from weekly blocks over all markets together.** Twelve
markets on one day are not independent and an hourly series is not independent
of itself; resampling rows would give an interval several times too narrow.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from traidingbrain.analysis.formulas import donchian_position, historical_volatility
from traidingbrain.analysis.indicators import atr, rolling_percentile_rank
from traidingbrain.config.settings import load_config
from traidingbrain.data.funding import FundingStore
from traidingbrain.data.store import ParquetStore
from traidingbrain.domain.enums import Timeframe
from traidingbrain.domain.market import DEFAULT_SPEC

HOUR_MS = 3_600_000
DAY_MS = 86_400_000

#: Horizons in hours, matching the declared series elsewhere.
HORIZONS: tuple[int, ...] = (24, 72, 168)

#: Lookback for the volatility percentile, in hours. Thirty days: long enough
#: that a band means "quiet or wild for this market", short enough to follow a
#: regime rather than average over years.
VOL_WINDOW = 30 * 24

#: Donchian lookback, in hours. Twenty days, the convention.
RANGE_WINDOW = 20 * 24

#: Relative-volume lookback, in hours.
VOLUME_WINDOW = 7 * 24

#: Warmup before any row is usable. The longest window plus headroom, so no
#: partially warm rolling statistic reaches a cell.
WARMUP = VOL_WINDOW + 48

#: Band edges as quantiles, fitted on the first share of the data and applied
#: to the rest. Boundaries chosen on the rows they are then tested on always
#: find a band that looks good.
BANDS = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
FIT_SHARE = 0.6
BAND_NAMES = ("niedrig", "mittel", "hoch")

#: Observations a cell needs before it is reported with a number.
MIN_CELL = 300

#: Bootstrap draws and block length for the interval.
DRAWS = 2000
BLOCK_DAYS = 7

#: Confidence before correction.
CONFIDENCE = 0.95

#: A cell must reproduce in the other part of the data before it counts.
#:
#: This is not a refinement, it is the test that decided the one candidate
#: this study produced. `atr_pct hoch` fired on both horizons with a monotone
#: band ordering -- structure, not scatter, which is why it was worth chasing.
#: Then: it fails the Bonferroni-corrected threshold on both horizons, and in
#: the *other* 60% of the data the same difference is +0.0664% instead of
#: +0.4198% at 24h and +0.5016% instead of +2.1586% at 168h. Four to six times
#: smaller. A property of one window, not of the market.
#:
#: So every cell is now measured on both parts and must clear both. The cost
#: is that the band edges are fitted on the first part and the first part is
#: then also measured, which is mild leakage -- reported as "in-sample" rather
#: than pretended away, because the comparison that matters is the SIZE of the
#: two effects, and in-sample is the half that flatters itself.
REPLICATE = True

#: Ratio below which a cell is called unreplicated. Half: an effect that
#: shrinks by more than two in the other window is not one effect.
REPLICATION_FLOOR = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", help="Comma-separated. Default: the first four active.")
    parser.add_argument("--horizons", help="Comma-separated hours. Default: 24,72,168.")
    return parser.parse_args()


def toll(slippage_bps: float) -> float:
    """Taker both sides plus slippage: a timed exit is a market order."""
    return 2.0 * float(DEFAULT_SPEC["taker_fee"]) + 2.0 * slippage_bps / 10_000.0


def states(frame: pd.DataFrame, rates: pd.DataFrame | None) -> pd.DataFrame:
    """Every declared state for every hour, from past data only.

    No `shift(-n)` anywhere in this function. Each column is a rolling
    statistic ending at the current bar, which is the property that makes the
    cells below mean anything.
    """
    out = pd.DataFrame(index=frame.index)
    close = frame["close"]

    # Volatilitaetsausbruch: where this hour's realised volatility sits in its
    # own recent distribution. The percentile, not the level, so BTC and SOL
    # are comparable.
    vol = historical_volatility(close, period=VOL_WINDOW // 24)
    out["vola"] = rolling_percentile_rank(vol, VOL_WINDOW)

    # An ATR-based second reading, because a single volatility definition
    # failing is weaker evidence than two failing.
    out["atr_pct"] = rolling_percentile_rank(atr(frame) / close, VOL_WINDOW)

    # Handelsspannen-Ausbruch: 0 at the range low, 1 at the range high.
    out["range_pos"] = donchian_position(frame, period=RANGE_WINDOW)

    # Momentum mit Volumen: the last day's return, and volume against its own
    # recent average. Crossed below rather than averaged, because the family's
    # claim is about the combination.
    out["ret_1d"] = close / close.shift(24) - 1.0
    out["vol_rel"] = frame["volume"] / (frame["volume"].rolling(VOLUME_WINDOW).mean() + 1e-12)

    # VWAP und Tageszeit: the hour itself. Not banded by quantile -- the hour
    # is already a label, and three sessions is the division the family means.
    hour = pd.to_datetime(frame["ts"], unit="ms", utc=True).dt.hour
    out["session"] = np.select(
        [hour < 8, hour < 16], ["asien", "europa"], default="amerika"  # noqa: PLR2004
    )

    # Funding als Information: the last known rate, as a percentile of its own
    # history. Joined backwards with the settlement lag, because a rate is
    # known at the END of its interval.
    if rates is not None and not rates.empty:
        merged = pd.merge_asof(
            frame[["ts"]].sort_values("ts"),
            rates.assign(available=rates["ts"] + 8 * HOUR_MS)
            .sort_values("available")[["available", "rate"]]
            .rename(columns={"available": "ts"}),
            on="ts",
            direction="backward",
        )
        out["funding"] = rolling_percentile_rank(
            merged["rate"].reset_index(drop=True), VOL_WINDOW
        ).to_numpy()
    return out


def forward(opens: np.ndarray, ahead: int) -> np.ndarray:
    """Signed open-to-open return `ahead` bars on, entered one bar after the state.

    One bar later because a state read at a close can only be acted on at the
    next open. Explicit indices rather than slice arithmetic: slices hid an
    off-by-one in the reversal study that compared a candle with itself.
    """
    n = opens.size
    out = np.full(n, np.nan)
    at = np.arange(0, n - 1 - ahead)
    out[at] = opens[at + 1 + ahead] / opens[at + 1] - 1.0
    return out


def two_group_interval(
    inside: np.ndarray, outside: np.ndarray, days_in: np.ndarray, days_out: np.ndarray
) -> tuple[float, float, float]:
    """Difference of means, with an interval from resampling whole weeks.

    Both groups are resampled by week, so the comparison keeps the
    autocorrelation each side has. Returns (difference, low, high).
    """
    if inside.size < MIN_CELL or outside.size < MIN_CELL:
        return float("nan"), float("nan"), float("nan")

    rng = np.random.default_rng(20261005)
    span = BLOCK_DAYS * DAY_MS
    groups_in = [np.flatnonzero(days_in // span == w) for w in np.unique(days_in // span)]
    groups_out = [np.flatnonzero(days_out // span == w) for w in np.unique(days_out // span)]
    if len(groups_in) < 3 or len(groups_out) < 3:  # noqa: PLR2004
        return float("nan"), float("nan"), float("nan")

    diffs = np.empty(DRAWS)
    for draw in range(DRAWS):
        a = np.concatenate([groups_in[i] for i in rng.integers(0, len(groups_in), len(groups_in))])
        b = np.concatenate(
            [groups_out[i] for i in rng.integers(0, len(groups_out), len(groups_out))]
        )
        diffs[draw] = inside[a].mean() - outside[b].mean()
    return (
        float(inside.mean() - outside.mean()),
        float(np.quantile(diffs, 0.025)),
        float(np.quantile(diffs, 0.975)),
    )


def labels_for(name: str, usable: pd.DataFrame, fit: pd.DataFrame) -> pd.Series | None:
    """The band each row falls in for one state, or None when unmeasurable.

    Split out of the reporting loop because it holds every special case: a
    session is already a label, the volume-momentum cross is a conjunction
    rather than a band, and the numeric states are cut on edges fitted earlier
    in the data.
    """
    if name == "vol_momentum":
        if "ret_1d" not in usable or "vol_rel" not in usable:
            return None
        # The family's actual claim: a move WITH volume behind it, not either
        # one alone.
        strong = usable["vol_rel"] > usable["vol_rel"].quantile(1.0 - 1.0 / 3.0)
        labels = pd.Series("ruhig", index=usable.index)
        labels[strong & (usable["ret_1d"] > 0)] = "auf+volumen"
        labels[strong & (usable["ret_1d"] <= 0)] = "ab+volumen"
        return labels

    if name == "session":
        return usable["session"]

    if name not in fit.columns or fit[name].isna().all():
        return None
    edges = np.unique(np.quantile(fit[name].dropna(), BANDS))
    if edges.size < 2:  # noqa: PLR2004 -- a cut needs two edges
        return None
    binned = pd.cut(usable[name], bins=edges, labels=False, include_lowest=True)
    return pd.Series(binned, index=usable.index).map(dict(enumerate(BAND_NAMES)))


def report_horizon(
    usable: pd.DataFrame, fit: pd.DataFrame, *, hours: int, cost: float, names: list[str]
) -> list[str]:
    """Every declared cell for one horizon. Returns the cells excluding zero."""
    column = f"fwd_{hours}"
    net_all = usable[column].to_numpy() - cost
    print(
        f"\n=== {hours}h voraus, {len(usable):,} Stunden, "
        f"unbedingt netto {100 * net_all.mean():+.4f}% ==="
    )

    hits: list[str] = []
    for name in names:
        labels = labels_for(name, usable, fit)
        if labels is None:
            continue
        for band in sorted(set(labels.dropna())):
            mask = (labels == band).to_numpy()
            inside = usable.loc[mask, column].to_numpy() - cost
            outside = usable.loc[~mask, column].to_numpy() - cost
            diff, low, high = two_group_interval(
                inside,
                outside,
                usable.loc[mask, "ts"].to_numpy(dtype="int64"),
                usable.loc[~mask, "ts"].to_numpy(dtype="int64"),
            )
            if np.isnan(diff):
                print(f"  {name:12s} {band!s:14s} n={len(inside):>6,d}  zu wenige")
                continue
            excludes = low > 0 or high < 0
            mark = ""
            if excludes:
                # Before it counts: does the same cell do the same thing in
                # the other part of the data? The one candidate this study
                # produced died here, at a quarter of its size.
                echo = replication(fit, name, band, hours=hours, cost=cost)
                ratio = abs(echo / diff) if diff else 0.0
                if echo * diff > 0 and ratio >= REPLICATION_FLOOR:
                    hits.append(f"{hours}h {name}={band}")
                    mark = f"  <- OHNE NULL und wiederholt ({100 * echo:+.4f}%)"
                else:
                    mark = (
                        f"  <- ohne Null, aber im anderen Fenster "
                        f"{100 * echo:+.4f}% ({ratio:.2f}x) -- kein Befund"
                    )
            print(
                f"  {name:12s} {band!s:14s} n={len(inside):>6,d}  "
                f"netto {100 * inside.mean():+8.4f}%  "
                f"Differenz {100 * diff:+8.4f}% "
                f"[{100 * low:+7.4f}, {100 * high:+7.4f}]{mark}"
            )
    return hits


def replication(fit: pd.DataFrame, name: str, band: object, *, hours: int, cost: float) -> float:
    """The same cell's difference, measured on the other part of the data.

    Returns the plain difference of means without an interval: the question
    here is whether the effect is the same SIZE, and a second interval on a
    cell already selected by the first would be the same mistake twice.

    The band edges were fitted on this part, so this reading flatters itself.
    That makes it the right comparator -- an effect that is smaller on the
    half that favours it is not an effect.
    """
    column = f"fwd_{hours}"
    if column not in fit.columns:
        return 0.0
    usable = fit[fit[column].notna()]
    labels = labels_for(name, usable, fit)
    if labels is None:
        return 0.0
    mask = (labels == band).to_numpy()
    if mask.sum() < MIN_CELL or (~mask).sum() < MIN_CELL:
        return 0.0
    inside = usable.loc[mask, column].to_numpy() - cost
    outside = usable.loc[~mask, column].to_numpy() - cost
    return float(inside.mean() - outside.mean())


def main() -> int:
    args = parse_args()
    config = load_config()
    store = ParquetStore(config.engine.paths.parquet_dir)
    funding_store = FundingStore(config.engine.paths.funding_dir)
    cost = toll(config.engine.simulation.slippage_bps)
    horizons = (
        [int(h) for h in args.horizons.split(",")] if args.horizons else list(HORIZONS)
    )
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",")]
        if args.symbols
        else list(config.engine.symbols.active[:4])
    )

    blocks: list[pd.DataFrame] = []
    for symbol in symbols:
        frame = store.read(symbol, Timeframe.H1)
        if frame.empty:
            print(f"{symbol}: keine H1-Daten")
            continue
        frame = frame.sort_values("ts").reset_index(drop=True)
        rows = funding_store.read(symbol)
        rates = (
            pd.DataFrame({"ts": [r.ts for r in rows], "rate": [r.rate for r in rows]})
            if rows
            else None
        )
        block = states(frame, rates)
        block["ts"] = frame["ts"].to_numpy(dtype="int64")
        opens = frame["open"].to_numpy(dtype="float64")
        for hours in horizons:
            block[f"fwd_{hours}"] = forward(opens, hours)
        blocks.append(block.iloc[WARMUP:])

    if not blocks:
        print("Nichts zu messen.")
        return 1

    data = pd.concat(blocks, ignore_index=True)
    cut = int(FIT_SHARE * len(data))
    fit, test = data.iloc[:cut], data.iloc[cut:].reset_index(drop=True)

    print(f"Maut {100 * cost:.4f}% je Wette (Taker beidseitig + Slippage).")
    print(f"{len(symbols)} Maerkte, {len(test):,} Pruefstunden nach {WARMUP}h Anlauf.")
    print(
        "Bandgrenzen auf den ersten 60% festgelegt, auf den Rest angewandt.\n"
        "Gemessen wird das VORZEICHENBEHAFTETE Ergebnis einer Long-Wette im Zustand,\n"
        "netto, gegen dieselbe Groesse im Gegenstueck. Eine deutlich negative Zelle\n"
        "ist auch ein Befund -- sie sagt: short.\n"
    )

    # Every declared cell, counted before anything is measured, so the
    # correction is a property of the plan and not of what turned up.
    numeric = ["vola", "atr_pct", "range_pos", "ret_1d", "funding"]
    numeric = [c for c in numeric if c in test.columns]
    cells = (len(numeric) * len(BAND_NAMES) + 3 + 3) * len(horizons)
    required = 1.0 - (1.0 - CONFIDENCE) / cells
    print(f"{cells} angemeldete Zellen. Bei {100 * CONFIDENCE:.0f}% feuern davon")
    print(
        f"{cells * (1 - CONFIDENCE):.1f} zufaellig, also ist eine einzelne Zelle ohne Null\n"
        f"kein Befund. Korrigierte Schwelle: {100 * required:.3f}%.\n"
    )

    hits: list[str] = []
    names = [*numeric, "session", "vol_momentum"]
    for hours in horizons:
        usable = test[test[f"fwd_{hours}"].notna()]
        hits += report_horizon(usable, fit, hours=hours, cost=cost, names=names)

    print("\n" + "=" * 78)
    if hits:
        print(f"{len(hits)} von {cells} Zellen schliessen die Null UNKORRIGIERT aus:")
        for hit in hits:
            print(f"  {hit}")
        print(
            f"\nErwartet waren {cells * (1 - CONFIDENCE):.1f} durch Zufall. "
            f"{len(hits)} ist damit\n"
            "kein Befund, sondern die Ausbeute von {cells} Fragen -- ausser die Zahl\n"
            "liegt deutlich darueber UND dieselbe Zelle feuert auf mehreren\n"
            "Horizonten. Sonst gilt: nichts gefunden.".replace("{cells}", str(cells))
        )
    else:
        print(
            f"Keine der {cells} Zellen schliesst die Null aus, auch unkorrigiert nicht.\n"
            "Fuenf Familien ohne Treffer: Volatilitaetsausbruch, Handelsspannen-\n"
            "Ausbruch, Tageszeit, Momentum mit Volumen, Funding als Information."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
