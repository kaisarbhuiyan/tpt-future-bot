#!/usr/bin/env python3
"""
TPT Future Bot — Dashboard Entry Point

Usage:
    streamlit run run_dashboard.py

Requires the bot to be running (python run_bot.py) in a separate terminal.
The dashboard connects to the FastAPI bot server at localhost:8000 by default.

To use a different bot API URL:
    API_BASE_URL=http://your-server:8000 streamlit run run_dashboard.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

# Streamlit entry point — must import the app module
from app.dashboard.streamlit_app import *  # noqa: F401, F403
