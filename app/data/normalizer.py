from dataclasses import dataclass
from datetime import datetime


INSTRUMENT_SPECS: dict[str, dict] = {
    "ES": {
        "tick_size": 0.25,
        "tick_value": 12.50,
        "point_value": 50.0,
        "yfinance_symbol": "ES=F",
        "full_name": "E-mini S&P 500",
    },
    "NQ": {
        "tick_size": 0.25,
        "tick_value": 5.00,
        "point_value": 20.0,
        "yfinance_symbol": "NQ=F",
        "full_name": "E-mini Nasdaq-100",
    },
}


@dataclass
class Candle:
    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


def get_instrument_spec(symbol: str) -> dict:
    spec = INSTRUMENT_SPECS.get(symbol.upper())
    if spec is None:
        raise ValueError(f"Unknown instrument: {symbol}. Allowed: {list(INSTRUMENT_SPECS.keys())}")
    return spec


def dollars_to_ticks(symbol: str, dollars: float) -> float:
    spec = get_instrument_spec(symbol)
    return dollars / spec["tick_value"]


def ticks_to_dollars(symbol: str, ticks: float) -> float:
    spec = get_instrument_spec(symbol)
    return ticks * spec["tick_value"]


def points_to_dollars(symbol: str, points: float, contracts: int = 1) -> float:
    spec = get_instrument_spec(symbol)
    return points * spec["point_value"] * contracts


def round_to_tick(symbol: str, price: float) -> float:
    spec = get_instrument_spec(symbol)
    tick = spec["tick_size"]
    return round(round(price / tick) * tick, 4)
