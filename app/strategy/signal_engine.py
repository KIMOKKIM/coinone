from typing import Any, Dict, List
import pandas as pd

from app.strategy.indicators import Indicators
import config as cfg


class SignalEngine:
    """4시간봉 기준 진입/청산 신호."""

    def __init__(
        self,
        sma_period: int = None,
        ema_period: int = None,
        bb_period: int = None,
        bb_std: float = None,
        vol_k: float = None,
        crash_lookback: int = None,
        crash_threshold_pct: float = None,
        volume_ma_period: int = None,
        ema_reclaim_bars: int = None,
    ):
        self.sma_period = sma_period or cfg.SMA_PERIOD
        self.ema_period = ema_period or cfg.EMA_PERIOD
        self.bb_period = bb_period or cfg.BB_PERIOD
        self.bb_std = bb_std or cfg.BB_STD
        self.vol_k = vol_k or getattr(cfg, "VOL_BREAKOUT_K", 0.5)
        self.crash_lookback = crash_lookback or cfg.CRASH_LOOKBACK_CANDLES
        self.crash_threshold_pct = crash_threshold_pct or cfg.CRASH_THRESHOLD_PCT
        self.volume_ma_period = volume_ma_period or cfg.VOLUME_MA_PERIOD
        self.ema_reclaim_bars = ema_reclaim_bars or cfg.EMA_RECLAIM_BARS

    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame에 지표 컬럼 추가."""
        if "sma50" in df.columns:
            return df
        df = df.copy()
        df["sma50"] = Indicators.sma(df["close"], self.sma_period)
        df["ema20"] = Indicators.ema(df["close"], self.ema_period)
        lower, mid, upper = Indicators.bollinger_bands(df["close"], self.bb_period, self.bb_std)
        df["bb_lower"], df["bb_mid"], df["bb_upper"] = lower, mid, upper
        # ATR not implemented in Indicators, use simple volatility proxy if needed
        df["volume_ma"] = Indicators.volume_ma(df["volume"], self.volume_ma_period)
        return df

    def trend_ok(self, row: pd.Series) -> bool:
        """추세 필터: 현재가가 SMA50 위, EMA20 위에서만 매수 허용."""
        if pd.isna(row.get("sma50")) or pd.isna(row.get("ema20")):
            return False
        return float(row["close"]) > float(row["sma50"]) and float(row["close"]) > float(row["ema20"])

    def ema_reclaim_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """EMA20 회복: 가격이 EMA20 아래였다가 상향 돌파 후 최소 N캔들 유지."""
        if idx < self.ema_reclaim_bars + 1:
            return False
        close = df["close"].iloc
        ema = df["ema20"].iloc
        for i in range(self.ema_reclaim_bars):
            if close[idx - i] <= ema[idx - i]:
                return False
        if close[idx - self.ema_reclaim_bars] > ema[idx - self.ema_reclaim_bars]:
            return False
        return True

    def bb_breakout_ok(self, row: pd.Series, volume_ok: bool) -> bool:
        """볼린저 상단 돌파 + 거래량 증가 동반."""
        if pd.isna(row.get("bb_upper")) or pd.isna(row.get("volume_ma")):
            return False
        body = float(row["close"]) - float(row["open"])
        breakout = body > 0 and float(row["close"]) > float(row["bb_upper"])
        return bool(breakout and volume_ok)

    def volume_ok(self, row: pd.Series) -> bool:
        """거래량이 최근 N개 평균 대비 증가."""
        if pd.isna(row.get("volume_ma")) or row["volume_ma"] == 0:
            return False
        return float(row["volume"]) >= float(row["volume_ma"])

    def volatility_breakout_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """K값 변동성 돌파: 당일 시가 + (전일 고가-저가)*K 상향 돌파."""
        if idx < 2:
            return False
        prev = df.iloc[idx - 1]
        curr = df.iloc[idx]
        range_prev = float(prev["high"]) - float(prev["low"])
        target = float(curr["open"]) + range_prev * self.vol_k
        return float(curr["close"]) >= target

    def crash_then_recovery_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """급락 다음 캔들 또는 이후 회복 확인 시만 진입."""
        if idx < self.crash_lookback + 1:
            return False
        window = df["close"].iloc[idx - self.crash_lookback : idx + 1]
        if len(window) < 2:
            return False
        drop = (float(window.iloc[-2]) - float(window.min())) / float(window.iloc[-2]) if window.iloc[-2] else 0
        if drop < self.crash_threshold_pct:
            return False
        return float(window.iloc[-1]) > float(window.iloc[-2])

    def box_resistance_near(self, row: pd.Series, box: Dict[str, float]) -> bool:
        """박스 상단 부근이면 추격매수 제한."""
        if not box or box.get("high", 0) == 0:
            return False
        close = float(row["close"])
        return close >= box["range_80"]

    def get_buy_signals(self, df: pd.DataFrame, box: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        각 행에 대해 매수 신호 상세 dict 반환.
        Plan: trend_ok, ema_reclaim_ok, bb_breakout_ok, volume_ok, volatility_breakout_ok, final_buy_signal.
        """
        df = self._ensure_indicators(df)
        out = []
        for i in range(len(df)):
            if i < max(self.sma_period, self.bb_period, self.volume_ma_period) + 2:
                out.append({"index": i, "final_buy_signal": False})
                continue
            row = df.iloc[i]
            trend_ok = self.trend_ok(row)
            ema_reclaim_ok = self.ema_reclaim_ok(df, i)
            vol_ok = self.volume_ok(row)
            bb_breakout_ok = self.bb_breakout_ok(row, vol_ok)
            volatility_breakout_ok = self.volatility_breakout_ok(df, i)
            crash_recovery_ok = self.crash_then_recovery_ok(df, i)
            resistance_near = self.box_resistance_near(row, box)
            final = (
                trend_ok
                and (ema_reclaim_ok or (bb_breakout_ok and crash_recovery_ok))
                and volatility_breakout_ok
                and not resistance_near
            )
            out.append({
                "index": i,
                "trend_ok": trend_ok,
                "ema_reclaim_ok": ema_reclaim_ok,
                "bb_breakout_ok": bb_breakout_ok,
                "volume_ok": vol_ok,
                "volatility_breakout_ok": volatility_breakout_ok,
                "crash_recovery_ok": crash_recovery_ok,
                "resistance_near": resistance_near,
                "final_buy_signal": final,
            })
        return out

    def get_sell_signal_trailing(self, current_price: float, recent_high: float, trailing_pct: float) -> bool:
        """트레일링 스탑: 고점 대비 N% 하락 시 청산 신호."""
        if recent_high <= 0:
            return False
        return current_price <= recent_high * (1 - trailing_pct)

