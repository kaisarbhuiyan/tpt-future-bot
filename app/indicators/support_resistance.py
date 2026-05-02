import pandas as pd
import numpy as np
from typing import Optional


def find_pivot_highs(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Find pivot highs (local maxima) requiring left and right confirmation bars."""
    highs = df["high"]
    pivot_highs = pd.Series(False, index=highs.index)
    for i in range(left, len(highs) - right):
        window = highs.iloc[i - left: i + right + 1]
        if highs.iloc[i] == window.max():
            pivot_highs.iloc[i] = True
    return pivot_highs


def find_pivot_lows(df: pd.DataFrame, left: int = 5, right: int = 5) -> pd.Series:
    """Find pivot lows (local minima) requiring left and right confirmation bars."""
    lows = df["low"]
    pivot_lows = pd.Series(False, index=lows.index)
    for i in range(left, len(lows) - right):
        window = lows.iloc[i - left: i + right + 1]
        if lows.iloc[i] == window.min():
            pivot_lows.iloc[i] = True
    return pivot_lows


def get_key_levels(
    df: pd.DataFrame,
    left: int = 5,
    right: int = 5,
    max_levels: int = 5,
) -> tuple[list[float], list[float]]:
    """
    Returns (support_levels, resistance_levels) sorted by proximity to current price.
    support_levels: recent pivot lows below current price
    resistance_levels: recent pivot highs above current price
    """
    if len(df) < left + right + 1:
        return [], []

    current_price = df["close"].iloc[-1]

    ph = find_pivot_highs(df, left, right)
    pl = find_pivot_lows(df, left, right)

    resistance = sorted(
        [float(df["high"].iloc[i]) for i, v in enumerate(ph) if v and df["high"].iloc[i] > current_price],
        key=lambda x: x - current_price,
    )[:max_levels]

    support = sorted(
        [float(df["low"].iloc[i]) for i, v in enumerate(pl) if v and df["low"].iloc[i] < current_price],
        key=lambda x: current_price - x,
    )[:max_levels]

    return support, resistance


def nearest_support(df: pd.DataFrame) -> Optional[float]:
    """Return the nearest support level below current price."""
    supports, _ = get_key_levels(df)
    return supports[0] if supports else None


def nearest_resistance(df: pd.DataFrame) -> Optional[float]:
    """Return the nearest resistance level above current price."""
    _, resistances = get_key_levels(df)
    return resistances[0] if resistances else None


def distance_to_level(price: float, level: float) -> float:
    """Absolute distance between price and a S/R level."""
    return abs(price - level)
