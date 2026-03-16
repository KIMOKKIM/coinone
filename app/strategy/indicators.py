import numpy as np
import pandas as pd

class Indicators:
    @staticmethod
    def sma(series, period):
        return series.rolling(period).mean()

    @staticmethod
    def ema(series, period):
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def bollinger_bands(series, period=20, std=2.0):
        ma = series.rolling(period).mean()
        sd = series.rolling(period).std()
        upper = ma + sd * std
        lower = ma - sd * std
        return lower, ma, upper

    @staticmethod
    def volume_ma(series, period=20):
        return series.rolling(period).mean()

    @staticmethod
    def recent_high_low_box(high_s, low_s, close_s, lookback):
        # return tuple of recent high and low arrays (simple)
        highs = high_s.rolling(lookback).max()
        lows = low_s.rolling(lookback).min()
        return {"highs": highs, "lows": lows}

# -*- coding: utf-8 -*-
"""
지표: SMA, EMA, 볼린저밴드, ATR, 거래량 평균, 최근 30일 고점/저점/박스 구간.
"""
from typing import Dict, List, Tuple

import pandas as pd

from app.utils.helpers import safe_float


class Indicators:
    """4시간봉/일봉 기준 지표 계산."""

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """단순 이동 평균."""
        return series.rolling(window=period).mean()

    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        """지수 이동 평균."""
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def bollinger_bands(close: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """볼린저 밴드: 중간선, 상단, 하단."""
        mid = close.rolling(window=period).mean()
        std = close.rolling(window=period).std()
        upper = mid + std * std_dev
        lower = mid - std * std_dev
        return lower, mid, upper

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """평균 진입 범위 (변동성)."""
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low - close.shift(1)).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def volume_ma(volume: pd.Series, period: int) -> pd.Series:
        """거래량 이동평균."""
        return volume.rolling(window=period).mean()

    @staticmethod
    def recent_high_low_box(high: pd.Series, low: pd.Series, close: pd.Series, lookback: int = 30) -> Dict[str, float]:
        """
        최근 N일 고점/저점/박스 구간 (60%, 80%, 90%).
        Plan: 절대값 하드코딩 대신 계산.
        """
        if len(high) < lookback or len(low) < lookback:
            return {"high": 0.0, "low": 0.0, "range_60": 0.0, "range_80": 0.0, "range_90": 0.0}
        h = high.iloc[-lookback:].max()
        l = low.iloc[-lookback:].min()
        r = h - l
        return {
            "high": float(h),
            "low": float(l),
            "range_60": float(l + r * 0.6),
            "range_80": float(l + r * 0.8),
            "range_90": float(l + r * 0.9),
        }
