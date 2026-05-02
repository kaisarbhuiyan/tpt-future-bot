from dataclasses import dataclass, field
from typing import Optional
import pandas as pd

from app.indicators.ema import compute_ema, ema_stack_direction
from app.indicators.vwap import compute_vwap, price_vs_vwap
from app.indicators.rsi import compute_rsi, rsi_signal
from app.indicators.macd import compute_macd, macd_momentum
from app.indicators.atr import compute_atr, atr_as_pct, volatility_label
from app.indicators.bollinger import compute_bollinger, bb_width, bb_pct
from app.indicators.volume import compute_relative_volume, volume_trend
from app.indicators.support_resistance import nearest_support, nearest_resistance
from app.indicators.market_structure import detect_market_structure, detect_opening_range


@dataclass
class IndicatorSnapshot:
    symbol: str
    timeframe: str
    current_price: float

    # EMA
    ema9: float = 0.0
    ema21: float = 0.0
    ema50: float = 0.0
    ema200: float = 0.0
    ema_stack_label: str = "mixed"
    ema_bullish: bool = False
    ema_bearish: bool = False

    # VWAP
    vwap: float = 0.0
    price_vs_vwap: str = "unknown"

    # RSI
    rsi: float = 50.0
    rsi_signal: str = "neutral"

    # MACD
    macd_line: float = 0.0
    macd_signal_line: float = 0.0
    macd_histogram: float = 0.0
    macd_momentum: str = "neutral"

    # ATR
    atr: float = 0.0
    atr_pct: float = 0.0
    volatility_label: str = "normal"

    # Bollinger Bands
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    bb_width_val: float = 0.0
    bb_pct_val: float = 0.5

    # Volume
    relative_volume: float = 1.0
    volume_trend: str = "flat"

    # Support / Resistance
    nearest_support: Optional[float] = None
    nearest_resistance: Optional[float] = None

    # Market Structure
    structure: str = "ranging"
    last_bos: Optional[str] = None
    last_choch: Optional[str] = None
    swing_highs: list = field(default_factory=list)
    swing_lows: list = field(default_factory=list)

    # Opening Range Breakout
    orb_high: Optional[float] = None
    orb_low: Optional[float] = None

    def is_valid(self) -> bool:
        """True if enough data was available to compute meaningful values."""
        return self.atr > 0 and self.ema200 > 0


class IndicatorEngine:
    """
    Central engine that takes a raw OHLCV DataFrame and returns a fully populated
    IndicatorSnapshot. All indicator computations are pure-function, stateless.
    """

    def compute(self, df: pd.DataFrame, symbol: str, timeframe: str = "5m") -> IndicatorSnapshot:
        if len(df) < 50:
            return IndicatorSnapshot(
                symbol=symbol,
                timeframe=timeframe,
                current_price=float(df["close"].iloc[-1]) if not df.empty else 0.0,
            )

        close = df["close"]
        current_price = float(close.iloc[-1])

        snap = IndicatorSnapshot(
            symbol=symbol,
            timeframe=timeframe,
            current_price=current_price,
        )

        # EMAs
        ema9_s = compute_ema(close, 9)
        ema21_s = compute_ema(close, 21)
        ema50_s = compute_ema(close, 50)
        ema200_s = compute_ema(close, 200) if len(df) >= 200 else compute_ema(close, len(df))

        snap.ema9 = float(ema9_s.iloc[-1])
        snap.ema21 = float(ema21_s.iloc[-1])
        snap.ema50 = float(ema50_s.iloc[-1])
        snap.ema200 = float(ema200_s.iloc[-1])
        snap.ema_bullish, snap.ema_bearish, snap.ema_stack_label = ema_stack_direction(
            snap.ema9, snap.ema21, snap.ema50, snap.ema200
        )

        # VWAP
        try:
            vwap_s = compute_vwap(df)
            snap.vwap = float(vwap_s.iloc[-1]) if not vwap_s.empty else 0.0
        except Exception:
            snap.vwap = float(close.rolling(20).mean().iloc[-1])
        snap.price_vs_vwap = price_vs_vwap(current_price, snap.vwap)

        # RSI
        rsi_s = compute_rsi(close, 14)
        snap.rsi = float(rsi_s.iloc[-1]) if not rsi_s.empty else 50.0
        snap.rsi_signal = rsi_signal(snap.rsi)

        # MACD
        macd_l, macd_sig, macd_hist = compute_macd(close)
        snap.macd_line = float(macd_l.iloc[-1]) if not macd_l.empty else 0.0
        snap.macd_signal_line = float(macd_sig.iloc[-1]) if not macd_sig.empty else 0.0
        snap.macd_histogram = float(macd_hist.iloc[-1]) if not macd_hist.empty else 0.0
        snap.macd_momentum = macd_momentum(macd_hist)

        # ATR
        atr_s = compute_atr(df, 14)
        snap.atr = float(atr_s.iloc[-1]) if not atr_s.empty else 0.0
        snap.atr_pct = atr_as_pct(snap.atr, current_price)
        snap.volatility_label = volatility_label(snap.atr_pct)

        # Bollinger Bands
        bb_mid, bb_up, bb_lo = compute_bollinger(close, 20, 2.0)
        snap.bb_middle = float(bb_mid.iloc[-1]) if not bb_mid.empty else current_price
        snap.bb_upper = float(bb_up.iloc[-1]) if not bb_up.empty else current_price
        snap.bb_lower = float(bb_lo.iloc[-1]) if not bb_lo.empty else current_price
        snap.bb_width_val = bb_width(snap.bb_upper, snap.bb_lower, snap.bb_middle)
        snap.bb_pct_val = bb_pct(current_price, snap.bb_upper, snap.bb_lower)

        # Volume
        if "volume" in df.columns and df["volume"].sum() > 0:
            rel_vol_s = compute_relative_volume(df["volume"], 20)
            snap.relative_volume = float(rel_vol_s.iloc[-1]) if not rel_vol_s.empty else 1.0
            snap.volume_trend = volume_trend(df["volume"], 3)

        # Support / Resistance
        if len(df) >= 15:
            snap.nearest_support = nearest_support(df)
            snap.nearest_resistance = nearest_resistance(df)

        # Market Structure
        if len(df) >= 20:
            ms = detect_market_structure(df, lookback=5)
            snap.structure = ms["structure"]
            snap.last_bos = ms["last_bos"]
            snap.last_choch = ms["last_choch"]
            snap.swing_highs = ms["swing_highs"]
            snap.swing_lows = ms["swing_lows"]

        # Opening Range Breakout
        snap.orb_high, snap.orb_low = detect_opening_range(df, minutes=30)

        return snap
