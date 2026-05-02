from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NO_TRADE = "NO_TRADE"


@dataclass
class ScoreBreakdown:
    """Detailed scoring for signal transparency."""
    trend_score: float = 0.0        # EMA stack (max 25)
    momentum_score: float = 0.0     # RSI + MACD (max 25)
    structure_score: float = 0.0    # HH/LL, BoS, CHoCH (max 20)
    vwap_score: float = 0.0         # VWAP position (max 15)
    volume_score: float = 0.0       # Relative volume (max 10)
    volatility_score: float = 0.0   # ATR, BB filter (max 5)
    total: float = 0.0


@dataclass
class TradeSignal:
    symbol: str
    direction: SignalDirection
    confidence: float               # 0–100 composite score
    reason: str                     # Human-readable explanation
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Risk levels
    entry_price: float = 0.0
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    invalidation_level: Optional[float] = None
    risk_reward: float = 0.0

    # Metadata
    timeframe: str = "5m"
    score_breakdown: Optional[ScoreBreakdown] = None

    def is_tradeable(self) -> bool:
        """Signal is only tradeable if direction is BUY or SELL (not NO_TRADE)."""
        return self.direction in (SignalDirection.BUY, SignalDirection.SELL)

    def has_complete_levels(self) -> bool:
        """True if stop loss and take profit are set."""
        return self.stop_loss is not None and self.take_profit is not None
