import ccxt

def test_bithumb_ohlcv():
    try:
        exchange = ccxt.bithumb()
        symbol = 'BTC/KRW'
        print(f"Testing Bithumb fetch_ohlcv for {symbol}...")
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=100)
        print(f"Success! Fetched {len(ohlcv)} candles.")
        print("Sample:", ohlcv[-1])
    except Exception as e:
        print(f"Error: {e}")

test_bithumb_ohlcv()
