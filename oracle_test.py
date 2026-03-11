#!/usr/bin/env python3
"""
Oracle 연결 및 BOT_TRADES 테이블 검증
사용법: ORACLE_DSN=... ORACLE_USER=... ORACLE_PASSWORD=... python oracle_test.py
"""
import os
import sys


def main():
    dsn = (os.getenv("ORACLE_DSN") or "").strip()
    user = (os.getenv("ORACLE_USER") or "").strip()
    password = (os.getenv("ORACLE_PASSWORD") or "").strip()

    if not (dsn and user and password):
        print("ORACLE_DSN, ORACLE_USER, ORACLE_PASSWORD 환경변수를 설정하세요.")
        sys.exit(1)

    try:
        import oracledb
    except ImportError:
        print("oracledb 미설치. pip install oracledb")
        sys.exit(1)

    print(f"연결 시도: {user}@{dsn}")
    try:
        conn = oracledb.connect(user=user, password=password, dsn=dsn)
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM DUAL")
        cur.fetchone()
        print("연결 성공")

        table = (os.getenv("ORACLE_TABLE") or "BOT_TRADES").strip()
        cur.execute(
            """
            SELECT COUNT(*) FROM user_tables WHERE table_name = :1
            """,
            [table.upper()],
        )
        exists = cur.fetchone()[0] > 0
        if exists:
            print(f"테이블 {table} 존재")
        else:
            print(f"테이블 {table} 없음. oracle_schema.sql 실행 필요")

        conn.close()
    except Exception as e:
        print(f"연결 실패: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
