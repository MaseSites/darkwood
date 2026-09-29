"""Looking back at a closed trade.

The specification asks for this, and the risk in building it is specific: a
post-mortem on a losing trade will always find something to blame. At a 35% win
rate the system loses roughly two trades in three, and if each loss produces a
change, the rules chase noise until nothing is left of them.

So three things are deliberate here.

**A loss is not evidence of a mistake.** The review is asked to distinguish four
cases -- the read was wrong, the read was right and the timing was wrong, the read
was right and the market changed, and nothing was wrong -- and the fourth is the
most common. A review that never returns "this worked as designed and lost" is a
review that is confabulating.

**Suggestions go into a queue and are never applied.** A system that rewrites its
own trading rules from its own post-mortems is precisely what the
confirm-before-execute rule exists to prevent, and it would do it invisibly.

**Nothing is reviewed until there is enough to review.** Individual trades are
noise. The aggregate view -- what the reviews say *collectively*, across dozens of
trades -- is where a real pattern would show up, and it is reported separately from
any single one.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from traidingbrain.brain import prompt as prompts
from traidingbrain.domain.enums import ExitReason, Factor
from traidingbrain.domain.snapshot import MarketSnapshot
from traidingbrain.domain.verdict import PostTradeReview
from traidingbrain.sim.broker import Fill

#: Reviews needed before the aggregate is worth reading. Below this, a pattern in
#: the reviews is a pattern in three coin flips.
MIN_REVIEWS_FOR_A_PATTERN = 25

#: Below this share of losses judged blameless, the reviews are finding faults
#: that are not there. At a 35% win rate most losses are a correct process.
MIN_BLAMELESS_SHARE = 0.3

#: A trade that goes wrong inside this many bars was mistimed rather than misread.
QUICK_LOSS_BARS = 2

HOUR_MS = 3_600_000

_DDL = """
CREATE TABLE IF NOT EXISTS reviews (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    proposal_id   TEXT NOT NULL,
    snapshot_hash TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    r_multiple    REAL NOT NULL,
    exit_reason   TEXT NOT NULL,
    payload       TEXT NOT NULL,
    created_ts    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reviews_by_symbol ON reviews (symbol);

-- Suggestions live here and are read by a person. Nothing in this system reads
-- this table back to change its own behaviour, and nothing should.
CREATE TABLE IF NOT EXISTS suggestions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id   INTEGER NOT NULL,
    text        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_ts  INTEGER NOT NULL
);
"""


class Reviewer(Protocol):
    def review(
        self, fill: Fill, snapshot_at_entry: MarketSnapshot, *, bars_held: int
    ) -> PostTradeReview: ...


@dataclass(frozen=True)
class StoredReview:
    id: int
    proposal_id: str
    symbol: str
    r_multiple: float
    exit_reason: str
    review: PostTradeReview
    created_ts: int


class ReviewQueue:
    """Reviews, and the suggestions they produce, kept for a person to read."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn:
            conn.executescript(_DDL)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def add(self, fill: Fill, review: PostTradeReview) -> int:
        now = int(datetime.now(tz=UTC).timestamp() * 1000)
        with closing(self._connect()) as conn:
            cursor = conn.execute(
                "INSERT INTO reviews "
                "(proposal_id, snapshot_hash, symbol, r_multiple, exit_reason, payload, created_ts)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    fill.proposal_id,
                    fill.snapshot_hash,
                    "",
                    fill.r_multiple,
                    fill.reason.value,
                    review.model_dump_json(),
                    now,
                ),
            )
            review_id = int(cursor.lastrowid or 0)
            conn.execute(
                "INSERT INTO suggestions (review_id, text, created_ts) VALUES (?, ?, ?)",
                (review_id, review.system_update_suggestion, now),
            )
        return review_id

    def all(self) -> list[StoredReview]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, proposal_id, symbol, r_multiple, exit_reason, payload, created_ts "
                "FROM reviews ORDER BY created_ts"
            ).fetchall()
        return [
            StoredReview(
                id=row[0],
                proposal_id=row[1],
                symbol=row[2],
                r_multiple=row[3],
                exit_reason=row[4],
                review=PostTradeReview.model_validate(json.loads(row[5])),
                created_ts=row[6],
            )
            for row in rows
        ]

    def open_suggestions(self) -> list[tuple[int, str]]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT id, text FROM suggestions WHERE status = 'open' ORDER BY created_ts DESC"
            ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def resolve_suggestion(self, suggestion_id: int, status: str) -> None:
        """Marked by a person, after they decided. Never by the system."""
        with closing(self._connect()) as conn:
            conn.execute("UPDATE suggestions SET status = ? WHERE id = ?", (status, suggestion_id))

    def count(self) -> int:
        with closing(self._connect()) as conn:
            return int(conn.execute("SELECT count(*) FROM reviews").fetchone()[0])


