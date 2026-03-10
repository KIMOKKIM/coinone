import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, TypedDict

import ccxt
import numpy as np
import pandas as pd


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        return float(x)
    except Exception:
        return default


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(window=period).mean()
    # pandas NAType가 numpy 변환을 방해하므로 np.nan 사용
    rs = gain / loss.replace(0.0, np.nan)
    return 100 - (100 / (1 + rs))


def fetch_ohlcv_paginated(
    exchange: ccxt.Exchange, symbol: str, timeframe: str, days: int, limit: int = 1000
) -> pd.DataFrame:
    since_ms = exchange.parse8601((datetime.now(timezone.utc) - timedelta(days=days)).isoformat())
    all_rows: List[List[Any]] = []

    print(f"[{exchange.id}] {symbol} {timeframe} {days}일 데이터 수집...")
    while True:
        batch = exchange.fetch_ohlcv(symbol, timeframe, since=since_ms, limit=limit)
        if not batch:
            break
        all_rows.extend(batch)
        last_ts = batch[-1][0]
        since_ms = int(last_ts) + 1
        if last_ts >= exchange.milliseconds() - 60_000:
            break
        time.sleep(0.1)

    df = pd.DataFrame(all_rows, columns=["ts", "open", "high", "low", "close", "volume"])
    df = df.drop_duplicates(subset=["ts"]).sort_values("ts").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    print(f"수집 완료: {len(df)} candles")
    return df


@dataclass(frozen=True)
class Params:
    mode: str = "scalper"  # scalper | grid
    bb_period: int = 20
    bb_std: float = 1.0
    rsi_period: int = 14
    rsi_entry: float = 45.0
    rsi_exit: float = 52.0
    # winrate를 높이려면 TP를 작게, SL을 상대적으로 크게 두는 형태가 많음(단, 기대값은 악화될 수 있음)
    take_profit_pct: float = 0.0010
    stop_loss_pct: float = 0.0100
    max_hold_minutes: int = 90
    buy_amount_pct: float = 0.2
    min_order_value: float = 10.0
    fee_rate: float = 0.001
    slippage: float = 0.0005
    allow_mid_entry: bool = True
    mid_entry_pct: float = 0.0015  # mid 대비 0.15% 이탈 시 추가 진입
    cooldown_minutes: float = 0.0  # 0이면 즉시 재진입 허용

    # grid 모드 (다중 랏)
    grid_max_lots: int = 6
    grid_lot_fraction: float = 0.18  # 잔고 대비 1랏 투입 비율(각 진입 시점 기준)
    grid_spacing_pct: float = 0.0012  # 마지막 진입가 대비 0.12% 하락 시 추가 매수
    grid_tp_pct: float = 0.0012       # 랏별 0.12% 이익 시 익절
    grid_sl_pct: float = 0.0          # 0이면 SL 비활성화(승률은 높아지지만 리스크↑)
    grid_time_stop_minutes: float = 0.0  # 0이면 타임스탑 비활성화
    compounding: bool = False         # True면 포지션 크기 = (잔고+평가액)*비율 (복리)
    leverage: float = 1.0             # 1=현물, >1=레버리지(포지션 확대, TARGET_RETURN_100용)


def add_indicators(df: pd.DataFrame, p: Params) -> pd.DataFrame:
    df = df.copy()
    df["mid"] = df["close"].rolling(window=p.bb_period).mean()
    df["std"] = df["close"].rolling(window=p.bb_period).std()
    df["upper"] = df["mid"] + (df["std"] * p.bb_std)
    df["lower"] = df["mid"] - (df["std"] * p.bb_std)
    df["rsi"] = _calc_rsi(df["close"], p.rsi_period)
    return df


class SymbolData(TypedDict):
    ts: np.ndarray
    close: np.ndarray
    lower: np.ndarray
    mid: np.ndarray
    rsi: np.ndarray
    start_dt: datetime
    end_dt: datetime
    warmup: int


