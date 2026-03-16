from pathlib import Path
import json
import config as cfg

def save_state(obj: dict):
    Path(cfg.STATE_DIR).mkdir(parents=True, exist_ok=True)
    with open(cfg.STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)

def load_state():
    try:
        with open(cfg.STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

