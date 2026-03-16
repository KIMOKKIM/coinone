#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Capture the local dashboard page and fetch /api/status.
Saves a PNG screenshot to the workspace when possible.

Usage:
  python temp_capture.py

If Playwright is not installed, the script will still fetch /api/status and print it,
and will show installation instructions for taking a screenshot.
"""
import json
import requests
from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent

def fetch_status():
    url = "http://127.0.0.1:5000/api/status"
    try:
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def try_screenshot():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / f"dashboard_screenshot_{ts}.png"
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        return (None, f"playwright not available: {e}")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # use load and a longer timeout to avoid networkidle hang
            page.goto("http://127.0.0.1:5000", wait_until="load", timeout=60000)
            page.wait_for_timeout(2000)
            page.screenshot(path=str(out), full_page=True)
            browser.close()
        return (str(out), None)
    except Exception as e:
        return (None, str(e))

def main():
    print("1) Fetching /api/status ...")
    status = fetch_status()
    print(json.dumps(status, indent=2, ensure_ascii=False))

    print("\n2) Attempting to take screenshot with Playwright...")
    path, err = try_screenshot()
    if path:
        print("Screenshot saved to:", path)
    else:
        print("Screenshot failed:", err)
        print("To enable screenshot, run:")
        print("  pip install playwright")
        print("  playwright install chromium")
        print("Then re-run: python temp_capture.py")

if __name__ == '__main__':
    main()

