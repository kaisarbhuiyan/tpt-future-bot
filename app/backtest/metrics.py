from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class BacktestMetrics:
    symbol: str
    timeframe: str
    start_date: str
    end_date: str

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0

    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0

    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0

    # Prop-firm violation flag
    prop_firm_violation: bool = False
    violation_reason: Optional[str] = None

    # List of trade P&Ls for Sharpe
    pnl_series: list = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def profit_factor(self) -> float:
        if self.gross_loss == 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return abs(self.gross_profit / self.gross_loss)

    @property
    def avg_risk_reward(self) -> float:
        if not self.pnl_series:
            return 0.0
        winning = [p for p in self.pnl_series if p > 0]
        losing = [p for p in self.pnl_series if p < 0]
        if not winning or not losing:
            return 0.0
        avg_win = sum(winning) / len(winning)
        avg_loss = abs(sum(losing) / len(losing))
        return avg_win / avg_loss if avg_loss > 0 else 0.0

    @property
    def sharpe_ratio(self) -> float:
        """Annualized Sharpe ratio assuming ~252 trading days."""
        if len(self.pnl_series) < 2:
            return 0.0
        n = len(self.pnl_series)
        mean = sum(self.pnl_series) / n
        variance = sum((x - mean) ** 2 for x in self.pnl_series) / (n - 1)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        daily_sharpe = mean / std
        return daily_sharpe * math.sqrt(252)

    def record_trade(self, pnl: float) -> None:
        self.total_trades += 1
        self.pnl_series.append(pnl)
        self.total_pnl += pnl
        if pnl > 0:
            self.winning_trades += 1
            self.gross_profit += pnl
        else:
            self.losing_trades += 1
            self.gross_loss += pnl

    def compute_max_drawdown(self, running_pnl_series: list) -> None:
        """Compute max drawdown from a running cumulative P&L series."""
        peak = 0.0
        max_dd = 0.0
        for val in running_pnl_series:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        self.max_drawdown = max_dd

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "max_drawdown": round(self.max_drawdown, 2),
            "sharpe_ratio": round(self.sharpe_ratio, 4),
            "avg_risk_reward": round(self.avg_risk_reward, 4),
            "total_pnl": round(self.total_pnl, 2),
            "prop_firm_violation": self.prop_firm_violation,
            "violation_reason": self.violation_reason,
        }