def preprocess_symbol(df: pd.DataFrame, p: Params) -> SymbolData:
    warmup = max(50, p.bb_period + p.rsi_period + 5)
    # numpy arrays (float64 / int64) for speed
    ts = df["ts"].to_numpy(dtype=np.int64, copy=False)
    close = df["close"].to_numpy(dtype=np.float64, copy=False)
    lower = df["lower"].to_numpy(dtype=np.float64, copy=False)
    mid = df["mid"].to_numpy(dtype=np.float64, copy=False)
    rsi = df["rsi"].to_numpy(dtype=np.float64, copy=False)
    start_dt = df.iloc[warmup]["datetime"].to_pydatetime()
    end_dt = df.iloc[-1]["datetime"].to_pydatetime()
    return {
        "ts": ts,
        "close": close,
        "lower": lower,
        "mid": mid,
        "rsi": rsi,
        "start_dt": start_dt,
        "end_dt": end_dt,
        "warmup": warmup,
    }


def run_backtest(data: SymbolData, p: Params) -> Dict[str, Any]:
    if p.mode == "grid":
        return run_backtest_grid(data, p)

    quote_balance = 10_000.0
    base_amount = 0.0
    entry_price = 0.0
    entry_close_raw = 0.0
    entry_base_gross = 0.0
    entry_i = -1
    entry_cost_quote = 0.0
    last_exit_i = -10_000

    closed: List[Dict[str, Any]] = []
    opens: int = 0

    ts = data["ts"]
    close_a = data["close"]
    lower_a = data["lower"]
    mid_a = data["mid"]
    rsi_a = data["rsi"]
    warmup = int(data["warmup"])

    n = len(ts)
    for i in range(warmup, n - 1):
        close = float(close_a[i])
        lower = float(lower_a[i])
        mid = float(mid_a[i])
        rsi = float(rsi_a[i]) if not np.isnan(rsi_a[i]) else 50.0

        if base_amount <= 0:
            if p.cooldown_minutes > 0 and (i - last_exit_i) < (p.cooldown_minutes * 60):
                continue

            mid_entry = False
            if p.allow_mid_entry and mid > 0:
                mid_entry = close <= mid * (1 - p.mid_entry_pct)

            if (close <= lower and rsi <= p.rsi_entry) or mid_entry:
                equity = quote_balance + base_amount * close
                base_quote = (equity * p.buy_amount_pct) if p.compounding else (quote_balance * p.buy_amount_pct)
                buy_quote = base_quote * p.leverage
                if buy_quote < p.min_order_value:
                    continue

                entry_close_raw = close
                entry_base_gross = buy_quote / close if close > 0 else 0.0
                buy_price = close * (1 + p.slippage)
                base_amount = (buy_quote * (1 - p.fee_rate)) / buy_price
                quote_balance -= buy_quote
                entry_price = buy_price
                entry_i = i
                entry_cost_quote = buy_quote
                opens += 1
            continue

        hold_min = (int(ts[i]) - int(ts[entry_i])) / 60000.0
        pnl_pct = (close - entry_price) / entry_price if entry_price > 0 else 0.0

        exit_reason: Optional[str] = None
        if pnl_pct <= -p.stop_loss_pct:
            exit_reason = "STOP_LOSS"
        elif pnl_pct >= p.take_profit_pct:
            exit_reason = "TAKE_PROFIT"
        elif close >= mid and rsi >= p.rsi_exit:
            exit_reason = "MEAN_REVERT_EXIT"
        elif hold_min >= p.max_hold_minutes:
            exit_reason = "TIME_STOP"

        if exit_reason:
            sell_price = close * (1 - p.slippage)
            sell_quote = base_amount * sell_price * (1 - p.fee_rate)
            quote_balance += sell_quote
            pnl_net = sell_quote - entry_cost_quote
            gross_exit_quote = entry_base_gross * close
            pnl_gross = gross_exit_quote - entry_cost_quote
            closed.append(
                {
                    "exit_reason": exit_reason,
                    "entry_price": entry_price,
                    "exit_price": sell_price,
                    "pnl_net": pnl_net,
                    "pnl_gross": pnl_gross,
                    "entry_i": entry_i,
                    "exit_i": i,
                }
            )
            base_amount = 0.0
            entry_price = 0.0
            entry_close_raw = 0.0
            entry_base_gross = 0.0
            entry_i = -1
            entry_cost_quote = 0.0
            last_exit_i = i

    final_equity = quote_balance + base_amount * float(close_a[-1])
    wins_net = sum(1 for t in closed if t["pnl_net"] > 0)
    wins_gross = sum(1 for t in closed if t["pnl_gross"] > 0)
    winrate_net = (wins_net / len(closed) * 100.0) if closed else 0.0
    winrate_gross = (wins_gross / len(closed) * 100.0) if closed else 0.0

    days = max(1.0, (data["end_dt"] - data["start_dt"]).total_seconds() / 86400.0)
    trades_per_day = (len(closed) / days) if days > 0 else 0.0

    return {
        "final_equity": final_equity,
        "return_pct": (final_equity - 10_000.0) / 10_000.0 * 100.0,
        "opens": opens,
        "closed": len(closed),
        "winrate_net": winrate_net,
        "winrate_gross": winrate_gross,
        "trades_per_day": trades_per_day,
        "last_5": closed[-5:],
        "period_days": days,
    }


