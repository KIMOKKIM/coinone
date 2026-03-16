# -*- coding: utf-8 -*-
"""
Configuration for the rebuilt BTC spot auto-trader.
Loads environment variables from .env (preserve .env).
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# project paths
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
STATE_DIR = PROJECT_ROOT / "state"
STATE_FILE = STATE_DIR / "state.json"

# trading pair and timeframe
SYMBOL = os.getenv("SYMBOL", "BTC")
MARKET = os.getenv("MARKET", "KRW")
TIMEFRAME = os.getenv("TIMEFRAME", "4h")
TIMEFRAME_DAILY = "1d"

# indicators
SMA_PERIOD = int(os.getenv("SMA_PERIOD", "50"))
EMA_PERIOD = int(os.getenv("EMA_PERIOD", "20"))
BB_PERIOD = int(os.getenv("BB_PERIOD", "20"))
BB_STD = float(os.getenv("BB_STD", "2.0"))
VOLUME_MA_PERIOD = int(os.getenv("VOLUME_MA_PERIOD", "20"))
BOX_LOOKBACK_BARS = int(os.getenv("BOX_LOOKBACK_BARS", "180"))

# risk & execution
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "0.04"))
TAKE_PROFIT_LEVELS = [float(x) for x in os.getenv("TAKE_PROFIT_LEVELS", "0.05,0.08,0.12").split(",")]
TAKE_PROFIT_RATIOS = [float(x) for x in os.getenv("TAKE_PROFIT_RATIOS", "0.3,0.3,0.4").split(",")]
ENABLE_TARGET_30_MODE = os.getenv("ENABLE_TARGET_30_MODE", "false").lower() in ("true", "1", "yes")
VOL_BREAKOUT_K = float(os.getenv("VOL_BREAKOUT_K", "0.5"))

MAX_CAPITAL_ALLOCATION = float(os.getenv("MAX_CAPITAL_ALLOCATION", "0.35"))
BUY_SPLIT_RATIOS = [float(x) for x in os.getenv("BUY_SPLIT_RATIOS", "0.3,0.3,0.4").split(",")]
COOLDOWN_HOURS = float(os.getenv("COOLDOWN_HOURS", "12"))
MIN_ORDER_KRW = float(os.getenv("MIN_ORDER_KRW", "5000"))

# crash / recovery
CRASH_LOOKBACK_CANDLES = int(os.getenv("CRASH_LOOKBACK_CANDLES", "6"))
CRASH_THRESHOLD_PCT = float(os.getenv("CRASH_THRESHOLD_PCT", "0.03"))
EMA_RECLAIM_BARS = int(os.getenv("EMA_RECLAIM_BARS", "1"))

# mode
PAPER_TRADING = os.getenv("PAPER_TRADING", "true").lower() in ("true", "1", "yes")

# API keys (keep .env intact)
COINONE_ACCESS_KEY = os.getenv("COINONE_ACCESS_KEY", "")
COINONE_SECRET_KEY = os.getenv("COINONE_SECRET_KEY", "")

# backtest
BACKTEST_START_DAYS = int(os.getenv("BACKTEST_START_DAYS", "90"))

# additional risk defaults
TRAILING_STOP_PCT = float(os.getenv("TRAILING_STOP_PCT", "0.02"))
TARGET_30_PCT = float(os.getenv("TARGET_30_PCT", "0.30"))

