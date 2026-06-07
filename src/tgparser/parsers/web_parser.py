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
]

_MESSAGE_ITEM_SELECTORS = [
    ".bubble",
    ".bubble-content",
    ".message",
    "div[class*='message' i]",
    ".chat-list .row",
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
        progress_callback: Callable[[str], None] | None = None,
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
                raise RuntimeError("Failed to restore web session into browser context.")

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

    def _navigate_to_channel(self, page: Page, channel_url: str) -> str:
        """Open the channel's page and return its display name."""
        page.goto("https://web.telegram.org/k/", wait_until="domcontentloaded")
        self._wait_for_any_selector(
            page, [".chatlist", ".chat-list", "#LeftColumn"], timeout=15_000
        )

        logger.info("Navigating to channel: %s", channel_url)
        hash_part = self._extract_hash(channel_url)
        page.evaluate(f"window.location.hash = '{hash_part}'")

        self._wait_for_any_selector(page, _MESSAGE_CONTAINER_SELECTORS, timeout=15_000)
        time.sleep(1.0)

        channel_name = self._extract_channel_name(page)
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
    def _extract_channel_name(page: Page) -> str:
        """Extract the channel title from the top bar of the chat view."""
        for sel in _AUTHOR_SELECTORS:
            try:
                el = page.query_selector(sel)
                if el:
                    return el.inner_text().strip()
            except Exception:
                pass
        try:
            title = page.title()
            if title and "Telegram" not in title:
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
            else:
                streak_no_new += 1
                logger.debug(
                    "Scroll %d/%d: no new messages (streak %d).",
                    attempt + 1,
                    max_scroll_attempts,
                    streak_no_new,
                )

            if len(all_messages) >= limit:
                logger.info("Reached message limit (%d).", limit)
                break

            if streak_no_new >= 3:
                logger.info(
                    "No new messages for %d scrolls — reached top of channel.",
                    streak_no_new,
                )
                break

            self._scroll_up(page, scroll_delay_ms)

        return all_messages[:limit]

    def _scroll_up(self, page: Page, delay_ms: int) -> None:
        """Scroll the message container to its top to trigger lazy-load."""
        try:
            page.evaluate(
                """() => {
                    const container = document.querySelector(
                        '.bubbles, .messages-container, #column-center, ' +
                        '[data-list-id="chat"]'
                    );
                    if (container) {
                        container.scrollTop = 0;
                    }
                }"""
            )
            time.sleep(max(delay_ms / 1000, 0.5))
        except Exception as exc:
            logger.warning("Scroll failed: %s", exc)
            time.sleep(max(delay_ms / 1000, 0.5))

    # ------------------------------------------------------------------
    # DOM → Message parsing
    # ------------------------------------------------------------------

    def _parse_message_elements(
        self, page: Page, channel_name: str
    ) -> list[Message]:
        """Extract all visible message bubbles from the current page DOM."""
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        elements: list[Tag] = []
        for sel in _MESSAGE_ITEM_SELECTORS:
            found = soup.select(sel)
            if found:
                elements = found
                break

        if not elements:
            logger.debug("No message elements found in current DOM.")
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
