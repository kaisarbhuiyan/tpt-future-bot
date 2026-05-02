from datetime import datetime, date, timezone


def _utc_now():
    return datetime.now(timezone.utc)
from typing import Optional
from sqlalchemy import (
    Column, Integer, Float, String, Boolean, DateTime, Date,
    ForeignKey, Text, Enum as SAEnum, UniqueConstraint
)
from sqlalchemy.orm import DeclarativeBase, relationship
import enum


class Base(DeclarativeBase):
    pass


class SignalDirection(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


class TradeStatus(str, enum.Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TradeMode(str, enum.Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(String(5), nullable=False)  # 1m, 5m, 15m, 1h
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False, default=0.0)
    created_at = Column(DateTime, default=_utc_now)


class Signal(Base):
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    timeframe = Column(String(5), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)
    direction = Column(SAEnum(SignalDirection), nullable=False)
    confidence = Column(Float, nullable=False)
    reason = Column(Text, nullable=False)
    invalidation_level = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    risk_reward = Column(Float, nullable=True)
    rule_check_passed = Column(Boolean, nullable=False, default=False)
    blocked_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utc_now)

    trades = relationship("Trade", back_populates="signal")
    rule_checks = relationship("RuleCheck", back_populates="signal")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(10), nullable=False, index=True)
    direction = Column(SAEnum(SignalDirection), nullable=False)
    entry_price = Column(Float, nullable=False)
    stop_loss = Column(Float, nullable=False)
    take_profit = Column(Float, nullable=False)
    contracts = Column(Integer, nullable=False)
    entry_time = Column(DateTime, nullable=False)
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl_dollars = Column(Float, nullable=True)
    pnl_ticks = Column(Float, nullable=True)
    status = Column(SAEnum(TradeStatus), nullable=False, default=TradeStatus.OPEN)
    mode = Column(SAEnum(TradeMode), nullable=False, default=TradeMode.PAPER)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    exit_reason = Column(String(50), nullable=True)  # SL_HIT, TP_HIT, EOD_FLATTEN, MANUAL
    created_at = Column(DateTime, default=_utc_now)

    signal = relationship("Signal", back_populates="trades")


class RuleCheck(Base):
    __tablename__ = "rule_checks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal_id = Column(Integer, ForeignKey("signals.id"), nullable=True)
    rule_name = Column(String(100), nullable=False)
    passed = Column(Boolean, nullable=False)
    reason = Column(Text, nullable=True)
    checked_at = Column(DateTime, default=_utc_now)

    signal = relationship("Signal", back_populates="rule_checks")


class DailyStats(Base):
    __tablename__ = "daily_stats"
    __table_args__ = (
        UniqueConstraint("date", "mode", name="uq_daily_stats"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    date = Column(Date, nullable=False, index=True)
    starting_balance = Column(Float, nullable=False)
    ending_balance = Column(Float, nullable=True)
    realized_pnl = Column(Float, nullable=False, default=0.0)
    trades_taken = Column(Integer, nullable=False, default=0)
    trades_blocked = Column(Integer, nullable=False, default=0)
    winning_trades = Column(Integer, nullable=False, default=0)
    losing_trades = Column(Integer, nullable=False, default=0)
    max_drawdown_reached = Column(Float, nullable=False, default=0.0)
    profit_target_hit = Column(Boolean, nullable=False, default=False)
    daily_loss_limit_hit = Column(Boolean, nullable=False, default=False)
    mode = Column(SAEnum(TradeMode), nullable=False, default=TradeMode.PAPER)
    created_at = Column(DateTime, default=_utc_now)
    updated_at = Column(DateTime, default=_utc_now, onupdate=datetime.utcnow)
