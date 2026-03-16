#!/usr/bin/env python3
\"\"\"Trader core: executes buys/sells in paper or live mode with safety checks.\"\"\"
from datetime import datetime, timezone
from typing import Optional, Tuple

import config as cfg
from app.exchange.coinone_client import CoinoneClient
from app.strategy.risk_manager import RiskManager
from app.services.notifier import buy_signal, api_error
from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Trader:
    \"\"\"실거래/페이퍼 실행. PAPER_TRADING=True면 실제 주문 없음.\"\"\"

    def __init__(self, client: CoinoneClient, risk: RiskManager, paper: bool = None):
        self.client = client
        self.risk = risk
        self.paper = paper if paper is not None else cfg.PAPER_TRADING
        self.min_order_krw = cfg.MIN_ORDER_KRW
        self._last_order_candle_ts: Optional[int] = None

    def can_order_this_candle(self, candle_ts: int) -> bool:
        \"\"\"동일 캔들에서 중복 주문 방지.\"\"\"
        if self._last_order_candle_ts == candle_ts:
            return False
        return True

    def _mark_order_candle(self, candle_ts: int) -> None:
        self._last_order_candle_ts = candle_ts

    def execute_buy(
        self, symbol: str, quote_balance: float, stage: int, candle_ts: int
    ) -> Tuple[float, Optional[float]]:
        \"\"\"분할 매수 1회 실행. (수량, 체결가) 반환. 실패 시 (0, None).\"\"\"
        buy_splits = self.risk.buy_size_splits(quote_balance)
        amount_quote = buy_splits[stage] if stage < len(buy_splits) else 0.0
        if amount_quote < self.min_order_krw:
            logger.info(\"매수 스킵: 주문금액 %.0f < 최소 %.0f\", amount_quote, self.min_order_krw)
            return 0.0, None
        if not self.can_order_this_candle(candle_ts):
            return 0.0, None
        try:
            ticker = self.client.fetch_ticker(symbol)
            price = safe_float(ticker.get(\"last\"), 0.0)
            if price <= 0:
                return 0.0, None
            amount_base = amount_quote / price
        except Exception as e:
            api_error(\"현재가 조회 실패\", e)
            return 0.0, None
        if self.paper:
            buy_signal(symbol, f\"stage {stage+1}\", {\"qty\": amount_base, \"price\": price})
            self._mark_order_candle(candle_ts)
            return amount_base, price
        try:
            order = self.client.create_market_buy_order(symbol, amount_base)
            buy_signal(symbol, f\"stage {stage+1}\", order)
            self._mark_order_candle(candle_ts)
            return amount_base, price
        except Exception as e:
            api_error(\"매수 주문 실패\", e)
            return 0.0, None

    def execute_sell(
        self, symbol: str, amount: float, reason: str, price: Optional[float] = None
    ) -> bool:
        \"\"\"매도 실행. 성공 시 True.\"\"\"
        if amount <= 0:
            return False
        if price is None:
            try:
                ticker = self.client.fetch_ticker(symbol)
                price = safe_float(ticker.get(\"last\"), 0.0)
            except Exception as e:
                api_error(\"현재가 조회 실패\", e)
                return False
        if amount * price < self.min_order_krw:
            logger.info(\"매도 스킵: 평가금 %.0f < 최소 %.0f\", amount * price, self.min_order_krw)
            return False
        if self.paper:
            buy_signal(symbol, f\"sell {reason}\", {\"qty\": amount, \"price\": price})
            return True
        try:
            self.client.create_market_sell_order(symbol, amount)
            buy_signal(symbol, f\"sell {reason}\", {\"qty\": amount, \"price\": price})
            return True
        except Exception as e:
            api_error(\"매도 주문 실패\", e)
            return False

