"""Loading the optional evidence, in one place.

Positioning and the calendar are both optional: the venue's history starts after
the candles do, and the calendar file may simply not have been fetched. Five call
sites construct a `SnapshotBuilder`, and if each decided for itself how to find
these, four of them would eventually be wrong in a different way -- and the
symptom would be a quiet `known: false` rather than an error.

So the decision lives here once: look for the data, use it if it is there, say
nothing if it is not, and never fail because of it. A backtest that cannot find
open interest is a backtest with one fewer factor, not a broken one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from traidingbrain.analysis.positioning import PositioningTimeline
from traidingbrain.config.settings import EngineConfig
from traidingbrain.data.calendar import CALENDAR_FILENAME, MacroCalendar
from traidingbrain.data.derivatives import DerivativesStore
from traidingbrain.data.sentiment import SentimentStore, SentimentTimeline

#: Subdirectory of the data root holding the positioning series.
DERIVATIVES_DIR = "derivatives"

#: One file, because a daily index over eight years is a few thousand rows.
SENTIMENT_FILE = "sentiment.parquet"


@dataclass(frozen=True)
class SnapshotContext:
    """The optional halves of a snapshot, with a line saying what was found.

    The description exists because absence is the failure mode nobody notices.
    A run that silently produced `known: false` on every bar looks exactly like a
    run over a period the venue does not cover, and only one of those is worth
    fixing.
    """

    positioning: PositioningTimeline | None
    calendar: MacroCalendar | None
    sentiment: SentimentTimeline | None
    description: str

    @property
    def is_complete(self) -> bool:
        return all((self.positioning, self.calendar, self.sentiment))


def load_context(symbol: str, frame: pd.DataFrame, config: EngineConfig) -> SnapshotContext:
    """Find whatever positioning and calendar data exists for this symbol."""
    data_root = config.paths.data_dir
    found: list[str] = []
    missing: list[str] = []

    # **Hier steht die Vermischung jetzt im Code statt unsichtbar.**
    #
    # Die gespeicherten Reihen sind BYBIT (BTCUSDT 2021-10-01 00:00 steht bei
    # 16419.749; das Binance-Archiv hat 47921.245 fuer dieselbe Stunde, siehe
    # learn/panel.py:138). Die Kerzen kommen laut config/settings.yaml von
    # BINANCE. Das ist Positionierung der einen Boerse gegen Kurse der anderen.
    #
    # `venue="bybit"` ist darum HARTKODIERT und widerspricht der
    # Konfiguration -- absichtlich. Master-Direktive 03, Phase 1: "Die
    # laufende Vorwaertsstichprobe darf durch diese Schutzmassnahme nicht
    # veraendert werden. Wenn das nicht garantiert werden kann, implementiere
    # Schutz und Tests isoliert, aktiviere ihn aber noch nicht."
    #
    # `venue=config.exchange.name` einzusetzen WAERE die Aktivierung: das
    # Manifest sagt bybit, der Speicher waere binance, und `read` gaebe eine
    # leere Reihe zurueck. Die Positionierung verschwaende damit aus dem
    # Entscheidungspfad -- eine echte Verhaltensaenderung, die andere Trades
    # erzeugt. Sie gehoert in einen geplanten Epochenwechsel, nicht in eine
    # Schutzmassnahme.
    #
    # `on_foreign="legacy"` statt "raise": bricht nicht ab, liefert leer, und
    # der Aufrufer unten berichtet das Fehlen in `missing`.
    store = DerivativesStore(
        data_root / DERIVATIVES_DIR, venue="bybit", on_foreign="legacy"
    )
    open_interest = store.read(symbol, "open_interest")
    account_ratio = store.read(symbol, "account_ratio")

    positioning: PositioningTimeline | None = None
    if not open_interest.empty or not account_ratio.empty:
        positioning = PositioningTimeline(
            frame,
            open_interest if not open_interest.empty else None,
            account_ratio if not account_ratio.empty else None,
        )
        found.append(f"{len(open_interest):,} open-interest readings")
        if not account_ratio.empty:
            found.append(f"{len(account_ratio):,} crowd readings")
    else:
        missing.append(
            f"no positioning data (run scripts/backfill_derivatives.py --symbols {symbol})"
        )

    calendar_path = data_root / CALENDAR_FILENAME
    calendar = MacroCalendar.load(calendar_path)
    # The derived half always exists, so the calendar is never None -- but the
    # fetched half is worth reporting separately, since its absence is silent.
    if calendar_path.exists():
        found.append(f"{len(calendar):,} calendar events")
    else:
        found.append(f"{len(calendar):,} calendar events (rules only)")
        missing.append("no FOMC dates (run scripts/fetch_fomc.py)")

    sentiment_frame = SentimentStore(data_root / SENTIMENT_FILE).read()
    sentiment = SentimentTimeline(sentiment_frame) if not sentiment_frame.empty else None
    if sentiment is not None:
        found.append(f"{len(sentiment_frame):,} sentiment readings")
    else:
        missing.append("no sentiment index (run scripts/backfill_sentiment.py)")

    parts = [", ".join(found) or "nothing"]
    if missing:
        parts.append("; ".join(missing))
    return SnapshotContext(
        positioning=positioning,
        calendar=calendar,
        sentiment=sentiment,
        description=" -- ".join(parts),
    )


def calendar_path(config: EngineConfig) -> Path:
    return config.paths.data_dir / CALENDAR_FILENAME
