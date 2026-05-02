import pandas as pd


def compute_bollinger(
    series: pd.Series,
    period: int = 20,
    std_dev: float = 2.0,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    Returns (middle, upper, lower).
    Middle = SMA(period), Bands = middle ± std_dev * rolling_std.
    """
    middle = series.rolling(window=period).mean()
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return middle, upper, lower


def bb_width(upper: float, lower: float, middle: float) -> float:
    """Bollinger Band Width — measure of current volatility."""
    if middle == 0:
        return 0.0
    return (upper - lower) / middle


def bb_pct(close: float, upper: float, lower: float) -> float:
    """
    %B: where price sits within the bands.
    0 = at lower band, 1 = at upper band, >1 = above upper, <0 = below lower.
    """
    band_range = upper - lower
    if band_range == 0:
        return 0.5
    return (close - lower) / band_range


def bb_squeeze(bb_width_series: pd.Series, lookback: int = 20) -> bool:
    """True if current BB width is at a multi-period low (squeeze condition)."""
    if len(bb_width_series) < lookback:
        return False
    current = bb_width_series.iloc[-1]
    historical_min = bb_width_series.iloc[-lookback:].min()
    return current <= historical_min * 1.05
