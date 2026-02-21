import ccxt
import time
import os
import json
import logging
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime

# -----------------------------------------------------------------------------
# 1. 설정 및 초기화
# -----------------------------------------------------------------------------

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger()

# .env 로드
load_dotenv()
ACCESS_KEY = os.getenv("COINONE_ACCESS_KEY")
SECRET_KEY = os.getenv("COINONE_SECRET_KEY")

# [주문용] 코인원 객체 생성
exchange = ccxt.coinone({
    'apiKey': ACCESS_KEY,
    'secret': SECRET_KEY,
    'enableRateLimit': True,
    'options': {'defaultType': 'spot'}
})

# [차트용] 빗썸 객체 생성 (코인원 차트 미지원 대체)
chart_exchange = ccxt.bithumb({
    'enableRateLimit': True
})

# 전략 설정
SYMBOL = 'BTC/KRW'      # 거래 대상
CHART_SYMBOL = 'BTC/KRW' # 차트 데이터 소스 (빗썸)
TIMEFRAME = '1h'        # 1시간봉
SMA_PERIOD = 30         # 추세 판단용 이동평균 (50 -> 30 완화)
BB_PERIOD = 20          # 볼린저밴드 기간
BB_STD = 1.5            # 볼린저밴드 표준편차 (2 -> 1.5 진입 조건 대폭 완화)
STOP_LOSS_PCT = 0.03    # 3% 손절
BUY_AMOUNT_PCT = 0.1    # 잔고의 10% 매수
MIN_ORDER_KRW = 5000    # 최소 주문 금액
STATE_FILE = 'trade_state.json' # 매수 평단가 저장용

# -----------------------------------------------------------------------------
# 2. 상태 관리 (손절매를 위한 평단가 저장)
# -----------------------------------------------------------------------------

def save_state(entry_price):
    with open(STATE_FILE, 'w') as f:
        json.dump({'entry_price': entry_price}, f)

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r') as f:
            try:
                data = json.load(f)
                return data.get('entry_price', 0)
            except json.JSONDecodeError:
                return 0
    return 0

def clear_state():
    if os.path.exists(STATE_FILE):
        try:
            os.remove(STATE_FILE)
        except OSError:
            pass

# -----------------------------------------------------------------------------
# 3. 데이터 분석 함수
# -----------------------------------------------------------------------------

def get_market_data(symbol, timeframe):
    """
    빗썸 OHLCV 데이터를 가져와서 SMA50, Bollinger Bands를 계산
    """
    try:
        # 코인원 대신 빗썸 데이터 사용
        ohlcv = chart_exchange.fetch_ohlcv(symbol, timeframe, limit=100)
        
        if not ohlcv:
            logger.warning("차트 데이터를 가져오지 못했습니다.")
            return None
            
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # 지표 계산
        df['sma50'] = df['close'].rolling(window=SMA_PERIOD).mean()
        
        # 볼린저 밴드 계산
        df['mid'] = df['close'].rolling(window=BB_PERIOD).mean()
        df['std'] = df['close'].rolling(window=BB_PERIOD).std()
        df['upper'] = df['mid'] + (df['std'] * BB_STD)
        df['lower'] = df['mid'] - (df['std'] * BB_STD)
        
        return df.iloc[-1] # 가장 최근 데이터 반환
    except Exception as e:
        logger.error(f"데이터 분석 중 오류: {e}")
        return None

def get_balance():
    try:
        balance = exchange.fetch_balance()
        # 안전하게 접근: 키가 없으면 0 반환
        krw_balance = balance.get('KRW', {}).get('free', 0)
        btc_balance = balance.get('BTC', {}).get('free', 0)
        return krw_balance, btc_balance
    except Exception as e:
        logger.error(f"잔고 조회 오류: {e}")
        return 0, 0

# -----------------------------------------------------------------------------
# 4. 매매 실행 함수
# -----------------------------------------------------------------------------

