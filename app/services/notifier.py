from app.utils.logger import get_logger
logger = get_logger(__name__)

def buy_signal(symbol, title, details):
    logger.info("BUY SIGNAL %s %s", symbol, title)

def api_error(title, err):
    logger.error("API ERROR %s %s", title, err)

# -*- coding: utf-8 -*-
"""
알림: 콘솔 상세 로그. 텔레그램 등은 추후 확장.
Plan: 매수신호, 1차 매수 실행, 손절/익절 실행, API 오류 등 로그.
"""
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Notifier:
    """콘솔 및 로그 파일에 이벤트 출력."""

    @staticmethod
    def buy_signal(symbol: str, reason: str, detail: dict = None) -> None:
        logger.info("[매수신호] %s - %s %s", symbol, reason, detail or "")

    @staticmethod
    def buy_executed(symbol: str, stage: int, amount: float, price: float, paper: bool) -> None:
        mode = "(페이퍼)" if paper else "(실제)"
        logger.info("[%s차 매수 실행%s] %s - 수량 %.8f @ %.0f", stage, mode, symbol, amount, price)

    @staticmethod
    def sell_executed(symbol: str, reason: str, amount: float, price: float, paper: bool) -> None:
        mode = "(페이퍼)" if paper else "(실제)"
        logger.info("[매도 실행%s] %s - %s 수량 %.8f @ %.0f", mode, symbol, reason, amount, price)

    @staticmethod
    def stop_loss(symbol: str, price: float, pnl_pct: float) -> None:
        logger.warning("[손절] %s @ %.0f 손익 %.2f%%", symbol, price, pnl_pct * 100)

    @staticmethod
    def take_profit(symbol: str, stage: int, price: float, pnl_pct: float) -> None:
        logger.info("[%s차 익절] %s @ %.0f 손익 %.2f%%", stage, symbol, price, pnl_pct * 100)

    @staticmethod
    def api_error(msg: str, exc: Exception = None) -> None:
        logger.error("[API 오류] %s %s", msg, exc or "")
