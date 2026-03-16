# utility helpers
from typing import Any
import math

def safe_float(v: Any, default: float = 0.0) -> float:
    try:
        return float(v)
    except Exception:
        return default

def ensure_dir(path):
    from pathlib import Path
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)

def pct_change(a: float, b: float) -> float:
    try:
        return (b - a) / a if a else 0.0
    except Exception:
        return 0.0

# -*- coding: utf-8 -*-
"""
공통 유틸: 숫자 변환, 디렉토리 생성 등.
"""
from pathlib import Path
from typing import Any, Optional


def safe_float(value: Any, default: float = 0.0) -> float:
    """안전한 float 변환."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_dir(path: Path) -> Path:
    """디렉토리가 없으면 생성."""
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
