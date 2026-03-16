# -*- coding: utf-8 -*-
"""실시간 동작 화면: 20초마다 현재가·잔고·신호 상태 출력."""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.indicators import Indicators
import pandas as pd

def tick():
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    client = CoinoneClient(cfg.COINONE_ACCESS_KEY, cfg.COINONE_SECRET_KEY)
    try:
        ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
        ticker = client.fetch_ticker(symbol)
        balance = client.fetch_balance()
    except Exception as e:
        print(f"[오류] {e}")
        return
    price = float(ticker.get("last", 0))
    krw = client.get_free_balance(balance, cfg.MARKET)
    btc = client.get_free_balance(balance, cfg.SYMBOL)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    lookback = min(getattr(cfg, "BOX_LOOKBACK_BARS", 180), len(df) - 1)
    box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], lookback)
    engine = SignalEngine()
    signals = engine.get_buy_signals(df, box)
    last = signals[-1] if signals else {}
    from datetime import datetime
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[{ts}] === 실시간 현황 ===")
    print(f"  현재가: {price:,.0f} {cfg.MARKET}")
    print(f"  잔고: KRW {krw:,.0f} / {cfg.SYMBOL} {btc:.8f}")
    print(f"  신호: trend_ok={last.get('trend_ok')} final_buy={last.get('final_buy_signal')}")
    print(f"  모드: {'페이퍼' if cfg.PAPER_TRADING else '실거래'}")
    print("  (Ctrl+C 종료, 20초마다 갱신)")

if __name__ == "__main__":
    once = "--once" in sys.argv
    print("실시간 대시보드 시작...")
    try:
        for i in range(1 if once else 999999):
            tick()
            if once:
                break
            time.sleep(20)
    except KeyboardInterrupt:
        print("\n종료")
