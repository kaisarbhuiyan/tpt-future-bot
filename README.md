# TPT Future Bot

A production-ready, prop-firm-compliant futures trading bot for a **$50,000 Take Profit Trader** account trading **ES and NQ** only.

> **EDUCATIONAL / SIMULATION USE FIRST.**
> Paper trading is the default mode. Live trading is disabled and requires two explicit gates to activate. All prop-firm rules are stored in an editable config file and must be manually verified before live use.

---

## Architecture

```
Data → Indicators → AI Signal → Rule Engine → Position Sizer → Execution → Dashboard
```

Every layer depends on the previous. **No trade bypasses the rule engine.**

---

## Project Structure

```
TPT Future Bot/
├── app/
│   ├── data/           # Market data fetching, session detection, DB storage
│   ├── indicators/     # EMA, VWAP, RSI, MACD, ATR, BB, Volume, S/R, Market Structure
│   ├── ai/             # Rule-based signal scoring engine (NOT an LLM)
│   ├── risk/           # Drawdown tracker, position sizer, pre-trade rule engine
│   ├── execution/      # Paper broker + Tradovate live adapter (stub)
│   ├── backtest/       # Walk-forward backtesting with commission/slippage
│   ├── scheduler/      # APScheduler: scan, EOD flatten, daily reset
│   ├── dashboard/      # Streamlit dashboard
│   ├── api/            # FastAPI routes and schemas
│   └── models/         # SQLAlchemy database models
├── config/
│   └── rules.yaml      # ⚠️  EDIT THIS — All prop-firm rules (must be verified with TPT)
├── logs/
├── tests/
├── run_bot.py          # Start bot (FastAPI + scheduler)
└── run_dashboard.py    # Start dashboard (Streamlit)
```

---

## Quick Start

### 1. Install Dependencies

```bash
cd "TPT Future Bot"
python -m venv .venv
source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate   # Windows

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env — fill in your settings (leave ENABLE_LIVE_TRADING=false)
```

### 3. Verify Prop-Firm Rules

**IMPORTANT:** Open `config/rules.yaml` and verify every value against your TPT dashboard before trading:

- Account size
- Max contracts per symbol
- Trailing drawdown limit
- Daily loss limit (if applicable)
- Permitted trading hours
- Profit target

### 4. Start the Bot (Paper Mode)

```bash
python run_bot.py
```

### 5. Start the Dashboard (separate terminal)

```bash
streamlit run run_dashboard.py
```

Open http://localhost:8501 in your browser.

---

## Config: `config/rules.yaml`

All prop-firm rules are stored here. Key sections:

| Section | Key Settings |
|---------|-------------|
| `account` | `account_size`, `allowed_symbols`, `max_contracts_per_symbol` |
| `trading_hours` | `permitted_start`, `permitted_end`, `eod_cutoff_minutes` |
| `drawdown` | `eod_trailing_drawdown_limit`, `daily_loss_limit`, `drawdown_safety_buffer` |
| `profit_target` | `evaluation_profit_target`, `daily_profit_target` |
| `risk` | `risk_pct_per_trade`, `min_risk_reward_ratio`, `min_confidence_score` |
| `position_management` | `max_consecutive_losses`, `max_trades_per_day` |
| `live_trading` | `live_trading_confirmed` (Gate 2 of 2) |

---

## Trading Logic

### Signal Engine (100% Technical Analysis)

The signal engine is a **weighted rule-based scoring system** (not an LLM).

**Scoring weights:**

| Component | Max Score | Indicators Used |
|-----------|-----------|-----------------|
| Trend | 25 pts | EMA 9/21/50/200 stack |
| Momentum | 25 pts | RSI (14), MACD (12/26/9) |
| Structure | 20 pts | HH/HL/LH/LL, Break of Structure |
| VWAP Position | 15 pts | Session-anchored VWAP |
| Volume | 10 pts | Relative volume vs 20-bar avg |
| Volatility | 5 pts | ATR%, Bollinger %B |

A trade signal is only generated when:
- Composite confidence ≥ `min_confidence_score` (default: 65)
- Risk:Reward ≥ `min_risk_reward_ratio` (default: 2.0)

### Rule Engine (Pre-Trade Checklist)

Every trade must pass **all 15 checks** before execution. First failure blocks the trade:

1. Symbol in allowed list (ES/NQ only)
2. Within permitted trading hours
3. Signal is BUY or SELL (not NO_TRADE)
4. Confidence ≥ threshold
5. Risk:Reward ≥ minimum
6. Stop loss exists
7. Take profit exists
8. Drawdown buffer is safe
9. Daily loss limit not hit
10. Daily profit target not yet reached
11. Max trades per day not exceeded
12. Max open positions not exceeded
13. Consecutive loss limit not hit
14. Minimum cooldown after last loss
15. Live trading gates check

