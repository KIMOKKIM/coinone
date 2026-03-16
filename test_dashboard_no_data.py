from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

import run_web_dashboard as dashboard
import json


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def fetch_ohlcv(self, *args, **kwargs):
        return []  # simulate no candle data

    def fetch_ticker(self, *args, **kwargs):
        return {}  # no ticker data

    def fetch_balance(self, *args, **kwargs):
        return {}  # no balance data

    def get_free_balance(self, balance, currency):
        return 0.0


def main():
    # Monkeypatch the CoinoneClient used by the dashboard
    dashboard.CoinoneClient = FakeClient
    status = dashboard.get_status()
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

