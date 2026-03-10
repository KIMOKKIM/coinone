# Oracle 환경 배포 가이드

## 1. 사전 요구사항

- Python 3.9+
- Oracle Database (로컬 또는 원격)
- Oracle Instant Client (선택, oracledb thin 모드는 불필요)

## 2. Oracle 테이블 생성

`oracle_schema.sql`을 Oracle SQL*Plus 또는 SQL Developer에서 실행:

```sql
-- BOT_TRADES 테이블 생성
@oracle_schema.sql
```

또는:

```bash
sqlplus user/pass@host:port/servicename @oracle_schema.sql
```

## 3. 환경변수 설정

`.env` 파일 생성 (`.env.example` 참고):

```ini
COINONE_ACCESS_KEY=...
COINONE_SECRET_KEY=...
LIVE_TRADING=false

# Oracle 연동 (선택)
ORACLE_DSN=호스트:포트/서비스명
ORACLE_USER=계정
ORACLE_PASSWORD=비밀번호
ORACLE_TABLE=BOT_TRADES
```

**ORACLE_DSN 예시:**
- 로컬 XE: `localhost:1521/XE`
- TNS: `(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=host)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=XE)))`

## 4. 의존성 설치

```bash
pip install -r requirements.txt
```

## 5. 실행

```bash
# Linux/Mac
chmod +x run.sh
./run.sh

# 또는
python main.py
```

## 6. Oracle Cloud (Linux)에서 실행

```bash
git clone https://github.com/KIMOKKIM/coinone.git
cd coinone
pip install -r requirements.txt
# .env 생성 후
nohup python main.py >> bot.log 2>&1 &
```

ORACLE_* 환경변수가 설정되면 체결/신호가 BOT_TRADES 테이블에 자동 기록됩니다.