def run_backtest_grid(data: SymbolData, p: Params) -> Dict[str, Any]:
    """
    grid 모드: 동일 심볼에 다중 랏을 쌓고(Spacing) 랏별 작은 TP로 청산.
    - SL/TimeStop을 끄면 '닫힌 거래 기준 승률'은 높아질 수 있으나,
      미청산(손실) 랏이 누적될 수 있으므로 보고서에 open_lots / unrealized를 함께 제공한다.
    """

    ts = data["ts"]
    close_a = data["close"]
    lower_a = data["lower"]
    mid_a = data["mid"]
    rsi_a = data["rsi"]
    warmup = int(data["warmup"])
    n = len(ts)

    quote_balance = 10_000.0

    lots: List[Dict[str, float]] = []
    closed: List[Dict[str, Any]] = []

    last_entry_close = 0.0
    last_exit_i = -10_000
    opens = 0

    for i in range(warmup, n - 1):
        close = float(close_a[i])
        lower = float(lower_a[i])
        mid = float(mid_a[i])
        rsi = float(rsi_a[i]) if not np.isnan(rsi_a[i]) else 50.0

        # 1) 랏별 청산 체크 (TP/SL/TimeStop)
        remaining: List[Dict[str, float]] = []
        for lot in lots:
            entry_close = float(lot["entry_close"])
            entry_ts = float(lot["entry_ts"])
            entry_cost = float(lot["entry_cost_quote"])
            base_net = float(lot["base_net"])
            base_gross = float(lot["base_gross"])

            hold_min = (int(ts[i]) - int(entry_ts)) / 60000.0
            pnl_pct = (close - entry_close) / entry_close if entry_close > 0 else 0.0

            exit_reason: Optional[str] = None
            if pnl_pct >= p.grid_tp_pct:
                exit_reason = "TAKE_PROFIT"
            elif p.grid_sl_pct > 0 and pnl_pct <= -p.grid_sl_pct:
                exit_reason = "STOP_LOSS"
            elif p.grid_time_stop_minutes > 0 and hold_min >= p.grid_time_stop_minutes:
                exit_reason = "TIME_STOP"

            if exit_reason:
                sell_price = close * (1 - p.slippage)
                sell_quote = base_net * sell_price * (1 - p.fee_rate)
                quote_balance += sell_quote

                pnl_net = sell_quote - entry_cost
                pnl_gross = (base_gross * close) - entry_cost

                closed.append(
                    {
                        "exit_reason": exit_reason,
                        "pnl_net": pnl_net,
                        "pnl_gross": pnl_gross,
                        "entry_i": int(lot["entry_i"]),
                        "exit_i": i,
                    }
                )
                last_exit_i = i
            else:
                remaining.append(lot)
        lots = remaining

        # 2) 신규 진입 조건 (눌림 + spacing)
        if p.cooldown_minutes > 0 and (i - last_exit_i) < (p.cooldown_minutes * 60):
            continue

        if len(lots) >= p.grid_max_lots:
            continue

        # 첫 랏: 하단/RSI 또는 mid 이탈
        mid_entry = p.allow_mid_entry and mid > 0 and close <= mid * (1 - p.mid_entry_pct)
        first_signal = (close <= lower and rsi <= p.rsi_entry) or mid_entry

        # 추가 랏: spacing 하락
        add_signal = False
        if lots and last_entry_close > 0:
            add_signal = close <= last_entry_close * (1 - p.grid_spacing_pct)

        if (not lots and first_signal) or (lots and add_signal):
            holdings_val = sum(float(l["base_net"]) * close for l in lots)
            equity = quote_balance + holdings_val
            base_quote = (equity * p.grid_lot_fraction) if p.compounding else (quote_balance * p.grid_lot_fraction)
            buy_quote = base_quote * p.leverage
            if buy_quote < p.min_order_value:
                continue

            base_gross = buy_quote / close if close > 0 else 0.0
            buy_price = close * (1 + p.slippage)
            base_net = (buy_quote * (1 - p.fee_rate)) / buy_price
            quote_balance -= buy_quote

            lots.append(
                {
                    "entry_close": close,
                    "entry_ts": float(ts[i]),
                    "entry_cost_quote": buy_quote,
                    "base_net": base_net,
                    "base_gross": base_gross,
                    "entry_i": float(i),
                }
            )
            last_entry_close = close
            opens += 1

    # 마크투마켓(청산 가정) 평가
    last_close = float(close_a[-1])
    liq_quote = 0.0
    for lot in lots:
        base_net = float(lot["base_net"])
        liq_quote += base_net * last_close * (1 - p.fee_rate) * (1 - p.slippage)
    final_equity = quote_balance + liq_quote

    wins_net = sum(1 for t in closed if t["pnl_net"] > 0)
    wins_gross = sum(1 for t in closed if t["pnl_gross"] > 0)
    winrate_net = (wins_net / len(closed) * 100.0) if closed else 0.0
    winrate_gross = (wins_gross / len(closed) * 100.0) if closed else 0.0

    days = max(1.0, (data["end_dt"] - data["start_dt"]).total_seconds() / 86400.0)
    trades_per_day = (len(closed) / days) if days > 0 else 0.0

    return {
        "final_equity": final_equity,
        "return_pct": (final_equity - 10_000.0) / 10_000.0 * 100.0,
        "opens": opens,
        "closed": len(closed),
        "open_lots": len(lots),
        "winrate_net": winrate_net,
        "winrate_gross": winrate_gross,
        "trades_per_day": trades_per_day,
        "period_days": days,
    }


