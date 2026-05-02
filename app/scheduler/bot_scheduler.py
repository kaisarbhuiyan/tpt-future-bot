import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from app.data.market_data import YFinanceFetcher
from app.data.session import is_trading_now, is_eod_flatten_time
from app.data.storage import upsert_candles
from app.indicators.engine import IndicatorEngine
from app.ai.signal_engine import SignalEngine
from app.risk.rule_engine import RuleEngine
from app.risk.position_sizer import calculate_contracts
from app.execution.base_broker import Order, OrderSide
from app.models.db_models import Signal as DBSignal, RuleCheck as DBRuleCheck, TradeMode
from app.ai.models import SignalDirection

logger = logging.getLogger(__name__)

SYMBOLS = ["ES", "NQ"]
PRIMARY_TIMEFRAME = "5m"


class BotScheduler:
    """
    Orchestrates all bot jobs using APScheduler.

    Jobs:
      scan_job            — every 60s: fetch data, compute indicators, generate signal,
                            run rule check, optionally place order
      position_monitor    — every 5s: check SL/TP for open positions
      eod_flatten_job     — daily at permitted_end: flatten all positions
      daily_reset_job     — daily at market open: reset daily counters
    """

    def __init__(
        self,
        config: dict,
        broker,
        drawdown_tracker,
        session_factory,
    ) -> None:
        self._config = config
        self._broker = broker
        self._dd = drawdown_tracker
        self._session_factory = session_factory
        self._scheduler = AsyncIOScheduler()
        self._running = False
        self._paused = False

        self._fetcher = YFinanceFetcher()
        self._indicator_engine = IndicatorEngine()
        self._signal_engine = SignalEngine()

        self._app_state: Optional[Any] = None  # Set externally if needed

    @property
    def running(self) -> bool:
        return self._scheduler.running

    def start(self) -> None:
        th = self._config.get("trading_hours", {})
        end_h, end_m = map(int, th.get("permitted_end", "16:00").split(":"))
        start_h, start_m = map(int, th.get("permitted_start", "09:30").split(":"))

        # Scan every 60 seconds
        self._scheduler.add_job(
            self._scan_job,
            trigger=IntervalTrigger(seconds=60),
            id="scan_job",
            name="Market scan",
            misfire_grace_time=30,
        )

        # Monitor positions every 5 seconds
        self._scheduler.add_job(
            self._position_monitor_job,
            trigger=IntervalTrigger(seconds=5),
            id="position_monitor",
            name="Position monitor",
            misfire_grace_time=10,
        )

        # EOD flatten
        self._scheduler.add_job(
            self._eod_flatten_job,
            trigger=CronTrigger(hour=end_h, minute=end_m, timezone="America/New_York"),
            id="eod_flatten",
            name="EOD flatten all positions",
        )

        # Daily reset at market open
        self._scheduler.add_job(
            self._daily_reset_job,
            trigger=CronTrigger(hour=start_h, minute=start_m, timezone="America/New_York"),
            id="daily_reset",
            name="Daily counter reset",
        )

        self._scheduler.start()
        self._running = True
        logger.info("BotScheduler started")

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._running = False
        logger.info("BotScheduler stopped")

    def pause(self) -> None:
        self._paused = True
        logger.info("BotScheduler paused — no new trades will be placed")

    def resume(self) -> None:
        self._paused = False
        logger.info("BotScheduler resumed")

    # ------------------------------------------------------------------ #
    # Jobs
    # ------------------------------------------------------------------ #

    async def _scan_job(self) -> None:
        """Main scan loop — runs every 60 seconds."""
        if self._paused:
            return

        now = datetime.now()
        allowed, reason = is_trading_now(self._config)
        if not allowed:
            logger.debug(f"Scan skipped — {reason}")
            return

        logger.info(f"Scanning {SYMBOLS} at {now.strftime('%H:%M:%S')}")

        for symbol in SYMBOLS:
            try:
                await self._process_symbol(symbol)
            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}", exc_info=True)

    async def _process_symbol(self, symbol: str) -> None:
        """Fetch → Indicators → Signal → Rules → Execute (if approved)."""
        # Fetch latest candles
        df = await self._fetcher.fetch_ohlcv(symbol, timeframe=PRIMARY_TIMEFRAME, bars=300)
        if df.empty:
            logger.warning(f"No data for {symbol}")
            return

        # Store to DB
        async with self._session_factory() as session:
            await upsert_candles(session, df, symbol, PRIMARY_TIMEFRAME)

        # Compute indicators
        snap = self._indicator_engine.compute(df, symbol, PRIMARY_TIMEFRAME)

        # Generate signal
        signal = self._signal_engine.generate_signal(snap, self._config)

        # Calculate position size
        atr = snap.atr
        contracts, dollar_risk, size_reason = calculate_contracts(
            symbol, atr, self._dd.state, self._config
        )

        # Add open position count to account state
        positions = await self._broker.get_positions()
        self._dd.state.open_positions_count = len(positions)

        # Run rule engine
        rule_engine = RuleEngine(self._dd, self._config)
        passed, blocked_reason, rule_results = rule_engine.check(signal, self._dd.state)

        # Persist signal to DB
        async with self._session_factory() as session:
            db_signal = DBSignal(
                symbol=symbol,
                timeframe=PRIMARY_TIMEFRAME,
                timestamp=signal.timestamp,
                direction=signal.direction.value,
                confidence=signal.confidence,
                reason=signal.reason,
                invalidation_level=signal.invalidation_level,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                risk_reward=signal.risk_reward,
                rule_check_passed=passed,
                blocked_reason=blocked_reason or None,
            )
            session.add(db_signal)
            await session.flush()

            # Persist individual rule checks
            for result in rule_results:
                session.add(DBRuleCheck(
                    signal_id=db_signal.id,
                    rule_name=result.rule_name,
                    passed=result.passed,
                    reason=result.reason,
                ))
            await session.commit()

        if not passed:
            logger.info(
                f"NO TRADE — {symbol} {signal.direction.value} "
                f"confidence={signal.confidence:.1f} | BLOCKED: {blocked_reason}"
            )
            return

        if contracts == 0:
            logger.warning(f"Position size is 0 for {symbol} — skipping (consecutive loss limit?)")
            return

        # Place order
        side = OrderSide.BUY if signal.direction == SignalDirection.BUY else OrderSide.SELL
        order = Order(
            symbol=symbol,
            side=side,
            contracts=contracts,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )

        result = await self._broker.place_order(order)
        logger.info(
            f"ORDER PLACED: {symbol} {side.value} {contracts}ct "
            f"@ {signal.entry_price:.2f} | SL={signal.stop_loss:.2f} "
            f"TP={signal.take_profit:.2f} | Result: {result.status.value}"
        )

    async def _position_monitor_job(self) -> None:
        """Every 5 seconds: check SL/TP on open positions."""
        positions = await self._broker.get_positions()
        if not positions:
            return

        # Get current prices for all open symbols
        current_prices: dict[str, float] = {}
        open_symbols = {p.symbol for p in positions}
        for symbol in open_symbols:
            try:
                price = await self._fetcher.get_latest_price(symbol)
                current_prices[symbol] = price
            except Exception:
                pass

        if not current_prices:
            return

        # Update unrealized P&L across all positions
        total_unrealized = 0.0
        from app.data.normalizer import get_instrument_spec
        from app.execution.base_broker import OrderSide as OS
        for pos in positions:
            price = current_prices.get(pos.symbol)
            if price is None:
                continue
            spec = get_instrument_spec(pos.symbol)
            if pos.side == OS.BUY:
                diff = price - pos.entry_price
            else:
                diff = pos.entry_price - price
            pos.unrealized_pnl = diff * spec["point_value"] * pos.contracts
            total_unrealized += pos.unrealized_pnl

        self._dd.on_unrealized_update(total_unrealized)

        # Check drawdown breach
        safe, reason = self._dd.check_drawdown()
        if not safe:
            logger.critical(f"DRAWDOWN BREACH: {reason} — emergency flatten triggered")
            await self._broker.flatten_all(reason="DRAWDOWN_BREACH")
            return

        # Check SL/TP
        closed = await self._broker.check_and_update_positions(current_prices)
        for trade in closed:
            self._dd.on_trade_close(trade["pnl"], datetime.now(timezone.utc))

    async def _eod_flatten_job(self) -> None:
        """Flatten all positions at end of permitted trading window."""
        logger.warning("EOD: Flattening all positions")
        await self._broker.flatten_all(reason="EOD_FLATTEN")
        self._paused = True
        logger.info("Bot paused after EOD flatten — will resume at daily reset")

    async def _daily_reset_job(self) -> None:
        """Reset all daily counters at market open."""
        self._dd.daily_reset()
        self._paused = False
        logger.info("Daily reset complete — bot active for new session")
