"""Web Telegram QR-code authentication via Playwright."""

import json
import os
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
        default_session_dir = Path("~/.tgparser/sessions").expanduser()
        configured = get_setting("session_dir", default=str(default_session_dir))
        if session_dir is not None:
            resolved = Path(session_dir)
        else:
            resolved = Path(str(configured))
            if not resolved.is_absolute():
                resolved = default_session_dir
        self.session_dir = resolved.expanduser()
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = self.session_dir / "web_session.json"
        self.headless = headless
        self.slow_mo = slow_mo or get_setting("browser", "slow_mo", default=100)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self, force: bool = False, password: str | None = None) -> bool:
        """Open browser, show QR, wait for scan, save session.

        The new ``/a/`` frontend has a three-stage login flow:
        1. QR code is displayed → user scans it with the phone.
        2. ``#auth-password-form`` is shown if 2FA is enabled.
        3. Chat list appears once login is complete.

        ``password`` is used to fill the 2FA form automatically.  If it's
        None and the password form appears, the function returns False.

        Returns True on success, False on failure.
        """
        if not force and self.is_session_valid():
            logger.info("Valid session found at %s — skipping auth.", self.session_file)
            return True

        if password is None:
            password = os.environ.get("TG_TWOFA_PASSWORD")
            if password:
                logger.info("Using 2FA password from TG_TWOFA_PASSWORD env var.")

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
            self._wait_for_password_if_needed(page, password)
            self._wait_for_chat_list(page)
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
        """Check whether a persisted session file exists and has valid data.

        Telegram Web stores its auth in localStorage (``dc*`` keys), not in
        cookies.  We therefore accept the session if *either* cookies or
        localStorage contain meaningful data.
        """
        if not self.session_file.exists():
            logger.debug("is_session_valid: file not found (%s)", self.session_file)
            return False
        try:
            data = self.load_session()
            if not data:
                logger.debug("is_session_valid: load_session returned None/empty")
                return False
            cookies = data.get("cookies", [])
            local_storage = data.get("local_storage", {})
            # Telegram Web auth keys in localStorage look like "dc2_authKey", "dc2_serverSalt", …
            ls_has_auth = any(k.startswith("dc") for k in local_storage)
            if cookies or ls_has_auth:
                logger.debug(
                    "is_session_valid: valid (cookies=%d, ls_keys=%d, ls_has_auth=%s)",
                    len(cookies), len(local_storage), ls_has_auth,
                )
                return True
            logger.debug(
                "is_session_valid: no cookies and no dc* keys in localStorage "
                "(cookies=%d, ls_keys=%d)", len(cookies), len(local_storage),
            )
            return False
        except Exception as exc:
            logger.warning("is_session_valid: error reading session file: %s", exc)
            return False

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
        # If there is no QR canvas at all, we might already be logged in
        if not page.query_selector("canvas.qr-canvas"):
            logger.info("QR canvas not found — checking if already logged in...")
            self._wait_for_login_complete(page)
            return

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
        """Wait for a successful login (redirect to /chat or QR canvas gone)."""
        # First try to detect a redirect to the chats page
        try:
            page.wait_for_url("**/k/**", timeout=LOGIN_WAIT_TIMEOUT_S * 1000)
        except PwTimeout:
            logger.warning("URL did not change to /k/ — continuing with login check.")

        # Check if the QR canvas is still present — if not, we are probably logged in
        qr_canvas = page.query_selector("canvas.qr-canvas")
        if qr_canvas is None:
            logger.info("QR canvas not found — assuming already logged in.")
            return

        # Wait for the QR canvas to disappear (user scanned QR and logged in)
        logger.info("QR canvas found — waiting for it to disappear...")
        try:
            qr_canvas.wait_for_element_state("hidden", timeout=LOGIN_WAIT_TIMEOUT_S * 1000)
        except PwTimeout:
            logger.warning("QR canvas did not become hidden within timeout — "
                           "falling back to chat-list detection.")
            # Fallback: check for any chat list element
            chat_selectors = [
                ".chatlist",
                ".chat-list",
                ".chat_list",
                ".chats-container",
                ".dialogs",
                ".chat-item-container",
                ".im_dialog_wrap",
                ".chats-list",
                ".im_dialog",
                ".chat_item",
                ".messages-container",
                ".chat-tabs",
                ".sidebar",
                ".left_column",
                ".chat-content",
            ]
            for sel in chat_selectors:
                try:
                    page.wait_for_selector(sel, timeout=10_000)
                    logger.info(
                        "Login confirmed — chat list visible (selector='%s').", sel
                    )
                    return
                except PwTimeout:
                    continue
            # If still nothing, check whether the QR canvas is now gone (maybe it was removed)
            try:
                page.wait_for_selector("canvas.qr-canvas", state="detached", timeout=10_000)
                logger.info("Login confirmed — QR canvas detached.")
                return
            except PwTimeout:
                pass
            raise PwTimeout(
                "Could not detect chat list or login completion within timeout."
            )

        logger.info("Login confirmed — QR canvas hidden.")

    def _wait_for_password_if_needed(
        self, page: Page, password: str | None
    ) -> None:
        """If 2FA is enabled, wait for the password form and fill it in.

        Telegram Web ``/a/`` shows ``#auth-password-form`` after a successful
        QR scan when the account has 2-Step Verification enabled.  If the
        form doesn't appear within 5 seconds we assume 2FA is disabled.
        """
        try:
            page.wait_for_selector(
                "#auth-password-form", state="visible", timeout=5_000
            )
        except PwTimeout:
            logger.info("No 2FA password form detected — continuing.")
            return

        logger.info("2FA password form detected — entering password.")
        if not password:
            # No programmatic password: wait for the user to enter it manually
            # on the same browser window.  We just block until the form is
            # submitted and the chat list appears.
            logger.info(
                "No 2FA password supplied — waiting up to 120s for the user to "
                "type it in the browser."
            )
            try:
                page.wait_for_selector(
                    "#auth-password-form",
                    state="hidden",
                    timeout=120_000,
                )
            except PwTimeout:
                logger.error("Timed out waiting for 2FA password entry.")
                raise
            return

        try:
            page.fill("#sign-in-password", password)
            time.sleep(0.3)
            page.press("#sign-in-password", "Enter")
        except Exception as exc:
            logger.error("Failed to enter 2FA password: %s", exc)
            raise

    def _wait_for_chat_list(self, page: Page) -> None:
        """Wait for the chat list to appear after login is complete.

        Different Telegram frontends use different selectors:
        - ``/k/`` (legacy): ``#LeftColumn`` / ``.chat-list``
        - ``/a/`` (new): ``#LeftColumn`` / ``.chatlist`` / ``.chat-background``

        We accept any of them.
        """
        selectors = [
            "#LeftColumn",
            ".chatlist",
            ".chat-list",
            ".chat-background",
            ".ChatList",
            "[class*=ChatList]",
            "[class*=MiddleColumn]",
            "[class*=chat-list i]",
        ]
        logger.info("Waiting for chat list (3-stage flow)...")
        last_err: Exception | None = None
        for sel in selectors:
            try:
                page.wait_for_selector(sel, state="visible", timeout=10_000)
                logger.info("Chat list detected via selector: %s", sel)
                # Give a moment for the list to fully populate
                time.sleep(1.0)
                return
            except PwTimeout as exc:
                last_err = exc
                continue
        raise PwTimeout(
            f"Chat list never appeared after login (selectors: {selectors}). "
            f"Last error: {last_err}"
        )

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
        logger.debug("_save_session: got %d cookies from context.", len(cookies))
        if cookies:
            for c in cookies[:3]:
                logger.debug("  cookie: name=%s domain=%s", c.get("name"), c.get("domain"))
        local_storage: dict[str, Any] = {}
        page = context.pages[0] if context.pages else None
        if page:
            # Wait for Telegram to populate localStorage (dc* keys)
            try:
                page.wait_for_function(
                    "() => Object.keys(localStorage).some(k => k.startsWith('dc'))",
                    timeout=15_000,
                )
            except Exception:
                logger.warning(
                    "localStorage dc* keys not found after 15s, "
                    "will still save what's available."
                )
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

        Returns True if at least one cookie or localStorage key was restored.
        Telegram Web relies on localStorage (dc* keys) rather than cookies,
        so an empty cookie list is acceptable as long as localStorage has data.
        """
        data = self.load_session()
        if not data:
            logger.info("No session data to restore.")
            return False

        cookies = data.get("cookies", [])
        ls_data = data.get("local_storage", {})

        if not cookies and not ls_data:
            logger.warning("Session file is empty (no cookies, no localStorage).")
            return False

        # Restore cookies (if any)
        if cookies:
            context.add_cookies(cookies)
            logger.debug("Restored %d cookies.", len(cookies))
        else:
            logger.debug("No cookies in session file (Telegram Web may not need them).")

        # Restore localStorage (requires a page on the right origin)
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
