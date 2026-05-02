import pandas as pd
import numpy as np


def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """
    RSI using Wilder's smoothing (equivalent to RMA/EWM with alpha=1/period).
    Returns values in [0, 100].
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    # When avg_loss = 0: all moves were gains → RSI = 100
    # When avg_gain = 0: all moves were losses → RSI = 0
    rsi = pd.Series(50.0, index=series.index, dtype=float)
    both_zero = (avg_gain == 0) & (avg_loss == 0)
    only_gains = (avg_loss == 0) & (avg_gain > 0)
    only_losses = (avg_gain == 0) & (avg_loss > 0)
    normal = (avg_gain > 0) | (avg_loss > 0)

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi_normal = 100 - (100 / (1 + rs))

    rsi = rsi_normal
    rsi[only_gains] = 100.0
    rsi[only_losses] = 0.0
    rsi[both_zero] = float("nan")
    return rsi


def rsi_signal(rsi: float) -> str:
    """Classify RSI zone."""
    if pd.isna(rsi):
        return "unknown"
    if rsi >= 70:
        return "overbought"
    elif rsi <= 30:
        return "oversold"
    elif 40 <= rsi <= 60:
        return "neutral"
    elif rsi > 60:
        return "bullish_momentum"
    else:
        return "bearish_momentum"
