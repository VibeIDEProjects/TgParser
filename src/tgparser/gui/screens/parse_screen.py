"""Parse screen - configure and run channel parsing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.markup import escape
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)
from tgparser.gui.widgets.copyable_rich_log import CopyableRichLog

from tgparser.auth.mtproto_auth import MTProtoAuth
from tgparser.config import get_secret, get_setting
from tgparser.models import Message
from tgparser.parsers.mtproto_parser import MTProtoParser
from tgparser.parsers.web_parser import WebParser

logger = logging.getLogger("tgparser")


class ParseScreen(Screen[None]):
    """Screen for configuring and running channel parsing."""

    BINDINGS: ClassVar = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "start_parse", "Start"),
    ]

    CSS = """
    ParseScreen {
        align: center top;
    }

    #parse-container {
        width: 90%;
        height: 100%;
        max-width: 120;
        border: solid $primary;
        padding: 1;
    }

	    #parse-header {
	        align: left middle;
	        margin-bottom: 1;
	    }

	    #parse-title {
	        text-style: bold;
	        content-align: center top;
	        margin-bottom: 1;
	    }

    #config-section {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin-bottom: 1;
    }

    .input-row {
        height: auto;
        margin-bottom: 1;
    }

    .input-row > Label {
        width: 20;
        padding-top: 1;
    }

    .input-row > Input, .input-row > Select {
        width: 1fr;
    }

    #filter-section {
        height: auto;
        border: solid $accent;
        padding: 1;
        margin-bottom: 1;
    }

    #parse-actions {
        height: auto;
        align: center middle;
        margin-bottom: 1;
    }

    #parse-actions Button {
        margin: 0 1;
        min-width: 20;
    }

    #progress-section {
        height: auto;
        margin-bottom: 1;
    }

    #parse-log {
        height: 1fr;
        min-height: 8;
        border: solid $surface;
    }

    #status-message {
        height: auto;
        margin-top: 1;
        text-style: italic;
    }
    """

    is_parsing: reactive[bool] = reactive(False)
    progress_total: reactive[int] = reactive(0)
    progress_value: reactive[int] = reactive(0)

    def __init__(self, channel: str = "", channel_type: str = "open", **kwargs) -> None:
        super().__init__(**kwargs)
        self._channel = channel
        self._channel_type = channel_type
        self._messages: list[Message] = []
        self._cancel_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="parse-container"):
            with Horizontal(id="parse-header"):
                yield Button("\u2190 Back", id="btn-back-header", variant="default")
                yield Static("\u25b6 [bold]Parse Channel[/]", id="parse-title")

            with Vertical(id="config-section"):
                with Horizontal(classes="input-row"):
                    yield Label("Channel:")
                    yield Input(
                        placeholder="@username or t.me/...",
                        id="channel-input",
                        value=self._channel,
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Channel Type:")
                    yield Select(
                        [(t, t) for t in ["open", "closed"]],
                        prompt="Select type",
                        id="channel-type-select",
                        value=self._channel_type,
                        allow_blank=False,
                    )

            with Vertical(id="filter-section"):
                yield Static("[bold]Filters[/]")
                with Horizontal(classes="input-row"):
                    yield Label("Message Limit:")
                    yield Input(
                        placeholder=str(
                            get_setting("defaults", "message_limit", default=100)
                        ),
                        id="limit-input",
                        type="integer",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Date From:")
                    yield Input(
                        placeholder="YYYY-MM-DD (e.g., 2025-01-01)",
                        id="date-from-input",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Date To:")
                    yield Input(
                        placeholder="YYYY-MM-DD (leave empty for now)",
                        id="date-to-input",
                    )

            with Horizontal(id="parse-actions"):
                yield Button("\u25b6 Start Parsing", id="btn-start", variant="success")
                yield Button("\u23f9 Stop", id="btn-stop", variant="error")
                yield Button("\u2715 Back", id="btn-back", variant="default")

            with Vertical(id="progress-section"):
                yield ProgressBar(id="progress-bar", total=100, show_eta=True)
                yield Static("0 messages parsed", id="progress-label")

            with Horizontal(id="log-actions"):
                yield Button("📋 Copy", id="btn-copy-log", variant="default")
                yield Button("🗑 Clear", id="btn-clear-log", variant="default")
            yield CopyableRichLog(
                id="parse-log",
                highlight=True,
                markup=True,
                wrap=True,
            )
            yield Static("", id="status-message")

    def on_mount(self) -> None:
        """Focus the channel input on mount."""
        self.query_one("#channel-input", Input).focus()

    @work(exclusive=True)
    async def action_start_parse(self) -> None:
        """Start parsing."""
        if self.is_parsing:
            return

        channel = self.query_one("#channel-input", Input).value.strip()
        channel_type = self.query_one("#channel-type-select", Select).value

        if not channel:
            self.query_one("#status-message", Static).update(
                "\u274c Please enter a channel name or URL."
            )
            return

        if channel.startswith("t.me/"):
            channel = channel.replace("t.me/", "")
        channel = channel.lstrip("@")

        limit_str = self.query_one("#limit-input", Input).value.strip()
        limit = (
            int(limit_str)
            if limit_str
            else get_setting("defaults", "message_limit", default=100)
        )

        date_from_str = self.query_one("#date-from-input", Input).value.strip()
        date_to_str = self.query_one("#date-to-input", Input).value.strip()

        date_from: datetime | None = None
        date_to: datetime | None = None

        if date_from_str:
            try:
                date_from = datetime.strptime(date_from_str, "%Y-%m-%d")
            except ValueError:
                self.query_one("#status-message", Static).update(
                    "\u274c Invalid date format. Use YYYY-MM-DD."
                )
                return

        if date_to_str:
            try:
                date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
            except ValueError:
                self.query_one("#status-message", Static).update(
                    "\u274c Invalid date format. Use YYYY-MM-DD."
                )
                return

        self.is_parsing = True
        self._cancel_event.clear()
        self._messages = []

        log = self.query_one("#parse-log", CopyableRichLog)
        log.clear()
        log.write(
            f"\U0001f504 Starting parsing of [bold]{channel}[/] ({channel_type})..."
        )
        log.write(
            f"   Limit: {limit}, Date from: {date_from_str or 'any'}, "
            f"Date to: {date_to_str or 'any'}"
        )

        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(total=limit, progress=0)
        self.query_one("#progress-label", Static).update("0 messages parsed")

        try:
            if channel_type == "open":
                await self._parse_open(
                    channel, limit, date_from, date_to, log, progress_bar
                )
            else:
                await self._parse_closed(
                    channel, limit, date_from, date_to, log, progress_bar
                )
        except asyncio.CancelledError:
            log.write("\u23f9 Parsing cancelled.")
        except Exception as exc:
            logger.exception("Parsing failed")
            log.write(f"\u274c Parsing error: {escape(str(exc))}")
            self.query_one("#status-message", Static).update(
                f"\u274c Error: {escape(str(exc))}"
            )
        finally:
            self.is_parsing = False
            progress_bar.update(progress=0)
            self.query_one("#progress-label", Static).update(
                f"{len(self._messages)} messages parsed"
            )

            if self._messages:
                self.app.current_channel = channel
                self.app._last_parsed_messages = self._messages
                log.write(
                    f"\u2705 Parsing complete! {len(self._messages)} messages extracted."
                )
                self.query_one("#status-message", Static).update(
                    f"\u2705 Done! {len(self._messages)} messages ready for export."
                )
            else:
                log.write("\u26a0\ufe0f No messages found.")
                self.query_one("#status-message", Static).update(
                    "\u26a0\ufe0f No messages found."
                )

    async def _parse_open(
        self,
        channel: str,
        limit: int,
        date_from: datetime | None,
        date_to: datetime | None,
        log: CopyableRichLog,
        progress_bar: ProgressBar,
    ) -> None:
        """Parse an open channel via MTProto."""
        api_id = get_secret("API_ID")
        api_hash = get_secret("API_HASH")

        if not api_id or not api_hash:
            log.write(
                "\u274c API_ID and API_HASH must be set in .env or via Auth screen."
            )
            raise ValueError("Missing API credentials")

        auth = MTProtoAuth(api_id=int(api_id), api_hash=api_hash)
        client = await auth.get_client()
        if not client:
            log.write("\u274c Not authenticated. Please run Auth first.")
            return

        parser = MTProtoParser(client)
        log.write("\U0001f4e1 Connected to Telegram via MTProto...")

        def progress_callback(current: int, total_: int) -> None:
            # This runs in a thread – we must use call_from_thread for UI updates
            self.app.call_from_thread(progress_bar.update, progress=current)
            self.app.call_from_thread(
                self.query_one("#progress-label", Static).update,
                f"{current} messages parsed",
            )

        messages = await parser.parse_channel(
            channel_username=channel,
            limit=limit,
            offset_date=date_from,
            progress_callback=progress_callback,
        )

        if date_to:
            messages = [m for m in messages if m.date <= date_to]

        self._messages = messages
        for msg in messages[-5:]:
            preview = msg.text[:80] + "..." if len(msg.text) > 80 else msg.text
            log.write(f"  [{msg.date.strftime('%H:%M')}] {preview}")

    async def _parse_closed(
        self,
        channel: str,
        limit: int,
        date_from: datetime | None,
        date_to: datetime | None,
        log: CopyableRichLog,
        progress_bar: ProgressBar,
    ) -> None:
        """Parse a closed channel via web (Playwright)."""
        log.write("\U0001f30d Launching browser for web parsing...")

        web_parser = WebParser()
        log.write("\U0001f50d Initializing web parser...")

        async def progress_callback(current: int, total_: int) -> None:
            progress_bar.update(progress=current)
            self.query_one("#progress-label", Static).update(
                f"{current} messages parsed"
            )

        scroll_delay = get_setting("parsing", "scroll_delay_ms", default=1500)
        max_scroll = get_setting("parsing", "max_scroll_attempts", default=50)

        messages = await asyncio.to_thread(
            web_parser.parse,
            channel,
            limit,
            max_scroll_attempts=max_scroll,
            scroll_delay_ms=scroll_delay,
            progress_callback=progress_callback,
        )

        if date_from:
            messages = [m for m in messages if m.date >= date_from]
        if date_to:
            messages = [m for m in messages if m.date <= date_to]

        self._messages = messages
        for msg in messages[-5:]:
            preview = msg.text[:80] + "..." if len(msg.text) > 80 else msg.text
            log.write(f"  [{msg.date.strftime('%H:%M')}] {preview}")

    def action_stop_parse(self) -> None:
        """Stop parsing."""
        if self.is_parsing:
            self._cancel_event.set()
            self.query_one("#status-message", Static).update(
                "\u23f9 Stopping parsing..."
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "btn-start":
            self.action_start_parse()
        elif btn_id == "btn-stop":
            self.action_stop_parse()
        elif btn_id == "btn-back" or btn_id == "btn-back-header":
            self.action_go_back()
        elif btn_id == "btn-copy-log":
            log = self.query_one("#parse-log", CopyableRichLog)
            text = log.copy_text()
            self.app.copy_to_clipboard(text)
            self.notify("Log copied to clipboard!", severity="info")
        elif btn_id == "btn-clear-log":
            self.query_one("#parse-log", CopyableRichLog).clear()

    def action_go_back(self) -> None:
        """Go back to the main screen."""
        self.dismiss(False)
