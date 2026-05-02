from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel


class BotStatusResponse(BaseModel):
    running: bool
    paused: bool
    mode: str  # "PAPER" | "LIVE"
    current_balance: float
    daily_pnl: float
    drawdown_buffer: float
    consecutive_losses: int
    trades_today: int
    open_positions: int
    last_scan: Optional[datetime]
    message: str


class SignalResponse(BaseModel):
    id: Optional[int]
    symbol: str
    timeframe: str
    direction: str
    confidence: float
    reason: str
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: float
    rule_check_passed: bool
    blocked_reason: Optional[str]
    timestamp: datetime


class PositionResponse(BaseModel):
    trade_id: int
    symbol: str
    side: str
    contracts: int
    entry_price: float
    stop_loss: float
    take_profit: float
    unrealized_pnl: float
    entry_time: datetime


class TradeResponse(BaseModel):
    id: int
    symbol: str
    direction: str
    entry_price: float
    exit_price: Optional[float]
    stop_loss: float
    take_profit: float
    contracts: int
    pnl_dollars: Optional[float]
    pnl_ticks: Optional[float]
    status: str
    exit_reason: Optional[str]
    entry_time: datetime
    exit_time: Optional[datetime]
    mode: str


class RiskStatusResponse(BaseModel):
    drawdown_used: float
    drawdown_limit: float
    drawdown_buffer_remaining: float
    daily_loss_limit: Optional[float]
    daily_pnl: float
    daily_profit_target: float
    consecutive_losses: int
    peak_balance: float
    current_equity: float
    is_drawdown_safe: bool
    drawdown_message: str


class RuleCheckResponse(BaseModel):
    rule_name: str
    passed: bool
    reason: str
    checked_at: datetime


class BacktestResultsResponse(BaseModel):
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    total_trades: int
    win_rate: float
    profit_factor: float
    max_drawdown: float
    sharpe_ratio: float
    avg_risk_reward: float
    total_pnl: float
    prop_firm_violation: bool
    violation_reason: Optional[str]


class EmergencyResponse(BaseModel):
    success: bool
    positions_closed: int
    message: str


class CommandResponse(BaseModel):
    success: bool
    message: str
