"""
Unit tests for the RuleEngine — every rule check must block correctly.
Tests run without market data or DB connections.
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def utc_now():
    return datetime.now(timezone.utc)

from app.ai.models import TradeSignal, SignalDirection
from app.risk.rule_engine import RuleEngine, RuleCheckResult
from app.risk.drawdown_tracker import DrawdownTracker, AccountState


# ------------------------------------------------------------------ #
# Fixtures
# ------------------------------------------------------------------ #

BASE_CONFIG = {
    "account": {
        "account_size": 50000,
        "allowed_symbols": ["ES", "NQ"],
        "max_contracts_per_symbol": 10,
        "max_open_positions": 2,
    },
    "trading_hours": {
        "permitted_start": "09:30",
        "permitted_end": "16:00",
        "allow_premarket": False,
        "allow_overnight": False,
        "eod_cutoff_minutes": 15,
    },
    "drawdown": {
        "eod_trailing_drawdown_limit": 2000,
        "daily_loss_limit": None,
        "drawdown_safety_buffer": 500,
    },
    "profit_target": {
        "evaluation_profit_target": 3000,
        "daily_profit_target": 600,
        "account_profit_stop": None,
    },
    "risk": {
        "risk_pct_per_trade": 0.0025,
        "max_risk_pct_per_trade": 0.005,
        "max_daily_risk_pct": 0.01,
        "min_risk_reward_ratio": 2.0,
        "min_confidence_score": 65,
        "atr_stop_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
    },
    "position_management": {
        "max_consecutive_losses": 2,
        "max_trades_per_day": 6,
    },
    "restrictions": {
        "block_during_news": True,
        "news_blackout_minutes": 5,
        "min_minutes_after_loss": 5,
    },
    "live_trading": {
        "live_trading_confirmed": False,
        "live_broker": "tradovate",
    },
}


def make_signal(
    symbol="ES",
    direction=SignalDirection.BUY,
    confidence=75.0,
    stop_loss=5000.0,
    take_profit=5030.0,
    risk_reward=2.5,
    entry_price=5010.0,
) -> TradeSignal:
    return TradeSignal(
        symbol=symbol,
        direction=direction,
        confidence=confidence,
        reason="Test signal",
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        timeframe="5m",
    )


def make_state(**kwargs) -> AccountState:
    state = AccountState(starting_balance=50000, current_balance=50000, peak_balance=50000)
    for k, v in kwargs.items():
        setattr(state, k, v)
    return state


def make_engine(config=None) -> tuple[RuleEngine, DrawdownTracker]:
    cfg = config or BASE_CONFIG
    dd = DrawdownTracker(cfg)
    engine = RuleEngine(dd, cfg)
    return engine, dd


def trading_time() -> datetime:
    """Returns a datetime inside permitted trading hours (ET)."""
    from datetime import timezone
    from zoneinfo import ZoneInfo
    return datetime.now(tz=ZoneInfo("America/New_York")).replace(hour=11, minute=0, second=0)


# ------------------------------------------------------------------ #
# Tests — Symbol allowed
# ------------------------------------------------------------------ #

def test_trade_blocked_when_symbol_not_allowed():
    engine, dd = make_engine()
    signal = make_signal(symbol="CL")  # Crude oil — not allowed
    passed, reason, results = engine.check(signal, dd.state, trading_time())
    assert not passed
    assert "symbol_allowed" in reason or "CL" in reason


def test_trade_passes_when_symbol_is_ES():
    engine, dd = make_engine()
    signal = make_signal(symbol="ES")
    # Will still be blocked by trading hours / other rules — just verify symbol passes
    results_map = {}
    # Run only the symbol check
    result = engine._check_symbol_allowed(signal, dd.state, trading_time())
    assert result.passed


def test_trade_passes_when_symbol_is_NQ():
    engine, dd = make_engine()
    signal = make_signal(symbol="NQ")
    result = engine._check_symbol_allowed(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Confidence threshold
# ------------------------------------------------------------------ #

def test_trade_blocked_when_confidence_below_threshold():
    engine, dd = make_engine()
    signal = make_signal(confidence=50.0)  # Below 65 threshold
    result = engine._check_confidence_threshold(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_passes_confidence_at_threshold():
    engine, dd = make_engine()
    signal = make_signal(confidence=65.0)
    result = engine._check_confidence_threshold(signal, dd.state, trading_time())
    assert result.passed


def test_trade_passes_confidence_above_threshold():
    engine, dd = make_engine()
    signal = make_signal(confidence=80.0)
    result = engine._check_confidence_threshold(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Risk/reward
# ------------------------------------------------------------------ #

def test_trade_blocked_when_rr_below_minimum():
    engine, dd = make_engine()
    signal = make_signal(risk_reward=1.5)  # Below 2.0 minimum
    result = engine._check_risk_reward(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_passes_rr_at_minimum():
    engine, dd = make_engine()
    signal = make_signal(risk_reward=2.0)
    result = engine._check_risk_reward(signal, dd.state, trading_time())
    assert result.passed


def test_trade_passes_rr_above_minimum():
    engine, dd = make_engine()
    signal = make_signal(risk_reward=3.5)
    result = engine._check_risk_reward(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Stop loss / take profit exist
# ------------------------------------------------------------------ #

def test_trade_blocked_when_no_stop_loss():
    engine, dd = make_engine()
    signal = make_signal()
    signal.stop_loss = None
    result = engine._check_stop_loss_exists(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_blocked_when_no_take_profit():
    engine, dd = make_engine()
    signal = make_signal()
    signal.take_profit = None
    result = engine._check_take_profit_exists(signal, dd.state, trading_time())
    assert not result.passed


# ------------------------------------------------------------------ #
# Tests — Max trades per day
# ------------------------------------------------------------------ #

def test_trade_blocked_when_max_trades_per_day_reached():
    engine, dd = make_engine()
    dd.state.trades_today = 6  # At max
    signal = make_signal()
    result = engine._check_max_trades_per_day(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_passes_when_trades_below_limit():
    engine, dd = make_engine()
    dd.state.trades_today = 3
    signal = make_signal()
    result = engine._check_max_trades_per_day(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Consecutive losses
# ------------------------------------------------------------------ #

def test_trade_blocked_when_consecutive_losses_maxed():
    engine, dd = make_engine()
    dd.state.consecutive_losses = 2  # At max
    signal = make_signal()
    result = engine._check_consecutive_losses(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_passes_with_one_consecutive_loss():
    engine, dd = make_engine()
    dd.state.consecutive_losses = 1
    signal = make_signal()
    result = engine._check_consecutive_losses(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Daily profit target
# ------------------------------------------------------------------ #

def test_trade_blocked_when_daily_profit_target_reached():
    engine, dd = make_engine()
    dd.state.daily_realized_pnl = 650.0  # Above $600 target
    signal = make_signal()
    result = engine._check_daily_profit_target(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_passes_when_daily_pnl_below_target():
    engine, dd = make_engine()
    dd.state.daily_realized_pnl = 300.0
    signal = make_signal()
    result = engine._check_daily_profit_target(signal, dd.state, trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Drawdown buffer
# ------------------------------------------------------------------ #

def test_trade_blocked_when_drawdown_buffer_exhausted():
    engine, dd = make_engine()
    # Simulate $1,600 drawdown — exceeds $1,500 safe threshold (2000 - 500 buffer)
    dd.state.peak_balance = 50000
    dd.state.current_balance = 48400  # $1,600 drawdown
    result = engine._check_drawdown_buffer(signal=make_signal(), state=dd.state, now=trading_time())
    assert not result.passed


def test_trade_passes_when_drawdown_buffer_safe():
    engine, dd = make_engine()
    dd.state.peak_balance = 50000
    dd.state.current_balance = 49500  # Only $500 drawdown
    result = engine._check_drawdown_buffer(signal=make_signal(), state=dd.state, now=trading_time())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Cooldown after loss
# ------------------------------------------------------------------ #

def test_trade_blocked_when_within_cooldown_after_loss():
    engine, dd = make_engine()
    dd.state.last_loss_time = utc_now() - timedelta(minutes=2)  # 2 min ago
    signal = make_signal()
    result = engine._check_min_time_since_last_loss(signal, dd.state, utc_now())
    assert not result.passed


def test_trade_passes_when_cooldown_elapsed():
    engine, dd = make_engine()
    dd.state.last_loss_time = utc_now() - timedelta(minutes=10)  # 10 min ago
    signal = make_signal()
    result = engine._check_min_time_since_last_loss(signal, dd.state, utc_now())
    assert result.passed


def test_trade_passes_when_no_previous_loss():
    engine, dd = make_engine()
    dd.state.last_loss_time = None
    signal = make_signal()
    result = engine._check_min_time_since_last_loss(signal, dd.state, utc_now())
    assert result.passed


# ------------------------------------------------------------------ #
# Tests — Live trading gates
# ------------------------------------------------------------------ #

def test_trade_passes_in_paper_mode_without_gates():
    engine, dd = make_engine()
    signal = make_signal()
    with patch.dict("os.environ", {"ENABLE_LIVE_TRADING": "false"}):
        result = engine._check_live_trading_gates(signal, dd.state, trading_time())
    assert result.passed


def test_trade_blocked_when_env_gate_open_but_config_gate_closed():
    engine, dd = make_engine()
    signal = make_signal()
    with patch.dict("os.environ", {"ENABLE_LIVE_TRADING": "true"}):
        result = engine._check_live_trading_gates(signal, dd.state, trading_time())
    assert not result.passed


def test_trade_blocked_when_config_gate_open_but_env_gate_closed():
    config = {**BASE_CONFIG, "live_trading": {"live_trading_confirmed": True, "live_broker": "tradovate"}}
    engine, dd = make_engine(config)
    signal = make_signal()
    with patch.dict("os.environ", {"ENABLE_LIVE_TRADING": "false"}):
        result = engine._check_live_trading_gates(signal, dd.state, trading_time())
    assert not result.passed


# ------------------------------------------------------------------ #
# Tests — Full checklist (all pass)
# ------------------------------------------------------------------ #

def test_trade_allowed_when_all_rules_pass():
    engine, dd = make_engine()
    dd.state.trades_today = 2
    dd.state.consecutive_losses = 0
    dd.state.daily_realized_pnl = 100.0
    dd.state.open_positions_count = 0
    signal = make_signal()

    # Patch trading hours to simulate trading time
    with patch("app.risk.rule_engine.is_trading_now", return_value=(True, "Regular session")):
        with patch.dict("os.environ", {"ENABLE_LIVE_TRADING": "false"}):
            passed, reason, results = engine.check(signal, dd.state)

    assert passed, f"Expected trade to pass but got: {reason}"


# ------------------------------------------------------------------ #
# Tests — Daily reset
# ------------------------------------------------------------------ #

def test_daily_reset_resets_counters():
    engine, dd = make_engine()
    dd.state.trades_today = 5
    dd.state.consecutive_losses = 2
    dd.state.daily_realized_pnl = -300.0
    dd.state.winning_trades_today = 2
    dd.state.losing_trades_today = 3

    dd.daily_reset()

    assert dd.state.trades_today == 0
    assert dd.state.consecutive_losses == 0
    assert dd.state.daily_realized_pnl == 0.0
    assert dd.state.winning_trades_today == 0
    assert dd.state.losing_trades_today == 0


# ------------------------------------------------------------------ #
# Tests — AccountState
# ------------------------------------------------------------------ #

def test_consecutive_loss_tracking():
    state = AccountState(starting_balance=50000, current_balance=50000, peak_balance=50000)
    state.update_after_trade_close(-100.0, utc_now())
    assert state.consecutive_losses == 1
    assert state.consecutive_wins == 0

    state.update_after_trade_close(-50.0, utc_now())
    assert state.consecutive_losses == 2

    state.update_after_trade_close(200.0, utc_now())
    assert state.consecutive_losses == 0
    assert state.consecutive_wins == 1


def test_peak_balance_updates_on_win():
    state = AccountState(starting_balance=50000, current_balance=50000, peak_balance=50000)
    state.update_after_trade_close(500.0, utc_now())
    assert state.peak_balance == 50500.0
    assert state.current_balance == 50500.0
