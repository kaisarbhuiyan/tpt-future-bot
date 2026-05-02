import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.base_broker import (
    BrokerAdapter, Order, OrderResult, OrderSide, OrderStatus, Position
)
from app.data.normalizer import points_to_dollars, get_instrument_spec
from app.models.db_models import Trade, TradeStatus, TradeMode, SignalDirection as DBSignalDirection

logger = logging.getLogger(__name__)


class PaperBroker(BrokerAdapter):
    """
    Paper trading broker — no real orders placed.
    Simulates fills at order entry price with immediate execution.
    All trades are recorded in the SQLite database.
    """

    def __init__(self, db_session_factory) -> None:
        self._session_factory = db_session_factory
        self._positions: dict[int, Position] = {}  # trade_id -> Position
        self._balance: float = 50000.0
        self._peak_balance: float = 50000.0
        self._next_trade_id: int = 1

    async def connect(self) -> None:
        logger.info("Paper broker connected (no real orders will be placed)")

    async def disconnect(self) -> None:
        logger.info("Paper broker disconnected")

    async def get_account_balance(self) -> float:
        unrealized = sum(p.unrealized_pnl for p in self._positions.values())
        return self._balance + unrealized

    async def get_positions(self) -> list[Position]:
        return list(self._positions.values())

    async def place_order(self, order: Order) -> OrderResult:
        """Simulate immediate fill at order entry price."""
        try:
            order.validate()
        except AssertionError as e:
            logger.error(f"Order validation failed: {e}")
            return OrderResult(
                order_id=str(uuid.uuid4()),
                status=OrderStatus.REJECTED,
                fill_price=None,
                message=str(e),
            )

        trade_id = self._next_trade_id
        self._next_trade_id += 1
        fill_price = order.entry_price

        position = Position(
            symbol=order.symbol,
            side=order.side,
            contracts=order.contracts,
            entry_price=fill_price,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            trade_id=trade_id,
            unrealized_pnl=0.0,
            entry_time=datetime.now(timezone.utc),
        )
        self._positions[trade_id] = position

        # Persist to DB
        async with self._session_factory() as session:
            direction = DBSignalDirection.BUY if order.side == OrderSide.BUY else DBSignalDirection.SELL
            db_trade = Trade(
                id=trade_id,
                symbol=order.symbol,
                direction=direction,
                entry_price=fill_price,
                stop_loss=order.stop_loss,
                take_profit=order.take_profit,
                contracts=order.contracts,
                entry_time=datetime.now(timezone.utc),
                status=TradeStatus.OPEN,
                mode=TradeMode.PAPER,
            )
            session.add(db_trade)
            await session.commit()

        logger.info(
            f"PAPER FILL: {order.side.value} {order.contracts} {order.symbol} "
            f"@ {fill_price:.2f} | SL={order.stop_loss:.2f} TP={order.take_profit:.2f} "
            f"| TradeID={trade_id}"
        )

        return OrderResult(
            order_id=str(trade_id),
            status=OrderStatus.FILLED,
            fill_price=fill_price,
            message="Paper order filled at market",
            trade_db_id=trade_id,
        )

    async def close_position(self, trade_id: int, reason: str = "MANUAL") -> bool:
        if trade_id not in self._positions:
            logger.warning(f"No open position with trade_id={trade_id}")
            return False
        position = self._positions.pop(trade_id)
        # Use last unrealized P&L as exit
        pnl = position.unrealized_pnl
        exit_price = position.entry_price  # Will be overridden by caller with current price
        await self._record_close(position, exit_price, pnl, reason)
        return True

    async def cancel_all_orders(self) -> bool:
        logger.info("Paper broker: no pending orders to cancel")
        return True

    async def flatten_all(self, reason: str = "EOD_FLATTEN") -> bool:
        """Close all positions at their last known unrealized price."""
        trade_ids = list(self._positions.keys())
        if not trade_ids:
            logger.info("Flatten all: no open positions")
            return True
        logger.warning(f"FLATTEN ALL ({reason}): closing {len(trade_ids)} positions")
        for trade_id in trade_ids:
            position = self._positions.pop(trade_id)
            exit_price = position.entry_price  # Conservative: fill at entry if no price update
            pnl = position.unrealized_pnl
            await self._record_close(position, exit_price, pnl, reason)
        return True

    async def check_and_update_positions(self, current_prices: dict[str, float]) -> list[dict]:
        """
        Called every few seconds by position monitor job.
        Checks SL and TP levels for each open position.
        Returns list of closed trade info dicts.
        """
        closed_trades: list[dict] = []
        to_close: list[tuple[int, float, str]] = []

        for trade_id, pos in self._positions.items():
            current_price = current_prices.get(pos.symbol)
            if current_price is None:
                continue

            # Update unrealized P&L
            spec = get_instrument_spec(pos.symbol)
            if pos.side == OrderSide.BUY:
                price_diff = current_price - pos.entry_price
            else:
                price_diff = pos.entry_price - current_price

            pos.unrealized_pnl = price_diff * spec["point_value"] * pos.contracts

            # Check SL
            if pos.side == OrderSide.BUY and current_price <= pos.stop_loss:
                to_close.append((trade_id, pos.stop_loss, "SL_HIT"))
            elif pos.side == OrderSide.SELL and current_price >= pos.stop_loss:
                to_close.append((trade_id, pos.stop_loss, "SL_HIT"))

            # Check TP
            elif pos.side == OrderSide.BUY and current_price >= pos.take_profit:
                to_close.append((trade_id, pos.take_profit, "TP_HIT"))
            elif pos.side == OrderSide.SELL and current_price <= pos.take_profit:
                to_close.append((trade_id, pos.take_profit, "TP_HIT"))

        for trade_id, exit_price, exit_reason in to_close:
            pos = self._positions.pop(trade_id)
            spec = get_instrument_spec(pos.symbol)
            if pos.side == OrderSide.BUY:
                price_diff = exit_price - pos.entry_price
            else:
                price_diff = pos.entry_price - exit_price

            pnl = price_diff * spec["point_value"] * pos.contracts
            tick_size = spec["tick_size"]
            pnl_ticks = price_diff / tick_size

            await self._record_close(pos, exit_price, pnl, exit_reason, pnl_ticks)
            closed_trades.append({
                "trade_id": trade_id,
                "symbol": pos.symbol,
                "exit_price": exit_price,
                "pnl": pnl,
                "reason": exit_reason,
            })
            logger.info(
                f"{exit_reason}: {pos.symbol} TradeID={trade_id} "
                f"Exit={exit_price:.2f} P&L=${pnl:.2f}"
            )

        return closed_trades

    async def _record_close(
        self,
        position: Position,
        exit_price: float,
        pnl: float,
        exit_reason: str,
        pnl_ticks: float = 0.0,
    ) -> None:
        """Update the Trade record in the DB when a position closes."""
        self._balance += pnl
        self._peak_balance = max(self._peak_balance, self._balance)

        async with self._session_factory() as session:
            from sqlalchemy import select
            stmt = select(Trade).where(Trade.id == position.trade_id)
            result = await session.execute(stmt)
            trade = result.scalar_one_or_none()
            if trade:
                trade.exit_price = exit_price
                trade.exit_time = datetime.now(timezone.utc)
                trade.pnl_dollars = round(pnl, 2)
                trade.pnl_ticks = round(pnl_ticks, 2)
                trade.status = TradeStatus.CLOSED
                trade.exit_reason = exit_reason
                await session.commit()