@dataclass
class ReviewPattern:
    """What the reviews say together, which is the only level worth acting on."""

    total: int
    losses: int
    nothing_was_wrong: int
    timing_blamed: int
    regime_blamed: int
    factor_blamed: dict[str, int]

    @property
    def has_enough(self) -> bool:
        return self.total >= MIN_REVIEWS_FOR_A_PATTERN

    def report(self) -> str:
        if not self.has_enough:
            return (
                f"  {self.total} reviews -- too few to read anything into "
                f"(need {MIN_REVIEWS_FOR_A_PATTERN}). Individual post-mortems are noise."
            )

        lines = [f"  {self.total} reviews, {self.losses} of them losses"]
        share = self.nothing_was_wrong / self.losses if self.losses else 0.0
        lines.append(
            f"    {self.nothing_was_wrong} losses ({share:.0%}) judged to be a correct "
            f"process losing money, which at this win rate is the expected outcome"
        )
        if share < MIN_BLAMELESS_SHARE and self.losses >= MIN_REVIEWS_FOR_A_PATTERN:
            lines.append(
                "    NOTE: fewer than a third of losses are being called correct. A review "
                "that almost always finds a fault is confabulating, not analysing."
            )
        lines.append(f"    timing blamed {self.timing_blamed}, regime blamed {self.regime_blamed}")
        if self.factor_blamed:
            ranked = sorted(self.factor_blamed.items(), key=lambda kv: -kv[1])
            lines.append(
                "    factors blamed: " + ", ".join(f"{name} {count}" for name, count in ranked)
            )
        return "\n".join(lines)


def find_pattern(reviews: list[StoredReview]) -> ReviewPattern:
    losses = [r for r in reviews if r.r_multiple < 0]
    blamed: dict[str, int] = {}
    for stored in reviews:
        factor = stored.review.failing_factor
        if factor is not None:
            blamed[factor.value] = blamed.get(factor.value, 0) + 1

    return ReviewPattern(
        total=len(reviews),
        losses=len(losses),
        nothing_was_wrong=sum(
            1
            for r in losses
            if r.review.failing_factor is None
            and not r.review.timing_was_wrong
            and not r.review.regime_was_misread
        ),
        timing_blamed=sum(1 for r in reviews if r.review.timing_was_wrong),
        regime_blamed=sum(1 for r in reviews if r.review.regime_was_misread),
        factor_blamed=blamed,
    )


class RuleBasedReviewer:
    """A reviewer with no model behind it.

    Exists so the whole post-trade path can be exercised offline, and because it
    is a useful control: if the model's reviews are not noticeably more insightful
    than these, the model is not adding anything to this part of the system either.
    """

    def review(
        self, fill: Fill, snapshot_at_entry: MarketSnapshot, *, bars_held: int
    ) -> PostTradeReview:
        won = fill.r_multiple > 0
        quick = bars_held <= QUICK_LOSS_BARS

        if won:
            evaluation = f"WIN {fill.r_multiple:+.2f}R"
            reason = "the target was reached before the stop"
            lesson = "nothing to change; a plan that worked"
        elif fill.reason is ExitReason.LIQUIDATION:
            evaluation = "LIQUIDATED"
            reason = "the exchange closed the position before the stop was reached"
            lesson = "leverage was too high for this stop distance"
        elif quick:
            evaluation = f"LOSS {fill.r_multiple:+.2f}R, stopped quickly"
            reason = "price went against the entry almost immediately"
            lesson = "an entry that is wrong within two bars is usually a timing problem"
        else:
            evaluation = f"LOSS {fill.r_multiple:+.2f}R"
            reason = "the stop was reached after the position had room to work"
            lesson = "nothing specific; a correct process loses most of the time at this win rate"

        return PostTradeReview(
            schema_version=1,
            trade_evaluation=evaluation,
            main_reason=reason,
            # A rule cannot tell which factor misled. Claiming one would be exactly
            # the confabulation this module warns about.
            failing_factor=Factor.STRUCTURE if fill.reason is ExitReason.LIQUIDATION else None,
            timing_was_wrong=quick and not won,
            regime_was_misread=False,
            lesson=lesson,
            system_update_suggestion=(
                "no change suggested" if won or not quick else "consider a wider entry window"
            ),
        )


def review_prompt(
    snapshot: MarketSnapshot, fill: Fill, bars_held: int
) -> tuple[list[dict[str, Any]], str]:
    """The two halves of a post-trade request, ready to send.

    A separate prompt from the pre-trade one, not a mode flag on it: two prompts
    means two cache prefixes, two smaller schemas, and evaluations that do not
    interfere with each other.
    """
    return (
        prompts.post_trade_system_blocks(),  # type: ignore[return-value]
        prompts.post_trade_user_content(
            snapshot.to_brain_input(),
            r_multiple=fill.r_multiple,
            bars_held=bars_held,
            exit_reason=fill.reason.value,
        ),
    )
