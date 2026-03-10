import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class TradeEvent:
    ts_utc: datetime
    symbol: str
    side: str  # BUY / SELL
    price: float
    amount: float
    reason: str
    mode: str  # dryrun / live
    order_id: Optional[str] = None


class OracleTradeStore:
    """
    ORACLE_* 환경변수가 있으면 체결/시그널 로그를 Oracle DB에 적재한다.
    설정이 없거나 연결 실패 시 자동으로 비활성화된다.
    """

    def __init__(self, dsn: str, user: str, password: str, table: str = "BOT_TRADES"):
        self.dsn = dsn
        self.user = user
        self.password = password
        self.table = table
        self._conn = None

        try:
            import oracledb  # noqa: F401
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"oracledb import 실패: {e}")

    @staticmethod
    def from_env() -> Optional["OracleTradeStore"]:
        dsn = (os.getenv("ORACLE_DSN") or "").strip()
        user = (os.getenv("ORACLE_USER") or "").strip()
        password = (os.getenv("ORACLE_PASSWORD") or "").strip()
        table = (os.getenv("ORACLE_TABLE") or "BOT_TRADES").strip()
        if not (dsn and user and password):
            return None
        try:
            return OracleTradeStore(dsn=dsn, user=user, password=password, table=table)
        except Exception:
            return None

    def _connect(self):
        if self._conn is not None:
            return self._conn
        import oracledb

        self._conn = oracledb.connect(user=self.user, password=self.password, dsn=self.dsn)
        return self._conn

    def log_trade(self, ev: TradeEvent) -> None:
        try:
            conn = self._connect()
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO {self.table}
                (TS_UTC, SYMBOL, SIDE, PRICE, AMOUNT, REASON, MODE, ORDER_ID)
                VALUES (:1, :2, :3, :4, :5, :6, :7, :8)
                """,
                [
                    ev.ts_utc.astimezone(timezone.utc),
                    ev.symbol,
                    ev.side,
                    float(ev.price),
                    float(ev.amount),
                    ev.reason,
                    ev.mode,
                    ev.order_id,
                ],
            )
            conn.commit()
        except Exception:
            # DB 장애로 봇이 멈추지 않게 조용히 무시 (로그는 상위에서 처리)
            return

