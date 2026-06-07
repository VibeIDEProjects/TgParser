"""Web Telegram QR-code authentication via Playwright."""

import json
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import (
    TimeoutError as PwTimeout,
)

from tgparser.config import get_setting
from tgparser.utils import logger

# Default wait timeouts (seconds)
QR_WAIT_TIMEOUT_S = 120
LOGIN_WAIT_TIMEOUT_S = 300
QR_RETRY_COUNT = 3


class WebAuth:
    """Authenticate to Telegram Web via QR code, persist session for reuse."""

    def __init__(
        self,
        session_dir: str | Path | None = None,
        headless: bool = False,
        slow_mo: int = 100,
    ) -> None:
        self.session_dir = Path(session_dir or get_setting("session_dir", default="data/sessions/"))
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.session_dir / "web_session.json"
        self.headless = headless
        self.slow_mo = slow_mo or get_setting("browser", "slow_mo", default=100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self, force: bool = False) -> bool:
        """Open browser, show QR, wait for scan, save session.

        Returns True on success, False on failure.
        """
        if not force and self.is_session_valid():
            logger.info("Valid session found at %s — skipping auth.", self.session_file)
            return True

        logger.info(
            "Launching browser for QR authentication (headless=%s)...",
            self.headless,
        )
        pw: Playwright | None = None
        browser: Browser | None = None

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.set_default_timeout(LOGIN_WAIT_TIMEOUT_S * 1000)

            self._navigate_to_login(page)
            self._wait_for_qr_until_scanned(page)
            self._save_session(context)

            logger.info(
                "Authentication successful — session saved to %s",
                self.session_file,
            )
            return True

        except PwTimeout as exc:
            logger.error("Timeout during authentication: %s", exc)
            return False
        except Exception as exc:
            logger.error("Authentication failed: %s", exc)
            return False
        finally:
            if browser:
                browser.close()
            if pw:
                pw.stop()

    def is_session_valid(self) -> bool:
        """Check whether a persisted session file exists (quick check).

        A full validity check (making a request with the session) is done
        later during parsing; here we only verify the file is present.
        """
        return self.session_file.exists()

    async def check_session(self) -> bool:
        """Check if a valid saved session exists.

        Returns True if the session file exists and appears usable.
        Unlike :meth:`is_session_valid`, this also tries to load the file
        to catch corruption.
        """
        if not self.session_file.exists():
            return False
        try:
            data = load_cookies(self.session_file)
            if not data.get("cookies", []) and not data.get("origins", []):
                return False
        except Exception:
            return False
        return True

    async def authenticate(self) -> bool:
        """Public wrapper around :meth:`login` for GUI convenience.

        Runs the synchronous :meth:`login` in a background thread so it
        can be awaited from the GUI event loop.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        import asyncio
        return await asyncio.to_thread(self.login)

    async def save_session(self, page: Page) -> None:
        """Save the current browser session to disk (public wrapper)."""
        self._save_session(page.context)

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _navigate_to_login(self, page: Page) -> None:
        """Open web.telegram.org and handle the landing / login redirect."""
        page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
        logger.info("Opened web.telegram.org/k/ — waiting for QR code...")

    def _wait_for_qr_until_scanned(self, page: Page) -> None:
        """Loop: wait for QR canvas, if it expires click Retry and re-wait.

        Raises PwTimeout if the user never scans within the overall time budget.
        """
        for attempt in range(1, QR_RETRY_COUNT + 1):
            logger.info(
                "QR attempt %d/%d — waiting up to %ds...",
                attempt,
                QR_RETRY_COUNT,
                QR_WAIT_TIMEOUT_S,
            )
            try:
                self._wait_for_qr_appear(page)
                self._wait_for_login_complete(page)
                return
            except PwTimeout:
                logger.warning("QR timed out (attempt %d/%d).", attempt, QR_RETRY_COUNT)
                if attempt < QR_RETRY_COUNT and self._retry_qr(page):
                    logger.info("QR refreshed — retrying...")
                    continue
                raise

        raise PwTimeout(f"QR authentication failed after {QR_RETRY_COUNT} attempts.")

    def _wait_for_qr_appear(self, page: Page) -> None:
        """Wait until the QR <canvas> element is visible on the login page."""
        page.wait_for_selector("canvas.qr-canvas", timeout=QR_WAIT_TIMEOUT_S * 1000)
        logger.info("QR code canvas detected — scan it with your phone.")

    def _wait_for_login_complete(self, page: Page) -> None:
        """Wait for a URL change indicating successful login (redirect to /chat)."""
        page.wait_for_url("**/k/**", timeout=LOGIN_WAIT_TIMEOUT_S * 1000)
        # Additional confirmation: wait for the chat list container
        page.wait_for_selector(".chatlist", timeout=10_000)
        logger.info("Login confirmed — chat list visible.")

    def _retry_qr(self, page: Page) -> bool:
        """Look for a Retry/refresh button on the expired QR screen and click it.

        Returns True if a retry element was found and clicked.
        """
        retry_selectors = [
            "button.btn-primary:has-text('Retry')",
            "button:has-text('Try again')",
            ".qr-retry-button",
            "button[title='Retry']",
        ]
        for sel in retry_selectors:
            try:
                btn = page.wait_for_selector(sel, timeout=3_000)
                if btn:
                    btn.click()
                    return True
            except PwTimeout:
                continue
        return False

    # ------------------------------------------------------------------
    # Session persistence
    # ------------------------------------------------------------------

    def _save_session(self, context: BrowserContext) -> None:
        """Extract cookies and localStorage, write to JSON file."""
        cookies = context.cookies()
        local_storage: dict[str, Any] = {}
        page = context.pages[0] if context.pages else None
        if page:
            try:
                local_storage = page.evaluate(
                    """() => {
                        const items = {};
                        for (let i = 0; i < localStorage.length; i++) {
                            const key = localStorage.key(i);
                            if (key) items[key] = localStorage.getItem(key);
                        }
                        return items;
                    }"""
                )
            except Exception as exc:
                logger.warning("Could not extract localStorage: %s", exc)

        session_data: dict[str, Any] = {
            "cookies": cookies,
            "local_storage": local_storage,
            "saved_at": time.time(),
        }
        self.session_file.write_text(
            json.dumps(session_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.debug(
            "Session saved: %d cookies, %d localStorage keys.",
            len(cookies),
            len(local_storage),
        )

    def load_session(self) -> dict[str, Any] | None:
        """Load persisted session data from JSON file.

        Returns dict with 'cookies' and 'local_storage' keys, or None.
        """
        if not self.session_file.exists():
            return None
        try:
            return json.loads(self.session_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load session file: %s", exc)
            return None

    def restore_session(self, context: BrowserContext) -> bool:
        """Restore cookies and localStorage into a browser context.

        Returns True if at least one cookie was restored.
        """
        data = self.load_session()
        if not data:
            logger.info("No session data to restore.")
            return False

        cookies = data.get("cookies", [])
        if cookies:
            context.add_cookies(cookies)
            logger.debug("Restored %d cookies.", len(cookies))
        else:
            logger.warning("Session file contains no cookies.")
            return False

        # Restore localStorage (requires a page on the right origin)
        ls_data = data.get("local_storage", {})
        if ls_data:
            page = context.new_page()
            try:
                page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
                for key, value in ls_data.items():
                    page.evaluate(
                        """([k, v]) => localStorage.setItem(k, v)""",
                        [key, value],
                    )
                page.close()
                logger.debug("Restored %d localStorage keys.", len(ls_data))
            except Exception as exc:
                logger.warning("Failed to restore localStorage: %s", exc)
                page.close()

        return True
