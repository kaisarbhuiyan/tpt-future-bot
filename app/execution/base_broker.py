from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class Order:
    """Represents a bracket order (entry + stop loss + take profit)."""
    symbol: str
    side: OrderSide
    contracts: int
    entry_price: float          # For paper: fill at this price
    stop_loss: float
    take_profit: float
    order_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def validate(self) -> None:
        assert self.contracts > 0, "Contracts must be > 0"
        assert self.stop_loss > 0, "Stop loss must be set"
        assert self.take_profit > 0, "Take profit must be set"
        assert self.symbol in ("ES", "NQ"), f"Unknown symbol: {self.symbol}"
        if self.side == OrderSide.BUY:
            assert self.stop_loss < self.entry_price, "BUY: SL must be below entry"
            assert self.take_profit > self.entry_price, "BUY: TP must be above entry"
        else:
            assert self.stop_loss > self.entry_price, "SELL: SL must be above entry"
            assert self.take_profit < self.entry_price, "SELL: TP must be below entry"


@dataclass
class OrderResult:
    order_id: str
    status: OrderStatus
    fill_price: Optional[float]
    message: str
    trade_db_id: Optional[int] = None


@dataclass
class Position:
    symbol: str
    side: OrderSide
    contracts: int
    entry_price: float
    stop_loss: float
    take_profit: float
    trade_id: int
    unrealized_pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.utcnow)


class BrokerAdapter(ABC):
    """Abstract interface that all broker implementations must satisfy."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to broker API."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close broker connection."""

    @abstractmethod
    async def get_account_balance(self) -> float:
        """Return current cash balance."""

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Return all currently open positions."""

    @abstractmethod
    async def place_order(self, order: Order) -> OrderResult:
        """Submit a bracket order. Must include entry, stop loss, take profit."""

    @abstractmethod
    async def close_position(self, trade_id: int, reason: str = "MANUAL") -> bool:
        """Close a specific open position by trade_id."""

    @abstractmethod
    async def cancel_all_orders(self) -> bool:
        """Cancel all pending/open orders."""

    @abstractmethod
    async def flatten_all(self, reason: str = "EOD_FLATTEN") -> bool:
        """
        Emergency: close ALL open positions immediately at market.
        Called by EOD job and emergency kill switch.
        """

    @abstractmethod
    async def check_and_update_positions(self, current_prices: dict[str, float]) -> list[dict]:
        """
        Evaluate open positions against current prices.
        Close positions that hit SL or TP.
        Returns list of closed trade dicts with P&L.
        """
