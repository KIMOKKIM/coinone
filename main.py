import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import ccxt
import numpy as np
import pandas as pd
from dotenv import load_dotenv

try:
    from oracle_store import OracleTradeStore, TradeEvent
except Exception:  # optional
    OracleTradeStore = None  # type: ignore[assignment]
    TradeEvent = None  # type: ignore[assignment]


logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("coinone-bot")


STATE_FILE = "trade_state.json"


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name) or "").strip().lower()
    if v == "":
        return default
    return v in {"1", "true", "yes", "y", "on"}


def _now_ms() -> int:
    return int(time.time() * 1000)


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def clear_symbol_state(symbol: str) -> None:
    st = load_state()
    if symbol in st:
        st.pop(symbol, None)
        save_state(st)


def _get_free_balance(balance: Dict[str, Any], currency: str) -> float:
    """
    CCXT 거래소별 balance 구조 차이를 흡수.
    - 표준: balance['free'][currency]
    - 일부 거래소: balance[currency]['free']
    """
    try:
        if isinstance(balance.get("free"), dict) and currency in balance["free"]:
            return _safe_float(balance["free"].get(currency, 0))
        cur = balance.get(currency)
        if isinstance(cur, dict):
            return _safe_float(cur.get("free", 0))
        return _safe_float(cur, 0)
    except Exception:
        return 0.0


def _split_symbol(symbol: str) -> Tuple[str, str]:
    base, quote = symbol.split("/")
    return base.strip(), quote.strip()


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    rs = gain / loss.replace(0.0, np.nan)
    return 100 - (100 / (1 + rs))


@dataclass(frozen=True)
class StrategyParams:
    bb_period: int = 20
    bb_std: float = 1.0
    rsi_period: int = 14
    rsi_entry: float = 35.0
    rsi_exit: float = 55.0
    take_profit_pct: float = 0.003  # 0.3%
    stop_loss_pct: float = 0.004    # 0.4%
    max_hold_minutes: int = 90
    cooldown_seconds: int = 60


