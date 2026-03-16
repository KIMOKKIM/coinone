#!/usr/bin/env python3
\"\"\"Run backtests for multiple periods (30/90/180/365 days) and produce CSV summary.

Generates per-period result CSVs under data/ and a summary CSV results_summary.csv.
\"\"\"
import sys
from pathlib import Path
import math
import json
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
import pandas as pd

from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.services.backtester import Backtester


PERIODS_DAYS = [30, 90, 180, 365]

def bars_needed_for_days(days: int, timeframe: str) -> int:
    # timeframe e.g. '4h' or '1d'
    if timeframe.endswith('h'):
        hours = int(timeframe[:-1])
        bars_per_day = 24 // hours
    elif timeframe.endswith('d'):
        days_tf = int(timeframe[:-1])
        bars_per_day = 1 // days_tf if days_tf else 1
    else:
        bars_per_day = 6
    return math.ceil(days * bars_per_day) + 50

def run_period(days: int):
    client = CoinoneClient(cfg.COINONE_ACCESS_KEY or "", cfg.COINONE_SECRET_KEY or "", sandbox=True)
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    bars = bars_needed_for_days(days, cfg.TIMEFRAME)
    ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=bars)
    df = pd.DataFrame(ohlcv, columns=["ts","open","high","low","close","volume"])
    engine = SignalEngine()
    risk = RiskManager()
    bt = Backtester(engine, risk)
    bt.initial_capital = 100000.0
    res = bt.run(df, symbol)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = Path(cfg.DATA_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_csv = out_dir / f"backtest_{days}d_{ts}.csv"
    pd.DataFrame([res]).to_csv(out_csv, index=False, encoding="utf-8-sig")
    return res, str(out_csv)

def main():
    results = []
    for d in PERIODS_DAYS:
        print(f"Running backtest for last {d} days...")
        try:
            res, path = run_period(d)
            res["period_days"] = d
            res["csv_path"] = path
            results.append(res)
            print("  ->", res)
        except Exception as e:
            print("  error for", d, e)
    # write summary
    out_summary = Path(cfg.DATA_DIR) / "results_summary.csv"
    pd.DataFrame(results).to_csv(out_summary, index=False, encoding="utf-8-sig")
    print("Summary saved to", out_summary)
    print("Done.")

if __name__ == '__main__':
    main()

