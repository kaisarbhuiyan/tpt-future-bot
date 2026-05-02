import logging
from datetime import datetime
from typing import Optional

import pandas as pd
from sqlalchemy import select, delete
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db_models import Candle as CandleModel

logger = logging.getLogger(__name__)


async def upsert_candles(session: AsyncSession, df: pd.DataFrame, symbol: str, timeframe: str) -> int:
    """
    Insert or update candles from a DataFrame.
    Returns number of rows written.
    """
    if df.empty:
        return 0

    rows = []
    for ts, row in df.iterrows():
        rows.append({
            "symbol": symbol.upper(),
            "timeframe": timeframe,
            "timestamp": ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row.get("volume", 0.0)),
            "created_at": datetime.utcnow(),
        })

    stmt = sqlite_insert(CandleModel).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["symbol", "timeframe", "timestamp"],
        set_={
            "open": stmt.excluded.open,
            "high": stmt.excluded.high,
            "low": stmt.excluded.low,
            "close": stmt.excluded.close,
            "volume": stmt.excluded.volume,
        },
    )
    await session.execute(stmt)
    await session.commit()
    logger.debug(f"Upserted {len(rows)} candles for {symbol}/{timeframe}")
    return len(rows)


async def load_candles(
    session: AsyncSession,
    symbol: str,
    timeframe: str,
    limit: int = 500,
) -> pd.DataFrame:
    """Load candles from DB and return as DataFrame."""
    stmt = (
        select(CandleModel)
        .where(CandleModel.symbol == symbol.upper())
        .where(CandleModel.timeframe == timeframe)
        .order_by(CandleModel.timestamp.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    candles = result.scalars().all()

    if not candles:
        return pd.DataFrame()

    rows = [
        {
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
        }
        for c in reversed(candles)
    ]
    df = pd.DataFrame(rows).set_index("timestamp")
    df.index = pd.to_datetime(df.index)
    return df


async def purge_old_candles(session: AsyncSession, days_to_keep: int = 90) -> int:
    """Remove candles older than N days to keep DB size manageable."""
    cutoff = datetime.utcnow() - pd.Timedelta(days=days_to_keep)
    stmt = delete(CandleModel).where(CandleModel.timestamp < cutoff)
    result = await session.execute(stmt)
    await session.commit()
    deleted = result.rowcount
    logger.info(f"Purged {deleted} candles older than {days_to_keep} days")
    return deleted