class Bot:
    def __init__(self) -> None:
        load_dotenv()

        self.live_trading = _env_bool("LIVE_TRADING", False)
        self.mode = (os.getenv("MODE") or "scalper").strip().lower()  # scalper | grid
        self.symbols = [
            s.strip()
            for s in (os.getenv("SYMBOLS") or "BTC/KRW").split(",")
            if s.strip()
        ]
        self.timeframe = (os.getenv("TIMEFRAME") or "1m").strip()
        self.poll_seconds = int(os.getenv("POLL_SECONDS") or "20")

        self.min_order_krw = _safe_float(os.getenv("MIN_ORDER_KRW"), 5000.0)
        # 백테스트 기본값(20%)과 맞추되, 환경변수로 덮어쓰기 허용
        self.buy_amount_pct = _safe_float(os.getenv("BUY_AMOUNT_PCT"), 0.20)

        # 기본값: backtest.py 1일 최적화 결과(하루 10회 내외 거래 기준)와 일치
        self.params = StrategyParams(
            bb_period=int(os.getenv("BB_PERIOD") or 12),
            bb_std=_safe_float(os.getenv("BB_STD"), 0.5),
            rsi_period=int(os.getenv("RSI_PERIOD") or 14),
            rsi_entry=_safe_float(os.getenv("RSI_ENTRY"), 35.0),
            rsi_exit=_safe_float(os.getenv("RSI_EXIT"), 48.0),
            take_profit_pct=_safe_float(os.getenv("TAKE_PROFIT_PCT"), 0.0025),
            stop_loss_pct=_safe_float(os.getenv("STOP_LOSS_PCT"), 0.0050),
            max_hold_minutes=int(os.getenv("MAX_HOLD_MINUTES") or 20),
            cooldown_seconds=int(os.getenv("COOLDOWN_SECONDS") or 0),
        )

        # grid params (MODE=grid 일 때만 사용)
        self.grid_max_lots = int(os.getenv("GRID_MAX_LOTS") or "10")
        self.grid_lot_fraction = _safe_float(os.getenv("GRID_LOT_FRACTION"), 0.10)
        self.grid_spacing_pct = _safe_float(os.getenv("GRID_SPACING_PCT"), 0.0008)
        self.grid_tp_pct = _safe_float(os.getenv("GRID_TP_PCT"), 0.0012)
        self.grid_sl_pct = _safe_float(os.getenv("GRID_SL_PCT"), 0.0)
        self.grid_time_stop_minutes = _safe_float(os.getenv("GRID_TIME_STOP_MINUTES"), 0.0)
        self.mid_entry_pct = _safe_float(os.getenv("MID_ENTRY_PCT"), 0.0015)

        access_key = os.getenv("COINONE_ACCESS_KEY")
        secret_key = os.getenv("COINONE_SECRET_KEY")

        self.exchange = ccxt.coinone(
            {
                "apiKey": access_key,
                "secret": secret_key,
                "enableRateLimit": True,
                "options": {"defaultType": "spot"},
            }
        )

        # 주문/잔고는 코인원, 차트는 업비트 OHLCV 사용
        self.chart_exchange = ccxt.upbit({"enableRateLimit": True})

        self.oracle = None
        if OracleTradeStore is not None:
            self.oracle = OracleTradeStore.from_env()
            if self.oracle:
                logger.info("Oracle trade logging 활성화됨 (ORACLE_* 환경변수 감지)")

        self._last_action_ms_by_symbol: Dict[str, int] = {}

        if self.live_trading:
            logger.warning(
                "LIVE_TRADING=true 입니다. 실제 주문이 전송됩니다. (기본은 드라이런)"
            )
        else:
            logger.info("드라이런 모드입니다. 신호/계산만 하고 주문은 전송하지 않습니다.")
        logger.info(f"MODE={self.mode}")

    def _fetch_last_closed_row(self, symbol: str) -> Optional[pd.Series]:
        try:
            ohlcv = self.chart_exchange.fetch_ohlcv(symbol, self.timeframe, limit=220)
            if not ohlcv or len(ohlcv) < 50:
                return None

            df = pd.DataFrame(
                ohlcv, columns=["ts", "open", "high", "low", "close", "volume"]
            )
            df["mid"] = df["close"].rolling(window=self.params.bb_period).mean()
            df["std"] = df["close"].rolling(window=self.params.bb_period).std()
            df["upper"] = df["mid"] + (df["std"] * self.params.bb_std)
            df["lower"] = df["mid"] - (df["std"] * self.params.bb_std)
            df["rsi"] = _calc_rsi(df["close"], self.params.rsi_period)

            # 마지막 캔들은 미완성일 수 있어 -2 사용
            if len(df) >= 2:
                return df.iloc[-2]
            return df.iloc[-1]
        except Exception as e:
            logger.error(f"[{symbol}] 차트 조회/지표 계산 실패(업비트 OHLCV): {e}")
            return None

    def _fetch_coinone_last(self, symbol: str) -> Optional[float]:
        try:
            t = self.exchange.fetch_ticker(symbol)
            return _safe_float(t.get("last"), None)  # type: ignore[arg-type]
        except Exception as e:
            logger.error(f"[{symbol}] 코인원 현재가 조회 실패: {e}")
            return None

    def _fetch_balances(self) -> Dict[str, float]:
        try:
            bal = self.exchange.fetch_balance()
            out: Dict[str, float] = {}
            for sym in self.symbols:
                base, quote = _split_symbol(sym)
                out[quote] = max(out.get(quote, 0.0), _get_free_balance(bal, quote))
                out[base] = max(out.get(base, 0.0), _get_free_balance(bal, base))
            return out
        except Exception as e:
            logger.error(f"잔고 조회 실패: {e}")
            return {}

    def _cooldown_ok(self, symbol: str) -> bool:
        last_ms = self._last_action_ms_by_symbol.get(symbol, 0)
        return (_now_ms() - last_ms) >= (self.params.cooldown_seconds * 1000)

    def _mark_action(self, symbol: str) -> None:
        self._last_action_ms_by_symbol[symbol] = _now_ms()

    def _get_position_state(self, symbol: str) -> Dict[str, Any]:
        st = load_state()
        pos = st.get(symbol)
        return pos if isinstance(pos, dict) else {}

    def _set_position_state(self, symbol: str, pos: Dict[str, Any]) -> None:
        st = load_state()
        st[symbol] = pos
        save_state(st)

    def _buy(self, symbol: str, buy_krw: float, price: float, reason: str) -> Tuple[float, Optional[str]]:
        if buy_krw < self.min_order_krw:
            logger.info(
                f"[{symbol}] 매수 스킵: 주문금액 {buy_krw:,.0f} < 최소 {self.min_order_krw:,.0f}"
            )
            return 0.0, None

        amount = buy_krw / price if price > 0 else 0.0
        if amount <= 0:
            return 0.0, None

        if not self.live_trading:
            logger.info(
                f"[{symbol}] (DRYRUN) BUY {amount:.6f} @ {price:,.0f} (KRW {buy_krw:,.0f}) [{reason}]"
            )
            if self.oracle and TradeEvent is not None:
                self.oracle.log_trade(
                    TradeEvent(
                        ts_utc=datetime.now(timezone.utc),
                        symbol=symbol,
                        side="BUY",
                        price=price,
                        amount=amount,
                        reason=reason,
                        mode="dryrun",
                        order_id=None,
                    )
                )
            self._mark_action(symbol)
            return amount, None

        try:
            order = self.exchange.create_market_buy_order(symbol, amount)
            order_id = str(order.get("id")) if order.get("id") is not None else None
            logger.info(f"[{symbol}] BUY 주문 성공: {order_id} [{reason}]")
            if self.oracle and TradeEvent is not None:
                self.oracle.log_trade(
                    TradeEvent(
                        ts_utc=datetime.now(timezone.utc),
                        symbol=symbol,
                        side="BUY",
                        price=price,
                        amount=amount,
                        reason=reason,
                        mode="live",
                        order_id=order_id,
                    )
                )
            self._mark_action(symbol)
            return amount, order_id
        except Exception as e:
            logger.error(f"[{symbol}] BUY 주문 실패: {e}")
            return 0.0, None

    def _place_buy(self, symbol: str, krw_free: float, price: float) -> None:
        buy_krw = krw_free * self.buy_amount_pct
        amount, order_id = self._buy(symbol, buy_krw, price, reason="SIGNAL")
        if amount <= 0:
            return
        self._set_position_state(
            symbol,
            {
                "entry_price": price,
                "entry_time_ms": _now_ms(),
                "amount": amount,
                "mode": "live" if self.live_trading else "dryrun",
                "order_id": order_id,
            },
        )

    def _sell(self, symbol: str, amount: float, price: float, reason: str) -> Optional[str]:
        base, quote = _split_symbol(symbol)
        sell_value = amount * price
        if sell_value < self.min_order_krw:
            logger.info(
                f"[{symbol}] 매도 스킵: 평가금 {sell_value:,.0f} {quote} < 최소 {self.min_order_krw:,.0f}"
            )
            return None

        if not self.live_trading:
            logger.info(f"[{symbol}] (DRYRUN) SELL {amount:.6f} @ {price:,.0f} ({reason})")
            if self.oracle and TradeEvent is not None:
                self.oracle.log_trade(
                    TradeEvent(
                        ts_utc=datetime.now(timezone.utc),
                        symbol=symbol,
                        side="SELL",
                        price=price,
                        amount=amount,
                        reason=reason,
                        mode="dryrun",
                        order_id=None,
                    )
                )
            self._mark_action(symbol)
            return None

        try:
            order = self.exchange.create_market_sell_order(symbol, amount)
            order_id = str(order.get("id")) if order.get("id") is not None else None
            logger.info(f"[{symbol}] SELL 주문 성공: {order_id} ({reason})")
            if self.oracle and TradeEvent is not None:
                self.oracle.log_trade(
                    TradeEvent(
                        ts_utc=datetime.now(timezone.utc),
                        symbol=symbol,
                        side="SELL",
                        price=price,
                        amount=amount,
                        reason=reason,
                        mode="live",
                        order_id=order_id,
                    )
                )
            self._mark_action(symbol)
            return order_id
        except Exception as e:
            logger.error(f"[{symbol}] SELL 주문 실패: {e}")
            return None

    def _place_sell(self, symbol: str, amount: float, price: float, reason: str) -> None:
        self._sell(symbol, amount, price, reason)
        clear_symbol_state(symbol)

    def step_symbol(self, symbol: str, balances: Dict[str, float]) -> None:
        row = self._fetch_last_closed_row(symbol)
        if row is None:
            logger.info(f"[{symbol}] 데이터 부족/조회 실패")
            return

        last_coinone = self._fetch_coinone_last(symbol)
        if last_coinone is None:
            return

        close = _safe_float(row["close"])
        lower = _safe_float(row["lower"])
        mid = _safe_float(row["mid"])
        upper = _safe_float(row["upper"])
        rsi = _safe_float(row["rsi"], 50.0)

        base, quote = _split_symbol(symbol)
        base_free = balances.get(base, 0.0)
        quote_free = balances.get(quote, 0.0)

        pos = self._get_position_state(symbol)
        has_pos = (base_free * last_coinone) >= self.min_order_krw or bool(pos)

        logger.info(
            f"[{symbol}] last={last_coinone:,.0f} (chartClose={close:,.0f}) "
            f"BB(L/M/U)={lower:,.0f}/{mid:,.0f}/{upper:,.0f} RSI={rsi:,.1f} "
            f"bal({quote})={quote_free:,.0f} bal({base})={base_free:.6f}"
        )

        if not self._cooldown_ok(symbol):
            return

        if self.mode == "grid":
            self._step_grid(symbol, balances, last_coinone, lower, mid, rsi, pos)
            return

        if has_pos:
            entry = _safe_float(pos.get("entry_price"), 0.0)
            amt = _safe_float(pos.get("amount"), base_free)
            if amt <= 0:
                amt = base_free

            hold_ms = _now_ms() - int(pos.get("entry_time_ms") or _now_ms())
            hold_min = hold_ms / 60000.0

            pnl_pct = 0.0
            if entry > 0:
                pnl_pct = (last_coinone - entry) / entry

            if entry > 0 and pnl_pct <= -self.params.stop_loss_pct:
                self._place_sell(symbol, amt, last_coinone, reason="STOP_LOSS")
                return

            if entry > 0 and pnl_pct >= self.params.take_profit_pct:
                self._place_sell(symbol, amt, last_coinone, reason="TAKE_PROFIT")
                return

            if last_coinone >= mid and rsi >= self.params.rsi_exit:
                self._place_sell(symbol, amt, last_coinone, reason="MEAN_REVERT_EXIT")
                return

            if hold_min >= self.params.max_hold_minutes:
                self._place_sell(symbol, amt, last_coinone, reason="TIME_STOP")
                return

            return

        # Entry (고빈도용: 좁은 밴드 + RSI)
        if last_coinone <= lower and rsi <= self.params.rsi_entry:
            self._place_buy(symbol, quote_free, last_coinone)

    def _step_grid(
        self,
        symbol: str,
        balances: Dict[str, float],
        last_price: float,
        lower: float,
        mid: float,
        rsi: float,
        pos: Dict[str, Any],
    ) -> None:
        base, quote = _split_symbol(symbol)
        quote_free = balances.get(quote, 0.0)

        lots: List[Dict[str, Any]] = []
        if isinstance(pos.get("lots"), list):
            lots = [x for x in pos["lots"] if isinstance(x, dict)]

        # exits
        remaining: List[Dict[str, Any]] = []
        for lot in lots:
            entry = _safe_float(lot.get("entry_price"), 0.0)
            amt = _safe_float(lot.get("amount"), 0.0)
            entry_time_ms = int(lot.get("entry_time_ms") or _now_ms())
            if entry <= 0 or amt <= 0:
                continue

            hold_min = (_now_ms() - entry_time_ms) / 60000.0
            pnl_pct = (last_price - entry) / entry

            reason: Optional[str] = None
            if pnl_pct >= self.grid_tp_pct:
                reason = "GRID_TP"
            elif self.grid_sl_pct > 0 and pnl_pct <= -self.grid_sl_pct:
                reason = "GRID_SL"
            elif self.grid_time_stop_minutes > 0 and hold_min >= self.grid_time_stop_minutes:
                reason = "GRID_TIME_STOP"

            if reason:
                self._sell(symbol, amt, last_price, reason=reason)
            else:
                remaining.append(lot)

        lots = remaining

        # entry
        if len(lots) >= self.grid_max_lots:
            self._set_position_state(symbol, {"mode": "grid", "lots": lots})
            return

        last_entry_price = _safe_float(pos.get("last_entry_price"), 0.0)
        if last_entry_price <= 0 and lots:
            last_entry_price = _safe_float(lots[-1].get("entry_price"), 0.0)

        mid_entry = mid > 0 and last_price <= mid * (1 - self.mid_entry_pct)
        first_signal = (last_price <= lower and rsi <= self.params.rsi_entry) or mid_entry
        add_signal = bool(lots) and last_entry_price > 0 and last_price <= last_entry_price * (1 - self.grid_spacing_pct)

        if (not lots and first_signal) or (lots and add_signal):
            buy_krw = quote_free * self.grid_lot_fraction
            amount, order_id = self._buy(symbol, buy_krw, last_price, reason="GRID_ENTRY")
            if amount > 0:
                lots.append(
                    {
                        "entry_price": last_price,
                        "entry_time_ms": _now_ms(),
                        "amount": amount,
                        "order_id": order_id,
                    }
                )
                self._set_position_state(
                    symbol, {"mode": "grid", "lots": lots, "last_entry_price": last_price}
                )
                return

        self._set_position_state(symbol, {"mode": "grid", "lots": lots, "last_entry_price": last_entry_price})

    def run(self) -> None:
        logger.info("=== 코인원 봇 시작 ===")
        logger.info(
            f"symbols={self.symbols} timeframe={self.timeframe} poll={self.poll_seconds}s "
            f"BB({self.params.bb_period},{self.params.bb_std}) RSI({self.params.rsi_period}) "
            f"TP={self.params.take_profit_pct*100:.2f}% SL={self.params.stop_loss_pct*100:.2f}%"
        )
        if self.mode == "grid":
            logger.info(
                "GRID: "
                f"maxLots={self.grid_max_lots} lotFraction={self.grid_lot_fraction} "
                f"spacing={self.grid_spacing_pct*100:.3f}% tp={self.grid_tp_pct*100:.3f}% "
                f"sl={self.grid_sl_pct*100:.3f}% timeStop={self.grid_time_stop_minutes}m"
            )
        logger.info("차트 소스: 빗썸 / 주문·잔고: 코인원")

        loop_idx = 0
        while True:
            loop_idx += 1
            loop_start = time.time()
            try:
                balances = self._fetch_balances()
                for sym in self.symbols:
                    self.step_symbol(sym, balances)
            except Exception as e:
                logger.error(f"메인 루프 예외: {e}")
            finally:
                elapsed = time.time() - loop_start
                logger.info(
                    f"[LOOP] #{loop_idx} 완료 (elapsed={elapsed:.2f}s, next_sleep={self.poll_seconds}s)"
                )

            time.sleep(self.poll_seconds)


def main() -> None:
    bot = Bot()
    bot.run()


if __name__ == "__main__":
    main()