def _parse_symbols(value: str) -> List[str]:
    syms = [s.strip() for s in (value or "").split(",") if s.strip()]
    return syms


def run_backtest_multi(df_by_symbol: Dict[str, pd.DataFrame], p: Params) -> Dict[str, Any]:
    per_symbol: Dict[str, Dict[str, Any]] = {}
    closed_total = 0
    opens_total = 0
    wins_net_total = 0
    wins_gross_total = 0
    open_lots_total = 0
    days_total_weighted = 0.0
    final_equity_sum = 0.0
    return_pct_sum = 0.0

    for sym, df in df_by_symbol.items():
        data = preprocess_symbol(df, p)
        res = run_backtest(data, p)
        per_symbol[sym] = res
        closed_total += int(res["closed"])
        opens_total += int(res["opens"])
        open_lots_total += int(res.get("open_lots", 0))
        wins_net_total += int(round(res["winrate_net"] * res["closed"] / 100.0)) if res["closed"] else 0
        wins_gross_total += int(round(res["winrate_gross"] * res["closed"] / 100.0)) if res["closed"] else 0
        days_total_weighted = max(days_total_weighted, float(res["period_days"]))
        final_equity_sum += float(res["final_equity"])
        return_pct_sum += float(res["return_pct"])

    winrate_net_total = (wins_net_total / closed_total * 100.0) if closed_total else 0.0
    winrate_gross_total = (wins_gross_total / closed_total * 100.0) if closed_total else 0.0
    trades_per_day_total = (closed_total / days_total_weighted) if days_total_weighted > 0 else 0.0

    return {
        "per_symbol": per_symbol,
        "final_equity_avg": (final_equity_sum / len(df_by_symbol)) if df_by_symbol else 0.0,
        "return_pct_avg": (return_pct_sum / len(df_by_symbol)) if df_by_symbol else 0.0,
        "opens_total": opens_total,
        "closed_total": closed_total,
        "open_lots_total": open_lots_total,
        "winrate_net_total": winrate_net_total,
        "winrate_gross_total": winrate_gross_total,
        "trades_per_day_total": trades_per_day_total,
        "period_days": days_total_weighted,
    }


