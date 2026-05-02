import pandas as pd
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def compute_vwap(df: pd.DataFrame) -> pd.Series:
    """
    Session-anchored VWAP. Resets at the start of each trading day.
    df must have columns: high, low, close, volume and a DatetimeIndex.
    """
    if df.empty:
        return pd.Series(dtype=float)

    df = df.copy()
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC").tz_convert(EASTERN)
    else:
        df.index = df.index.tz_convert(EASTERN)

    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    df["_tp"] = typical_price
    df["_tpv"] = typical_price * df["volume"]
    df["_date"] = df.index.date

    vwap = pd.Series(index=df.index, dtype=float)
    for day, group in df.groupby("_date"):
        cumvol = group["volume"].cumsum()
        cumtpv = group["_tpv"].cumsum()
        vwap.loc[group.index] = cumtpv / cumvol.replace(0, float("nan"))

    return vwap


def price_vs_vwap(close: float, vwap: float) -> str:
    """Returns 'above', 'below', or 'at' relative to VWAP."""
    if vwap == 0 or pd.isna(vwap):
        return "unknown"
    diff_pct = (close - vwap) / vwap * 100
    if diff_pct > 0.05:
        return "above"
    elif diff_pct < -0.05:
        return "below"
    return "at"
