import asyncio
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Optional

import pandas as pd

from app.data.market_data import YFinanceFetcher
from app.indicators.engine import IndicatorEngine
from app.ai.signal_engine import SignalEngine
from app.ai.models import SignalDirection
from app.risk.drawdown_tracker import DrawdownTracker, AccountState
from app.risk.rule_engine import RuleEngine
from app.risk.position_sizer import calculate_contracts
from app.data.normalizer import get_instrument_spec
from app.data.session import is_trading_now
from app.backtest.metrics import BacktestMetrics

logger = logging.getLogger(__name__)

# Commission: $2.10 per contract per side (NFA + exchange)
COMMISSION_PER_CONTRACT_PER_SIDE = 2.10

# Slippage: 1 tick per fill (conservative)
SLIPPAGE_TICKS = 1


class BacktestEngine:
    """
    Walk-forward backtesting engine for ES and NQ.

    For each bar:
      1. Compute indicators on lookback window
      2. Generate signal
      3. Run rule engine against simulated account state
      4. If approved: simulate fill at next bar open
      5. Track P&L with commission + slippage
      6. Compute metrics at end

    Does NOT use future bars for decisions — strictly walk-forward.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._indicator_engine = IndicatorEngine()
        self._signal_engine = SignalEngine()
        self._fetcher = YFinanceFetcher()

    async def run(
        self,
        symbol: str,
        timeframe: str = "5m",
        lookback_bars: int = 300,
        lookback_days: int = 60,
    ) -> BacktestMetrics:
        """
        Run a backtest for the given symbol.
        Returns a BacktestMetrics object with all performance statistics.
        """
        logger.info(f"Starting backtest: {symbol}/{timeframe} over last {lookback_days} days")

        df = await self._fetcher.fetch_ohlcv(symbol, timeframe=timeframe, bars=lookback_bars)
        if df.empty or len(df) < lookback_bars // 2:
            raise ValueError(f"Insufficient data for {symbol} backtest")

        spec = get_instrument_spec(symbol)
        tick_size = spec["tick_size"]
        tick_value = spec["tick_value"]
        point_value = spec["point_value"]

        start_date = str(df.index[0].date())
        end_date = str(df.index[-1].date())

        metrics = BacktestMetrics(
            symbol=symbol,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )

        # Simulated account state — reset for each backtest
        dd_tracker = DrawdownTracker(self._config)
        rule_engine = RuleEngine(dd_tracker, self._config)
        acct = dd_tracker.state

        min_lookback = 50
        open_trade: Optional[dict] = None
        running_pnl: list[float] = []
        cumulative_pnl = 0.0

        for i in range(min_lookback, len(df) - 1):
            window = df.iloc[: i + 1]
            current_bar = df.iloc[i]
            next_bar = df.iloc[i + 1]  # Fill at next bar open

            # Check for open trade SL/TP hit
            if open_trade is not None:
                side = open_trade["side"]
                entry = open_trade["entry"]
                sl = open_trade["sl"]
                tp = open_trade["tp"]
                contracts = open_trade["contracts"]

                high = current_bar["high"]
                low = current_bar["low"]

                exit_price = None
                exit_reason = None

                if side == "BUY":
                    if low <= sl:
                        exit_price = sl
                        exit_reason = "SL_HIT"
                    elif high >= tp:
                        exit_price = tp
                        exit_reason = "TP_HIT"
                else:
                    if high >= sl:
                        exit_price = sl
                        exit_reason = "SL_HIT"
                    elif low <= tp:
                        exit_price = tp
                        exit_reason = "TP_HIT"

                if exit_price is not None:
                    if side == "BUY":
                        pnl_points = exit_price - entry
                    else:
                        pnl_points = entry - exit_price

                    pnl = pnl_points * point_value * contracts
                    commission = COMMISSION_PER_CONTRACT_PER_SIDE * 2 * contracts
                    slippage = SLIPPAGE_TICKS * tick_value * contracts
                    net_pnl = pnl - commission - slippage

                    metrics.record_trade(net_pnl)
                    cumulative_pnl += net_pnl
                    running_pnl.append(cumulative_pnl)
                    dd_tracker.on_trade_close(net_pnl, datetime.now(timezone.utc))

                    # Check prop-firm violation
                    dd_cfg = self._config.get("drawdown", {})
                    dd_limit = dd_cfg.get("eod_trailing_drawdown_limit", 2000)
                    used = acct.trailing_drawdown_used
                    if used >= dd_limit:
                        metrics.prop_firm_violation = True
                        metrics.violation_reason = (
                            f"EOD trailing drawdown limit breached: "
                            f"${used:.2f} >= ${dd_limit:.2f}"
                        )
                        logger.warning(f"PROP FIRM VIOLATION at bar {i}: {metrics.violation_reason}")

                    open_trade = None
                    logger.debug(f"BT CLOSE [{exit_reason}]: {symbol} P&L=${net_pnl:.2f}")

            if open_trade is not None:
                continue  # One position at a time

            # Generate signal on current window
            snap = self._indicator_engine.compute(window, symbol, timeframe)
            signal = self._signal_engine.generate_signal(snap, self._config)

            if signal.direction == SignalDirection.NO_TRADE:
                continue

            # Simulate mock time for rule check
            bar_time = window.index[-1].to_pydatetime()

            passed, blocked_reason, _ = rule_engine.check(signal, acct, now=bar_time)
            if not passed:
                continue

            # Calculate position size
            contracts, dollar_risk, _ = calculate_contracts(symbol, snap.atr, acct, self._config)
            if contracts == 0:
                continue

            # Fill at next bar open with slippage
            fill_price = float(next_bar["open"])
            slippage_points = SLIPPAGE_TICKS * tick_size
            if signal.direction == SignalDirection.BUY:
                fill_price += slippage_points
            else:
                fill_price -= slippage_points

            open_trade = {
                "side": signal.direction.value,
                "entry": fill_price,
                "sl": signal.stop_loss,
                "tp": signal.take_profit,
                "contracts": contracts,
                "bar_index": i,
            }
            acct.trades_today += 1
            logger.debug(
                f"BT OPEN: {symbol} {signal.direction.value} @ {fill_price:.2f} "
                f"SL={signal.stop_loss:.2f} TP={signal.take_profit:.2f} "
                f"contracts={contracts}"
            )

        # Close any open trade at end of data
        if open_trade is not None:
            last_close = float(df["close"].iloc[-1])
            if open_trade["side"] == "BUY":
                pnl_points = last_close - open_trade["entry"]
            else:
                pnl_points = open_trade["entry"] - last_close
            pnl = pnl_points * point_value * open_trade["contracts"]
            commission = COMMISSION_PER_CONTRACT_PER_SIDE * 2 * open_trade["contracts"]
            net_pnl = pnl - commission
            metrics.record_trade(net_pnl)
            cumulative_pnl += net_pnl
            running_pnl.append(cumulative_pnl)

        metrics.compute_max_drawdown(running_pnl)

        logger.info(
            f"Backtest complete: {symbol} | {metrics.total_trades} trades | "
            f"Win rate {metrics.win_rate:.1%} | Total P&L ${metrics.total_pnl:.2f} | "
            f"Sharpe {metrics.sharpe_ratio:.2f} | Max DD ${metrics.max_drawdown:.2f} | "
            f"Prop violation: {metrics.prop_firm_violation}"
        )
        return metrics