### Position Sizing (ATR-Based)

```
dollar_risk    = account_balance × risk_pct_per_trade (default: 0.25%)
stop_distance  = ATR(14) × atr_stop_multiplier (default: 1.5)
dollars_per_ct = stop_distance × point_value_per_contract
contracts      = floor(dollar_risk / dollars_per_ct)
contracts      = min(contracts, max_contracts_per_symbol)
```

ES point value: $50 | NQ point value: $20

---

## Instrument Specs

| Spec | ES (E-mini S&P 500) | NQ (E-mini Nasdaq-100) |
|------|---------------------|------------------------|
| Tick size | 0.25 pts | 0.25 pts |
| Tick value | $12.50 | $5.00 |
| Point value | $50.00 | $20.00 |
| yfinance symbol | ES=F | NQ=F |

---

## Safety Architecture

### Two-Gate Live Trading System

Live trading requires **both** gates to be open simultaneously:

```
Gate 1 (env):    ENABLE_LIVE_TRADING=true   (in .env)
Gate 2 (config): live_trading_confirmed: true (in config/rules.yaml)
```

The rule engine checks both gates on **every single trade**.

### Emergency Kill Switch

```bash
# Via API
curl -X POST http://localhost:8000/emergency/flatten

# Via dashboard
Click the "EMERGENCY STOP" button
```

Flattens all positions immediately and pauses the bot.

### Additional Safety Features

- Automatic EOD flatten before `permitted_end`
- Halt trading after N consecutive losses (configurable)
- Drawdown breach auto-flatten with logging
- No martingale / no grid / no averaging down (hardcoded OFF)
- All decisions logged with full audit trail

---

## Dashboard

The Streamlit dashboard at http://localhost:8501 shows:

- Bot status (RUNNING/PAUSED/STOPPED) and mode (PAPER/LIVE)
- Account balance, daily P&L, drawdown buffer
- Rule compliance status (last 10 checks)
- ES and NQ candlestick charts with EMA/VWAP overlays
- Latest AI signals with confidence scores
- Open positions with unrealized P&L
- Today's trade history
- Blocked trades with reasons
- Emergency stop button

---

## Running Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=app --cov-report=term-missing
```

All risk rule tests cover:
- Symbol blocking
- Drawdown buffer exhaustion
- Max trades per day
- Consecutive loss limit
- Confidence threshold
- R:R minimum
- Live trading gates
- Daily profit/loss limits
- Cooldown period enforcement

---

## Backtesting

```bash
# Via API (after bot is running)
curl http://localhost:8000/backtest/results
```

Or run directly:

```python
import asyncio
from app.backtest.engine import BacktestEngine
import yaml

with open("config/rules.yaml") as f:
    config = yaml.safe_load(f)

engine = BacktestEngine(config)
metrics = asyncio.run(engine.run("ES", timeframe="5m", lookback_bars=300))
print(metrics.to_dict())
```

Backtest includes:
- Commission: $2.10/contract/side
- Slippage: 1 tick per fill
- Walk-forward (no look-ahead bias)
- Prop-firm violation detection

---

## Enabling Live Trading (Tradovate)

Only proceed after:
1. Paper trading without issues for ≥ 5 trading days
2. All `config/rules.yaml` values verified with TPT dashboard
3. Valid Tradovate API credentials

Steps:
1. Fill in Tradovate credentials in `.env`
2. Set `TRADOVATE_ENV=demo` first (Tradovate sim environment)
3. Set `live_trading_confirmed: true` in `config/rules.yaml`
4. Set `ENABLE_LIVE_TRADING=true` in `.env`
5. Complete the `tradovate_broker.py` implementation (currently a documented stub)
6. Test with `TRADOVATE_ENV=demo` before switching to `live`

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/status` | Bot status, balance, P&L |
| GET | `/signals/latest` | Latest signal per symbol |
| GET | `/signals/history` | Signal history |
| GET | `/trades/open` | Open positions |
| GET | `/trades/history` | Closed trade history |
| GET | `/risk/status` | Drawdown and risk state |
| GET | `/risk/rules` | Recent rule check results |
| POST | `/bot/start` | Start the scheduler |
| POST | `/bot/stop` | Stop the scheduler |
| POST | `/bot/pause` | Pause (no new trades) |
| POST | `/emergency/flatten` | Flatten all + pause |
| GET | `/health` | Health check |

Interactive API docs: http://localhost:8000/docs

---

## Disclaimer

This software is for **educational and simulation purposes**. It does not constitute financial advice. Futures trading involves substantial risk of loss. Past backtested performance does not guarantee future results. Always verify prop-firm rules directly with Take Profit Trader before trading with real capital. The authors are not responsible for any financial losses.
