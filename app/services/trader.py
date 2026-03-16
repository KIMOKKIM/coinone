from typing import Optional
import config as cfg
from app.utils.logger import get_logger
from app.exchange.coinone_client import CoinoneClient
import time

logger = get_logger(__name__)

class Trader:
    def __init__(self, client: Optional[CoinoneClient]=None, paper: bool=True):
        self.paper = paper or cfg.PAPER_TRADING
        self.client = client or CoinoneClient(cfg.COINONE_ACCESS_KEY, cfg.COINONE_SECRET_KEY)
        # simple in-memory order simulation
        self.orders = []

    def execute_buy(self, symbol: str, quote_balance: float, stage: int, ts: int):
        \"\"\"Execute market buy for the target stage. Returns (qty, price).\"\"\"
        if quote_balance < cfg.MIN_ORDER_KRW:
            logger.info(\"Insufficient quote balance for buy: %s\", quote_balance)
            return 0.0, 0.0
        price = self._fetch_price(symbol)
        size_quote = quote_balance * (cfg.BUY_SPLIT_RATIOS[stage] if stage < len(cfg.BUY_SPLIT_RATIOS) else cfg.BUY_SPLIT_RATIOS[-1])
        qty = size_quote / price
        if self.paper:
            logger.info(\"PAPER buy: %s KRW @ %s => qty=%s\", round(size_quote), price, qty)
            self.orders.append({"side":"buy","qty":qty,"price":price,"ts":ts})
            return qty, price
        else:
            # live order via CCXT - market buy
            try:
                res = self.client.create_market_buy_order(symbol, qty)
                logger.info(\"Live buy order: %s\", res)
                return float(res.get("filled", qty)), price
            except Exception as e:
                logger.exception(\"Live buy failed: %s\", e)
                return 0.0, 0.0

    def execute_sell(self, symbol: str, qty: float, reason: str, price_override: float = None):
        price = price_override or self._fetch_price(symbol)
        if self.paper:
            logger.info(\"PAPER sell: %s qty @ %s reason=%s\", qty, price, reason)
            self.orders.append({"side":"sell","qty":qty,"price":price,"reason":reason})
            return True
        else:
            try:
                res = self.client.create_market_sell_order(symbol, qty)
                logger.info(\"Live sell order: %s\", res)
                return True
            except Exception as e:
                logger.exception(\"Live sell failed: %s\", e)
                return False

    def _fetch_price(self, symbol: str) -> float:
        t = self.client.fetch_ticker(symbol)
        return float(t.get("last", 0) or t.get("close", 0) or 0)

    def run_loop(self):
        # naive loop for demo; in production use scheduler/cron/systemd
        logger.info(\"Trader loop start. paper=%s\", self.paper)
        while True:
            try:
                # call upper-level orchestration; kept minimal here
                time.sleep(60)
            except KeyboardInterrupt:
                break

# -*- coding: utf-8 -*-
"""
트레이더: 신호 기반 주문 실행, 중복 주문 방지, 슬리피지·최소 주문금액 고려, 로그 저장.
"""
from datetime import datetime, timezone
from typing import Optional, Tuple

import config as cfg
from app.exchange.coinone_client import CoinoneClient, CoinoneClientError
from app.strategy.portfolio import Portfolio
from app.strategy.risk_manager import RiskManager
from app.services.notifier import Notifier
from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Trader:
    """실거래/페이퍼 실행. PAPER_TRADING=True면 실제 주문 없음."""

    def __init__(self, client: CoinoneClient, risk: RiskManager, paper: bool = None):
        self.client = client
        self.risk = risk
        self.paper = paper if paper is not None else cfg.PAPER_TRADING
        self.min_order_krw = cfg.MIN_ORDER_KRW
        self._last_order_candle_ts: Optional[int] = None

    def can_order_this_candle(self, candle_ts: int) -> bool:
        """동일 캔들에서 중복 주문 방지."""
        if self._last_order_candle_ts == candle_ts:
            return False
        return True

    def _mark_order_candle(self, candle_ts: int) -> None:
        self._last_order_candle_ts = candle_ts

    def execute_buy(
        self, symbol: str, quote_balance: float, stage: int, candle_ts: int
    ) -> Tuple[float, Optional[float]]:
        """
        분할 매수 1회 실행. (수량, 체결가) 반환. 실패 시 (0, None).
        """
        amount_quote = self.risk.position_size_quote(quote_balance, stage)
        if amount_quote < self.min_order_krw:
            logger.info("매수 스킵: 주문금액 %.0f < 최소 %.0f", amount_quote, self.min_order_krw)
            return 0.0, None
        if not self.can_order_this_candle(candle_ts):
            return 0.0, None
        try:
            ticker = self.client.fetch_ticker(symbol)
            price = safe_float(ticker.get("last"), 0.0)
            if price <= 0:
                return 0.0, None
            amount_base = amount_quote / price
        except CoinoneClientError as e:
            Notifier.api_error("현재가 조회 실패", e)
            return 0.0, None
        if self.paper:
            Notifier.buy_executed(symbol, stage + 1, amount_base, price, paper=True)
            self._mark_order_candle(candle_ts)
            return amount_base, price
        try:
            order = self.client.create_market_buy_order(symbol, amount_base)
            Notifier.buy_executed(symbol, stage + 1, amount_base, price, paper=False)
            self._mark_order_candle(candle_ts)
            return amount_base, price
        except CoinoneClientError as e:
            Notifier.api_error("매수 주문 실패", e)
            return 0.0, None

    def execute_sell(
        self, symbol: str, amount: float, reason: str, price: Optional[float] = None
    ) -> bool:
        """매도 실행. 성공 시 True."""
        if amount <= 0:
            return False
        if price is None:
            try:
                ticker = self.client.fetch_ticker(symbol)
                price = safe_float(ticker.get("last"), 0.0)
            except CoinoneClientError as e:
                Notifier.api_error("현재가 조회 실패", e)
                return False
        if amount * price < self.min_order_krw:
            logger.info("매도 스킵: 평가금 %.0f < 최소 %.0f", amount * price, self.min_order_krw)
            return False
        if self.paper:
            Notifier.sell_executed(symbol, reason, amount, price, paper=True)
            return True
        try:
            self.client.create_market_sell_order(symbol, amount)
            Notifier.sell_executed(symbol, reason, amount, price, paper=False)
            return True
        except CoinoneClientError as e:
            Notifier.api_error("매도 주문 실패", e)
            return False
