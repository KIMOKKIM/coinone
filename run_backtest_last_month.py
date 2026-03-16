from pathlib import Path
import sys
import math
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
import pandas as pd

from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.services.backtester import Backtester


def timeframe_hours(tf: str) -> float:
    tf = tf.strip().lower()
    if tf.endswith('h'):
        return float(tf[:-1]) if tf[:-1] else 1.0
    if tf.endswith('d'):
        return float(tf[:-1]) * 24.0
    if tf.endswith('m'):
        return float(tf[:-1]) / 60.0
    try:
        return float(tf)
    except Exception:
        return 4.0


def main():
    days = int(getattr(cfg, 'BACKTEST_START_DAYS', 30))
    tf = cfg.TIMEFRAME
    hours_per_bar = timeframe_hours(tf)
    bars_needed = math.ceil(days * 24.0 / hours_per_bar) + 10

    print('Running backtest for last %d days (timeframe=%s), need %d bars' % (days, tf, bars_needed))

    client = CoinoneClient(cfg.COINONE_ACCESS_KEY or '', cfg.COINONE_SECRET_KEY or '')
    symbol = '%s/%s' % (cfg.SYMBOL, cfg.MARKET)
    ohlcv = client.fetch_ohlcv(symbol, tf, limit=bars_needed)
    print('Fetched bars: %d' % len(ohlcv))
    if not ohlcv:
        print('Failed to fetch candles: check network or API')
        return

    df = pd.DataFrame(ohlcv, columns=['ts', 'open', 'high', 'low', 'close', 'volume'])

    engine = SignalEngine()
    box = None
    try:
        from app.strategy.indicators import Indicators
        lookback = min(getattr(cfg, 'BOX_LOOKBACK_BARS', 180), len(df) - 1)
        box = Indicators.recent_high_low_box(df['high'], df['low'], df['close'], lookback)
    except Exception:
        box = None

    sigs = engine.get_buy_signals(df, box)
    buy_count = sum(1 for s in sigs if s.get('final_buy_signal'))
    print('Buy signals count: %d' % buy_count)

    risk = RiskManager()
    bt = Backtester(engine, risk)
    bt.initial_capital = 100_000.0
    result = bt.run(df, symbol)

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_csv = cfg.DATA_DIR / ('backtest_result_last_month_%s.csv' % ts)
    cfg.DATA_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([result]).to_csv(out_csv, index=False, encoding='utf-8-sig')
    print('\\nBacktest result:')
    for k, v in result.items():
        print('%s: %s' % (k, v))
    print('Saved result to %s' % out_csv)


if __name__ == '__main__':
    main()

