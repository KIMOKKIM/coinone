import time
from typing import Callable

def run_once(func: Callable):
    try:
        func()
    except Exception as e:
        print("run_once error:", e)

def run_loop(func: Callable, interval_sec: int = 20):
    while True:
        try:
            func()
            time.sleep(interval_sec)
        except KeyboardInterrupt:
            break
        except Exception as e:
            print("scheduler loop error:", e)

# -*- coding: utf-8 -*-
"""
스케줄러: 4시간봉 마감 시점에 맞춰 전략 실행. 테스트 모드에서는 즉시 1회 실행 가능.
"""
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# 4시간봉 마감: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
CANDLE_INTERVAL_SEC = 4 * 3600


def next_4h_candle_utc() -> int:
    """다음 4시간봉 마감 시각(UTC) Unix timestamp."""
    now = datetime.now(timezone.utc)
    hour = now.hour
    base = hour // 4 * 4
    next_4h = now.replace(hour=base, minute=0, second=0, microsecond=0)
    if next_4h <= now:
        from datetime import timedelta
        next_4h += timedelta(hours=4)
    return int(next_4h.timestamp())


def run_once(fn: Callable[[], None]) -> None:
    """테스트 모드: 즉시 1회 실행."""
    logger.info("즉시 1회 실행 (테스트 모드)")
    fn()


def run_on_4h_candle(fn: Callable[[], None], stop_event: Optional[Callable[[], bool]] = None) -> None:
    """4시간봉 마감 시점에 fn 실행. stop_event()가 True면 종료."""
    while True:
        ts = next_4h_candle_utc()
        wait = ts - time.time()
        if wait > 0:
            logger.info("다음 4시간봉 마감까지 %.0f초 대기", wait)
            while wait > 0 and (stop_event is None or not stop_event()):
                time.sleep(min(60, wait))
                wait = ts - time.time()
        if stop_event and stop_event():
            break
        try:
            fn()
        except Exception as e:
            logger.exception("스케줄 실행 중 오류: %s", e)
