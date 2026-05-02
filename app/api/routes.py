import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select, desc

from app.api.schemas import (
    BotStatusResponse, SignalResponse, PositionResponse, TradeResponse,
    RiskStatusResponse, RuleCheckResponse, EmergencyResponse, CommandResponse,
    BacktestResultsResponse,
)
from app.models.db_models import Signal, Trade, RuleCheck, DailyStats, TradeStatus

logger = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------ #
# Bot Control
# ------------------------------------------------------------------ #

@router.get("/status", response_model=BotStatusResponse)
async def get_status(request: Request):
    state = request.app.state
    scheduler = getattr(state, "scheduler", None)
    dd_tracker = getattr(state, "drawdown_tracker", None)
    broker = getattr(state, "broker", None)

    running = scheduler.running if scheduler else False
    paused = getattr(state, "paused", False)
    mode = getattr(state, "trading_mode", "PAPER")

    balance = 50000.0
    daily_pnl = 0.0
    drawdown_buffer = 2000.0
    consecutive_losses = 0
    trades_today = 0
    open_positions = 0

    if dd_tracker:
        acct = dd_tracker.state
        balance = acct.current_balance
        daily_pnl = acct.daily_realized_pnl
        config = getattr(state, "config", {})
        dd_limit = config.get("drawdown", {}).get("eod_trailing_drawdown_limit", 2000)
        drawdown_buffer = acct.remaining_drawdown_buffer(dd_limit)
        consecutive_losses = acct.consecutive_losses
        trades_today = acct.trades_today

    if broker:
        positions = await broker.get_positions()
        open_positions = len(positions)

    last_scan = getattr(state, "last_scan_time", None)

    return BotStatusResponse(
        running=running,
        paused=paused,
        mode=mode,
        current_balance=round(balance, 2),
        daily_pnl=round(daily_pnl, 2),
        drawdown_buffer=round(drawdown_buffer, 2),
        consecutive_losses=consecutive_losses,
        trades_today=trades_today,
        open_positions=open_positions,
        last_scan=last_scan,
        message="Bot operational" if running and not paused else "Bot stopped/paused",
    )


@router.post("/bot/start", response_model=CommandResponse)
async def start_bot(request: Request):
    state = request.app.state
    scheduler = getattr(state, "scheduler", None)
    if scheduler and not scheduler.running:
        scheduler.start()
        state.paused = False
        return CommandResponse(success=True, message="Bot started")
    return CommandResponse(success=False, message="Bot already running or scheduler not initialized")


@router.post("/bot/stop", response_model=CommandResponse)
async def stop_bot(request: Request):
    state = request.app.state
    scheduler = getattr(state, "scheduler", None)
    if scheduler and scheduler.running:
        scheduler.pause()
        state.paused = True
        return CommandResponse(success=True, message="Bot stopped")
    return CommandResponse(success=False, message="Bot not running")


@router.post("/bot/pause", response_model=CommandResponse)
async def pause_bot(request: Request):
    state = request.app.state
    state.paused = True
    return CommandResponse(success=True, message="Bot paused — monitoring continues, no new trades")


# ------------------------------------------------------------------ #
# Emergency
# ------------------------------------------------------------------ #

@router.post("/emergency/flatten", response_model=EmergencyResponse)
async def emergency_flatten(request: Request):
    state = request.app.state
    broker = getattr(state, "broker", None)
    if broker is None:
        raise HTTPException(status_code=503, detail="Broker not initialized")

    positions = await broker.get_positions()
    count = len(positions)
    await broker.flatten_all(reason="EMERGENCY_KILL_SWITCH")

    if hasattr(state, "paused"):
        state.paused = True

    logger.critical(f"EMERGENCY FLATTEN: {count} positions closed via kill switch")
    return EmergencyResponse(
        success=True,
        positions_closed=count,
        message=f"Emergency flatten complete. {count} position(s) closed. Bot paused.",
    )


# ------------------------------------------------------------------ #
# Signals
# ------------------------------------------------------------------ #

@router.get("/signals/latest", response_model=List[SignalResponse])
async def get_latest_signals(request: Request):
    state = request.app.state
    db = state.db_session_factory
    async with db() as session:
        results = []
        for symbol in ["ES", "NQ"]:
            stmt = (
                select(Signal)
                .where(Signal.symbol == symbol)
                .order_by(desc(Signal.created_at))
                .limit(1)
            )
            r = await session.execute(stmt)
            sig = r.scalar_one_or_none()
            if sig:
                results.append(_signal_to_response(sig))
        return results


@router.get("/signals/history", response_model=List[SignalResponse])
async def get_signal_history(request: Request, limit: int = 50, symbol: Optional[str] = None):
    state = request.app.state
    db = state.db_session_factory
    async with db() as session:
        stmt = select(Signal).order_by(desc(Signal.created_at)).limit(limit)
        if symbol:
            stmt = stmt.where(Signal.symbol == symbol.upper())
        r = await session.execute(stmt)
        signals = r.scalars().all()
        return [_signal_to_response(s) for s in signals]


