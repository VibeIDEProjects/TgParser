"""Compare /a/ vs /k/ frontends."""
import sys
import time
from pathlib import Path

from tgparser.auth.web_auth import WebAuth
from playwright.sync_api import sync_playwright

OUT = Path(r"C:\Users\borod\tgparser_explore")
OUT.mkdir(parents=True, exist_ok=True)

def log(*args, **kwargs):
    print(*args, **kwargs, flush=True)

wa = WebAuth()
log("session file:", wa.session_file)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False, slow_mo=100)
    context = browser.new_context(viewport={"width": 1400, "height": 900})
    wa.restore_session(context)
    page = context.new_page()

    for frontend in ["/k/", "/a/"]:
        log(f"\n=== {frontend} ===")
        page.goto(
            f"https://web.telegram.org{frontend}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        time.sleep(10)
        log("URL:", page.url)
        log("Title:", page.title())
        html = page.content()
        log("HTML length:", len(html))
        (OUT / f"{frontend.strip('/')}_page.html").write_text(html, encoding="utf-8")
        try:
            h1 = page.evaluate("() => document.querySelector('h1')?.innerText || ''")
            log("h1:", h1)
        except Exception as e:
            log("h1 err:", e)
        for sel in [".chat-list", ".chatlist", "#LeftColumn", "[class*=ChatList]", "[class*=chat-list i]", "[class*=LeftColumn]"]:
            try:
                cnt = page.evaluate("(s) => document.querySelectorAll(s).length", sel)
                if cnt:
                    log(f"  {sel}: {cnt}")
            except Exception:
                pass
        page.screenshot(path=str(OUT / f"{frontend.strip('/')}_home.png"), full_page=False)
        log("Hash navigate...")
        page.evaluate("window.location.hash = '#-1003929682471'")
        time.sleep(10)
        log("URL:", page.url)
        log("Title:", page.title())
        html2 = page.content()
        log("HTML length:", len(html2))
        (OUT / f"{frontend.strip('/')}_channel.html").write_text(html2, encoding="utf-8")
        page.screenshot(path=str(OUT / f"{frontend.strip('/')}_channel.png"), full_page=False)
        for sel in [".chat-list", ".chatlist", "#LeftColumn", "[class*=ChatList]", "[class*=MiddleColumn]", ".bubble", ".Message", "[class*=Message]", "[class*=message i]", "[data-message-id]"]:
            try:
                cnt = page.evaluate("(s) => document.querySelectorAll(s).length", sel)
                if cnt:
                    log(f"  {sel}: {cnt}")
            except Exception:
                pass
    time.sleep(2)
    browser.close()
log("\nDONE")
