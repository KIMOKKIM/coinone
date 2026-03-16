import logging
from pathlib import Path
import config as cfg

def get_logger(name: str):
    LOG_DIR = Path(cfg.LOGS_DIR)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = logging.FileHandler(LOG_DIR / f"{name}.log", encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s"))
        logger.addHandler(fh)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s - %(message)s"))
        logger.addHandler(sh)
    return logger

# -*- coding: utf-8 -*-
"""
로거: 콘솔 및 파일 로그 출력. 한글 깨짐 방지를 위해 UTF-8 강제.
"""
import io
import logging
import sys
from pathlib import Path

# config 로드 전에는 상대 경로 사용
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _utf8_stdout():
    """Windows 콘솔 한글 출력용 UTF-8 스트림."""
    try:
        if hasattr(sys.stdout, "buffer"):
            enc = getattr(sys.stdout, "encoding", None) or ""
            if enc.lower() != "utf-8":
                return io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass
    return sys.stdout


def get_logger(name: str = "coinone_bot", log_dir: Path = None) -> logging.Logger:
    """로거 생성. logs/ 디렉토리에 UTF-8로 기록."""
    log_dir = log_dir or LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "bot.log"

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)
    fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # 콘솔 (UTF-8로 출력해 한글 깨짐 방지)
    ch = logging.StreamHandler(_utf8_stdout())
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # 파일
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger
