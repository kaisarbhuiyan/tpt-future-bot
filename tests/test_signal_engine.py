"""
Unit tests for the AI signal engine scoring logic.
Uses synthetic IndicatorSnapshot data — no market data fetching.
"""

import pytest
from app.ai.models import SignalDirection
from app.ai.signal_engine import SignalEngine
from app.indicators.engine import IndicatorSnapshot

BASE_CONFIG = {
    "risk": {
        "min_confidence_score": 65,
        "min_risk_reward_ratio": 2.0,
        "atr_stop_multiplier": 1.5,
        "atr_tp_multiplier": 3.0,
    },
}


def make_snapshot(**kwargs) -> IndicatorSnapshot:
    """Create a valid IndicatorSnapshot with sensible defaults."""
    defaults = dict(
        symbol="ES",
        timeframe="5m",
        current_price=5000.0,
        ema9=5010.0,
        ema21=5005.0,
        ema50=4990.0,
        ema200=4950.0,
        ema_stack_label="full_bull",
        ema_bullish=True,
        ema_bearish=False,
        vwap=4998.0,
        price_vs_vwap="above",
        rsi=55.0,
        rsi_signal="bullish_momentum",
        macd_line=2.0,
        macd_signal_line=1.5,
        macd_histogram=0.5,
        macd_momentum="bullish",
        atr=8.0,
        atr_pct=0.16,
        volatility_label="normal",
        bb_upper=5020.0,
        bb_lower=4980.0,
        bb_middle=5000.0,
        bb_width_val=0.008,
        bb_pct_val=0.5,
        relative_volume=1.3,
        volume_trend="increasing",
        nearest_support=4985.0,
        nearest_resistance=5020.0,
        structure="uptrend",
        last_bos="bullish",
        last_choch=None,
        swing_highs=[4990.0, 5010.0],
        swing_lows=[4970.0, 4985.0],
        orb_high=5015.0,
        orb_low=4990.0,
    )
    defaults.update(kwargs)
    snap = IndicatorSnapshot.__new__(IndicatorSnapshot)
    snap.__dict__.update(defaults)
    return snap


class TestSignalEngine:
    def setup_method(self):
        self.engine = SignalEngine()

    def test_strong_bull_setup_produces_buy_signal(self):
        snap = make_snapshot()
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert signal.direction == SignalDirection.BUY

    def test_strong_bear_setup_produces_sell_signal(self):
        snap = make_snapshot(
            ema9=4990.0, ema21=4995.0, ema50=5010.0, ema200=5050.0,
            ema_stack_label="full_bear", ema_bullish=False, ema_bearish=True,
            price_vs_vwap="below",
            rsi=42.0, rsi_signal="bearish_momentum",
            macd_histogram=-0.5, macd_momentum="bearish",
            structure="downtrend", last_bos="bearish",
        )
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert signal.direction == SignalDirection.SELL

    def test_no_trade_when_confidence_below_threshold(self):
        # Mixed signals → low confidence → NO_TRADE
        snap = make_snapshot(
            ema_stack_label="mixed", ema_bullish=False, ema_bearish=False,
            price_vs_vwap="at",
            rsi=50.0,
            macd_histogram=0.0, macd_momentum="neutral",
            structure="ranging", last_bos=None,
            relative_volume=0.7,
        )
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert signal.direction == SignalDirection.NO_TRADE

    def test_signal_has_stop_loss_and_take_profit_for_buy(self):
        snap = make_snapshot()
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        if signal.direction == SignalDirection.BUY:
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.stop_loss < signal.entry_price
            assert signal.take_profit > signal.entry_price

    def test_signal_has_stop_loss_and_take_profit_for_sell(self):
        snap = make_snapshot(
            ema9=4990.0, ema21=4995.0, ema50=5010.0, ema200=5050.0,
            ema_stack_label="full_bear", ema_bullish=False, ema_bearish=True,
            price_vs_vwap="below",
            rsi=42.0, macd_histogram=-0.5, macd_momentum="bearish",
            structure="downtrend", last_bos="bearish",
        )
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        if signal.direction == SignalDirection.SELL:
            assert signal.stop_loss is not None
            assert signal.take_profit is not None
            assert signal.stop_loss > signal.entry_price
            assert signal.take_profit < signal.entry_price

    def test_risk_reward_at_least_min_rr_when_tradeable(self):
        snap = make_snapshot()
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        if signal.is_tradeable():
            min_rr = BASE_CONFIG["risk"]["min_risk_reward_ratio"]
            assert signal.risk_reward >= min_rr

    def test_no_trade_when_insufficient_bars(self):
        snap = make_snapshot(atr=0.0, ema200=0.0)  # is_valid() returns False
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert signal.direction == SignalDirection.NO_TRADE

    def test_confidence_score_is_within_range(self):
        snap = make_snapshot()
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert 0.0 <= signal.confidence <= 100.0

    def test_buy_score_higher_for_full_bull(self):
        snap_bull = make_snapshot(
            ema_stack_label="full_bull", ema_bullish=True,
            price_vs_vwap="above", rsi=55.0,
            macd_histogram=0.5, macd_momentum="bullish",
            structure="uptrend", last_bos="bullish",
        )
        snap_partial = make_snapshot(
            ema_stack_label="partial_bull", ema_bullish=True,
            price_vs_vwap="at", rsi=50.0,
            macd_histogram=0.1, macd_momentum="neutral",
            structure="ranging", last_bos=None,
        )
        buy_bull, _, _ = self.engine._score_buy(snap_bull)
        buy_partial, _, _ = self.engine._score_buy(snap_partial)
        assert buy_bull > buy_partial

    def test_reason_string_is_non_empty_for_tradeable_signal(self):
        snap = make_snapshot()
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        if signal.is_tradeable():
            assert len(signal.reason) > 0

    def test_signal_symbol_matches_snapshot_symbol(self):
        snap = make_snapshot(symbol="NQ")
        signal = self.engine.generate_signal(snap, BASE_CONFIG)
        assert signal.symbol == "NQ"

    def test_no_trade_returned_as_non_tradeable(self):
        signal = self.engine._no_trade(
            make_snapshot(), "Test reason", BASE_CONFIG
        )
        assert not signal.is_tradeable()
        assert signal.direction == SignalDirection.NO_TRADE
