from app.utils.logger import get_logger
import os
import requests

logger = get_logger(__name__)

# Telegram notifier (disabled unless env vars provided)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def _send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text}, timeout=5)
        return r.status_code == 200
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False

def buy_signal(symbol, title, details):
    msg = f"[BUY] {symbol} {title} {details}"
    logger.info(msg)
    _send_telegram(msg)

def api_error(title, err):
    msg = f"[API ERROR] {title}: {err}"
    logger.error(msg)
    _send_telegram(msg)

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
