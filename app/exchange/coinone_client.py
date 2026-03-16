# -*- coding: utf-8 -*-
"""Minimal Coinone client wrapper for candles, ticker, balance and (paper) orders."""
from typing import Any, Dict, List
from pathlib import Path
import time
import requests
import ccxt

import config as cfg
from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


class CoinoneClient:
    def __init__(self, access_key: str, secret_key: str, sandbox: bool = False):
        self._access = access_key
        self._secret = secret_key
        self._exchange = None
        self._sandbox = sandbox

    def _get_exchange(self):
        if self._exchange is None:
            self._exchange = ccxt.coinone({
                "apiKey": self._access,
                "secret": self._secret,
                "enableRateLimit": True,
            })
            if self._sandbox:
                try:
                    self._exchange.set_sandbox_mode(True)
                except Exception:
                    pass
        return self._exchange

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 500, since: int = None) -> List[List]:
        # Use public v2 chart endpoint for reliable OHLCV
        quote, base = symbol.split("/") if "/" in symbol else ("KRW", "BTC")
        if quote.upper() != "KRW":
            quote, base = "KRW", quote
        url = f"https://api.coinone.co.kr/public/v2/chart/{quote}/{base}"
        params = {"interval": timeframe}
        rows = []
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data.get("result") != "success":
                logger.warning("chart API returned error: %s", data)
                return []
            chart = data.get("chart", [])
            for c in chart:
                rows.append([int(c["timestamp"]), float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"]), float(c.get("target_volume") or c.get("quote_volume") or 0)])
        except Exception as e:
            logger.exception("fetch_ohlcv failed: %s", e)
        return rows[-limit:] if limit and rows else rows

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        ex = self._get_exchange()
        try:
            return ex.fetch_ticker(symbol)
        except Exception as e:
            logger.warning("fetch_ticker via ccxt failed: %s. Trying public ticker", e)
            # fallback to public ticker endpoint
            try:
                quote, base = symbol.split("/")
                url = f"https://api.coinone.co.kr/public/v2/ticker_new/{quote}/{base}"
                r = requests.get(url, timeout=5); r.raise_for_status()
                d = r.json()
                return {"last": safe_float(d.get("last") or d.get("close") or 0)}
            except Exception:
                return {"last": 0}

    def fetch_balance(self) -> Dict[str, Any]:
        ex = self._get_exchange()
        try:
            return ex.fetch_balance()
        except Exception as e:
            logger.warning("fetch_balance failed: %s", e)
            # try v2.1 endpoint directly (best-effort)
            try:
                url = "https://api.coinone.co.kr/v2.1/account/balance/all"
                # cannot sign without API helper; return empty
                return {"info": {"result": "error", "errorMsg": str(e)}}
            except Exception:
                return {"info": {"result": "error", "errorMsg": str(e)}}

    def get_free_balance(self, balance: Dict[str, Any], currency: str) -> float:
        try:
            # check standard ccxt structure
            free = balance.get("free") or {}
            if isinstance(free, dict):
                for k in (currency, currency.upper(), currency.lower()):
                    if k in free:
                        return safe_float(free.get(k))
            # check info.balances list
            info = balance.get("info") or {}
            for item in (info.get("balances") or []):
                if isinstance(item, dict) and str(item.get("currency","")).upper() == currency.upper():
                    return safe_float(item.get("available") or item.get("avail") or item.get("balance") or 0)
            # fallbacks
            val = balance.get(currency) or balance.get(currency.upper()) or balance.get(currency.lower())
            if isinstance(val, dict):
                return safe_float(val.get("free") or val.get("avail") or val.get("available") or val.get("total") or 0)
            return safe_float(val or 0)
        except Exception:
            return 0.0

# -*- coding: utf-8 -*-
"""
Coinone API 클라이언트: 캔들/현재가/잔고/주문, 재시도 및 예외 처리.
Plan: 동일 거래소(Coinone) 기준 데이터·주문 사용.
캔들은 Coinone 공식 public v2/chart 사용 (ccxt는 fetchOHLCV 미지원).
"""
import time
from typing import Any, Dict, List, Optional

import ccxt
import requests

from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 재시도 설정
MAX_RETRIES = 3
RETRY_DELAY = 1.0


class CoinoneClientError(Exception):
    """API/네트워크 오류."""
    pass


class CoinoneClient:
    """Coinone 현물 전용 클라이언트 (레버리지/선물 미지원)."""

    def __init__(self, access_key: str, secret_key: str, sandbox: bool = False):
        self._access_key = access_key
        self._secret_key = secret_key
        self._exchange: Optional[ccxt.Exchange] = None
        self._sandbox = sandbox

    def _get_exchange(self) -> ccxt.Exchange:
        """ccxt 거래소 인스턴스 생성 (지연 초기화)."""
        if self._exchange is None:
            self._exchange = ccxt.coinone({
                "apiKey": self._access_key,
                "secret": self._secret_key,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            })
            if self._sandbox:
                self._exchange.set_sandbox_mode(True)
        return self._exchange

    def _request(self, fn, *args, **kwargs) -> Any:
        """재시도 로직으로 API 호출."""
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                return fn(*args, **kwargs)
            except ccxt.NetworkError as e:
                last_err = e
                logger.warning("네트워크 오류 (재시도 %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            except ccxt.ExchangeError as e:
                last_err = e
                logger.warning("거래소 오류 (재시도 %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            except Exception as e:
                last_err = e
                logger.warning("오류 (재시도 %d/%d): %s", attempt + 1, MAX_RETRIES, e)
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
        raise CoinoneClientError(f"API 호출 실패: {last_err}") from last_err

    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int = 100, since: Optional[int] = None) -> List[List]:
        """캔들 데이터 조회. Coinone 공식 public v2/chart 사용 (재시도 포함)."""
        quote, base = symbol.split("/") if "/" in symbol else (symbol[-3:], symbol[:3])
        if quote.upper() != "KRW":
            quote, base = "KRW", quote
        interval = timeframe if timeframe in ("1m", "3m", "5m", "15m", "30m", "1h", "2h", "4h", "6h", "1d", "1w") else "4h"
        url = f"https://api.coinone.co.kr/public/v2/chart/{quote}/{base}"
        all_rows: List[List] = []
        ts_ms = since
        for _ in range(MAX_RETRIES * 2):
            try:
                params = {"interval": interval}
                if ts_ms:
                    params["timestamp"] = ts_ms
                r = requests.get(url, params=params, timeout=10)
                r.raise_for_status()
                data = r.json()
                if data.get("result") != "success":
                    raise CoinoneClientError(data.get("error_code", "unknown"))
                chart = data.get("chart") or []
                for c in chart:
                    all_rows.append([
                        int(c["timestamp"]),
                        float(c["open"]),
                        float(c["high"]),
                        float(c["low"]),
                        float(c["close"]),
                        float(c.get("target_volume") or c.get("quote_volume") or 0),
                    ])
                if data.get("is_last") or len(chart) < 2:
                    break
                if chart:
                    ts_ms = int(chart[-1]["timestamp"])
                if len(all_rows) >= limit:
                    break
                time.sleep(0.2)
            except (requests.RequestException, KeyError, ValueError) as e:
                logger.warning("캔들 조회 재시도: %s", e)
                time.sleep(RETRY_DELAY)
        all_rows.sort(key=lambda x: x[0])
        return all_rows[-limit:] if len(all_rows) > limit else all_rows

    def fetch_ticker(self, symbol: str) -> Dict[str, Any]:
        """현재가 조회."""
        ex = self._get_exchange()
        return self._request(ex.fetch_ticker, symbol)

    def fetch_balance(self) -> Dict[str, Any]:
        """잔고 조회."""
        ex = self._get_exchange()
        return self._request(ex.fetch_balance)

    def create_market_buy_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """시장가 매수."""
        ex = self._get_exchange()
        return self._request(ex.create_market_buy_order, symbol, amount)

    def create_market_sell_order(self, symbol: str, amount: float) -> Dict[str, Any]:
        """시장가 매도."""
        ex = self._get_exchange()
        return self._request(ex.create_market_sell_order, symbol, amount)

    def create_limit_buy_order(self, symbol: str, amount: float, price: float) -> Dict[str, Any]:
        """지정가 매수."""
        ex = self._get_exchange()
        return self._request(ex.create_limit_buy_order, symbol, amount, price)

    def create_limit_sell_order(self, symbol: str, amount: float, price: float) -> Dict[str, Any]:
        """지정가 매도."""
        ex = self._get_exchange()
        return self._request(ex.create_limit_sell_order, symbol, amount, price)

    def get_free_balance(self, balance: Dict[str, Any], currency: str) -> float:
        """잔고에서 사용 가능 금액/수량 추출 (CCXT/Coinone 구조 흡수)."""
        try:
            # 표준: balance['free'][currency]
            free_d = balance.get("free")
            if isinstance(free_d, dict):
                for k in (currency, currency.upper(), currency.lower()):
                    if k in free_d and free_d.get(k) not in (None, "ERRORMSG"):
                        return safe_float(free_d[k])
            # balance[currency] = { free, avail, available, total }
            for key in (currency, currency.upper(), currency.lower()):
                cur = balance.get(key)
                if cur is None:
                    continue
                if isinstance(cur, dict):
                    v = cur.get("free") or cur.get("avail") or cur.get("available")
                    if v is not None:
                        return safe_float(v)
                    return safe_float(cur.get("total", 0))
                return safe_float(cur, 0)
            # Coinone info.balances 배열: { currency, available }
            info = balance.get("info") or {}
            for item in (info.get("balances") or []):
                if isinstance(item, dict) and str(item.get("currency", "")).upper() == currency.upper():
                    return safe_float(item.get("available") or item.get("avail") or 0)
        except Exception:
            pass
        return 0.0

    def check_order_permission(self) -> bool:
        """주문 권한 체크: API 키로 잔고 조회 가능 여부."""
        try:
            self.fetch_balance()
            return True
        except Exception as e:
            logger.error("주문 권한 체크 실패: %s", e)
            return False
