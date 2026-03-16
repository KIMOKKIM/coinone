from typing import Any, Dict, List
import pandas as pd
import config as cfg
from app.strategy.indicators import Indicators
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager

class Backtester:
    def __init__(self, signal_engine: SignalEngine, risk_manager: RiskManager):
        self.signal = signal_engine
        self.risk = risk_manager
        self.initial_capital = 100000.0

    def run(self, df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
        df = df.copy()
        df["ema20"] = Indicators.ema(df["close"], cfg.EMA_PERIOD)
        lower, mid, upper = Indicators.bollinger_bands(df["close"], cfg.BB_PERIOD, cfg.BB_STD)
        df["bb_lower"], df["bb_mid"], df["bb_upper"] = lower, mid, upper
        df["volume_ma"] = Indicators.volume_ma(df["volume"], cfg.VOLUME_MA_PERIOD)
        box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], cfg.BOX_LOOKBACK_BARS)
        signals = self.signal.get_buy_signals(df, box)
        quote = self.initial_capital
        position = None
        equity = [quote]
        trades: List[Dict[str, Any]] = []
        for i in range(len(df)):
            price = float(df["close"].iloc[i])
            sig = signals[i] if i < len(signals) else {}
            # entry
            if sig.get("final_buy_signal") and position is None:
                alloc = self.risk.max_position_quote(quote)
                size = alloc * self.risk.buy_split[0]
                if size >= cfg.MIN_ORDER_KRW:
                    qty = size / price
                    position = {"entry_price": price, "qty": qty}
                    quote -= size
                    trades.append({"type": "buy", "price": price, "qty": qty})
            # manage position
            if position:
                # stop loss
                if self.risk.should_stop_loss(position["entry_price"], price):
                    quote += position["qty"] * price
                    trades.append({"type": "sell", "reason": "stop", "price": price, "qty": position["qty"]})
                    position = None
                else:
                    # tp stages
                    for s_idx, tp in enumerate(self.risk.tp_levels):
                        if (price - position["entry_price"]) / position["entry_price"] >= tp:
                            sell_qty = position["qty"] * self.risk.tp_ratios[s_idx]
                            quote += sell_qty * price
                            position["qty"] -= sell_qty
                            trades.append({"type": "sell", "reason": f"tp{s_idx+1}", "price": price, "qty": sell_qty})
                    if position and position["qty"] <= 0:
                        position = None
            equity.append(quote + (position["qty"] * price if position else 0))
        final = equity[-1]
        total_return = (final - self.initial_capital) / self.initial_capital * 100.0
        return {"total_return_pct": round(total_return,2), "final_equity": round(final,2), "trade_count": len(trades)}

# -*- coding: utf-8 -*-
"""
백테스터: 실거래와 동일한 전략 로직으로 과거 데이터 백테스트.
총 수익률, MDD, 승률, 평균 수익/손실, 거래 횟수, 결과 CSV 저장.
"""
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

import config as cfg
from app.strategy.indicators import Indicators
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.strategy.portfolio import Portfolio
from app.utils.helpers import safe_float
from app.utils.logger import get_logger

logger = get_logger(__name__)


class Backtester:
    """4시간봉 DataFrame 기준 백테스트. 전략 로직은 SignalEngine·RiskManager 재사용."""

    def __init__(self, signal_engine: SignalEngine, risk_manager: RiskManager):
        self.signal = signal_engine
        self.risk = risk_manager
        self.initial_capital = 10_000.0

    def run(
        self,
        df: pd.DataFrame,
        symbol: str = "BTC/KRW",
    ) -> Dict[str, Any]:
        """
        백테스트 실행. df 컬럼: open, high, low, close, volume, (ts optional).
        반환: total_return_pct, mdd_pct, win_rate, avg_profit, avg_loss, trade_count, equity_curve, result_csv_path.
        """
        if len(df) < max(cfg.SMA_PERIOD, cfg.BB_PERIOD) + 10:
            return {"error": "데이터 부족", "total_return_pct": 0.0, "trade_count": 0}
        df = df.copy()
        df["sma50"] = Indicators.sma(df["close"], cfg.SMA_PERIOD)
        df["ema20"] = Indicators.ema(df["close"], cfg.EMA_PERIOD)
        lower, mid, upper = Indicators.bollinger_bands(df["close"], cfg.BB_PERIOD, cfg.BB_STD)
        df["bb_lower"], df["bb_mid"], df["bb_upper"] = lower, mid, upper
        df["volume_ma"] = Indicators.volume_ma(df["volume"], cfg.VOLUME_MA_PERIOD)
        lookback = getattr(cfg, "BOX_LOOKBACK_BARS", 180)
        box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], lookback)
        signals = self.signal.get_buy_signals(df, box)
        quote = self.initial_capital
        position = Portfolio()
        equity_curve = [quote]
        trades: List[Dict] = []
        for i in range(len(df)):
            row = df.iloc[i]
            price = float(row["close"])
            if i < len(signals):
                sig = signals[i]
                if sig.get("final_buy_signal") and not position.has_position() and self.risk.cooldown_ok(position.last_stop_time):
                    size_quote = quote * self.risk.max_capital_allocation * self.risk.buy_split_ratios[0]
                    if size_quote >= cfg.MIN_ORDER_KRW:
                        qty = size_quote / price
                        position.add_buy(price, qty, 1)
                        quote -= size_quote
                        trades.append({"type": "buy", "price": price, "qty": qty, "stage": 1})
            if position.has_position():
                position.update_recent_high(price)
                if self.risk.should_stop_loss(position.avg_entry_price, price):
                    quote += position.quantity * price
                    trades.append({"type": "sell", "reason": "stop_loss", "price": price, "qty": position.quantity})
                    position = Portfolio()
                else:
                    ratio = self.risk.take_profit_sell_ratio(position.avg_entry_price, price, position.sell_stage)
                    if ratio and position.quantity > 0:
                        sell_qty = position.quantity * ratio
                        quote += sell_qty * price
                        position.add_sell(sell_qty, position.sell_stage + 1)
                        trades.append({"type": "sell", "reason": "take_profit", "price": price, "qty": sell_qty})
            mv = position.market_value(price) if position.has_position() else 0.0
            equity_curve.append(quote + mv)
        final_equity = equity_curve[-1] if equity_curve else self.initial_capital
        total_return_pct = (final_equity - self.initial_capital) / self.initial_capital * 100.0
        peak = self.initial_capital
        mdd = 0.0
        for e in equity_curve:
            if e > peak:
                peak = e
            dd = (peak - e) / peak * 100.0 if peak else 0.0
            if dd > mdd:
                mdd = dd
        sell_trades = [t for t in trades if t["type"] == "sell"]
        wins = sum(1 for t in sell_trades if t.get("reason") == "take_profit")
        win_rate = (wins / len(sell_trades) * 100.0) if sell_trades else 0.0
        result = {
            "total_return_pct": round(total_return_pct, 2),
            "mdd_pct": round(mdd, 2),
            "win_rate": round(win_rate, 1),
            "trade_count": len(trades),
            "final_equity": round(final_equity, 2),
        }
        cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
        out_path = cfg.DATA_DIR / "backtest_result.csv"
        pd.DataFrame([result]).to_csv(out_path, index=False, encoding="utf-8-sig")
        logger.info("백테스트 완료: 수익률 %.2f%% MDD %.2f%% 승률 %.1f%% 거래 %d회", result["total_return_pct"], result["mdd_pct"], result["win_rate"], result["trade_count"])
        return result
