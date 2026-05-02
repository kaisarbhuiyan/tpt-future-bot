#!/usr/bin/env python3
"""
TPT Future Bot — Main Entry Point

Usage:
    python run_bot.py

Starts the FastAPI server which launches the scheduler automatically.
The bot runs in PAPER TRADING mode by default.

To enable live trading (after all safety conditions are met):
    ENABLE_LIVE_TRADING=true python run_bot.py

Dashboard (separate terminal):
    streamlit run run_dashboard.py
"""

import os
import sys
from pathlib import Path

# Ensure project root is in Python path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

import uvicorn
import logging

logger = logging.getLogger(__name__)


def print_startup_banner() -> None:
    live_env = os.getenv("ENABLE_LIVE_TRADING", "false").lower()
    mode = "LIVE" if live_env == "true" else "PAPER"
    border = "=" * 60
    print(f"\n{border}")
    print(f"  TPT FUTURE BOT")
    print(f"  Prop Firm: Take Profit Trader")
    print(f"  Account: $50,000")
    print(f"  Instruments: ES, NQ")
    print(f"  Mode: {mode}")
    print(f"{border}")
    if mode == "LIVE":
        print("\n  ⚠️  WARNING: LIVE TRADING IS ACTIVE")
        print("  Real money is at risk. Verify all rules before proceeding.")
        print(f"{border}")
    else:
        print("\n  ✓ Paper trading mode — no real orders will be placed")
        print(f"{border}\n")


def check_safety() -> None:
    """Perform pre-flight safety checks before starting."""
    live_env = os.getenv("ENABLE_LIVE_TRADING", "false").lower() == "true"

    if live_env:
        import yaml
        from pathlib import Path
        config_path = Path(__file__).parent / "config" / "rules.yaml"
        with open(config_path) as f:
            config = yaml.safe_load(f)
        config_gate = config.get("live_trading", {}).get("live_trading_confirmed", False)
        if not config_gate:
            print("\n❌ SAFETY CHECK FAILED:")
            print("  ENABLE_LIVE_TRADING=true but live_trading_confirmed=false in config/rules.yaml")
            print("  Both gates must be open for live trading. Bot will NOT start in live mode.")
            print("  Starting in PAPER mode instead...")
            os.environ["ENABLE_LIVE_TRADING"] = "false"


def main() -> None:
    print_startup_banner()
    check_safety()

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))

    print(f"Starting FastAPI server on {host}:{port}")
    print(f"API docs: http://localhost:{port}/docs")
    print(f"Health check: http://localhost:{port}/health")
    print("Press Ctrl+C to stop\n")

    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
    )


if __name__ == "__main__":
    main()
