import ccxt
import pandas as pd
import time
from datetime import datetime, timedelta

def fetch_ohlcv_data(symbol='BTC/USDT', timeframe='1h', days=180):
    exchange = ccxt.binance()
    since = exchange.parse8601((datetime.now() - timedelta(days=days)).isoformat())
    all_ohlcv = []
    
    print(f"[{symbol}] 1h 데이터 {days}일치 수집 시작...")
    
    while True:
        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=1000)
            if not ohlcv: break
            all_ohlcv.extend(ohlcv)
            last_timestamp = ohlcv[-1][0]
            since = last_timestamp + 1
            if last_timestamp >= exchange.milliseconds(): break
            time.sleep(0.1)
        except Exception as e:
            print(f"데이터 수집 에러: {e}")
            break
            
    df = pd.DataFrame(all_ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
    print(f"데이터 수집 완료: 총 {len(df)}개")
    return df

def calculate_indicators(df):
    # 50 SMA (추세 판단)
    df['sma50'] = df['close'].rolling(window=50).mean()
    
    # 볼린저 밴드 (20, 2)
    df['mid'] = df['close'].rolling(window=20).mean()
    df['std'] = df['close'].rolling(window=20).std()
    df['upper'] = df['mid'] + (df['std'] * 2)
    df['lower'] = df['mid'] - (df['std'] * 2)
    
    return df

def run_backtest(df):
    initial_balance = 10000.0
    balance = initial_balance
    btc_balance = 0.0
    entry_price = 0.0
    fee_rate = 0.001
    
    trades = []
    
    # 시뮬레이션
    for i in range(50, len(df)):
        row = df.iloc[i]
        close = row['close']
        sma50 = row['sma50']
        lower = row['lower']
        upper = row['upper']
        
        # 보유 중일 때 (매도 조건 체크)
        if btc_balance > 0:
            current_val = btc_balance * close
            
            # 1. 절대 손절 (-3%)
            if close <= entry_price * 0.97:
                sell_val = btc_balance * close * (1 - fee_rate)
                balance += sell_val
                trades.append({'type': 'STOP_LOSS', 'price': close, 'pnl': (sell_val - (entry_price * btc_balance))})
                btc_balance = 0
                entry_price = 0
            
            # 2. 익절 (볼린저 상단 터치)
            elif close >= upper:
                sell_val = btc_balance * close * (1 - fee_rate)
                balance += sell_val
                trades.append({'type': 'TAKE_PROFIT', 'price': close, 'pnl': (sell_val - (entry_price * btc_balance))})
                btc_balance = 0
                entry_price = 0
                
        # 미보유 중일 때 (매수 조건 체크)
        else:
            # 추세 필터 (SMA 위) AND 눌림목 (볼린저 하단 아래)
            if close > sma50 and close <= lower:
                buy_amount = balance * 0.1 # 10% 투입
                fee = buy_amount * fee_rate
                actual_buy = buy_amount - fee
                btc_buy = actual_buy / close
                
                balance -= buy_amount
                btc_balance += btc_buy
                entry_price = close
                trades.append({'type': 'BUY', 'price': close})

    final_val = balance + (btc_balance * df.iloc[-1]['close'])
    profit = ((final_val - initial_balance) / initial_balance) * 100
    
    print("\n=== 백테스팅 결과 (추세+볼린저+손절) ===")
    print(f"테스트 기간: 6개월 (1h 캔들)")
    print(f"최종 수익률: {profit:.2f}%")
    print(f"총 거래 횟수: {len(trades)}회")
    print(f"승률: {len([t for t in trades if t.get('pnl', 0) > 0]) / len([t for t in trades if 'pnl' in t]) * 100:.1f}%" if trades else "거래 없음")
    
    # 최근 5개 거래
    print("\n[최근 거래 5건]")
    for t in trades[-5:]:
        print(f"{t['type']} | 가격: {t['price']:.2f}")

if __name__ == "__main__":
    df = fetch_ohlcv_data()
    if len(df) > 50:
        df = calculate_indicators(df)
        run_backtest(df)