# -*- coding: utf-8 -*-
"""
신호 엔진: 매수/매도 신호 생성. 전략 조건을 개별 함수로 분리하고 dict로 상세 반환.
Plan: trend_ok, ema_reclaim_ok, bb_breakout_ok, volume_ok, volatility_breakout_ok, final_buy_signal 등.
"""
from typing import Any, Dict, List, Optional

import pandas as pd

from app.strategy.indicators import Indicators
import config as cfg


class SignalEngine:
    """4시간봉 기준 진입/청산 신호."""

    def __init__(
        self,
        sma_period: int = None,
        ema_period: int = None,
        bb_period: int = None,
        bb_std: float = None,
        vol_k: float = None,
        crash_lookback: int = None,
        crash_threshold_pct: float = None,
        volume_ma_period: int = None,
        ema_reclaim_bars: int = None,
    ):
        self.sma_period = sma_period or cfg.SMA_PERIOD
        self.ema_period = ema_period or cfg.EMA_PERIOD
        self.bb_period = bb_period or cfg.BB_PERIOD
        self.bb_std = bb_std or cfg.BB_STD
        self.vol_k = vol_k or cfg.VOL_BREAKOUT_K
        self.crash_lookback = crash_lookback or cfg.CRASH_LOOKBACK_CANDLES
        self.crash_threshold_pct = crash_threshold_pct or cfg.CRASH_THRESHOLD_PCT
        self.volume_ma_period = volume_ma_period or cfg.VOLUME_MA_PERIOD
        self.ema_reclaim_bars = ema_reclaim_bars or cfg.EMA_RECLAIM_BARS

    def _ensure_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """DataFrame에 지표 컬럼 추가."""
        if "sma50" in df.columns:
            return df
        df = df.copy()
        df["sma50"] = Indicators.sma(df["close"], self.sma_period)
        df["ema20"] = Indicators.ema(df["close"], self.ema_period)
        lower, mid, upper = Indicators.bollinger_bands(df["close"], self.bb_period, self.bb_std)
        df["bb_lower"], df["bb_mid"], df["bb_upper"] = lower, mid, upper
        df["atr"] = Indicators.atr(df["high"], df["low"], df["close"], 14)
        df["volume_ma"] = Indicators.volume_ma(df["volume"], self.volume_ma_period)
        return df

    def trend_ok(self, row: pd.Series) -> bool:
        """추세 필터: 현재가가 SMA50 위, EMA20 위에서만 매수 허용."""
        if pd.isna(row.get("sma50")) or pd.isna(row.get("ema20")):
            return False
        return float(row["close"]) > float(row["sma50"]) and float(row["close"]) > float(row["ema20"])

    def ema_reclaim_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """EMA20 회복: 가격이 EMA20 아래였다가 상향 돌파 후 최소 N캔들 유지."""
        if idx < self.ema_reclaim_bars + 1:
            return False
        close = df["close"].iloc
        ema = df["ema20"].iloc
        for i in range(self.ema_reclaim_bars):
            if close[idx - i] <= ema[idx - i]:
                return False
        if close[idx - self.ema_reclaim_bars] > ema[idx - self.ema_reclaim_bars]:
            return False
        return True

    def bb_breakout_ok(self, row: pd.Series, volume_ok: bool) -> bool:
        """볼린저 상단 돌파 + 거래량 증가 동반."""
        if pd.isna(row.get("bb_upper")) or pd.isna(row.get("volume_ma")):
            return False
        body = float(row["close"]) - float(row["open"])
        breakout = body > 0 and float(row["close"]) > float(row["bb_upper"])
        return bool(breakout and volume_ok)

    def volume_ok(self, row: pd.Series) -> bool:
        """거래량이 최근 N개 평균 대비 증가."""
        if pd.isna(row.get("volume_ma")) or row["volume_ma"] == 0:
            return False
        return float(row["volume"]) >= float(row["volume_ma"])

    def volatility_breakout_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """K값 변동성 돌파: 당일 시가 + (전일 고가-저가)*K 상향 돌파."""
        if idx < 2:
            return False
        prev = df.iloc[idx - 1]
        curr = df.iloc[idx]
        range_prev = float(prev["high"]) - float(prev["low"])
        target = float(curr["open"]) + range_prev * self.vol_k
        return float(curr["close"]) >= target

    def crash_then_recovery_ok(self, df: pd.DataFrame, idx: int) -> bool:
        """급락 다음 캔들 또는 이후 회복 확인 시만 진입."""
        if idx < self.crash_lookback + 1:
            return False
        window = df["close"].iloc[idx - self.crash_lookback : idx + 1]
        if len(window) < 2:
            return False
        drop = (float(window.iloc[-2]) - float(window.min())) / float(window.iloc[-2]) if window.iloc[-2] else 0
        if drop < self.crash_threshold_pct:
            return False
        return float(window.iloc[-1]) > float(window.iloc[-2])

    def box_resistance_near(self, row: pd.Series, box: Dict[str, float]) -> bool:
        """박스 상단 부근이면 추격매수 제한."""
        if not box or box.get("high", 0) == 0:
            return False
        close = float(row["close"])
        return close >= box["range_80"]

    def get_buy_signals(self, df: pd.DataFrame, box: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        각 행에 대해 매수 신호 상세 dict 반환.
        Plan: trend_ok, ema_reclaim_ok, bb_breakout_ok, volume_ok, volatility_breakout_ok, final_buy_signal.
        """
        df = self._ensure_indicators(df)
        out = []
        for i in range(len(df)):
            if i < max(self.sma_period, self.bb_period, self.volume_ma_period) + 2:
                out.append({"index": i, "final_buy_signal": False})
                continue
            row = df.iloc[i]
            trend_ok = self.trend_ok(row)
            ema_reclaim_ok = self.ema_reclaim_ok(df, i)
            vol_ok = self.volume_ok(row)
            bb_breakout_ok = self.bb_breakout_ok(row, vol_ok)
            volatility_breakout_ok = self.volatility_breakout_ok(df, i)
            crash_recovery_ok = self.crash_then_recovery_ok(df, i)
            resistance_near = self.box_resistance_near(row, box)
            final = (
                trend_ok
                and (ema_reclaim_ok or (bb_breakout_ok and crash_recovery_ok))
                and volatility_breakout_ok
                and not resistance_near
            )
            out.append({
                "index": i,
                "trend_ok": trend_ok,
                "ema_reclaim_ok": ema_reclaim_ok,
                "bb_breakout_ok": bb_breakout_ok,
                "volume_ok": vol_ok,
                "volatility_breakout_ok": volatility_breakout_ok,
                "crash_recovery_ok": crash_recovery_ok,
                "resistance_near": resistance_near,
                "final_buy_signal": final,
            })
        return out

    def get_sell_signal_trailing(self, current_price: float, recent_high: float, trailing_pct: float) -> bool:
        """트레일링 스탑: 고점 대비 N% 하락 시 청산 신호."""
        if recent_high <= 0:
            return False
        return current_price <= recent_high * (1 - trailing_pct)
