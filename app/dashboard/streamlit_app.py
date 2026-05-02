"""
TPT Future Bot — Streamlit Dashboard

Run with:
    streamlit run run_dashboard.py

Connects to the FastAPI bot server (default: http://localhost:8000).
Auto-refreshes every 10 seconds.
"""

import os
import time
from datetime import datetime

import httpx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000")
REFRESH_INTERVAL = 10  # seconds


def fetch(endpoint: str, default=None):
    try:
        r = httpx.get(f"{API_BASE}{endpoint}", timeout=5.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return default


def post(endpoint: str) -> dict:
    try:
        r = httpx.post(f"{API_BASE}{endpoint}", timeout=10.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"success": False, "message": str(e)}


def color_pnl(val: float) -> str:
    return "🟢" if val > 0 else "🔴" if val < 0 else "⚪"


def mode_badge(mode: str) -> str:
    return "🟡 PAPER" if mode == "PAPER" else "🔴 LIVE"


# ------------------------------------------------------------------ #
# Page config
# ------------------------------------------------------------------ #

st.set_page_config(
    page_title="TPT Future Bot",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.metric-card { background: #1e1e2e; padding: 12px; border-radius: 8px; }
.blocked { color: #ff6b6b; }
.passed { color: #69db7c; }
.signal-buy { color: #69db7c; font-weight: bold; }
.signal-sell { color: #ff6b6b; font-weight: bold; }
.signal-notrade { color: #868e96; }
</style>
""", unsafe_allow_html=True)

# ------------------------------------------------------------------ #
# Header
# ------------------------------------------------------------------ #

status_data = fetch("/status", default={})
running = status_data.get("running", False)
paused = status_data.get("paused", False)
mode = status_data.get("mode", "PAPER")

col_title, col_status, col_mode, col_emergency = st.columns([3, 1, 1, 1])
with col_title:
    st.title("📈 TPT Future Bot")
    st.caption(f"Take Profit Trader | $50,000 Account | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
with col_status:
    if running and not paused:
        st.success("● RUNNING")
    elif paused:
        st.warning("⏸ PAUSED")
    else:
        st.error("● STOPPED")
with col_mode:
    if mode == "LIVE":
        st.error(f"🔴 LIVE TRADING")
    else:
        st.info("🟡 PAPER MODE")
with col_emergency:
    if st.button("🛑 EMERGENCY STOP", type="primary", use_container_width=True):
        result = post("/emergency/flatten")
        if result.get("success"):
            st.error(f"Emergency stop executed: {result.get('positions_closed', 0)} positions closed")
        else:
            st.error(f"Emergency stop failed: {result.get('message', 'Unknown error')}")

st.divider()

# ------------------------------------------------------------------ #
# Row 1 — Account Overview
# ------------------------------------------------------------------ #

st.subheader("Account Overview")
c1, c2, c3, c4 = st.columns(4)

balance = status_data.get("current_balance", 50000)
daily_pnl = status_data.get("daily_pnl", 0.0)
dd_buffer = status_data.get("drawdown_buffer", 2000.0)
trades_today = status_data.get("trades_today", 0)
open_positions = status_data.get("open_positions", 0)
consecutive_losses = status_data.get("consecutive_losses", 0)

with c1:
    st.metric("Account Balance", f"${balance:,.2f}")
with c2:
    pnl_icon = "▲" if daily_pnl >= 0 else "▼"
    st.metric("Daily P&L", f"{pnl_icon} ${abs(daily_pnl):,.2f}",
              delta=f"${daily_pnl:,.2f}")
with c3:
    dd_color = "🟢" if dd_buffer > 1000 else "🟡" if dd_buffer > 500 else "🔴"
    st.metric(f"Drawdown Buffer {dd_color}", f"${dd_buffer:,.2f}")
with c4:
    st.metric("Trades Today", f"{trades_today} | Open: {open_positions}",
              delta=f"{consecutive_losses} consec. losses" if consecutive_losses > 0 else None,
              delta_color="inverse")

st.divider()

# ------------------------------------------------------------------ #
# Row 2 — Rule Compliance Status
# ------------------------------------------------------------------ #

col_rules, col_risk = st.columns([2, 1])

with col_rules:
    st.subheader("Rule Compliance — Last 10 Checks")
    rule_data = fetch("/risk/rules", default=[])
    if rule_data:
        rows = []
        for rc in rule_data[:10]:
            rows.append({
                "Rule": rc.get("rule_name", ""),
                "Status": "✅ PASS" if rc.get("passed") else "❌ FAIL",
                "Reason": rc.get("reason", ""),
                "Time": rc.get("checked_at", "")[:16].replace("T", " "),
            })
        df_rules = pd.DataFrame(rows)
        st.dataframe(df_rules, use_container_width=True, hide_index=True)
    else:
        st.info("No rule checks recorded yet")

with col_risk:
    st.subheader("Risk Status")
    risk_data = fetch("/risk/status", default={})
    if risk_data:
        dd_used = risk_data.get("drawdown_used", 0)
        dd_limit = risk_data.get("drawdown_limit", 2000)
        dd_pct = min(dd_used / dd_limit, 1.0) if dd_limit > 0 else 0.0
        st.progress(dd_pct, text=f"Drawdown Used: ${dd_used:.0f} / ${dd_limit:.0f}")
        st.metric("Peak Balance", f"${risk_data.get('peak_balance', 50000):,.2f}")
        st.metric("Current Equity", f"${risk_data.get('current_equity', 50000):,.2f}")
        safe = risk_data.get("is_drawdown_safe", True)
        if not safe:
            st.error(f"⚠️ {risk_data.get('drawdown_message', '')}")
        else:
            st.success(f"✓ {risk_data.get('drawdown_message', 'OK')}")

st.divider()

# ------------------------------------------------------------------ #
# Row 3 — Charts
# ------------------------------------------------------------------ #

st.subheader("Market Charts")
chart_col_es, chart_col_nq = st.columns(2)


def build_chart(symbol: str) -> go.Figure:
    """Build a candlestick chart with EMA overlays."""
    import yfinance as yf
    from app.indicators.ema import compute_ema
    from app.indicators.vwap import compute_vwap
    from app.indicators.bollinger import compute_bollinger

    specs = {"ES": "ES=F", "NQ": "NQ=F"}
    yf_sym = specs.get(symbol, symbol)
    try:
        df = yf.download(yf_sym, period="1d", interval="5m", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.rename(columns={"Open": "open", "High": "high", "Low": "low",
                                 "Close": "close", "Volume": "volume"})
    except Exception:
        return go.Figure().update_layout(title=f"{symbol} — Data unavailable")

    if df.empty:
        return go.Figure().update_layout(title=f"{symbol} — No data")

    close = df["close"]
    ema9 = compute_ema(close, 9)
    ema21 = compute_ema(close, 21)

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["open"], high=df["high"],
        low=df["low"], close=df["close"], name=symbol,
    ))
    fig.add_trace(go.Scatter(x=df.index, y=ema9, name="EMA9",
                             line=dict(color="#69db7c", width=1)))
    fig.add_trace(go.Scatter(x=df.index, y=ema21, name="EMA21",
                             line=dict(color="#ffa94d", width=1)))

    try:
        vwap = compute_vwap(df)
        fig.add_trace(go.Scatter(x=df.index, y=vwap, name="VWAP",
                                 line=dict(color="#74c0fc", width=1.5, dash="dot")))
    except Exception:
        pass

    fig.update_layout(
        title=f"{symbol} — 5m",
        xaxis_rangeslider_visible=False,
        height=350,
        margin=dict(l=10, r=10, t=40, b=10),
        template="plotly_dark",
    )
    return fig


with chart_col_es:
    with st.spinner("Loading ES chart..."):
        st.plotly_chart(build_chart("ES"), use_container_width=True)

with chart_col_nq:
    with st.spinner("Loading NQ chart..."):
        st.plotly_chart(build_chart("NQ"), use_container_width=True)

st.divider()

# ------------------------------------------------------------------ #
# Row 4 — Latest AI Signals
# ------------------------------------------------------------------ #

st.subheader("Latest AI Signals")
signals = fetch("/signals/latest", default=[])
if signals:
    rows = []
    for s in signals:
        direction = s.get("direction", "NO_TRADE")
        icon = "🟢 BUY" if direction == "BUY" else "🔴 SELL" if direction == "SELL" else "⚪ NO TRADE"
        rows.append({
            "Symbol": s.get("symbol"),
            "Direction": icon,
            "Confidence": f"{s.get('confidence', 0):.1f}%",
            "R:R": f"{s.get('risk_reward', 0):.2f}",
            "Stop Loss": f"{s.get('stop_loss') or '—'}",
            "Take Profit": f"{s.get('take_profit') or '—'}",
            "Rule Check": "✅" if s.get("rule_check_passed") else "❌",
            "Blocked": s.get("blocked_reason") or "—",
            "Time": str(s.get("timestamp", ""))[:16].replace("T", " "),
        })
    df_signals = pd.DataFrame(rows)
    st.dataframe(df_signals, use_container_width=True, hide_index=True)
else:
    st.info("No signals generated yet — bot may be outside trading hours")

st.divider()

# ------------------------------------------------------------------ #
# Row 5 — Open Positions
# ------------------------------------------------------------------ #

st.subheader("Open Positions")
positions = fetch("/trades/open", default=[])
if positions:
    rows = []
    for p in positions:
        pnl = p.get("unrealized_pnl", 0.0)
        rows.append({
            "Trade ID": p.get("trade_id"),
            "Symbol": p.get("symbol"),
            "Side": p.get("side"),
            "Contracts": p.get("contracts"),
            "Entry": f"${p.get('entry_price', 0):.2f}",
            "Stop Loss": f"${p.get('stop_loss', 0):.2f}",
            "Take Profit": f"${p.get('take_profit', 0):.2f}",
            "Unrealized P&L": f"{color_pnl(pnl)} ${pnl:,.2f}",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No open positions")

st.divider()

# ------------------------------------------------------------------ #
# Row 6 — Trade History
# ------------------------------------------------------------------ #

st.subheader("Today's Trade History")
trades = fetch("/trades/history?today_only=true&limit=30", default=[])
if trades:
    rows = []
    for t in trades:
        pnl = t.get("pnl_dollars") or 0.0
        rows.append({
            "ID": t.get("id"),
            "Symbol": t.get("symbol"),
            "Dir": t.get("direction"),
            "Contracts": t.get("contracts"),
            "Entry": f"${t.get('entry_price', 0):.2f}",
            "Exit": f"${t.get('exit_price', 0):.2f}" if t.get("exit_price") else "—",
            "P&L $": f"{color_pnl(pnl)} ${pnl:,.2f}",
            "P&L Ticks": f"{t.get('pnl_ticks', 0):.1f}",
            "Exit Reason": t.get("exit_reason") or "—",
            "Mode": t.get("mode"),
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
else:
    st.info("No trades today")

st.divider()

# ------------------------------------------------------------------ #
# Row 7 — Blocked Trades & Bot Controls
# ------------------------------------------------------------------ #

col_blocked, col_controls = st.columns([2, 1])

with col_blocked:
    st.subheader("Recently Blocked Trades")
    all_signals = fetch("/signals/history?limit=20", default=[])
    blocked = [s for s in all_signals if not s.get("rule_check_passed") and s.get("direction") != "NO_TRADE"]
    if blocked:
        rows = []
        for s in blocked[:10]:
            rows.append({
                "Symbol": s.get("symbol"),
                "Direction": s.get("direction"),
                "Confidence": f"{s.get('confidence', 0):.1f}",
                "Blocked Reason": s.get("blocked_reason") or "—",
                "Time": str(s.get("timestamp", ""))[:16].replace("T", " "),
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No blocked trades")

with col_controls:
    st.subheader("Bot Controls")
    if st.button("▶ Start Bot", use_container_width=True):
        r = post("/bot/start")
        st.toast(r.get("message", ""))
    if st.button("⏸ Pause Bot", use_container_width=True):
        r = post("/bot/pause")
        st.toast(r.get("message", ""))
    if st.button("⏹ Stop Bot", use_container_width=True):
        r = post("/bot/stop")
        st.toast(r.get("message", ""))

# ------------------------------------------------------------------ #
# Auto-refresh
# ------------------------------------------------------------------ #

st.divider()
st.caption(f"Auto-refreshing every {REFRESH_INTERVAL}s | Last updated: {datetime.now().strftime('%H:%M:%S')}")
time.sleep(REFRESH_INTERVAL)
st.rerun()
