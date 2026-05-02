import pandas as pd
from app.indicators.ema import compute_ema


def compute_macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (macd_line, signal_line, histogram).
    Standard MACD(12, 26, 9).
    """
    ema_fast = compute_ema(series, fast)
    ema_slow = compute_ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = compute_ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def macd_momentum(histogram: pd.Series) -> str:
    """
    Returns 'bullish', 'bearish', or 'neutral' based on histogram trend.
    Looks at last 2 bars.
    """
    if len(histogram) < 2:
        return "neutral"
    last = histogram.iloc[-1]
    prev = histogram.iloc[-2]
    if pd.isna(last) or pd.isna(prev):
        return "neutral"
    if last > 0 and last > prev:
        return "bullish"
    elif last < 0 and last < prev:
        return "bearish"
    elif last > 0:
        return "bullish_weakening"
    elif last < 0:
        return "bearish_weakening"
    return "neutral"
