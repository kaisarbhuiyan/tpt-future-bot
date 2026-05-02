import pandas as pd
import numpy as np


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range using Wilder's smoothing.
    df must have columns: high, low, close.
    """
    high = df["high"]
    low = df["low"]
    close_prev = df["close"].shift(1)

    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()

    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = true_range.ewm(alpha=1 / period, adjust=False).mean()
    return atr


def atr_as_pct(atr: float, close: float) -> float:
    """ATR expressed as percentage of current price."""
    if close == 0:
        return 0.0
    return (atr / close) * 100


def volatility_label(atr_pct: float) -> str:
    """Classify current volatility level."""
    if atr_pct < 0.1:
        return "very_low"
    elif atr_pct < 0.25:
        return "low"
    elif atr_pct < 0.5:
        return "normal"
    elif atr_pct < 1.0:
        return "elevated"
    else:
        return "high"