# ------------------------------------------------------------------ #
# Trades & Positions
# ------------------------------------------------------------------ #

@router.get("/trades/open", response_model=List[PositionResponse])
async def get_open_trades(request: Request):
    state = request.app.state
    broker = getattr(state, "broker", None)
    if broker is None:
        return []
    positions = await broker.get_positions()
    return [
        PositionResponse(
            trade_id=p.trade_id,
            symbol=p.symbol,
            side=p.side.value,
            contracts=p.contracts,
            entry_price=p.entry_price,
            stop_loss=p.stop_loss,
            take_profit=p.take_profit,
            unrealized_pnl=round(p.unrealized_pnl, 2),
            entry_time=p.entry_time,
        )
        for p in positions
    ]


@router.get("/trades/history", response_model=List[TradeResponse])
async def get_trade_history(request: Request, limit: int = 50, today_only: bool = False):
    state = request.app.state
    db = state.db_session_factory
    async with db() as session:
        stmt = (
            select(Trade)
            .where(Trade.status == TradeStatus.CLOSED)
            .order_by(desc(Trade.exit_time))
            .limit(limit)
        )
        if today_only:
            today_start = datetime.combine(date.today(), datetime.min.time())
            stmt = stmt.where(Trade.entry_time >= today_start)
        r = await session.execute(stmt)
        trades = r.scalars().all()
        return [_trade_to_response(t) for t in trades]


# ------------------------------------------------------------------ #
# Risk
# ------------------------------------------------------------------ #

@router.get("/risk/status", response_model=RiskStatusResponse)
async def get_risk_status(request: Request):
    state = request.app.state
    dd = getattr(state, "drawdown_tracker", None)
    config = getattr(state, "config", {})

    if dd is None:
        raise HTTPException(status_code=503, detail="DrawdownTracker not initialized")

    acct = dd.state
    dd_limit = config.get("drawdown", {}).get("eod_trailing_drawdown_limit", 2000)
    daily_loss_limit = config.get("drawdown", {}).get("daily_loss_limit")
    daily_profit_target = config.get("profit_target", {}).get("daily_profit_target", 600)

    safe, message = dd.check_drawdown()
    return RiskStatusResponse(
        drawdown_used=round(acct.trailing_drawdown_used, 2),
        drawdown_limit=dd_limit,
        drawdown_buffer_remaining=round(acct.remaining_drawdown_buffer(dd_limit), 2),
        daily_loss_limit=daily_loss_limit,
        daily_pnl=round(acct.daily_realized_pnl, 2),
        daily_profit_target=daily_profit_target,
        consecutive_losses=acct.consecutive_losses,
        peak_balance=round(acct.peak_balance, 2),
        current_equity=round(acct.equity, 2),
        is_drawdown_safe=safe,
        drawdown_message=message,
    )


@router.get("/risk/rules", response_model=List[RuleCheckResponse])
async def get_rule_checks(request: Request, limit: int = 20):
    state = request.app.state
    db = state.db_session_factory
    async with db() as session:
        stmt = (
            select(RuleCheck)
            .order_by(desc(RuleCheck.checked_at))
            .limit(limit)
        )
        r = await session.execute(stmt)
        checks = r.scalars().all()
        return [
            RuleCheckResponse(
                rule_name=c.rule_name,
                passed=c.passed,
                reason=c.reason or "",
                checked_at=c.checked_at,
            )
            for c in checks
        ]


# ------------------------------------------------------------------ #
# Backtest
# ------------------------------------------------------------------ #

@router.get("/backtest/results", response_model=Optional[BacktestResultsResponse])
async def get_backtest_results(request: Request):
    state = request.app.state
    results = getattr(state, "last_backtest_results", None)
    return results


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _signal_to_response(sig: Signal) -> SignalResponse:
    return SignalResponse(
        id=sig.id,
        symbol=sig.symbol,
        timeframe=sig.timeframe,
        direction=sig.direction.value,
        confidence=sig.confidence,
        reason=sig.reason,
        stop_loss=sig.stop_loss,
        take_profit=sig.take_profit,
        risk_reward=sig.risk_reward or 0.0,
        rule_check_passed=sig.rule_check_passed,
        blocked_reason=sig.blocked_reason,
        timestamp=sig.timestamp,
    )


def _trade_to_response(t: Trade) -> TradeResponse:
    return TradeResponse(
        id=t.id,
        symbol=t.symbol,
        direction=t.direction.value,
        entry_price=t.entry_price,
        exit_price=t.exit_price,
        stop_loss=t.stop_loss,
        take_profit=t.take_profit,
        contracts=t.contracts,
        pnl_dollars=t.pnl_dollars,
        pnl_ticks=t.pnl_ticks,
        status=t.status.value,
        exit_reason=t.exit_reason,
        entry_time=t.entry_time,
        exit_time=t.exit_time,
        mode=t.mode.value,
    )
