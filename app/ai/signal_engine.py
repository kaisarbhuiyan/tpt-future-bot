from datetime import datetime, timezone
from typing import Any
import logging
import math

from app.ai.models import SignalDirection, TradeSignal, ScoreBreakdown
from app.indicators.engine import IndicatorSnapshot
from app.data.normalizer import get_instrument_spec, round_to_tick

logger = logging.getLogger(__name__)


class SignalEngine:
    """
    Rule-based scoring engine for ES/NQ futures.

    NOT an LLM. Scores technical conditions using weighted rules.
    Every decision is deterministic, auditable, and configurable.

    Scoring weights (total = 100):
      Trend (EMA stack):     25 pts
      Momentum (RSI+MACD):   25 pts
      Structure (HH/LL/BoS): 20 pts
      VWAP position:         15 pts
      Volume confirmation:   10 pts
      Volatility filter:      5 pts
    """

    def generate_signal(
        self,
        snap: IndicatorSnapshot,
        config: dict,
    ) -> TradeSignal:
        """
        Analyze indicator snapshot and produce a TradeSignal.
        Always returns a signal — caller is responsible for rule-check filtering.
        """
        if not snap.is_valid():
            return self._no_trade(snap, "Insufficient indicator data (< 50 bars)", config)

        risk_cfg = config.get("risk", {})
        min_confidence = risk_cfg.get("min_confidence_score", 65)
        min_rr = risk_cfg.get("min_risk_reward_ratio", 2.0)
        atr_stop_mult = risk_cfg.get("atr_stop_multiplier", 1.5)
        atr_tp_mult = risk_cfg.get("atr_tp_multiplier", 3.0)

        buy_score, buy_breakdown, buy_reason = self._score_buy(snap)
        sell_score, sell_breakdown, sell_reason = self._score_sell(snap)

        direction, confidence, score_bd, reason_parts = self._pick_direction(
            buy_score, buy_breakdown, buy_reason,
            sell_score, sell_breakdown, sell_reason,
        )

        if direction == SignalDirection.NO_TRADE or confidence < min_confidence:
            return self._no_trade(
                snap,
                f"Confidence {confidence:.1f} below threshold {min_confidence}",
                config,
                confidence=confidence,
            )

        # Compute trade levels
        entry = snap.current_price
        spec = get_instrument_spec(snap.symbol)

        if direction == SignalDirection.BUY:
            sl = round_to_tick(snap.symbol, entry - snap.atr * atr_stop_mult)
            tp = round_to_tick(snap.symbol, entry + snap.atr * atr_tp_mult)
            invalidation = sl - snap.atr * 0.5
        else:
            sl = round_to_tick(snap.symbol, entry + snap.atr * atr_stop_mult)
            tp = round_to_tick(snap.symbol, entry - snap.atr * atr_tp_mult)
            invalidation = sl + snap.atr * 0.5

        # Risk/reward
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        rr = reward / risk if risk > 0 else 0.0

        if rr < min_rr:
            return self._no_trade(
                snap,
                f"R:R {rr:.2f} below minimum {min_rr}",
                config,
                confidence=confidence,
            )

        reason = " | ".join(reason_parts)

        return TradeSignal(
            symbol=snap.symbol,
            direction=direction,
            confidence=round(confidence, 2),
            reason=reason,
            timestamp=datetime.now(timezone.utc),
            entry_price=round(entry, 2),
            stop_loss=sl,
            take_profit=tp,
            invalidation_level=round(invalidation, 2),
            risk_reward=round(rr, 2),
            timeframe=snap.timeframe,
            score_breakdown=score_bd,
        )

    def _score_buy(self, snap: IndicatorSnapshot) -> tuple[float, ScoreBreakdown, list[str]]:
        score = ScoreBreakdown()
        reasons = []

        # --- Trend: EMA stack (max 25) ---
        if snap.ema_stack_label == "full_bull":
            score.trend_score = 25
            reasons.append("Full bullish EMA stack (9>21>50>200)")
        elif snap.ema_stack_label == "partial_bull":
            score.trend_score = 15
            reasons.append("Partial bullish EMA stack (9>21>50)")
        elif snap.ema_stack_label in ("full_bear", "partial_bear"):
            score.trend_score = 0
        else:
            score.trend_score = 5

        # Price above EMA50 bonus
        if snap.current_price > snap.ema50:
            score.trend_score = min(25, score.trend_score + 3)
            reasons.append("Price above EMA50")

        # --- Momentum: RSI + MACD (max 25) ---
        # RSI sweet spot for longs: 40–65 (not overbought)
        if 40 <= snap.rsi <= 65:
            score.momentum_score += 15
            reasons.append(f"RSI {snap.rsi:.1f} in bullish zone (40–65)")
        elif snap.rsi < 40 and snap.rsi > 30:
            score.momentum_score += 8
            reasons.append(f"RSI {snap.rsi:.1f} oversold bounce zone")
        elif snap.rsi > 70:
            score.momentum_score += 0  # overbought — no momentum credit

        if snap.macd_momentum in ("bullish",):
            score.momentum_score += 10
            reasons.append("MACD histogram positive and rising")
        elif snap.macd_momentum == "bullish_weakening":
            score.momentum_score += 4
        score.momentum_score = min(25, score.momentum_score)

        # --- Structure: market structure (max 20) ---
        if snap.structure == "uptrend" and snap.last_bos == "bullish":
            score.structure_score = 20
            reasons.append("Uptrend with bullish BoS confirmed")
        elif snap.structure == "uptrend":
            score.structure_score = 12
            reasons.append("Uptrend structure")
        elif snap.last_bos == "bullish":
            score.structure_score = 10
            reasons.append("Bullish Break of Structure")
        elif snap.last_choch == "bullish":
            score.structure_score = 8
            reasons.append("Bullish Change of Character (CHoCH)")
        score.structure_score = min(20, score.structure_score)

        # --- VWAP (max 15) ---
        if snap.price_vs_vwap == "above":
            score.vwap_score = 15
            reasons.append("Price above VWAP")
        elif snap.price_vs_vwap == "at":
            score.vwap_score = 8
        else:
            score.vwap_score = 0
        score.vwap_score = min(15, score.vwap_score)

        # --- Volume (max 10) ---
        if snap.relative_volume >= 1.5:
            score.volume_score = 10
            reasons.append(f"High relative volume ({snap.relative_volume:.1f}x avg)")
        elif snap.relative_volume >= 1.2:
            score.volume_score = 7
            reasons.append(f"Above-average volume ({snap.relative_volume:.1f}x avg)")
        elif snap.relative_volume >= 0.8:
            score.volume_score = 4
        else:
            score.volume_score = 0  # very low volume — no conviction

        # --- Volatility filter (max 5) ---
        if snap.bb_pct_val <= 0.8 and snap.volatility_label not in ("very_low",):
            score.volatility_score = 5
        elif snap.bb_pct_val > 1.0:
            score.volatility_score = 0  # extended beyond upper band
        else:
            score.volatility_score = 2

        score.total = (
            score.trend_score
            + score.momentum_score
            + score.structure_score
            + score.vwap_score
            + score.volume_score
            + score.volatility_score
        )
        return score.total, score, reasons

    def _score_sell(self, snap: IndicatorSnapshot) -> tuple[float, ScoreBreakdown, list[str]]:
        score = ScoreBreakdown()
        reasons = []

        # --- Trend (max 25) ---
        if snap.ema_stack_label == "full_bear":
            score.trend_score = 25
            reasons.append("Full bearish EMA stack (9<21<50<200)")
        elif snap.ema_stack_label == "partial_bear":
            score.trend_score = 15
            reasons.append("Partial bearish EMA stack (9<21<50)")
        elif snap.ema_stack_label in ("full_bull", "partial_bull"):
            score.trend_score = 0
        else:
            score.trend_score = 5

        if snap.current_price < snap.ema50:
            score.trend_score = min(25, score.trend_score + 3)
            reasons.append("Price below EMA50")

        # --- Momentum (max 25) ---
        if 35 <= snap.rsi <= 60:
            score.momentum_score += 15
            reasons.append(f"RSI {snap.rsi:.1f} in bearish zone (35–60)")
        elif snap.rsi > 60 and snap.rsi < 70:
            score.momentum_score += 8
            reasons.append(f"RSI {snap.rsi:.1f} overbought pullback zone")
        elif snap.rsi < 30:
            score.momentum_score += 0

        if snap.macd_momentum in ("bearish",):
            score.momentum_score += 10
            reasons.append("MACD histogram negative and falling")
        elif snap.macd_momentum == "bearish_weakening":
            score.momentum_score += 4
        score.momentum_score = min(25, score.momentum_score)

        # --- Structure (max 20) ---
        if snap.structure == "downtrend" and snap.last_bos == "bearish":
            score.structure_score = 20
            reasons.append("Downtrend with bearish BoS confirmed")
        elif snap.structure == "downtrend":
            score.structure_score = 12
            reasons.append("Downtrend structure")
        elif snap.last_bos == "bearish":
            score.structure_score = 10
            reasons.append("Bearish Break of Structure")
        elif snap.last_choch == "bearish":
            score.structure_score = 8
            reasons.append("Bearish Change of Character (CHoCH)")
        score.structure_score = min(20, score.structure_score)

        # --- VWAP (max 15) ---
        if snap.price_vs_vwap == "below":
            score.vwap_score = 15
            reasons.append("Price below VWAP")
        elif snap.price_vs_vwap == "at":
            score.vwap_score = 8
        else:
            score.vwap_score = 0
        score.vwap_score = min(15, score.vwap_score)

        # --- Volume (max 10) ---
        if snap.relative_volume >= 1.5:
            score.volume_score = 10
            reasons.append(f"High relative volume ({snap.relative_volume:.1f}x avg)")
        elif snap.relative_volume >= 1.2:
            score.volume_score = 7
        elif snap.relative_volume >= 0.8:
            score.volume_score = 4
        else:
            score.volume_score = 0

        # --- Volatility (max 5) ---
        if snap.bb_pct_val >= 0.2 and snap.volatility_label not in ("very_low",):
            score.volatility_score = 5
        elif snap.bb_pct_val < 0.0:
            score.volatility_score = 0
        else:
            score.volatility_score = 2

        score.total = (
            score.trend_score
            + score.momentum_score
            + score.structure_score
            + score.vwap_score
            + score.volume_score
            + score.volatility_score
        )
        return score.total, score, reasons

    def _pick_direction(
        self,
        buy_score: float, buy_bd: ScoreBreakdown, buy_reasons: list[str],
        sell_score: float, sell_bd: ScoreBreakdown, sell_reasons: list[str],
    ) -> tuple[SignalDirection, float, ScoreBreakdown, list[str]]:
        """Pick the stronger direction if it clears the threshold."""
        if buy_score >= sell_score:
            return SignalDirection.BUY, buy_score, buy_bd, buy_reasons
        else:
            return SignalDirection.SELL, sell_score, sell_bd, sell_reasons

    def _no_trade(
        self,
        snap: IndicatorSnapshot,
        reason: str,
        config: dict,
        confidence: float = 0.0,
    ) -> TradeSignal:
        return TradeSignal(
            symbol=snap.symbol,
            direction=SignalDirection.NO_TRADE,
            confidence=round(confidence, 2),
            reason=reason,
            timestamp=datetime.now(timezone.utc),
            entry_price=snap.current_price,
            timeframe=snap.timeframe,
        )
