from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional
import logging
import os


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    """Normalize any datetime to UTC-aware. Treats naive datetimes as UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

from app.ai.models import TradeSignal, SignalDirection
from app.risk.drawdown_tracker import AccountState, DrawdownTracker
from app.data.session import is_trading_now

logger = logging.getLogger(__name__)


@dataclass
class RuleCheckResult:
    passed: bool
    rule_name: str
    reason: str

    def __bool__(self) -> bool:
        return self.passed


class RuleEngine:
    """
    Pre-trade compliance engine.

    Every trade must pass ALL rules before execution.
    Any single failure blocks the trade immediately.
    Every check is logged individually for the audit trail.
    """

    def __init__(self, drawdown_tracker: DrawdownTracker, config: dict) -> None:
        self._dd = drawdown_tracker
        self._config = config

    def check(
        self,
        signal: TradeSignal,
        account_state: AccountState,
        now: Optional[datetime] = None,
    ) -> tuple[bool, str, list[RuleCheckResult]]:
        """
        Run full pre-trade rule checklist.

        Returns:
            (all_passed: bool, blocked_reason: str | "", results: list[RuleCheckResult])
        """
        now = _to_utc(now) if now is not None else _utc_now()
        checks: list[Callable] = [
            self._check_symbol_allowed,
            self._check_trading_hours,
            self._check_signal_is_tradeable,
            self._check_confidence_threshold,
            self._check_risk_reward,
            self._check_stop_loss_exists,
            self._check_take_profit_exists,
            self._check_drawdown_buffer,
            self._check_daily_loss_limit,
            self._check_daily_profit_target,
            self._check_max_trades_per_day,
            self._check_max_open_positions,
            self._check_consecutive_losses,
            self._check_min_time_since_last_loss,
            self._check_live_trading_gates,
        ]

        results: list[RuleCheckResult] = []
        for check_fn in checks:
            result: RuleCheckResult = check_fn(signal, account_state, now)
            results.append(result)
            if not result.passed:
                logger.warning(
                    f"Trade BLOCKED [{result.rule_name}]: {result.reason} "
                    f"| {signal.symbol} {signal.direction.value}"
                )
                return False, result.reason, results

        logger.info(
            f"Trade APPROVED: {signal.symbol} {signal.direction.value} "
            f"confidence={signal.confidence:.1f} R:R={signal.risk_reward:.2f}"
        )
        return True, "", results

    # ------------------------------------------------------------------ #
    # Individual rule checks
    # ------------------------------------------------------------------ #

    def _check_symbol_allowed(self, signal, state, now) -> RuleCheckResult:
        allowed = [s.upper() for s in self._config.get("account", {}).get("allowed_symbols", ["ES", "NQ"])]
        if signal.symbol.upper() not in allowed:
            return RuleCheckResult(False, "symbol_allowed", f"{signal.symbol} not in allowed symbols: {allowed}")
        return RuleCheckResult(True, "symbol_allowed", f"{signal.symbol} is allowed")

    def _check_trading_hours(self, signal, state, now) -> RuleCheckResult:
        allowed, reason = is_trading_now(self._config, now)
        return RuleCheckResult(allowed, "trading_hours", reason)

    def _check_signal_is_tradeable(self, signal, state, now) -> RuleCheckResult:
        if signal.direction == SignalDirection.NO_TRADE:
            return RuleCheckResult(False, "signal_tradeable", "Signal direction is NO_TRADE")
        return RuleCheckResult(True, "signal_tradeable", f"Direction: {signal.direction.value}")

    def _check_confidence_threshold(self, signal, state, now) -> RuleCheckResult:
        threshold = self._config.get("risk", {}).get("min_confidence_score", 65)
        if signal.confidence < threshold:
            return RuleCheckResult(
                False, "confidence_threshold",
                f"Confidence {signal.confidence:.1f} < threshold {threshold}"
            )
        return RuleCheckResult(True, "confidence_threshold", f"Confidence {signal.confidence:.1f} >= {threshold}")

    def _check_risk_reward(self, signal, state, now) -> RuleCheckResult:
        min_rr = self._config.get("risk", {}).get("min_risk_reward_ratio", 2.0)
        if signal.risk_reward < min_rr:
            return RuleCheckResult(
                False, "risk_reward",
                f"R:R {signal.risk_reward:.2f} < minimum {min_rr}"
            )
        return RuleCheckResult(True, "risk_reward", f"R:R {signal.risk_reward:.2f} >= {min_rr}")

    def _check_stop_loss_exists(self, signal, state, now) -> RuleCheckResult:
        if signal.stop_loss is None:
            return RuleCheckResult(False, "stop_loss_exists", "No stop loss defined — trade blocked")
        return RuleCheckResult(True, "stop_loss_exists", f"Stop loss: {signal.stop_loss}")

    def _check_take_profit_exists(self, signal, state, now) -> RuleCheckResult:
        if signal.take_profit is None:
            return RuleCheckResult(False, "take_profit_exists", "No take profit defined — trade blocked")
        return RuleCheckResult(True, "take_profit_exists", f"Take profit: {signal.take_profit}")

    def _check_drawdown_buffer(self, signal, state, now) -> RuleCheckResult:
        safe, reason = self._dd.check_drawdown()
        return RuleCheckResult(safe, "drawdown_buffer", reason)

    def _check_daily_loss_limit(self, signal, state, now) -> RuleCheckResult:
        ok, reason = self._dd.check_daily_loss_limit()
        return RuleCheckResult(ok, "daily_loss_limit", reason)

    def _check_daily_profit_target(self, signal, state, now) -> RuleCheckResult:
        target = self._config.get("profit_target", {}).get("daily_profit_target", 600)
        if state.daily_realized_pnl >= target:
            return RuleCheckResult(
                False, "daily_profit_target",
                f"Daily profit target reached: ${state.daily_realized_pnl:.2f} >= ${target:.2f}"
            )
        return RuleCheckResult(True, "daily_profit_target", f"Daily P&L ${state.daily_realized_pnl:.2f} < target ${target:.2f}")

    def _check_max_trades_per_day(self, signal, state, now) -> RuleCheckResult:
        max_trades = self._config.get("position_management", {}).get("max_trades_per_day", 6)
        if state.trades_today >= max_trades:
            return RuleCheckResult(
                False, "max_trades_per_day",
                f"Max trades per day reached ({state.trades_today}/{max_trades})"
            )
        return RuleCheckResult(True, "max_trades_per_day", f"Trades today: {state.trades_today}/{max_trades}")

    def _check_max_open_positions(self, signal, state, now) -> RuleCheckResult:
        max_pos = self._config.get("account", {}).get("max_open_positions", 2)
        # open_positions_count is tracked externally; we check via account_state attribute if available
        open_count = getattr(state, "open_positions_count", 0)
        if open_count >= max_pos:
            return RuleCheckResult(
                False, "max_open_positions",
                f"Max open positions reached ({open_count}/{max_pos})"
            )
        return RuleCheckResult(True, "max_open_positions", f"Open positions: {open_count}/{max_pos}")

    def _check_consecutive_losses(self, signal, state, now) -> RuleCheckResult:
        max_losses = self._config.get("position_management", {}).get("max_consecutive_losses", 2)
        if state.consecutive_losses >= max_losses:
            return RuleCheckResult(
                False, "consecutive_losses",
                f"Trading halted: {state.consecutive_losses} consecutive losses (max: {max_losses})"
            )
        return RuleCheckResult(True, "consecutive_losses", f"Consecutive losses: {state.consecutive_losses}/{max_losses}")

    def _check_min_time_since_last_loss(self, signal, state, now) -> RuleCheckResult:
        min_minutes = self._config.get("restrictions", {}).get("min_minutes_after_loss", 5)
        if state.last_loss_time is None:
            return RuleCheckResult(True, "min_time_since_loss", "No recent loss")
        now_utc = _to_utc(now)
        elapsed = (now_utc - _to_utc(state.last_loss_time)).total_seconds() / 60
        if elapsed < min_minutes:
            remaining = min_minutes - elapsed
            return RuleCheckResult(
                False, "min_time_since_loss",
                f"Must wait {remaining:.1f} more minutes after last loss (cooldown: {min_minutes}m)"
            )
        return RuleCheckResult(True, "min_time_since_loss", f"Cooldown elapsed ({elapsed:.1f}m >= {min_minutes}m)")

    def _check_live_trading_gates(self, signal, state, now) -> RuleCheckResult:
        """Two-gate live trading safety check."""
        env_gate = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
        config_gate = self._config.get("live_trading", {}).get("live_trading_confirmed", False)

        if not env_gate and not config_gate:
            return RuleCheckResult(True, "live_trading_gates", "Paper trading mode — gates not required")

        if env_gate and not config_gate:
            return RuleCheckResult(
                False, "live_trading_gates",
                "ENABLE_LIVE_TRADING=true but live_trading_confirmed=false in rules.yaml — both gates required"
            )
        if not env_gate and config_gate:
            return RuleCheckResult(
                False, "live_trading_gates",
                "live_trading_confirmed=true but ENABLE_LIVE_TRADING env var is not set — both gates required"
            )
        return RuleCheckResult(True, "live_trading_gates", "Both live trading gates are open")
