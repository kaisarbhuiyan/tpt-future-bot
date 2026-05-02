import pandas as pd


def compute_relative_volume(
    volume_series: pd.Series,
    lookback: int = 20,
) -> pd.Series:
    """
    Relative volume = current volume / rolling average volume.
    Values > 1.0 mean above-average volume; < 1.0 means below-average.
    """
    avg_vol = volume_series.rolling(window=lookback).mean()
    rel_vol = volume_series / avg_vol.replace(0, float("nan"))
    return rel_vol


def volume_trend(volume_series: pd.Series, bars: int = 3) -> str:
    """
    Classify recent volume trend over last N bars.
    Returns 'increasing', 'decreasing', or 'flat'.
    """
    if len(volume_series) < bars + 1:
        return "flat"
    recent = volume_series.iloc[-bars:]
    slope = recent.iloc[-1] - recent.iloc[0]
    avg = recent.mean()
    if avg == 0:
        return "flat"
    change_pct = slope / avg
    if change_pct > 0.1:
        return "increasing"
    elif change_pct < -0.1:
        return "decreasing"
    return "flat"


def is_volume_confirming(
    rel_volume: float,
    direction: str,
    price_change_pct: float,
) -> bool:
    """
    True if volume confirms the price move.
    Requires above-average volume (>= 1.1x) when price makes a meaningful move.
    """
    if rel_volume >= 1.1 and abs(price_change_pct) > 0.05:
        return True
    return False
