import ccxt
import pandas as pd
import traceback

def test_fetch_ohlcv():
    try:
        exchange = ccxt.coinone({'enableRateLimit': True})
        symbol = 'BTC/KRW'
        timeframe = '1h'
        
        print(f"Testing fetch_ohlcv for {symbol} with {timeframe}...")
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        
        if ohlcv is None or len(ohlcv) == 0:
            print("Error: fetch_ohlcv returned empty or None.")
            return

        print(f"Successfully fetched {len(ohlcv)} candles.")
        print("Sample data:", ohlcv[0])

        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        print("\nDataFrame head:")
        print(df.head())
        
        # 지표 계산 테스트
        df['sma50'] = df['close'].rolling(window=50).mean()
        print("\nSMA50 calculated.")
        
        last_row = df.iloc[-1]
        print(f"Latest Close: {last_row['close']}, SMA50: {last_row['sma50']}")
        
    except Exception as e:
        print("Exception occurred:")
        traceback.print_exc()

if __name__ == "__main__":
    test_fetch_ohlcv()
