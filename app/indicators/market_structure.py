import pandas as pd
from typing import Optional


def find_swing_highs(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Returns a boolean Series: True where a swing high is confirmed."""
    highs = df["high"]
    result = pd.Series(False, index=highs.index)
    for i in range(lookback, len(highs) - lookback):
        window = highs.iloc[i - lookback: i + lookback + 1]
        if highs.iloc[i] == window.max():
            result.iloc[i] = True
    return result


def find_swing_lows(df: pd.DataFrame, lookback: int = 5) -> pd.Series:
    """Returns a boolean Series: True where a swing low is confirmed."""
    lows = df["low"]
    result = pd.Series(False, index=lows.index)
    for i in range(lookback, len(lows) - lookback):
        window = lows.iloc[i - lookback: i + lookback + 1]
        if lows.iloc[i] == window.min():
            result.iloc[i] = True
    return result


def detect_market_structure(df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    Analyzes the last N swing points to determine market structure.

    Returns a dict with:
      structure: "uptrend" | "downtrend" | "ranging"
      last_bos: "bullish" | "bearish" | None  (Break of Structure)
      last_choch: "bullish" | "bearish" | None  (Change of Character)
      swing_highs: list of recent swing high prices
      swing_lows: list of recent swing low prices
    """
    if len(df) < lookback * 3:
        return {
            "structure": "ranging",
            "last_bos": None,
            "last_choch": None,
            "swing_highs": [],
            "swing_lows": [],
        }

    sh_mask = find_swing_highs(df, lookback)
    sl_mask = find_swing_lows(df, lookback)

    swing_highs = df["high"][sh_mask].tolist()
    swing_lows = df["low"][sl_mask].tolist()

    last_bos: Optional[str] = None
    last_choch: Optional[str] = None
    structure = "ranging"

    if len(swing_highs) >= 2 and len(swing_lows) >= 2:
        hh = swing_highs[-1] > swing_highs[-2]  # Higher High
        hl = swing_lows[-1] > swing_lows[-2]    # Higher Low
        lh = swing_highs[-1] < swing_highs[-2]  # Lower High
        ll = swing_lows[-1] < swing_lows[-2]    # Lower Low

        if hh and hl:
            structure = "uptrend"
            last_bos = "bullish"
        elif lh and ll:
            structure = "downtrend"
            last_bos = "bearish"
        elif hh and ll:
            # Expanding: mixed signals
            structure = "ranging"
        elif lh and hl:
            # Contracting: mixed signals
            structure = "ranging"

        # CHoCH: structure flip
        # Bearish CHoCH: was uptrend, now making lower low
        # Bullish CHoCH: was downtrend, now making higher high
        if structure == "ranging":
            if hh:
                last_choch = "bullish"
            elif ll:
                last_choch = "bearish"

    return {
        "structure": structure,
        "last_bos": last_bos,
        "last_choch": last_choch,
        "swing_highs": swing_highs[-5:],
        "swing_lows": swing_lows[-5:],
    }


def detect_opening_range(df: pd.DataFrame, minutes: int = 30) -> tuple[Optional[float], Optional[float]]:
    """
    Detect Opening Range Breakout (ORB) levels.
    Returns (orb_high, orb_low) for the first N minutes of the session.
    Returns (None, None) if insufficient data.
    """
    if df.empty:
        return None, None

    idx = df.index
    if idx.tz is None:
        from zoneinfo import ZoneInfo
        idx = idx.tz_localize("UTC").tz_convert(ZoneInfo("America/New_York"))
    else:
        from zoneinfo import ZoneInfo
        idx = idx.tz_convert(ZoneInfo("America/New_York"))

    today = idx[-1].date()
    session_open = pd.Timestamp(f"{today} 09:30:00", tz="America/New_York")
    session_orb_end = session_open + pd.Timedelta(minutes=minutes)

    df_copy = df.copy()
    df_copy.index = idx
    orb_df = df_copy[(df_copy.index >= session_open) & (df_copy.index <= session_orb_end)]

    if orb_df.empty:
        return None, None

    return float(orb_df["high"].max()), float(orb_df["low"].min())