def _iter_param_candidates() -> Iterable[Params]:
    # 목표: 수익률↑ + 거래수 100회/일↑ + 승률↑
    bb_periods = [12, 14, 18, 20]
    bb_stds = [0.5, 0.6, 0.8, 1.0]
    rsi_entries = [35.0, 40.0, 45.0, 50.0]
    rsi_exits = [48.0, 50.0, 52.0, 55.0]
    # 수수료(0.2%) 이상 TP 필요. 0.3%~0.8% 구간 확대
    tps = [0.0025, 0.003, 0.004, 0.005, 0.006, 0.008]
    sls = [0.005, 0.006, 0.008, 0.010, 0.012, 0.015]
    mid_entry_pcts = [0.0008, 0.001, 0.0012, 0.0015, 0.002]
    max_holds = [20, 30, 45, 60, 90]
    buy_amount_pcts = [0.15, 0.20, 0.25]

    for bb_period in bb_periods:
        for bb_std in bb_stds:
            for rsi_entry in rsi_entries:
                for rsi_exit in rsi_exits:
                    if rsi_exit <= rsi_entry:
                        continue
                    for tp in tps:
                        for sl in sls:
                            if sl <= tp:
                                continue
                            for mid_entry_pct in mid_entry_pcts:
                                for max_hold in max_holds:
                                    for buy_amt in buy_amount_pcts:
                                        yield Params(
                                            bb_period=bb_period,
                                            bb_std=bb_std,
                                            rsi_period=14,
                                            rsi_entry=rsi_entry,
                                            rsi_exit=rsi_exit,
                                            take_profit_pct=tp,
                                            stop_loss_pct=sl,
                                            max_hold_minutes=max_hold,
                                            buy_amount_pct=buy_amt,
                                            min_order_value=10.0,
                                            fee_rate=0.001,
                                            slippage=0.0005,
                                            allow_mid_entry=True,
                                            mid_entry_pct=mid_entry_pct,
                                            cooldown_minutes=0.0,
                                        )


def optimize_params(
    df_by_symbol: Dict[str, pd.DataFrame],
    target_trades_per_day: float,
    target_winrate: float,
    winrate_mode: str = "net",  # net or gross
    max_trials: int = 250,
    objective: str = "return",  # return | trades_winrate
) -> Tuple[Params, Dict[str, Any]]:
    best_p: Optional[Params] = None
    best_res: Optional[Dict[str, Any]] = None
    best_score = -1e18

    for idx, p in enumerate(_iter_param_candidates()):
        if idx >= max_trials:
            break
        res = run_backtest_multi(df_by_symbol, p)

        tpd = float(res["trades_per_day_total"])
        wr = float(res["winrate_gross_total"] if winrate_mode == "gross" else res["winrate_net_total"])
        ret = float(res["return_pct_avg"])

        if objective == "return":
            # 수익률 최우선. 거래수>=100 보너스. 큰 손실 페널티
            score = ret * 800.0
            if tpd >= target_trades_per_day:
                score += 3000.0
            score += min(150.0, tpd) * 1.0
            score += wr * 2.0
            if ret < -8.0:
                score -= 4000.0
            elif ret < 0:
                score -= 500.0
        else:
            score = min(200.0, tpd) * 2.0 + wr * 5.0
            if tpd >= target_trades_per_day:
                score += 5000.0
            if wr >= target_winrate:
                score += 5000.0
            if ret < -10.0:
                score -= 2000.0

        if score > best_score:
            best_score = score
            best_p = p
            best_res = res

    if best_p is None or best_res is None:
        raise RuntimeError("파라미터 탐색 실패")
    return best_p, best_res


