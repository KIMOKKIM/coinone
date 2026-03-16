# -*- coding: utf-8 -*-
"""실행 및 백테스트 테스트 스크립트."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.strategy.indicators import Indicators
from app.services.backtester import Backtester
import pandas as pd

def test_candle_fetch():
    """캔들 조회 테스트."""
    print("=== 1. 캔들 조회 테스트 ===")
    client = CoinoneClient(cfg.COINONE_ACCESS_KEY or "dummy", cfg.COINONE_SECRET_KEY or "dummy")
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=100)
    print(f"  수집 캔들 수: {len(ohlcv)}")
    if ohlcv:
        last = ohlcv[-1]
        print(f"  최근 봉: ts={last[0]}, O={last[1]}, H={last[2]}, L={last[3]}, C={last[4]}, V={last[5]}")
    return ohlcv

def test_signals(df):
    """신호 엔진 테스트."""
    print("\n=== 2. 신호 엔진 테스트 ===")
    engine = SignalEngine()
    lookback = min(getattr(cfg, "BOX_LOOKBACK_BARS", 180), len(df) - 1)
    box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], lookback)
    signals = engine.get_buy_signals(df, box)
    buy_count = sum(1 for s in signals if s.get("final_buy_signal"))
    print(f"  전체 봉 수: {len(signals)}, 매수 신호 수: {buy_count}")
    if signals:
        last = signals[-1]
        print(f"  최근 봉 신호: trend_ok={last.get('trend_ok')}, final_buy_signal={last.get('final_buy_signal')}")
    return signals

def test_backtest(df, symbol):
    """백테스트 실행 (초기자본 10만원으로 최소주문금액 5000원 충족)."""
    print("\n=== 3. 백테스트 실행 ===")
    signal = SignalEngine()
    risk = RiskManager()
    bt = Backtester(signal, risk)
    bt.initial_capital = 100_000.0  # 10만원 -> 1차 매수 100000*0.35*0.3=10500 >= 5000
    result = bt.run(df, symbol)
    print(f"  수익률: {result.get('total_return_pct')}%")
    print(f"  MDD: {result.get('mdd_pct')}%")
    print(f"  승률: {result.get('win_rate')}%")
    print(f"  거래 횟수: {result.get('trade_count')}")
    print(f"  최종 자산: {result.get('final_equity')}")
    return result

if __name__ == "__main__":
    ohlcv = test_candle_fetch()
    if not ohlcv or len(ohlcv) < 50:
        print("캔들 부족으로 백테스트 스킵")
        sys.exit(0)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    test_signals(df)
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    test_backtest(df, symbol)
    print("\n=== 테스트 완료 ===")
