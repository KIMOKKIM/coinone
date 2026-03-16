# -*- coding: utf-8 -*-
"""잔고 응답 구조 디버깅."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg
from app.exchange.coinone_client import CoinoneClient

def dump_struct(obj, prefix="", max_depth=3):
    if max_depth <= 0:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("info", "ERRORMSG"):
                if isinstance(v, dict):
                    dump_struct(v, prefix + k + ".", max_depth - 1)
                else:
                    print(prefix + k, ":", repr(v)[:80])
            elif k in ("free", "used", "total") and isinstance(v, dict):
                for kk, vv in list(v.items())[:8]:
                    print(prefix + k + "." + str(kk), ":", vv)
            elif isinstance(v, (list, dict)):
                print(prefix + k, ":", type(v).__name__, "len=", len(v))
                if isinstance(v, dict) and len(v) <= 10:
                    dump_struct(v, prefix + k + ".", max_depth - 1)
            else:
                print(prefix + k, ":", repr(v)[:60])
    elif isinstance(obj, list):
        for i, item in enumerate(obj[:5]):
            print(prefix + "[%d]" % i, ":", item)
        if len(obj) > 5:
            print(prefix, "... (%d more)" % (len(obj) - 5))

c = CoinoneClient(cfg.COINONE_ACCESS_KEY, cfg.COINONE_SECRET_KEY)
print("=== fetch_balance() 응답 구조 ===")
try:
    b = c.fetch_balance()
    info = b.get("info") or {}
    if info.get("result") == "error" or info.get("errorCode"):
        print("[!] API 오류:", info.get("errorCode"), info.get("errorMsg", info.get("ERRORMSG", "")))
        print("    => Coinone 화이트리스트에 현재 IP를 추가해야 잔고가 표시됩니다.")
    dump_struct(b)
    print("\n=== get_free_balance 결과 ===")
    krw = c.get_free_balance(b, "KRW")
    btc = c.get_free_balance(b, "BTC")
    print("KRW:", krw, "| BTC:", btc)
except Exception as e:
    print("오류:", e)
    import traceback
    traceback.print_exc()
