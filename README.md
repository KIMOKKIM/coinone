# BTC Spot Auto-Trader (Rebuilt)

This repository is a fresh rebuild of a BTC spot automatic trading system targeted at Coinone (KRW markets).

Key points:
- Paper trading is the default mode.
- Emphasis on safety, state persistence, and backtestability.
- Structure includes exchange client, strategy, services, and utilities.

Quick start:
1. Copy your existing `.env` into the project root (do not modify its contents).
2. Create a Python virtual environment and install dependencies:
   ```
   python -m venv .venv
   .venv\\Scripts\\activate
   pip install -r requirements.txt
   playwright install chromium
   ```
3. Run backtest:
   ```
   python main.py --backtest --days 90
   ```
4. Run local dashboard:
   ```
   python main.py --dashboard
   ```

# Coinone BTC 현물 자동매매

Plan.md 지침에 따른 **비레버리지 현물 전용** 자동매매 프로그램입니다.

## 제한 사항

- **레버리지·선물·공매도 미지원** (현물만 사용)
- 실거래 전 **백테스트 및 페이퍼트레이딩** 필수
- 분석·주문 모두 **Coinone** 기준

## 프로젝트 구조

```
project/
  main.py              # 진입점
  config.py            # 설정 (env 연동)
  state.json           # 포지션 상태 저장
  .env.example
  requirements.txt
  logs/
  data/
  app/
    exchange/          # coinone_client
    strategy/          # indicators, signal_engine, risk_manager, portfolio
    services/          # trader, backtester, notifier, scheduler
    utils/             # logger, helpers
```

## 설치

```bash
cd coinone
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
cp .env.example .env
# .env에 COINONE_ACCESS_KEY, COINONE_SECRET_KEY 설정 (실거래 시)
```

## 설정 (.env)

- `PAPER_TRADING=true` : 페이퍼트레이딩 (기본, 실주문 없음)
- `PAPER_TRADING=false` : 실거래 (실제 주문 전송)
- `SYMBOL`, `MARKET`, `TIMEFRAME`, `STOP_LOSS_PCT`, `TAKE_PROFIT_LEVELS` 등은 `.env.example` 참고

## 실행

### 1회 실행 (테스트)

```bash
python main.py
```

### 백테스트

```bash
# 백테스트 전용 스크립트 실행 (동일 전략 로직 사용)
python -c "
import config as cfg
from app.exchange.coinone_client import CoinoneClient
from app.strategy.signal_engine import SignalEngine
from app.strategy.risk_manager import RiskManager
from app.services.backtester import Backtester
import pandas as pd

client = CoinoneClient(cfg.COINONE_ACCESS_KEY, cfg.COINONE_SECRET_KEY)
symbol = f'{cfg.SYMBOL}/{cfg.MARKET}'
ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=500)
df = pd.DataFrame(ohlcv, columns=['ts','open','high','low','close','volume'])
signal = SignalEngine()
risk = RiskManager()
bt = Backtester(signal, risk)
result = bt.run(df, symbol)
print(result)
"
```

## 실거래 전 체크리스트

- [ ] 백테스트로 동일 전략 수익/손실 확인
- [ ] `PAPER_TRADING=true` 로 페이퍼트레이딩 충분히 실행
- [ ] `.env`에 실제 API 키 설정 후 `PAPER_TRADING=false` 로 전환
- [ ] 주문 권한 체크 (잔고 조회 성공 여부)
- [ ] 한 사이클 최대 자금 비율(`MAX_CAPITAL_ALLOCATION`) 확인
- [ ] 손절/익절 비율 및 쿨다운 시간 확인

## 로그

- 콘솔 및 `logs/bot.log` 에 매수신호, 매수/매도 실행, 손절, API 오류 등 기록

## 상태 저장

- `state.json` 에 평균매수가, 보유수량, 매수/매도 단계, 최근 손절 시각, 트레일링용 최고가 저장
- 재시작 후 이전 포지션 복구
