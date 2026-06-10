"""Try various navigation strategies."""
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from tgparser.auth.web_auth import WebAuth
from playwright.sync_api import sync_playwright

OUT = Path(r"C:\Users\borod\tgparser_explore")

wa = WebAuth()
strategies = [
    # 1. goto a/ then goto a/#hash
    ("goto_a_then_hash", lambda p: (
        p.goto("https://web.telegram.org/a/", wait_until="domcontentloaded"),
        time.sleep(8),
        p.goto("https://web.telegram.org/a/#-1003929682471", wait_until="domcontentloaded"),
        time.sleep(15),
    )),
    # 2. goto a/#hash directly
    ("goto_hash_directly", lambda p: (
        p.goto("https://web.telegram.org/a/#-1003929682471", wait_until="domcontentloaded"),
        time.sleep(20),
    )),
    # 3. set hash, wait, then reload
    ("set_hash_then_reload", lambda p: (
        p.goto("https://web.telegram.org/a/", wait_until="domcontentloaded"),
        time.sleep(8),
        p.evaluate("window.location.hash = '#-1003929682471'"),
        time.sleep(8),
        p.reload(wait_until="domcontentloaded"),
        time.sleep(15),
    )),
]

results = {}
for name, fn in strategies:
    print(f"\n=== {name} ===", flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=100)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        wa.restore_session(context)
        page = context.new_page()
        fn(page)
        info = page.evaluate(
            """() => ({
                url: window.location.href,
                dataMid: document.querySelectorAll('[data-message-id]').length,
                messageList: document.querySelectorAll('.message-list-item').length,
                bubble: document.querySelectorAll('.bubble').length,
            })"""
        )
        print(f"  {info}", flush=True)
        results[name] = info
        page.screenshot(path=str(OUT / f"strat_{name}.png"), full_page=False)
        browser.close()

import json
print("\n=== RESULTS ===", flush=True)
print(json.dumps(results, indent=2, ensure_ascii=False), flush=True)
