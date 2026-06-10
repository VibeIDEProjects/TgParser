"""Parser for closed/private Telegram channels via Web Telegram (Playwright + BS4).

Uses an existing Playwright session (restored by :class:`WebAuth`) to
navigate to the channel, scroll through the message history, bypass
copy-protection, and extract message data from the DOM.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from tgparser.auth.web_auth import WebAuth
from tgparser.config import get_setting
from tgparser.models.message import Message

logger = logging.getLogger("tgparser")

# ---------------------------------------------------------------------------
# JS / CSS payloads injected into the page to defeat copy-protection
# ---------------------------------------------------------------------------

COPY_PROTECTION_CSS = """
*, *::before, *::after {
    user-select: text !important;
    -webkit-user-select: text !important;
    -moz-user-select: text !important;
    -ms-user-select: text !important;
}
"""

COPY_PROTECTION_JS = """
;(function () {
    document.querySelectorAll('*').forEach(function (el) {
        el.oncopy = null;
        el.oncut = null;
        el.onpaste = null;
        el.oncontextmenu = null;
        el.ondragstart = null;
        el.onselectstart = null;
        el.onmousedown = null;
    });
    document.body.style.userSelect = 'text';
    document.body.style.webkitUserSelect = 'text';
    Array.from(document.querySelectorAll(
        '.copy-protection-overlay, ' +
        '.tgme-page-extra, ' +
        '[class*="protect"], ' +
        '[class*="nonselectable"], ' +
        '[style*="user-select: none"], ' +
        '[style*="user-select:none"]'
    )).forEach(function (el) { el.remove(); });
})();
"""

# ---------------------------------------------------------------------------
# Message element selectors — multiple fallbacks for robustness.
# Web K may change class names; this list is generous.
# ---------------------------------------------------------------------------

_MESSAGE_CONTAINER_SELECTORS = [
    ".bubbles",
    ".messages-container",
    "#column-center .messages-container",
    "[data-list-id='chat']",
    # New /a/ frontend
    ".chat-background",
    ".MiddleColumn",
    "[class*='MiddleColumn' i]",
    "[class*='messages' i]",
]

_MESSAGE_ITEM_SELECTORS = [
    ".bubble",
    ".bubble-content",
    ".message",
    "div[class*='message' i]",
    ".chat-list .row",
    # New /a/ frontend
    ".Message",
    ".message-list-item",
    "[class*='Message' i][class*='bubble' i]",
    "[data-message-id]",
    "[class*='Bubble' i]",
]

_TEXT_SELECTORS = [
    ".message-text",
    ".text-content",
    ".bubble-content .text",
    "[class*='message-text' i]",
    "[class*='text-content' i]",
]

_AUTHOR_SELECTORS = [
    ".peer-title",
    ".sender-name",
    ".name",
    ".author",
    "[class*='peer-title' i]",
    "[class*='sender' i]",
    # /a/ frontend
    "[class*='ChatInfo']",
    "[class*='chat-title' i]",
    "[class*='top'] [class*='title' i]",
    ".chat-info .title",
    ".ChatInfo .title",
    "h3[class*='title' i]",
]

# In the new /a/ frontend a real message is rendered as ``.message-list-item``
# (an item in the middle column) containing a child with ``.Message``.
# The left sidebar / chat list also uses ``.bubble`` so we explicitly avoid it.
_INNER_MESSAGE_SELECTORS_A = [
    ".message-list-item",
    "[class*='message-list-item' i]",
    "[class*='MiddleColumn'] .Message",
    "[class*='MiddleColumn'] [class*='message-content' i]",
    "[data-message-id] [class*='message-content' i]",
    "[data-message-id]",
    "[class*='Message']:not([class*='MessageList']):not([class*='MessageInput']):not([class*='MessageSend']):not([class*='Composer']):not([class*='MessageMeta']):not([class*='LastMessage'])",
]

# Scoped CSS selector passed to BeautifulSoup.  We restrict the search to the
# middle column so that sidebar "bubbles" (chat-list items) are not picked up.
_INNER_MESSAGE_SELECTORS_K = [
    ".bubbles .bubble",
    ".messages-container .message",
    ".messages-container .bubble",
    "#column-center .bubble",
    "#column-center .message",
    "#column-center [class*='bubble' i]",
    "#column-center [class*='message' i]",
]

_DATE_SELECTORS = [
    "time",
    ".time",
    ".date",
    "[data-timestamp]",
    ".message-time",
]

_MEDIA_IMG_SELECTORS = "img:not([class*='emoji']):not([class*='sticker'])"
_MEDIA_VIDEO_SELECTORS = "video, video source"
_MEDIA_LINK_SELECTORS = "a.media-link, a[class*='link'], a.preview-link"

_FORWARDED_SELECTORS = [
    ".forwarded",
    ".is-forwarded",
    "[class*='forward' i]",
    ".fwd",
]


class WebParser:
    """Parse messages from closed Telegram channels via the web interface.

    Parameters
    ----------
    web_auth : WebAuth
        Initialised auth helper that can restore a Playwright session.
    headless : bool | None
        Override the ``browser.headless`` config value.
    timeout_ms : int
        Default timeout for Playwright operations (milliseconds).
    slow_mo : int
        Artificial delay between Playwright actions (milliseconds).
    """

    def __init__(
        self,
        web_auth: WebAuth | None = None,
        headless: bool | None = None,
        timeout_ms: int = 30_000,
        slow_mo: int | None = None,
    ) -> None:
        self._web_auth = web_auth or WebAuth()
        self._headless = (
            headless if headless is not None
            else bool(get_setting("browser", "headless", default=True))
        )
        self._timeout_ms = timeout_ms
        self._slow_mo = (
            slow_mo if slow_mo is not None
            else int(get_setting("browser", "slow_mo", default=0) or 0)
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(
        self,
        channel_url: str,
        limit: int = 100,
        *,
        max_scroll_attempts: int | None = None,
        scroll_delay_ms: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> list[Message]:
        """Synchronous parse of a closed channel.

        Parameters
        ----------
        channel_url : str
            Channel identifier: ``@username``, ``https://t.me/+hash``,
            or a full ``https://web.telegram.org/k/#@…`` URL.
        limit : int
            Maximum number of messages to collect.
        max_scroll_attempts : int | None
            How many times to scroll upward looking for older messages.
            Falls back to ``parsing.max_scroll_attempts`` from config.
        scroll_delay_ms : int | None
            Delay between scroll attempts (ms).  Falls back to
            ``parsing.scroll_delay_ms`` from config.
        progress_callback : Callable[[str], None] | None
            Optional callback for progress messages (called with a string).
        log_callback : Callable[[str], None] | None
            Optional callback for detailed log lines (e.g. selector results,
            current page URL).  Falls back to ``print(..., flush=True)``.

        Returns
        -------
        list[Message]
            Parsed domain models, newest-first.
        """
        max_scroll = (
            max_scroll_attempts
            if max_scroll_attempts is not None
            else int(get_setting("parsing", "max_scroll_attempts", default=50) or 50)
        )
        scroll_delay = (
            scroll_delay_ms
            if scroll_delay_ms is not None
            else int(get_setting("parsing", "scroll_delay_ms", default=1500) or 1500)
        )

        def _emit(msg: str) -> None:
            if log_callback is not None:
                try:
                    log_callback(msg)
                except Exception:
                    pass
            print(msg, flush=True)
        self._log_cb = _emit

        if not self._web_auth.is_session_valid():
            raise RuntimeError(
                "No valid web session found. Run `tgparser auth --method web` first."
            )

        pw: Playwright | None = None
        browser: Browser | None = None

        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch(
                headless=self._headless, slow_mo=self._slow_mo
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )

            if not self._web_auth.restore_session(context):
                # Gather debug info
                import json
                info = (
                    f"session_file={self._web_auth.session_file!s}, "
                    f"exists={self._web_auth.session_file.exists()}, "
                    f"is_valid={self._web_auth.is_session_valid()}"
                )
                try:
                    raw = self._web_auth.session_file.read_text()
                    data = json.loads(raw)
                    info += f", cookies_in_file={len(data.get('cookies', []))}"
                    info += f", ls_keys={len(data.get('local_storage', {}))}"
                except Exception as exc:
                    info += f", read_session_file_error={exc}"
                raise RuntimeError(
                    "Failed to restore web session into browser context. "
                    f"[{info}] "
                    "Please authenticate first via 'tgparser auth' or the Auth screen."
                )

            page = context.new_page()
            page.set_default_timeout(self._timeout_ms)

            channel_name = self._navigate_to_channel(page, channel_url)
            self._bypass_copy_protection(page)

            messages = self._scroll_and_collect(
                page, channel_name, limit, max_scroll, scroll_delay
            )

            logger.info(
                "Parsed %d messages from %s (web).",
                len(messages),
                channel_url,
            )
            return messages

        except Exception:
            logger.exception("Web parsing failed for %s", channel_url)
            raise
        finally:
            if browser:
                browser.close()
            if pw:
                pw.stop()

    # ------------------------------------------------------------------
    # Channel navigation
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_hash_fragment(channel_url: str) -> str:
        """Make sure a Telegram Web URL has a ``#`` fragment.

        Telegram Web's SPA router is keyed on the URL fragment.  When the
        URL is opened without ``#`` (e.g. because it was pasted as
        ``https://web.telegram.org/a/-100xxx``), the SPA treats the path
        as a regular page and the channel never opens.  This helper
        inserts the missing ``#`` so that ``page.goto`` lands on the
        right channel.

        Only Telegram Web URLs (https://web.telegram.org/{a,k,beta}/...)
        are affected; other URL shapes are returned unchanged.
        """
        for prefix in (
            "https://web.telegram.org/a/",
            "https://web.telegram.org/k/",
            "https://web.telegram.org/beta/",
        ):
            if channel_url.startswith(prefix) and "#" not in channel_url:
                tail = channel_url[len(prefix):]
                if tail:
                    return f"{prefix}#{tail}"
        return channel_url

    def _navigate_to_channel(self, page: Page, channel_url: str) -> str:
        """Open the channel's page and return its display name.

        The new /a/ frontend is an SPA.  In our testing, the only reliable
        way to land on a channel is a direct ``page.goto()`` to the full URL
        with the hash.  Any prior navigation to ``/a/`` first leaves the
        SPA in a state that ignores later hash changes.
        """
        # Detect which Telegram web frontend the user is using: /a/, /k/, /beta/
        base = "https://web.telegram.org/k/"
        if "web.telegram.org/a/" in channel_url:
            base = "https://web.telegram.org/a/"
        elif "web.telegram.org/beta/" in channel_url:
            base = "https://web.telegram.org/beta/"
        self._log_cb(f"\n  Detected Telegram frontend: {base.strip('/')}")

        # Build the full URL.  We always go directly to the channel URL.
        hash_part = self._extract_hash(channel_url)
        if channel_url.startswith("https://web.telegram.org/"):
            target_url = self._ensure_hash_fragment(channel_url)
        else:
            target_url = f"{base}#{hash_part}"
        if target_url != channel_url:
            self._log_cb(f"  Inserted missing '#' fragment: {target_url!r}")
        self._log_cb(f"  page.goto({target_url!r})")
        page.goto(target_url, wait_until="domcontentloaded")

        # Step 2: wait until at least one real message is rendered.
        try:
            self._wait_for_any_selector(
                page,
                [
                    "[data-message-id]",
                    # /k/ legacy
                    "#column-center .message",
                    "#column-center .bubble",
                    ".bubbles .bubble",
                ],
                timeout=30_000,
            )
        except Exception as exc:
            self._log_cb(f"  WARN: messages not yet visible: {exc}")

        # Give the SPA extra time to fully render the channel.
        time.sleep(2.0)

        channel_name = self._extract_channel_name(page)
        self._log_cb(f"  Channel identified as: {channel_name!r} (current URL: {page.url})")
        logger.info("Channel identified as: %s", channel_name)
        return channel_name

    @staticmethod
    def _extract_hash(channel_url: str) -> str:
        """Extract the hash part (``@name`` or ``+hash``) from a channel reference."""
        url = channel_url.strip()
        if url.startswith("https://web.telegram.org/"):
            if "#" in url:
                return url.split("#", 1)[1]
            return url.rsplit("/", 1)[-1]
        if url.startswith("https://t.me/"):
            return url.replace("https://t.me/", "").strip("/")
        if url.startswith("@"):
            return url.lstrip("@")
        return url

    @staticmethod
    @staticmethod
    def _extract_channel_name(page: Page) -> str:
        """Extract the channel title from the top bar of the chat view.

        The new /a/ frontend puts the title in ``[class*="ChatInfo"] [class*="title"]``.
        The legacy /k/ frontend uses the document title (set to the channel name).
        """
        for sel in [
            "[class*='ChatInfo'] [class*='title' i]",
            "[class*='chat-info' i] [class*='title' i]",
            "[class*='top'] [class*='title' i]",
            ".peer-title",
            ".sender-name",
        ]:
            try:
                el = page.query_selector(sel)
                if el:
                    txt = (el.inner_text() or "").strip()
                    if txt and len(txt) < 200:
                        return txt
            except Exception:
                continue
        try:
            title = page.title()
            if title and "Telegram" not in title and title.strip():
                return title
        except Exception:
            pass
        return "unknown"

    # ------------------------------------------------------------------
    # Copy protection bypass
    # ------------------------------------------------------------------

    def _bypass_copy_protection(self, page: Page) -> None:
        """Inject CSS overrides and strip JS event handlers that block selection/copy."""
        try:
            page.add_style_tag(content=COPY_PROTECTION_CSS)
            logger.debug("Injected copy-protection CSS override.")
        except Exception as exc:
            logger.warning("Failed to inject CSS override: %s", exc)

        try:
            page.evaluate(COPY_PROTECTION_JS)
            logger.debug("Stripped copy-protection JS handlers.")
        except Exception as exc:
            logger.warning("Failed to strip JS handlers: %s", exc)

    # ------------------------------------------------------------------
    # Scroll & collect loop
    # ------------------------------------------------------------------

    def _scroll_and_collect(
        self,
        page: Page,
        channel_name: str,
        limit: int,
        max_scroll_attempts: int,
        scroll_delay_ms: int,
    ) -> list[Message]:
        """Scroll upward repeatedly, parsing the DOM after each scroll."""
        seen_ids: set[int] = set()
        all_messages: list[Message] = []
        streak_no_new = 0

        cb = getattr(self, "_log_cb", None) or (lambda m, _p=print: _p(m, flush=True))

        # Disable the Telegram Web ``with-bottom-snap`` behaviour so
        # our programmatic ``scrollTop = 0`` is not silently rolled
        # back to the bottom of the virtualised list.
        try:
            page.add_style_tag(content=
                ".MessageList { scroll-snap-type: none !important; "
                "scroll-behavior: auto !important; }"
            )
        except Exception as exc:
            logger.debug("add_style_tag failed: %s", exc)

        for attempt in range(max_scroll_attempts):
            batch = self._parse_message_elements(page, channel_name)
            new_messages = [m for m in batch if m.id not in seen_ids]

            if new_messages:
                seen_ids.update(m.id for m in new_messages)
                all_messages.extend(new_messages)
                streak_no_new = 0
                logger.debug(
                    "Scroll %d/%d: +%d messages (total %d/%d).",
                    attempt + 1,
                    max_scroll_attempts,
                    len(new_messages),
                    len(all_messages),
                    limit,
                )
                if attempt % 5 == 0 or len(new_messages) > 0:
                    cb(
                        f"  Progress: {len(all_messages)}/{limit} messages "
                        f"(scroll {attempt + 1}/{max_scroll_attempts})"
                    )
            else:
                streak_no_new += 1
                logger.debug(
                    "Scroll %d/%d: no new messages (streak %d).",
                    attempt + 1,
                    max_scroll_attempts,
                    streak_no_new,
                )
                if streak_no_new >= 20:
                    cb(
                        f"  Reached top of channel (no new messages for {streak_no_new} scrolls)"
                    )

            if len(all_messages) >= limit:
                logger.info("Reached message limit (%d).", limit)
                break

            if streak_no_new >= 20:
                logger.info(
                    "No new messages for %d scrolls — reached top of channel.",
                    streak_no_new,
                )
                break

            self._scroll_up(page, scroll_delay_ms)

        return all_messages[:limit]

    def _scroll_up(self, page: Page, delay_ms: int) -> None:
        """Scroll the message container upward to load older messages.

        Telegram Web uses a column-reverse virtualised list where a
        bare ``scrollTop = 0`` write is **ignored** by the lazy
        loader — the React/InertiaJS layer listens to wheel events
        and key presses instead.  This helper tries, in order:

        1. Dispatch a real ``wheel`` event with negative ``deltaY``
           on every plausible scroller.  This is the same signal a
           physical mouse wheel emits, and is what TDesktop's Web
           view actually listens for.
        2. ``PageUp`` keyboard key — forces the native browser
           scroll path that bypasses any custom inertia handling.
        3. ``scrollBy(0, -large)`` and ``scrollTop = 0`` as final
           fallbacks for the legacy ``bubbles`` / ``#column-center``
           selectors.
        """
        sleep_s = max(delay_ms / 1000, 0.5)
        try:
            page.evaluate(
                """() => {
                    // Order matters: the LEFT sidebar also has
                    // ``custom-scroll`` and is scrollable, so we
                    // must prefer the right column's message list.
                    const selectors = [
                        // New ``/a/`` frontend
                        '.MessageList',
                        '[class*="MessageList"]',
                        '[class*="MiddleColumn"] [class*="MessageList"]',
                        // Generic middle column descendants
                        '[class*="MiddleColumn"] [class*="scroller" i]',
                        '[class*="MiddleColumn"] [class*="Scroll" i]',
                        '[class*="MiddleColumn"] [class*="Container" i]',
                        '[class*="MiddleColumn"]',
                        // Legacy ``/k/`` frontend
                        '#column-center .bubbles',
                        '.bubbles',
                        '.messages-container',
                        '#column-center',
                        // Final fallback: the chat-list sidebar
                        // (better than nothing).
                        '.chat-list',
                        '[data-list-id="chat"]',
                    ];
                    let target = null;
                    for (const sel of selectors) {
                        const el = document.querySelector(sel);
                        if (!el) continue;
                        // For virtualised lists the real scroller is
                        // the closest ancestor that overflows.
                        let cur = el;
                        while (cur && (cur.scrollHeight <= cur.clientHeight + 50)) {
                            cur = cur.parentElement;
                            if (!cur) { cur = el; break; }
                        }
                        // Sanity: the chosen target must actually be
                        // scrollable, otherwise a sidebar bubble
                        // matching one of the broad class wildcards
                        // would steal our scroll.
                        if (cur && cur.scrollHeight > cur.clientHeight + 50) {
                            target = cur;
                            break;
                        }
                    }
                    if (!target) target = document.scrollingElement || document.documentElement;
                    // NOTE: Telegram Web's .MessageList uses
                    // ``flex-direction: column-reverse`` so the
                    // visual TOP (oldest messages) is at
                    // ``scrollTop = scrollHeight`` and the visual
                    // BOTTOM (newest) is at ``scrollTop = 0``.
                    // We therefore set a **positive** scroll
                    // value to move toward older messages.
                    // 1) Jump straight to the top of the list.
                    try { target.scrollTop = target.scrollHeight; } catch (e) {}
                    // 2) Programmatic scrollBy in the same direction.
                    try { target.scrollBy({ top: 5000, behavior: 'instant' }); } catch (e) {}
                    // 3) Real wheel event with POSITIVE deltaY —
                    //    this is what physical wheel-down emits,
                    //    and column-reverse maps it to "older".
                    try {
                        const wheelEvt = new WheelEvent('wheel', {
                            deltaY: 2400,
                            deltaMode: 0,
                            bubbles: true,
                            cancelable: true,
                        });
                        target.dispatchEvent(wheelEvt);
                    } catch (e) { /* noop */ }
                    // 4) Window-level scroll (in case the document
                    // body is the actual scroller).
                    try { window.scrollBy(0, 2000); } catch (e) {}
                    // 5) Final fallback: the old scrollTop = 0 in
                    // case column direction is ever flipped.
                    try { target.scrollTop = 0; } catch (e) {}
                }"""
            )
            # 4) Real keyboard — try multiple keys in case the
            # column-reverse direction surprises the event handler.
            for k in ("PageDown", "End", "Home", "PageUp"):
                try:
                    page.keyboard.press(k)
                except Exception as exc:
                    logger.debug("%s failed: %s", k, exc)

            time.sleep(sleep_s)
        except Exception as exc:
            logger.warning("Scroll failed: %s", exc)
            time.sleep(sleep_s)

    # ------------------------------------------------------------------
    # DOM → Message parsing
    # ------------------------------------------------------------------

    def _parse_message_elements(
        self, page: Page, channel_name: str
    ) -> list[Message]:
        """Extract all visible message bubbles from the current page DOM."""
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        cb = getattr(self, "_log_cb", None)
        if cb is None:
            cb = lambda m, _print=print: _print(m, flush=True)

        # Pick the right selector list depending on the current frontend.
        if "/a/" in page.url:
            scoped_selectors = _INNER_MESSAGE_SELECTORS_A
            cb("  Frontend: /a/ — using scoped MiddleColumn selectors")
        else:
            scoped_selectors = _INNER_MESSAGE_SELECTORS_K
            cb("  Frontend: /k/ — using legacy #column-center selectors")

        elements: list[Tag] = []
        # First try the scoped selectors (only MiddleColumn / #column-center).
        for sel in scoped_selectors:
            found = soup.select(sel)
            cb(f"  SELECTOR {sel} -> {len(found)} elements")
            if found:
                elements = found
                break

        # Fall back to the generic selector list if the scoped list found nothing.
        if not elements:
            for sel in _MESSAGE_ITEM_SELECTORS:
                found = soup.select(sel)
                cb(f"  FALLBACK SELECTOR {sel} -> {len(found)} elements")
                if found:
                    elements = found
                    break

        if not elements:
            cb(
                f"  -> No message elements found (html len={len(html)}, "
                f"url={page.url}, title={page.title()!r})"
            )
            logger.info(
                "[web_parser] No message elements found in DOM (html length=%d). "
                "Page URL: %s", len(html), page.url,
            )
            return []

        if not elements:
            cb = getattr(self, "_log_cb", None)
            if cb is None:
                cb = lambda m, _print=print: _print(m, flush=True)
            cb(
                f"  -> No message elements found (html len={len(html)}, "
                f"url={page.url}, title={page.title()!r})"
            )
            logger.info(
                "[web_parser] No message elements found in DOM (html length=%d). "
                "Page URL: %s", len(html), page.url,
            )
            return []

        messages: list[Message] = []
        for el in elements:
            try:
                msg = self._parse_message_element(el, channel_name)
                if msg is not None:
                    messages.append(msg)
            except Exception as exc:
                logger.debug("Failed to parse a message element: %s", exc)
                continue

        return messages

    def _parse_message_element(
        self, el: Tag, channel_name: str
    ) -> Message | None:
        """Parse a single message DOM element into our :class:`Message` model."""
        msg_id = _extract_id(el)
        text = _extract_text(el)
        author = _extract_author(el)
        date = _extract_date(el)
        media_urls = _extract_media_urls(el)
        is_forwarded = _detect_forwarded(el)

        if not text and not media_urls:
            return None

        return Message(
            id=msg_id,
            channel=channel_name,
            date=date or datetime.now(UTC),
            author=author,
            text=text or "",
            media_urls=media_urls,
            reactions=None,
            is_forwarded=is_forwarded,
            raw_source="web",
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _wait_for_any_selector(
        page: Page, selectors: list[str], timeout: int = 15_000
    ) -> None:
        """Wait for at least one of the given selectors to appear."""
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=timeout)
                logger.debug("Selector found: %s", sel)
                return
            except Exception:
                continue
        logger.warning(
            "None of the expected selectors appeared within %d ms: %s",
            timeout,
            selectors,
        )


# -----------------------------------------------------------------------
# Standalone extraction helpers (module-level, usable without instance)
# -----------------------------------------------------------------------

def _extract_id(el: Tag) -> int:
    """Extract a stable message id from DOM attributes or content hash."""
    for attr in ("data-message-id", "data-id", "id"):
        val = el.get(attr)
        if val and val.strip():
            try:
                return abs(hash(val)) % (10**9)
            except (ValueError, TypeError, AttributeError):
                pass
    text = el.get_text(strip=True)[:300]
    return abs(hash(text)) % (10**9)


def _extract_text(el: Tag) -> str | None:
    """Extract message text from DOM element."""
    for sel in _TEXT_SELECTORS:
        text_el = el.select_one(sel)
        if text_el:
            t = text_el.get_text(strip=True)
            if t:
                return t
    # Fallback: get all text, strip known non-text elements
    el_copy = BeautifulSoup(str(el), "html.parser")
    for skip_sel in (".peer-title", ".sender-name", ".time", ".reply-markup", ".bubble-meta"):
        for skip_el in el_copy.select(skip_sel):
            skip_el.decompose()
    text = el_copy.get_text(strip=True)
    return text or None


def _extract_author(el: Tag) -> str | None:
    """Extract message sender name."""
    for sel in _AUTHOR_SELECTORS:
        author_el = el.select_one(sel)
        if author_el:
            name = author_el.get_text(strip=True)
            if name:
                return name
    return None


def _extract_date(el: Tag) -> datetime | None:
    """Extract message date/time from DOM element."""
    time_el = el.select_one("time")
    if time_el:
        dt_str = time_el.get("datetime", "")
        if dt_str:
            try:
                return datetime.fromisoformat(dt_str).replace(tzinfo=UTC)
            except (ValueError, TypeError):
                pass

    for sel in _DATE_SELECTORS:
        date_el = el.select_one(sel)
        if date_el:
            ts = date_el.get("data-timestamp", "")
            if ts:
                try:
                    return datetime.fromtimestamp(int(ts), tz=UTC)
                except (ValueError, TypeError):
                    pass
            text = date_el.get_text(strip=True)
            if text:
                try:
                    return _parse_human_date(text)
                except (ValueError, TypeError):
                    pass

    return None


def _parse_human_date(text: str) -> datetime | None:
    """Best-effort parse of human-readable dates like '12:34 PM' or 'Jan 1'."""

    now = datetime.now(UTC)
    text = text.strip()

    # "12:34" or "12:34 PM" — today
    for fmt in ("%I:%M %p", "%H:%M", "%I:%M%p"):
        try:
            t = datetime.strptime(text, fmt).time()
            return datetime.combine(now.date(), t, tzinfo=UTC)
        except (ValueError, TypeError):
            continue

    # "Jan 1" or "1 Jan" — this year
    for fmt in ("%b %d", "%d %b", "%B %d", "%d %B"):
        try:
            d = datetime.strptime(f"{text} {now.year}", f"{fmt} %Y").date()
            return datetime.combine(d, datetime.min.time(), tzinfo=UTC)
        except (ValueError, TypeError):
            continue

    # "Jan 1, 2024"
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except (ValueError, TypeError):
            continue

    # ISO attempt
    try:
        return datetime.fromisoformat(text).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        pass

    return None


def _extract_media_urls(el: Tag) -> list[str]:
    """Extract media URLs (images, videos, documents) from the element."""
    urls: list[str] = []

    for img in el.select(_MEDIA_IMG_SELECTORS):
        src = img.get("src", "") or img.get("data-src", "")
        if src and not src.startswith("data:") and "emoji" not in src.lower():
            urls.append(src)

    for video in el.select(_MEDIA_VIDEO_SELECTORS):
        src = video.get("src", "")
        if src:
            urls.append(src)

    for a in el.select(_MEDIA_LINK_SELECTORS):
        href = a.get("href", "")
        if href and href.startswith("http"):
            urls.append(href)

    # Deduplicate preserving order
    seen: set[str] = set()
    result: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


def _detect_forwarded(el: Tag) -> bool:
    """Detect whether the message is forwarded."""
    for sel in _FORWARDED_SELECTORS:
        if el.select_one(sel):
            return True
    text = el.get_text(strip=True).lower()
    return "forwarded from" in text
