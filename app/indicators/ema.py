import pandas as pd


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average using standard EWM (span-based)."""
    return series.ewm(span=period, adjust=False).mean()


def ema_stack_direction(
    ema9: float, ema21: float, ema50: float, ema200: float
) -> tuple[bool, bool, str]:
    """
    Returns (is_bullish, is_bearish, label).
    Full bull: ema9 > ema21 > ema50 > ema200
    Full bear: ema9 < ema21 < ema50 < ema200
    """
    full_bull = ema9 > ema21 > ema50 > ema200
    full_bear = ema9 < ema21 < ema50 < ema200
    partial_bull = ema9 > ema21 > ema50
    partial_bear = ema9 < ema21 < ema50

    if full_bull:
        return True, False, "full_bull"
    elif full_bear:
        return False, True, "full_bear"
    elif partial_bull:
        return True, False, "partial_bull"
    elif partial_bear:
        return False, True, "partial_bear"
    else:
        return False, False, "mixed"