if __name__ == "__main__":
    exchange_id = (os.getenv("EXCHANGE_ID") or "binance").strip()
    symbols = _parse_symbols(os.getenv("SYMBOLS") or "")
    if not symbols:
        symbols = [
            "BTC/USDT",
            "ETH/USDT",
            "SOL/USDT",
            "XRP/USDT",
            "BNB/USDT",
            "DOGE/USDT",
            "ADA/USDT",
            "TRX/USDT",
            "AVAX/USDT",
            "LINK/USDT",
        ]
    timeframe = (os.getenv("TIMEFRAME") or "1m").strip()
    days = int(os.getenv("DAYS") or "30")
    do_opt = _safe_float(os.getenv("OPTIMIZE"), 1.0) >= 1.0
    target_trades_per_day = _safe_float(os.getenv("TARGET_TRADES_PER_DAY"), 100.0)
    target_winrate = _safe_float(os.getenv("TARGET_WINRATE"), 90.0)
    max_trials = int(os.getenv("MAX_TRIALS") or "350")
    target_winrate_mode = (os.getenv("TARGET_WINRATE_MODE") or "net").strip().lower()
    opt_objective = (os.getenv("OPTIMIZE_OBJECTIVE") or "return").strip().lower()
    mode = (os.getenv("MODE") or "scalper").strip().lower()

    ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
    df_by_symbol: Dict[str, pd.DataFrame] = {}
    for sym in symbols:
        df = fetch_ohlcv_paginated(ex, sym, timeframe, days=days)
        if len(df) < 300:
            print(f"{sym}: 데이터 부족, 스킵")
            continue
        df_by_symbol[sym] = df

    if not df_by_symbol:
        raise SystemExit("유효한 심볼 데이터가 없습니다.")

    target_100 = _safe_float(os.getenv("TARGET_RETURN_100"), 0.0) >= 1.0
    if target_100:
        print("[TARGET_RETURN_100] 수익률 100% 목표 모드: 복리+공격적 파라미터+저비용 가정")
        do_opt = False

    _fee = 0.0 if target_100 else _safe_float(os.getenv("FEE_RATE"), 0.001)
    _slip = 0.0 if target_100 else _safe_float(os.getenv("SLIPPAGE"), 0.0005)
    _buy_pct = 0.9 if target_100 else _safe_float(os.getenv("BUY_AMOUNT_PCT"), 0.2)
    _grid_frac = 0.75 if target_100 else _safe_float(os.getenv("GRID_LOT_FRACTION"), 0.18)
    _grid_tp = 0.003 if target_100 else _safe_float(os.getenv("GRID_TP_PCT"), 0.0012)
    _tp = 0.006 if target_100 else _safe_float(os.getenv("TAKE_PROFIT_PCT"), 0.0010)
    _sl = 0.015 if target_100 else _safe_float(os.getenv("STOP_LOSS_PCT"), 0.0100)

    params = Params(
        mode=mode,
        bb_period=int(os.getenv("BB_PERIOD") or (12 if target_100 else 20)),
        bb_std=_safe_float(os.getenv("BB_STD"), 0.5 if target_100 else 1.0),
        rsi_period=int(os.getenv("RSI_PERIOD") or 14),
        rsi_entry=_safe_float(os.getenv("RSI_ENTRY"), 35.0 if target_100 else 45.0),
        rsi_exit=_safe_float(os.getenv("RSI_EXIT"), 48.0 if target_100 else 52.0),
        take_profit_pct=_tp,
        stop_loss_pct=_sl,
        max_hold_minutes=int(os.getenv("MAX_HOLD_MINUTES") or (45 if target_100 else 90)),
        buy_amount_pct=_buy_pct,
        min_order_value=_safe_float(os.getenv("MIN_ORDER_VALUE"), 10.0),
        fee_rate=_fee,
        slippage=_slip,
        allow_mid_entry=_safe_float(os.getenv("ALLOW_MID_ENTRY"), 1.0) >= 1.0,
        mid_entry_pct=_safe_float(os.getenv("MID_ENTRY_PCT"), 0.002 if target_100 else 0.0015),
        cooldown_minutes=_safe_float(os.getenv("COOLDOWN_MINUTES"), 0.0),
        compounding=target_100,
        grid_max_lots=int(os.getenv("GRID_MAX_LOTS") or (12 if target_100 else 6)),
        grid_lot_fraction=_grid_frac,
        grid_spacing_pct=_safe_float(os.getenv("GRID_SPACING_PCT"), 0.0008 if target_100 else 0.0012),
        grid_tp_pct=_grid_tp,
        grid_sl_pct=_safe_float(os.getenv("GRID_SL_PCT"), 0.0),
        grid_time_stop_minutes=_safe_float(os.getenv("GRID_TIME_STOP_MINUTES"), 0.0),
        leverage=_safe_float(os.getenv("LEVERAGE"), 6.0 if target_100 else 1.0),
    )

    for sym in list(df_by_symbol.keys()):
        df_by_symbol[sym] = add_indicators(df_by_symbol[sym], params)

    chosen_params = params
    if do_opt:
        print(
            f"\n[최적화] 목표: trades/day>={target_trades_per_day:.0f}, winrate>={target_winrate:.0f}% "
            f"objective={opt_objective} (trials={max_trials})"
        )
        chosen_params, _ = optimize_params(
            df_by_symbol,
            target_trades_per_day=target_trades_per_day,
            target_winrate=target_winrate,
            winrate_mode=("gross" if target_winrate_mode == "gross" else "net"),
            max_trials=max_trials,
            objective=opt_objective,
        )

    res = run_backtest_multi(df_by_symbol, chosen_params)

    print("\n=== 백테스트 결과 (BB+RSI scalper) ===")
    print(f"거래소: {exchange_id} | 타임프레임: {timeframe} | 기간: {res['period_days']:.1f}d")
    print(f"심볼수: {len(res['per_symbol'])} | 심볼: {', '.join(res['per_symbol'].keys())}")
    print(
        "파라미터: "
        f"BB({chosen_params.bb_period},{chosen_params.bb_std}) "
        f"RSI(entry={chosen_params.rsi_entry},exit={chosen_params.rsi_exit}) "
        f"TP={chosen_params.take_profit_pct*100:.3f}% "
        f"SL={chosen_params.stop_loss_pct*100:.3f}% "
        f"MAX_HOLD={chosen_params.max_hold_minutes}m "
        f"MID_ENTRY={chosen_params.allow_mid_entry}({chosen_params.mid_entry_pct*100:.3f}%) "
        f"compounding={chosen_params.compounding} leverage={chosen_params.leverage}x fee={chosen_params.fee_rate} slip={chosen_params.slippage}"
    )
    print(f"(심볼별) 평균 수익률: {res['return_pct_avg']:.2f}% | 평균 최종자산: {res['final_equity_avg']:.2f}")
    print(
        f"(합산) 진입: {res['opens_total']} | 청산: {res['closed_total']} | "
        f"승률(net): {res['winrate_net_total']:.1f}% | 승률(gross): {res['winrate_gross_total']:.1f}%"
    )
    if mode == "grid":
        print(f"(합산) 오픈 랏 수(종료 시점): {res['open_lots_total']}")
    print(f"(합산) 하루 평균 청산 횟수: {res['trades_per_day_total']:.1f}")
