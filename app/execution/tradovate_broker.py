"""
TRADOVATE LIVE BROKER ADAPTER — STUB

This file is intentionally a stub. DO NOT activate without:
  1. ENABLE_LIVE_TRADING=true in .env
  2. live_trading_confirmed: true in config/rules.yaml
  3. Valid Tradovate API credentials in .env
  4. At least 5 days of successful paper trading

Tradovate API docs: https://api.tradovate.com
WebSocket feed: wss://md.tradovate.com/v1/websocket (market data)
REST endpoint demo: https://demo.tradovateapi.com/v1
REST endpoint live: https://live.tradovateapi.com/v1

Setup steps:
  1. Create Tradovate account at https://trader.tradovate.com
  2. Go to Account → API Access → Create App
  3. Copy credentials to .env
  4. Test with TRADOVATE_ENV=demo first
"""

import logging
import os
from app.execution.base_broker import BrokerAdapter, Order, OrderResult, OrderStatus, Position

logger = logging.getLogger(__name__)

BASE_URL_DEMO = "https://demo.tradovateapi.com/v1"
BASE_URL_LIVE = "https://live.tradovateapi.com/v1"


class TradovateBroker(BrokerAdapter):
    """
    Live Tradovate broker adapter.
    All methods raise NotImplementedError until fully implemented.
    The live trading gate check prevents accidental activation.
    """

    def __init__(self) -> None:
        env = os.getenv("TRADOVATE_ENV", "demo").lower()
        self._base_url = BASE_URL_DEMO if env == "demo" else BASE_URL_LIVE
        self._token: str | None = None
        logger.warning(
            f"TradovateBroker initialized in {env.upper()} mode. "
            f"Base URL: {self._base_url}"
        )

    def _check_live_gates(self) -> None:
        """Defensive check — both gates must be open before ANY live operation."""
        import os
        env_gate = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"
        if not env_gate:
            raise RuntimeError(
                "Live trading gate is CLOSED. "
                "Set ENABLE_LIVE_TRADING=true in .env to proceed."
            )

    async def connect(self) -> None:
        self._check_live_gates()
        raise NotImplementedError(
            "Tradovate connection not implemented. "
            "Implement OAuth token exchange using credentials from .env. "
            "See: https://api.tradovate.com/#operation/accessTokenRequest"
        )

    async def disconnect(self) -> None:
        logger.info("Tradovate broker disconnected (stub)")

    async def get_account_balance(self) -> float:
        self._check_live_gates()
        raise NotImplementedError("GET /account/list + /cashBalance/getCashBalanceSnapshot")

    async def get_positions(self) -> list[Position]:
        self._check_live_gates()
        raise NotImplementedError("GET /position/list")

    async def place_order(self, order: Order) -> OrderResult:
        self._check_live_gates()
        raise NotImplementedError(
            "POST /order/placeOrder with bracket legs. "
            "Use OSO (One Sends Other) for entry + SL + TP bracket. "
            "Ref: https://api.tradovate.com/#operation/placeOrder"
        )

    async def close_position(self, trade_id: int, reason: str = "MANUAL") -> bool:
        self._check_live_gates()
        raise NotImplementedError("POST /order/liquidatePosition")

    async def cancel_all_orders(self) -> bool:
        self._check_live_gates()
        raise NotImplementedError("POST /order/cancelOrder for each open order")

    async def flatten_all(self, reason: str = "EOD_FLATTEN") -> bool:
        self._check_live_gates()
        raise NotImplementedError(
            "Iterate positions and call liquidatePosition for each. "
            "Or use POST /order/cancelledByStrategy if using Tradovate strategies."
        )

    async def check_and_update_positions(self, current_prices: dict[str, float]) -> list[dict]:
        self._check_live_gates()
        raise NotImplementedError(
            "With live broker, SL/TP are server-side orders. "
            "Poll /position/list and /order/list to detect fills."
        )
