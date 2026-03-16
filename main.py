# -*- coding: utf-8 -*-
"""
Coinone BTC 현물 자동매매 메인 진입점.
Plan.md: 레버리지/선물/공매도 금지, 현물만, 백테스트·페이퍼 지원, 모듈화.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.strategy.portfolio import Portfolio
from app.services.trader_core import Trader
from app.services.backtester import Backtester
from app.services.notifier import Notifier
from app.services.scheduler import run_once
from app.utils.helpers import safe_float
from app.utils.logger import get_logger
from app.utils.helpers import ensure_dir

logger = get_logger(__name__)


def load_state() -> dict:
    """저장된 포지션 상태 로드."""
    if not cfg.STATE_FILE.exists():
        return {}
    try:
        with open(cfg.STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("상태 파일 로드 실패: %s", e)
        return {}


def save_state(state: dict) -> None:
    """포지션 상태 저장."""
    ensure_dir(cfg.STATE_FILE.parent)
    with open(cfg.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def run_strategy_once() -> None:
    """전략 1회 실행: 캔들 조회 → 신호 → 주문(페이퍼/실거래) → 상태 저장."""
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    client = CoinoneClient(cfg.COINONE_ACCESS_KEY, cfg.COINONE_SECRET_KEY)
    risk = RiskManager()
    signal_engine = SignalEngine()
    trader = Trader(client, risk, paper=cfg.PAPER_TRADING)
    state = load_state()
    portfolio = Portfolio(state.get("portfolio"))

    if cfg.PAPER_TRADING:
        logger.info("페이퍼트레이딩 모드 - 실제 주문 없음")
    else:
        logger.warning("실거래 모드 - 실제 주문 전송됨")
        if not client.check_order_permission():
            logger.error("API 키/권한 확인 필요. 종료.")
            return

    try:
        ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
    except Exception as e:
        Notifier.api_error("캔들 조회 실패", e)
        return
    if not ohlcv or len(ohlcv) < 50:
        logger.warning("캔들 데이터 부족")
        return

    import pandas as pd
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    from app.strategy.indicators import Indicators
    lookback = getattr(cfg, "BOX_LOOKBACK_BARS", 180)
    box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], min(lookback, len(df) - 1))
    signals = signal_engine.get_buy_signals(df, box)
    if not signals:
        logger.info("매수 신호 없음")
        save_state({"portfolio": portfolio.to_state()})
        return

    last_sig = signals[-1]
    if not last_sig.get("final_buy_signal"):
        save_state({"portfolio": portfolio.to_state()})
        return

    balance = client.fetch_balance()
    quote_bal = client.get_free_balance(balance, cfg.MARKET)
    if not risk.cooldown_ok(portfolio.last_stop_time):
        logger.info("쿨다운 중 - 신규 진입 보류")
        save_state({"portfolio": portfolio.to_state()})
        return

    candle_ts = int(df["ts"].iloc[-1]) if "ts" in df.columns else 0
    if not portfolio.has_position():
        qty, price = trader.execute_buy(symbol, quote_bal, 0, candle_ts)
        if qty > 0 and price:
            portfolio.add_buy(price, qty, 1)
            Notifier.buy_signal(symbol, "1차 진입", last_sig)
    else:
        ticker = client.fetch_ticker(symbol)
        price = safe_float(ticker.get("last"), 0.0)
        portfolio.update_recent_high(price)
        if risk.should_stop_loss(portfolio.avg_entry_price, price):
            trader.execute_sell(symbol, portfolio.quantity, "손절", price)
            portfolio.set_stop_time(datetime.now(timezone.utc).isoformat())
            portfolio.quantity = 0.0
            portfolio.avg_entry_price = 0.0
            portfolio.buy_stage = 0
            portfolio.sell_stage = 0
        else:
            ratio = risk.take_profit_sell_ratio(portfolio.avg_entry_price, price, portfolio.sell_stage)
            if ratio and portfolio.quantity > 0:
                sell_qty = portfolio.quantity * ratio
                if trader.execute_sell(symbol, sell_qty, "익절", price):
                    portfolio.add_sell(sell_qty, portfolio.sell_stage + 1)

    save_state({"portfolio": portfolio.to_state()})


if __name__ == "__main__":
    # --live: 실거래 모드 (PAPER_TRADING=false). .env의 PAPER_TRADING보다 우선.
    use_live = "--live" in sys.argv
    if use_live:
        cfg.PAPER_TRADING = False
        logger.warning("*** 실거래 모드 (--live) - 실제 주문이 전송됩니다 ***")
    run_once(run_strategy_once)
