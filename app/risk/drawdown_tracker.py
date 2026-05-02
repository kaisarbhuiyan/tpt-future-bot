from dataclasses import dataclass, field
from datetime import datetime, date, timezone
from typing import Optional
import logging


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

logger = logging.getLogger(__name__)


@dataclass
class AccountState:
    """Live snapshot of account financials and trading state."""
    # Balances
    starting_balance: float = 50000.0
    current_balance: float = 50000.0
    peak_balance: float = 50000.0       # Highest equity ever reached
    unrealized_pnl: float = 0.0

    # Daily tracking
    daily_realized_pnl: float = 0.0
    daily_risk_committed: float = 0.0   # Sum of max risk on open trades
    trades_today: int = 0
    winning_trades_today: int = 0
    losing_trades_today: int = 0

    # Streak tracking
    consecutive_losses: int = 0
    consecutive_wins: int = 0

    # Timestamps
    last_loss_time: Optional[datetime] = None
    last_trade_time: Optional[datetime] = None
    session_date: date = field(default_factory=date.today)

    @property
    def equity(self) -> float:
        return self.current_balance + self.unrealized_pnl

    @property
    def trailing_drawdown_used(self) -> float:
        """How much of the trailing drawdown has been consumed."""
        return max(0.0, self.peak_balance - self.equity)

    def remaining_drawdown_buffer(self, eod_trailing_limit: float) -> float:
        """Dollars remaining before hitting the EOD trailing drawdown limit."""
        return eod_trailing_limit - self.trailing_drawdown_used

    def is_drawdown_safe(self, eod_trailing_limit: float, safety_buffer: float) -> tuple[bool, str]:
        """
        Returns (safe: bool, reason: str).
        Safe = remaining buffer > safety_buffer.
        """
        remaining = self.remaining_drawdown_buffer(eod_trailing_limit)
        if remaining <= 0:
            return False, f"EOD trailing drawdown limit BREACHED (used ${self.trailing_drawdown_used:.2f} of ${eod_trailing_limit:.2f})"
        if remaining <= safety_buffer:
            return False, (
                f"Drawdown safety buffer reached — ${remaining:.2f} remaining "
                f"(buffer: ${safety_buffer:.2f})"
            )
        return True, f"Drawdown OK — ${remaining:.2f} buffer remaining"

    def update_after_trade_close(self, pnl: float, timestamp: datetime) -> None:
        """Call after every trade closes to update all counters."""
        self.current_balance += pnl
        self.daily_realized_pnl += pnl
        self.last_trade_time = timestamp

        if pnl > 0:
            self.winning_trades_today += 1
            self.consecutive_wins += 1
            self.consecutive_losses = 0
        elif pnl < 0:
            self.losing_trades_today += 1
            self.consecutive_losses += 1
            self.consecutive_wins = 0
            # Always store as UTC-aware
            if timestamp.tzinfo is None:
                self.last_loss_time = timestamp.replace(tzinfo=timezone.utc)
            else:
                self.last_loss_time = timestamp.astimezone(timezone.utc)

        self.trades_today += 1
        # Update peak balance if new high
        self.peak_balance = max(self.peak_balance, self.current_balance)

    def daily_reset(self) -> None:
        """Reset daily counters. Call once at market open each day."""
        self.daily_realized_pnl = 0.0
        self.daily_risk_committed = 0.0
        self.trades_today = 0
        self.winning_trades_today = 0
        self.losing_trades_today = 0
        self.unrealized_pnl = 0.0
        self.consecutive_losses = 0
        self.consecutive_wins = 0
        self.last_loss_time = None
        self.session_date = date.today()
        logger.info(f"Daily reset complete. Starting balance: ${self.current_balance:.2f}")


class DrawdownTracker:
    """Manages the AccountState and enforces drawdown rules."""

    def __init__(self, config: dict) -> None:
        self._config = config
        acct_cfg = config.get("account", {})
        dd_cfg = config.get("drawdown", {})
        self.state = AccountState(
            starting_balance=acct_cfg.get("account_size", 50000),
            current_balance=acct_cfg.get("account_size", 50000),
            peak_balance=acct_cfg.get("account_size", 50000),
        )
        self._trailing_limit = dd_cfg.get("eod_trailing_drawdown_limit", 2000)
        self._safety_buffer = dd_cfg.get("drawdown_safety_buffer", 500)
        self._daily_loss_limit = dd_cfg.get("daily_loss_limit")

    def check_drawdown(self) -> tuple[bool, str]:
        return self.state.is_drawdown_safe(self._trailing_limit, self._safety_buffer)

    def check_daily_loss_limit(self) -> tuple[bool, str]:
        if self._daily_loss_limit is None:
            return True, "No daily loss limit configured"
        if self.state.daily_realized_pnl <= -abs(self._daily_loss_limit):
            return False, (
                f"Daily loss limit hit: ${self.state.daily_realized_pnl:.2f} "
                f"(limit: -${abs(self._daily_loss_limit):.2f})"
            )
        return True, f"Daily loss OK: ${self.state.daily_realized_pnl:.2f}"

    def on_trade_close(self, pnl: float, timestamp: datetime) -> None:
        self.state.update_after_trade_close(pnl, timestamp)
        safe, reason = self.check_drawdown()
        if not safe:
            logger.critical(f"DRAWDOWN ALERT: {reason}")

    def on_unrealized_update(self, unrealized: float) -> None:
        self.state.unrealized_pnl = unrealized

    def daily_reset(self) -> None:
        self.state.daily_reset()
