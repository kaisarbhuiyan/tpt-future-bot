import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Optional
import logging

import pandas as pd
import yfinance as yf

from app.data.normalizer import INSTRUMENT_SPECS, Candle

logger = logging.getLogger(__name__)

TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "1h": "1h",
}

YFINANCE_PERIOD_MAP = {
    "1m": "7d",
    "5m": "60d",
    "15m": "60d",
    "1h": "730d",
}


class DataFetcher(ABC):
    @abstractmethod
    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        bars: int = 200,
    ) -> pd.DataFrame:
        """Fetch OHLCV data. Returns DataFrame with columns: open, high, low, close, volume."""

    @abstractmethod
    async def get_latest_price(self, symbol: str) -> float:
        """Get the most recent price for a symbol."""


class YFinanceFetcher(DataFetcher):
    """
    Free market data fetcher using yfinance.
    Suitable for paper trading and backtesting.
    Note: yfinance data may be 15-min delayed for intraday.
    """

    def _get_yf_symbol(self, symbol: str) -> str:
        spec = INSTRUMENT_SPECS.get(symbol.upper())
        if spec is None:
            raise ValueError(f"Unknown symbol: {symbol}")
        return spec["yfinance_symbol"]

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "5m",
        bars: int = 200,
    ) -> pd.DataFrame:
        yf_symbol = self._get_yf_symbol(symbol)
        interval = TIMEFRAME_MAP.get(timeframe, "5m")
        period = YFINANCE_PERIOD_MAP.get(timeframe, "60d")

        loop = asyncio.get_event_loop()
        df = await loop.run_in_executor(
            None,
            lambda: yf.download(
                yf_symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            ),
        )

        if df.empty:
            logger.warning(f"No data returned from yfinance for {yf_symbol}")
            return pd.DataFrame()

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        })
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df.index = pd.to_datetime(df.index)
        df = df.tail(bars)
        df.attrs["symbol"] = symbol
        df.attrs["timeframe"] = timeframe
        return df

    async def get_latest_price(self, symbol: str) -> float:
        df = await self.fetch_ohlcv(symbol, timeframe="1m", bars=2)
        if df.empty:
            raise RuntimeError(f"Could not fetch latest price for {symbol}")
        return float(df["close"].iloc[-1])


class TradovateDataFetcher(DataFetcher):
    """
    Tradovate real-time data fetcher.
    Stub — requires active Tradovate credentials and websocket connection.
    Used when ENABLE_LIVE_TRADING=true and live_broker=tradovate.
    """

    def __init__(self, broker_adapter=None):
        self._broker = broker_adapter

    async def fetch_ohlcv(self, symbol: str, timeframe: str = "5m", bars: int = 200) -> pd.DataFrame:
        raise NotImplementedError(
            "TradovateDataFetcher requires a live Tradovate connection. "
            "Set up Tradovate credentials in .env and use a live broker adapter."
        )

    async def get_latest_price(self, symbol: str) -> float:
        raise NotImplementedError(
            "TradovateDataFetcher requires a live Tradovate connection."
        )


def create_fetcher(live_trading_enabled: bool = False) -> DataFetcher:
    """Factory: returns appropriate fetcher based on trading mode."""
    if live_trading_enabled:
        logger.warning("Live trading mode: using Tradovate data fetcher")
        return TradovateDataFetcher()
    return YFinanceFetcher()
