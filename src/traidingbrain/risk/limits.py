"""The limits that do not care how good the setup looks.

Everything else in this system is an opinion about the market. This module is not.
It counts what has already happened and refuses on that basis, and it is
deliberately the last thing consulted -- after the analysis, after the model, after
the sizing -- so that a persuasive argument cannot route around it.

The failure these prevent is not a bad trade. It is the sequence: a loss, then a
larger position to make it back, then a worse loss. Every limit here is a
circuit-breaker on that sequence, and the cooldown in particular exists because
the moment after three consecutive losses is exactly when judgement is worst and
conviction is highest.

The kill switch is a file. Not a flag in memory, not a method on a running object:
a file, so it can be set from another terminal, by another process, or by a person
who cannot reach the running system any other way. A kill switch only the running
process can set is not a kill switch.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from traidingbrain.config.settings import LimitsConfig
from traidingbrain.domain.proposal import ClosedTrade, Position

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS


@dataclass(frozen=True)
class LimitVerdict:
    """Whether a new trade is allowed, and if not, what is blocking it."""

    allowed: bool
    blockers: list[str]

    @property
    def reason(self) -> str:
        return "; ".join(self.blockers) if self.blockers else "within all limits"


class KillSwitch:
    """A file whose existence stops everything.

    Checked before every send. Engaging it also cancels resting orders, because a
    kill switch that only prevents *new* orders leaves the existing ones running,
    which is the opposite of what anyone reaching for it wants.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def is_engaged(self) -> bool:
        return self.path.exists()

    def engage(self, reason: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(tz=UTC).isoformat()
        self.path.write_text(f"{stamp}\n{reason}\n", encoding="utf-8")

    def release(self) -> None:
        """Deliberately manual. Nothing in the system clears this by itself.

        A switch that resets on a timer or on restart is a switch that turns
        itself back on at the worst possible moment.
        """
        self.path.unlink(missing_ok=True)

    def reason(self) -> str:
        if not self.is_engaged():
            return ""
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return lines[1] if len(lines) > 1 else "no reason recorded"


@dataclass
class AccountState:
    """What the account has been doing lately.

    Supplied by the caller rather than read here, so the same checks run
    identically against a simulator and against a live account.
    """

    equity: float
    starting_equity_today: float
    starting_equity_this_week: float
    open_positions: list[Position]
    recent_trades: list[ClosedTrade]
    now_ms: int

    def realised_today(self) -> float:
        cutoff = self.now_ms - DAY_MS
        return sum(t.net_pnl for t in self.recent_trades if t.closed_ts >= cutoff)

    def realised_this_week(self) -> float:
        cutoff = self.now_ms - 7 * DAY_MS
        return sum(t.net_pnl for t in self.recent_trades if t.closed_ts >= cutoff)

    def consecutive_losses(self) -> int:
        """Losses at the end of the sequence, counted backwards.

        Backwards on purpose: what matters is the current run, not the total.
        """
        run = 0
        for trade in sorted(self.recent_trades, key=lambda t: t.closed_ts, reverse=True):
            if trade.net_pnl >= 0:
                break
            run += 1
        return run

    def last_loss_ts(self) -> int | None:
        losses = [t.closed_ts for t in self.recent_trades if t.net_pnl < 0]
        return max(losses) if losses else None


class RiskLimits:
    """Every check that can block a trade for reasons other than the market."""

    def __init__(self, config: LimitsConfig, kill_switch: KillSwitch | None = None) -> None:
        self.config = config
        self.kill_switch = kill_switch

    def check(self, state: AccountState, *, symbol: str) -> LimitVerdict:
        blockers: list[str] = []

        if self.kill_switch is not None and self.kill_switch.is_engaged():
            # First, and on its own sufficient. Nothing below can unblock it.
            return LimitVerdict(
                allowed=False, blockers=[f"kill switch engaged: {self.kill_switch.reason()}"]
            )

        if len(state.open_positions) >= self.config.max_open_positions:
            blockers.append(
                f"{len(state.open_positions)} positions already open "
                f"(limit {self.config.max_open_positions})"
            )

        in_symbol = sum(1 for p in state.open_positions if p.symbol == symbol)
        if in_symbol >= self.config.max_positions_per_symbol:
            blockers.append(
                f"already {in_symbol} position(s) in {symbol} "
                f"(limit {self.config.max_positions_per_symbol})"
            )

        # Measured against the equity at the start of the period, not current
        # equity: otherwise the allowance shrinks as losses accumulate and the
        # limit is never quite reached.
        daily_loss = -state.realised_today()
        daily_allowance = state.starting_equity_today * self.config.max_daily_loss_pct
        if daily_loss >= daily_allowance:
            blockers.append(
                f"down {daily_loss:,.0f} today, at or past the "
                f"{self.config.max_daily_loss_pct:.0%} daily limit ({daily_allowance:,.0f})"
            )

        weekly_loss = -state.realised_this_week()
        weekly_allowance = state.starting_equity_this_week * self.config.max_weekly_loss_pct
        if weekly_loss >= weekly_allowance:
            blockers.append(
                f"down {weekly_loss:,.0f} this week, at or past the "
                f"{self.config.max_weekly_loss_pct:.0%} weekly limit ({weekly_allowance:,.0f})"
            )

        losses = state.consecutive_losses()
        if losses >= self.config.cooldown_after_consecutive_losses:
            last = state.last_loss_ts()
            if last is not None:
                elapsed_hours = (state.now_ms - last) / HOUR_MS
                if elapsed_hours < self.config.cooldown_hours:
                    remaining = self.config.cooldown_hours - elapsed_hours
                    blockers.append(
                        f"{losses} losses in a row; cooling off for another {remaining:.1f}h"
                    )

        return LimitVerdict(allowed=not blockers, blockers=blockers)

    def cooldown_ends_at(self, state: AccountState) -> datetime | None:
        """When trading resumes, for the dashboard to display."""
        if state.consecutive_losses() < self.config.cooldown_after_consecutive_losses:
            return None
        last = state.last_loss_ts()
        if last is None:
            return None
        return datetime.fromtimestamp(last / 1000, tz=UTC) + timedelta(
            hours=self.config.cooldown_hours
        )
