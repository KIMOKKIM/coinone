import config as cfg
from datetime import datetime, timedelta, timezone

class RiskManager:
    def __init__(self):
        self.max_capital_allocation = cfg.MAX_CAPITAL_ALLOCATION
        self.buy_split = cfg.BUY_SPLIT_RATIOS
        self.cooldown_hours = cfg.COOLDOWN_HOURS
        self.stop_loss_pct = cfg.STOP_LOSS_PCT
        self.tp_levels = cfg.TAKE_PROFIT_LEVELS
        self.tp_ratios = cfg.TAKE_PROFIT_RATIOS

    def max_position_quote(self, total_quote: float) -> float:
        return total_quote * self.max_capital_allocation

    def buy_size_splits(self, total_quote: float):
        max_quote = self.max_position_quote(total_quote)
        return [max_quote * r for r in self.buy_split]

    def should_stop_loss(self, entry_price: float, current_price: float) -> bool:
        if entry_price <= 0:
            return False
        return (current_price - entry_price) / entry_price <= -self.stop_loss_pct

    def take_profit_sell_ratio(self, entry_price: float, current_price: float, sell_stage: int):
        if sell_stage >= len(self.tp_levels):
            return 0.0
        tp = self.tp_levels[sell_stage]
        if (current_price - entry_price) / entry_price >= tp:
            return self.tp_ratios[sell_stage]
        return 0.0

    def cooldown_ok(self, last_stop_iso: str) -> bool:
        if not last_stop_iso:
            return True
        try:
            last = datetime.fromisoformat(last_stop_iso)
            return datetime.now(timezone.utc) - last >= timedelta(hours=self.cooldown_hours)
        except Exception:
            return True

# -*- coding: utf-8 -*-
"""
리스크 관리: 포지션 크기 계산, 최대 손실 제한, 손절/익절/트레일링스탑, 쿨다운.
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

import config as cfg
from app.utils.helpers import safe_float


class RiskManager:
    """손절/익절/자금 한도/재진입 제한."""

    def __init__(
        self,
        stop_loss_pct: float = None,
        take_profit_levels: list = None,
        take_profit_ratios: list = None,
        max_capital_allocation: float = None,
        buy_split_ratios: list = None,
        cooldown_hours: float = None,
        trailing_stop_pct: float = None,
        enable_target_30: bool = None,
        target_30_pct: float = None,
    ):
        self.stop_loss_pct = stop_loss_pct if stop_loss_pct is not None else cfg.STOP_LOSS_PCT
        self.take_profit_levels = take_profit_levels or cfg.TAKE_PROFIT_LEVELS
        self.take_profit_ratios = take_profit_ratios or cfg.TAKE_PROFIT_RATIOS
        self.max_capital_allocation = max_capital_allocation if max_capital_allocation is not None else cfg.MAX_CAPITAL_ALLOCATION
        self.buy_split_ratios = buy_split_ratios or cfg.BUY_SPLIT_RATIOS
        self.cooldown_hours = cooldown_hours if cooldown_hours is not None else cfg.COOLDOWN_HOURS
        self.trailing_stop_pct = trailing_stop_pct if trailing_stop_pct is not None else cfg.TRAILING_STOP_PCT
        self.enable_target_30 = enable_target_30 if enable_target_30 is not None else cfg.ENABLE_TARGET_30_MODE
        self.target_30_pct = target_30_pct if target_30_pct is not None else cfg.TARGET_30_PCT

    def position_size_quote(self, total_balance_quote: float, stage: int) -> float:
        """한 사이클에 쓸 수 있는 금액의 N차 분할 매수 금액 (quote)."""
        cap = total_balance_quote * self.max_capital_allocation
        if stage < 0 or stage >= len(self.buy_split_ratios):
            return 0.0
        return cap * self.buy_split_ratios[stage]

    def should_stop_loss(self, entry_price: float, current_price: float) -> bool:
        """고정 손절 % 도달 시 True."""
        if entry_price <= 0:
            return False
        pnl_pct = (current_price - entry_price) / entry_price
        return pnl_pct <= -self.stop_loss_pct

    def take_profit_sell_ratio(self, entry_price: float, current_price: float, sell_stage: int) -> Optional[float]:
        """
        분할 익절: 현재가가 어느 구간이면 해당 비중 반환. 아니면 None.
        sell_stage: 이미 0차, 1차, 2차 익절했으면 0,1,2 → 다음은 1,2,3 구간.
        """
        if entry_price <= 0 or sell_stage >= len(self.take_profit_levels):
            return None
        pnl_pct = (current_price - entry_price) / entry_price
        level = self.take_profit_levels[sell_stage]
        if pnl_pct >= level:
            return self.take_profit_ratios[sell_stage]
        return None

    def target_30_sell_all(self, entry_price: float, current_price: float) -> bool:
        """30% 목표 모드: +30% 도달 시 전량 매도."""
        if not self.enable_target_30 or entry_price <= 0:
            return False
        pnl_pct = (current_price - entry_price) / entry_price
        return pnl_pct >= self.target_30_pct

    def cooldown_ok(self, last_stop_time: Optional[str]) -> bool:
        """손절 직후 쿨다운 경과 여부. last_stop_time은 ISO 형식 문자열 또는 None."""
        if last_stop_time is None or self.cooldown_hours <= 0:
            return True
        try:
            dt = datetime.fromisoformat(last_stop_time.replace("Z", "+00:00"))
        except Exception:
            return True
        now = datetime.now(timezone.utc)
        return (now - dt).total_seconds() >= self.cooldown_hours * 3600

    def trailing_stop_triggered(self, current_price: float, recent_high: float) -> bool:
        """고점 대비 N% 하락 시 True."""
        if recent_high <= 0:
            return False
        return current_price <= recent_high * (1 - self.trailing_stop_pct)
