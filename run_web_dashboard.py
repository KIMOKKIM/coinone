from datetime import datetime
import traceback
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config as cfg

try:
    from flask import Flask, jsonify, render_template_string
except Exception:
    print("Flask is required. Install with: pip install flask")
    raise

from app.exchange.coinone_client import CoinoneClient
from app.strategy.indicators import Indicators
from app.strategy.signal_engine import SignalEngine
import pandas as pd
import logging

APP = Flask(__name__)
# reduce verbose request logs from the werkzeug dev server
logging.getLogger("werkzeug").setLevel(logging.ERROR)
# fully disable werkzeug access logs (optional)
logging.getLogger("werkzeug").disabled = True
# reduce flask app logger
APP.logger.setLevel(logging.ERROR)

HTML = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <meta http-equiv="refresh" content="0">
    <title>Coinone Dashboard</title>
    <style>
      body { font-family: Arial, Helvetica, sans-serif; margin: 20px; }
      .card { border: 1px solid #ddd; padding: 12px; border-radius: 6px; max-width: 720px; }
      .row { display: flex; gap: 20px; margin-bottom: 8px; }
      .label { color: #666; width: 120px; }
      .value { font-weight: 600; }
      .ok { color: green; }
      .bad { color: red; }
    </style>
  </head>
  <body>
    <h2>Coinone Local Dashboard</h2>
    <div class="card">
      <div id="lastUpdated">--</div>
      <div class="row"><div class="label">현재가</div><div class="value" id="price">--</div></div>
      <div class="row"><div class="label">잔고 (KRW)</div><div class="value" id="krw">--</div></div>
      <div class="row"><div class="label">잔고 (BTC)</div><div class="value" id="btc">--</div></div>
      <div class="row"><div class="label">신호</div><div class="value" id="signal">--</div></div>
      <div class="row"><div class="label">모드</div><div class="value" id="mode">--</div></div>
      <div style="margin-top:12px;color:#444;font-size:0.9em">
        <div id="msg"></div>
      </div>
    </div>
    <script>
      async function fetchStatus() {
        try {
          const r = await fetch('/api/status');
          const j = await r.json();
          document.getElementById('lastUpdated').textContent = '갱신: ' + j.ts;
          document.getElementById('price').textContent = j.price ? j.price.toLocaleString() + ' ' + j.market : '--';
          document.getElementById('krw').textContent = j.krw !== null ? j.krw.toLocaleString() : '--';
          document.getElementById('btc').textContent = j.btc !== null ? j.btc : '--';
          document.getElementById('signal').innerHTML = 'trend_ok=' + j.trend_ok + ' final_buy=' + j.final_buy;
          document.getElementById('mode').textContent = j.mode;
          document.getElementById('msg').textContent = j.msg || '';
        } catch (e) {
          document.getElementById('msg').textContent = 'Error: ' + e;
        }
      }
      fetchStatus();
      // poll every 60 seconds
      setInterval(fetchStatus, 60000);
    </script>
  </body>
</html>
"""


def get_status():
    client = CoinoneClient(cfg.COINONE_ACCESS_KEY or "", cfg.COINONE_SECRET_KEY or "")
    symbol = f"{cfg.SYMBOL}/{cfg.MARKET}"
    try:
        ohlcv = client.fetch_ohlcv(symbol, cfg.TIMEFRAME, limit=200)
        ticker = client.fetch_ticker(symbol)
        balance = client.fetch_balance()
    except Exception as e:
        tb = traceback.format_exc()
        return {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "price": None,
            "market": cfg.MARKET,
            "krw": None,
            "btc": None,
            "trend_ok": None,
            "final_buy": None,
            "mode": "paper" if cfg.PAPER_TRADING else "live",
            "msg": f"API error: {e}",
            "trace": tb,
        }
    price = float(ticker.get("last", 0) or 0)
    krw = client.get_free_balance(balance, cfg.MARKET)
    btc = client.get_free_balance(balance, cfg.SYMBOL)
    df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
    lookback = min(getattr(cfg, "BOX_LOOKBACK_BARS", 180), len(df) - 1)
    box = Indicators.recent_high_low_box(df["high"], df["low"], df["close"], lookback)
    engine = SignalEngine()
    signals = engine.get_buy_signals(df, box)
    last = signals[-1] if signals else {}
    return {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "price": price,
        "market": cfg.MARKET,
        "krw": krw,
        "btc": round(btc, 8) if btc is not None else None,
        "trend_ok": last.get("trend_ok"),
        "final_buy": last.get("final_buy_signal"),
        "mode": "paper" if cfg.PAPER_TRADING else "live",
        "msg": "",
    }


@APP.route("/api/status")
def api_status():
    return jsonify(get_status())


@APP.route("/")
def index():
    return render_template_string(HTML)


if __name__ == "__main__":
    print("Starting local web dashboard at http://127.0.0.1:5000")
    APP.run(host="127.0.0.1", port=5000, debug=False)