def buy_coin(krw_balance, price):
    try:
        buy_amount_krw = krw_balance * BUY_AMOUNT_PCT
        if buy_amount_krw < MIN_ORDER_KRW:
            logger.warning(f"매수 실패: 최소 주문 금액({MIN_ORDER_KRW}원) 미달")
            return

        amount = buy_amount_krw / price
        logger.info(f"매수 시도: {amount:.6f} BTC (가격: {price:,.0f} KRW)")
        
        # 실제 주문 전송 (코인원)
        order = exchange.create_market_buy_order(SYMBOL, amount)
        logger.info(f"매수 주문 성공: {order['id']}")
        
        # 매수 성공 시 상태 저장
        save_state(price)
        logger.info("매수 완료 및 평단가 저장")
        
    except Exception as e:
        logger.error(f"매수 주문 실패: {e}")

def sell_coin(btc_balance, reason="전량 매도"):
    try:
        current_price = exchange.fetch_ticker(SYMBOL)['last']
        amount_val = btc_balance * current_price
        
        if amount_val < MIN_ORDER_KRW:
            logger.warning(f"매도 실패: 최소 주문 금액({MIN_ORDER_KRW}원) 미달")
            return

        logger.info(f"{reason} 시도: {btc_balance:.6f} BTC")
        
        # 실제 주문 전송 (코인원)
        order = exchange.create_market_sell_order(SYMBOL, btc_balance)
        logger.info(f"매도 주문 성공: {order['id']}")
        
        # 매도 성공 시 상태 초기화
        clear_state()
        logger.info("매도 완료 및 상태 초기화")
        
    except Exception as e:
        logger.error(f"매도 주문 실패: {e}")

# -----------------------------------------------------------------------------
# 5. 메인 로직
# -----------------------------------------------------------------------------

def main():
    logger.info("=== 코인원 퀀트 봇 시작 (추세추종 + 볼린저밴드) ===")
    logger.info(f"설정: 1시간봉, SMA{SMA_PERIOD} 위에서 BB하단 매수, BB상단 매도, -3% 손절")
    logger.info("데이터 소스: 빗썸(Bithumb) BTC/KRW (코인원 차트 미지원 대체)")

    while True:
        try:
            # 1. 데이터 조회 (빗썸 차트 + 코인원 잔고)
            data = get_market_data(CHART_SYMBOL, TIMEFRAME)
            krw, btc = get_balance()
            entry_price = load_state() # 이전에 저장된 매수 평단가

            if data is None:
                time.sleep(10)
                continue
            
            close = data['close']
            sma50 = data['sma50']
            lower = data['lower']
            upper = data['upper']
            
            # 보유 중인지 여부 판단 (코인 가치가 5000원 이상이면 보유 중으로 간주)
            current_val = btc * close
            has_position = current_val > MIN_ORDER_KRW

            logger.info(f"가격: {close:,.0f} | SMA50: {sma50:,.0f} | BB하단: {lower:,.0f} | 보유BTC: {btc:.6f}")

            # 2. 로직 수행
            
            if has_position:
                # [손절매 체크] 진입가 대비 -3% 하락 시
                if entry_price > 0 and close < entry_price * (1 - STOP_LOSS_PCT):
                    logger.warning(f"⛔ 손절매 발동! (진입가: {entry_price:,.0f}, 현재가: {close:,.0f})")
                    sell_coin(btc, reason="손절매")
                
                # [익절 매도] 볼린저 밴드 상단 도달
                elif close >= upper:
                    logger.info("📈 익절 신호! (볼린저 상단 도달)")
                    sell_coin(btc, reason="익절 매도")
            
            else:
                # [매수 조건]
                # 1. 추세 필터: 현재가가 50 SMA 보다 위에 있어야 함 (상승 추세)
                # 2. 눌림목: 현재가가 볼린저 밴드 하단보다 낮거나 같음
                if close > sma50 and close <= lower:
                    logger.info("🚀 매수 신호! (상승 추세 속 눌림목)")
                    buy_coin(krw, close)
            
        except Exception as e:
            logger.error(f"메인 루프 에러: {e}")
        
        time.sleep(60) # 1분 대기

if __name__ == "__main__":
    main()
