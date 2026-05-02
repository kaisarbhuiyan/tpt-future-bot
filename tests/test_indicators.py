"""
Unit tests for technical indicator calculations.
Uses synthetic price data — no network calls.
"""

import pytest
import pandas as pd
import numpy as np

from app.indicators.ema import compute_ema, ema_stack_direction
from app.indicators.rsi import compute_rsi, rsi_signal
from app.indicators.macd import compute_macd, macd_momentum
from app.indicators.atr import compute_atr, atr_as_pct
from app.indicators.bollinger import compute_bollinger, bb_pct, bb_width
from app.indicators.volume import compute_relative_volume, volume_trend


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def make_close_series(n: int = 100, start: float = 5000.0, trend: float = 1.0) -> pd.Series:
    """Generate synthetic closing prices with a gentle trend."""
    prices = [start + i * trend + np.random.normal(0, 2) for i in range(n)]
    return pd.Series(prices, dtype=float)


def make_ohlcv(n: int = 100, start: float = 5000.0) -> pd.DataFrame:
    close = make_close_series(n, start)
    high = close + np.random.uniform(1, 5, n)
    low = close - np.random.uniform(1, 5, n)
    open_ = close + np.random.uniform(-2, 2, n)
    volume = np.random.uniform(1000, 5000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


# ------------------------------------------------------------------ #
# EMA Tests
# ------------------------------------------------------------------ #

class TestEMA:
    def test_ema_returns_series_of_same_length(self):
        close = make_close_series()
        ema = compute_ema(close, 9)
        assert len(ema) == len(close)

    def test_ema_last_value_is_finite(self):
        close = make_close_series()
        ema = compute_ema(close, 9)
        assert np.isfinite(ema.iloc[-1])

    def test_ema_approaches_price_in_flat_market(self):
        close = pd.Series([100.0] * 200)
        ema = compute_ema(close, 9)
        assert abs(ema.iloc[-1] - 100.0) < 0.001

    def test_ema_stack_direction_full_bull(self):
        is_bull, is_bear, label = ema_stack_direction(210, 200, 190, 180)
        assert is_bull
        assert not is_bear
        assert label == "full_bull"

    def test_ema_stack_direction_full_bear(self):
        is_bull, is_bear, label = ema_stack_direction(180, 190, 200, 210)
        assert not is_bull
        assert is_bear
        assert label == "full_bear"

    def test_ema_stack_direction_partial_bull(self):
        is_bull, is_bear, label = ema_stack_direction(210, 200, 190, 215)
        assert is_bull
        assert label == "partial_bull"

    def test_ema_stack_direction_mixed(self):
        is_bull, is_bear, label = ema_stack_direction(200, 210, 195, 205)
        assert label == "mixed"


# ------------------------------------------------------------------ #
# RSI Tests
# ------------------------------------------------------------------ #

class TestRSI:
    def test_rsi_bounds(self):
        close = make_close_series(100)
        rsi = compute_rsi(close, 14)
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_overbought_after_sustained_rally(self):
        # Use 100 bars so Wilder smoothing (alpha=1/14) converges fully
        close = pd.Series([100.0 + i * 2 for i in range(100)])
        rsi = compute_rsi(close, 14)
        assert rsi.iloc[-1] > 70

    def test_rsi_oversold_after_sustained_decline(self):
        close = pd.Series([200.0 - i * 2 for i in range(50)])
        rsi = compute_rsi(close, 14)
        assert rsi.iloc[-1] < 30

    def test_rsi_signal_labels(self):
        assert rsi_signal(75) == "overbought"
        assert rsi_signal(25) == "oversold"
        assert rsi_signal(50) == "neutral"
        assert rsi_signal(65) == "bullish_momentum"

    def test_rsi_neutral_market(self):
        prices = []
        for i in range(100):
            prices.append(100.0 + (1 if i % 2 == 0 else -1))
        close = pd.Series(prices, dtype=float)
        rsi = compute_rsi(close, 14)
        last = rsi.iloc[-1]
        assert 40 <= last <= 60


# ------------------------------------------------------------------ #
# MACD Tests
# ------------------------------------------------------------------ #

class TestMACD:
    def test_macd_returns_three_series(self):
        close = make_close_series()
        macd_line, signal_line, hist = compute_macd(close)
        assert len(macd_line) == len(close)
        assert len(signal_line) == len(close)
        assert len(hist) == len(close)

    def test_histogram_equals_macd_minus_signal(self):
        close = make_close_series()
        macd_line, signal_line, hist = compute_macd(close)
        expected_hist = macd_line - signal_line
        diff = (hist - expected_hist).abs().max()
        assert diff < 1e-10

    def test_macd_momentum_bullish(self):
        hist = pd.Series([0.1, 0.2, 0.3, 0.5])
        assert macd_momentum(hist) == "bullish"

    def test_macd_momentum_bearish(self):
        hist = pd.Series([-0.1, -0.2, -0.4, -0.6])
        assert macd_momentum(hist) == "bearish"


# ------------------------------------------------------------------ #
# ATR Tests
# ------------------------------------------------------------------ #

class TestATR:
    def test_atr_is_positive(self):
        df = make_ohlcv(50)
        atr = compute_atr(df, 14)
        assert (atr.dropna() > 0).all()

    def test_atr_increases_with_volatility(self):
        df_low_vol = make_ohlcv(50, start=5000.0)
        df_low_vol["high"] = df_low_vol["close"] + 1
        df_low_vol["low"] = df_low_vol["close"] - 1

        df_high_vol = make_ohlcv(50, start=5000.0)
        df_high_vol["high"] = df_high_vol["close"] + 50
        df_high_vol["low"] = df_high_vol["close"] - 50

        atr_low = compute_atr(df_low_vol, 14).iloc[-1]
        atr_high = compute_atr(df_high_vol, 14).iloc[-1]
        assert atr_high > atr_low

    def test_atr_pct_is_reasonable(self):
        df = make_ohlcv(50, start=5000.0)
        atr = compute_atr(df, 14).iloc[-1]
        pct = atr_as_pct(atr, 5000.0)
        assert 0 <= pct <= 5.0  # Reasonable range


# ------------------------------------------------------------------ #
# Bollinger Bands Tests
# ------------------------------------------------------------------ #

class TestBollinger:
    def test_upper_above_lower(self):
        close = make_close_series()
        mid, upper, lower = compute_bollinger(close, 20, 2.0)
        valid_idx = mid.dropna().index
        assert (upper[valid_idx] > lower[valid_idx]).all()

    def test_bb_pct_at_lower_band_is_zero(self):
        pct = bb_pct(close=100.0, upper=110.0, lower=100.0)
        assert pct == 0.0

    def test_bb_pct_at_upper_band_is_one(self):
        pct = bb_pct(close=110.0, upper=110.0, lower=100.0)
        assert pct == 1.0

    def test_bb_width_increases_with_volatility(self):
        close_low = pd.Series([100.0] * 30)
        close_high = pd.Series([100.0 + np.random.normal(0, 5) for _ in range(30)])
        _, up_low, lo_low = compute_bollinger(close_low, 20, 2.0)
        _, up_high, lo_high = compute_bollinger(close_high, 20, 2.0)
        width_low = bb_width(up_low.iloc[-1], lo_low.iloc[-1], 100.0)
        width_high = bb_width(up_high.iloc[-1], lo_high.iloc[-1], 100.0)
        assert width_high > width_low


# ------------------------------------------------------------------ #
# Volume Tests
# ------------------------------------------------------------------ #

class TestVolume:
    def test_relative_volume_near_one_for_stable_volume(self):
        vol = pd.Series([1000.0] * 30)
        rel = compute_relative_volume(vol, 20)
        assert abs(rel.iloc[-1] - 1.0) < 0.01

    def test_relative_volume_above_one_for_spike(self):
        vol = pd.Series([1000.0] * 29 + [5000.0])
        rel = compute_relative_volume(vol, 20)
        assert rel.iloc[-1] > 1.5

    def test_volume_trend_increasing(self):
        vol = pd.Series([100, 200, 300, 400, 500], dtype=float)
        result = volume_trend(vol, bars=3)
        assert result == "increasing"

    def test_volume_trend_decreasing(self):
        vol = pd.Series([500, 400, 300, 200, 100], dtype=float)
        result = volume_trend(vol, bars=3)
        assert result == "decreasing"

    def test_volume_trend_flat(self):
        vol = pd.Series([1000.0] * 5)
        result = volume_trend(vol, bars=3)
        assert result == "flat"
