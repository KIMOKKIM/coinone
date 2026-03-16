from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime

@dataclass
class Portfolio:
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    buy_stage: int = 0
    sell_stage: int = 0
    last_stop_time: Optional[str] = None

    def has_position(self) -> bool:
        return self.quantity > 0

    def add_buy(self, price: float, qty: float, stage: int):
        total_cost = self.avg_entry_price * self.quantity + price * qty
        self.quantity += qty
        if self.quantity > 0:
            self.avg_entry_price = total_cost / self.quantity
        self.buy_stage = stage

    def add_sell(self, qty: float, stage: int):
        self.quantity = max(0.0, self.quantity - qty)
        self.sell_stage = stage

    def update_recent_high(self, price: float):
        # placeholder for trailing logic
        pass

    def set_stop_time(self, iso: str):
        self.last_stop_time = iso

    def to_state(self):
        return {
            "quantity": self.quantity,
            "avg_entry_price": self.avg_entry_price,
            "buy_stage": self.buy_stage,
            "sell_stage": self.sell_stage,
            "last_stop_time": self.last_stop_time,
        }

# -*- coding: utf-8 -*-
"""
포트폴리오: 평균매수가, 보유수량, 평가손익, 분할매수/매도 단계 추적.
"""
from typing import Any, Dict, Optional

from app.utils.helpers import safe_float


class Portfolio:
    """보유 포지션 및 매수/매도 단계 상태."""

    def __init__(self, state: Optional[Dict[str, Any]] = None):
        state = state or {}
        self.avg_entry_price = safe_float(state.get("avg_entry_price"), 0.0)
        self.quantity = safe_float(state.get("quantity"), 0.0)
        self.buy_stage = int(state.get("buy_stage", 0))  # 0: 없음, 1: 1차만, 2: 2차까지, 3: 3차까지
        self.sell_stage = int(state.get("sell_stage", 0))  # 0: 익절 안 함, 1,2,3: 1~3차 익절 완료
        self.last_stop_time = state.get("last_stop_time")  # ISO str or None
        self.recent_high = safe_float(state.get("recent_high"), 0.0)

    def to_state(self) -> Dict[str, Any]:
        """상태 저장용 dict."""
        return {
            "avg_entry_price": self.avg_entry_price,
            "quantity": self.quantity,
            "buy_stage": self.buy_stage,
            "sell_stage": self.sell_stage,
            "last_stop_time": self.last_stop_time,
            "recent_high": self.recent_high,
        }

    def has_position(self) -> bool:
        """포지션 보유 여부."""
        return self.quantity > 0

    def market_value(self, current_price: float) -> float:
        """평가 금액 (quote)."""
        return self.quantity * current_price

    def pnl_pct(self, current_price: float) -> float:
        """평가 손익률."""
        if self.avg_entry_price <= 0:
            return 0.0
        return (current_price - self.avg_entry_price) / self.avg_entry_price

    def update_recent_high(self, price: float) -> None:
        """트레일링 스탑용 최고가 갱신."""
        if price > self.recent_high:
            self.recent_high = price

    def add_buy(self, price: float, qty: float, stage: int) -> None:
        """분할 매수 반영 (평균단가·수량·단계)."""
        total_cost = self.avg_entry_price * self.quantity + price * qty
        self.quantity += qty
        self.avg_entry_price = total_cost / self.quantity if self.quantity else 0.0
        self.buy_stage = max(self.buy_stage, stage)
        self.update_recent_high(price)

    def add_sell(self, qty: float, stage: int) -> None:
        """분할 매도 반영 (수량·익절 단계)."""
        self.quantity -= qty
        if self.quantity <= 0:
            self.quantity = 0.0
            self.avg_entry_price = 0.0
            self.buy_stage = 0
            self.sell_stage = 0
            self.recent_high = 0.0
        else:
            self.sell_stage = max(self.sell_stage, stage)

    def set_stop_time(self, iso_time: Optional[str]) -> None:
        """손절 발생 시각 저장 (쿨다운용)."""
        self.last_stop_time = iso_time
