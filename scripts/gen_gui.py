import os


def w(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f'Written {path} ({os.path.getsize(path)} bytes)')


def write_app(base):
    w(os.path.join(base, '__init__.py'), '''"""GUI interface for TgParser - built with Textual (TUI)."""

from tgparser.gui.app import TgParserApp

__all__ = ["TgParserApp"]
''')


def write_screens_init(screens):
    w(os.path.join(screens, '__init__.py'), '''"""GUI screens."""

from tgparser.gui.screens.auth_screen import AuthScreen
from tgparser.gui.screens.main_screen import MainScreen
from tgparser.gui.screens.parse_screen import ParseScreen
from tgparser.gui.screens.result_screen import ResultScreen

__all__ = ["AuthScreen", "MainScreen", "ParseScreen", "ResultScreen"]
''')


def write_app_py(base):
    w(os.path.join(base, 'app.py'), '''"""Main Textual application for TgParser GUI."""

from __future__ import annotations

import logging
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import Footer, Header

from tgparser.gui.screens.main_screen import MainScreen

logger = logging.getLogger("tgparser")


class TgParserApp(App[None]):
    """Main TgParser GUI application."""

    TITLE = "TgParser"
    SUB_TITLE = "Telegram Channel Parser"
    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS: ClassVar = [
        Binding("ctrl+c", "quit", "Quit", priority=True),
        Binding("ctrl+d", "toggle_dark", "Toggle dark mode"),
        Binding("f1", "show_about", "About", priority=False),
    ]

    current_channel: reactive[str | None] = reactive(None)
    is_authenticated: reactive[bool] = reactive(False)
    auth_type: reactive[str | None] = reactive(None)

    _last_parsed_messages: list = []

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        yield Header()
        yield Footer()

    def on_mount(self) -> None:
        """Handle app startup."""
        self.push_screen(MainScreen())

    def action_toggle_dark(self) -> None:
        """Toggle between light and dark mode."""
        self.dark = not self.dark

    def action_show_about(self) -> None:
        """Show about dialog."""
        from textual.screen import ModalScreen
        from textual.widgets import Label

        class AboutScreen(ModalScreen[None]):
            def compose(self) -> ComposeResult:
                yield Label(
                    "[bold]TgParser v0.1.0[/]\\n\\n"
                    "Telegram Channel Parser\\n"
                    "Extract messages from open (MTProto) \\n"
                    "and closed (web) Telegram channels.\\n\\n"
                    "Press any key to close."
                )

            def on_key(self) -> None:
                self.dismiss()

        self.push_screen(AboutScreen())

    def open_auth_screen(self) -> None:
        """Navigate to the authentication screen."""
        from tgparser.gui.screens.auth_screen import AuthScreen
        self.push_screen(AuthScreen())

    def open_parse_screen(self, channel: str, channel_type: str = "open") -> None:
        """Navigate to the parsing screen."""
        from tgparser.gui.screens.parse_screen import ParseScreen
        self.push_screen(ParseScreen(channel=channel, channel_type=channel_type))

    def open_result_screen(self, channel: str) -> None:
        """Navigate to the result/export screen."""
        from tgparser.gui.screens.result_screen import ResultScreen
        self.push_screen(ResultScreen(channel=channel))


def run_gui() -> None:
    """Entry point for the GUI."""
    app = TgParserApp()
    app.run()


if __name__ == "__main__":
    run_gui()
''')


def write_main_screen(screens):
    w(os.path.join(screens, 'main_screen.py'), '''"""Main screen - channel list and quick actions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Rule,
    Static,
)

from tgparser.storage import get_last_message_id

logger = logging.getLogger("tgparser")


class ChannelTable(DataTable):
    """Table showing parsed channels and their status."""

    def __init__(self) -> None:
        super().__init__()
        self.add_columns("Channel", "Type", "Last Parsed", "Messages")
        self._channels: dict[str, dict] = {}

    def add_channel(
        self,
        name: str,
        channel_type: str,
        last_parsed: str = "\\u2014",
        message_count: int = 0,
    ) -> None:
        """Add or update a channel row."""
        row_key = name
        if row_key in self._channels:
            self.update_cell(row_key, "Last Parsed", last_parsed)
            self.update_cell(row_key, "Messages", str(message_count))
        else:
            self._channels[row_key] = {
                "name": name,
                "type": channel_type,
            }
            self.add_row(
                name,
                channel_type,
                last_parsed,
                str(message_count),
                key=row_key,
            )


class MainScreen(Screen[None]):
    """Main screen with channel overview and quick actions."""

    BINDINGS: ClassVar = [
        Binding("a", "open_auth", "Auth"),
        Binding("p", "open_parse", "Parse"),
        Binding("r", "refresh_channels", "Refresh"),
        Binding("escape", "app.quit", "Quit"),
    ]

    CSS = """
    MainScreen {
        align: center top;
    }

    #main-container {
        width: 100%;
        height: 100%;
        padding: 1;
    }

    #header-section {
        height: auto;
        padding: 0 1;
        margin-bottom: 1;
    }

    #channel-table {
        height: 1fr;
        min-height: 10;
        border: solid $primary;
        margin-bottom: 1;
    }

    #channel-table > .datatable--header {
        background: $primary;
        color: $text;
    }

    #actions-panel {
        height: auto;
        min-height: 8;
        border: solid $accent;
        padding: 1;
        margin-bottom: 1;
    }

    #actions-panel > Horizontal {
        height: auto;
        align: center middle;
    }

    #actions-panel Button {
        margin: 0 1;
        min-width: 18;
    }

    #status-bar {
        height: 3;
        padding: 0 1;
        background: $boost;
        content-align: center middle;
    }
    """

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="main-container"):
            with Vertical(id="header-section"):
                yield Static(
                    "[bold]TgParser \\u2014 Telegram Channel Parser[/]\\n"
                    "Manage your channels, parse messages, and export data.",
                    id="welcome-text",
                )
                yield Rule()

            yield ChannelTable(id="channel-table")

            with Vertical(id="actions-panel"):
                yield Static("[bold]Quick Actions[/]", classes="section-title")
                with Horizontal():
                    yield Button("\\U0001f510 Auth", id="btn-auth", variant="primary")
                    yield Button("\\u25b6 Parse Channel", id="btn-parse", variant="success")
                    yield Button("\\U0001f4cb Export Results", id="btn-export", variant="default")
                    yield Button("\\U0001f504 Refresh", id="btn-refresh", variant="default")

            yield Static("Ready. Press [bold underline]F1[/] for help.", id="status-bar")

    def on_mount(self) -> None:
        """Load channels on mount."""
        self._load_channels()

    def _load_channels(self) -> None:
        """Load previously parsed channels from storage."""
        output_dir = Path("data/output")
        if not output_dir.exists():
            return

        table = self.query_one("#channel-table", ChannelTable)
        for folder in output_dir.iterdir():
            if folder.is_dir():
                files = list(folder.glob("*.json")) + list(folder.glob("*.csv"))
                if files:
                    latest = max(files, key=lambda f: f.stat().st_mtime)
                    if latest.suffix == ".json":
                        try:
                            with open(latest, encoding="utf-8") as f:
                                data = json.load(f)
                            msg_count = len(data) if isinstance(data, list) else 0
                        except (json.JSONDecodeError, OSError):
                            msg_count = 0
                    else:
                        msg_count = 0

                    table.add_channel(
                        name=folder.name,
                        channel_type="unknown",
                        last_parsed=latest.name,
                        message_count=msg_count,
                    )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "btn-auth":
            self.action_open_auth()
        elif btn_id == "btn-parse":
            self.action_open_parse()
        elif btn_id == "btn-export":
            self.action_export()
        elif btn_id == "btn-refresh":
            self._load_channels()
            self.query_one("#status-bar", Static).update("\\u2705 Channels refreshed.")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle channel selection."""
        channel_name = event.row_key.value
        if channel_name:
            self.app.current_channel = channel_name
            self.action_open_parse()

    def action_open_auth(self) -> None:
        """Open authentication screen."""
        self.app.open_auth_screen()

    def action_open_parse(self) -> None:
        """Open parse screen."""
        channel = self.app.current_channel
        if channel:
            self.app.open_parse_screen(channel)
        else:
            from tgparser.gui.screens.parse_screen import ParseScreen
            self.app.push_screen(ParseScreen(channel=""))

    def action_export(self) -> None:
        """Open result/export screen."""
        channel = self.app.current_channel
        if channel:
            self.app.open_result_screen(channel)
        else:
            self.query_one("#status-bar", Static).update(
                "\\u26a0\\ufe0f Select a channel first from the table above."
            )

    def action_refresh_channels(self) -> None:
        """Refresh channel list."""
        self._load_channels()
        self.query_one("#status-bar", Static).update("\\u2705 Channels refreshed.")
''')


def write_auth_screen(screens):
    w(os.path.join(screens, 'auth_screen.py'), '''"""Authentication screen."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from tgparser.auth.mtproto_auth import MTProtoAuth
from tgparser.auth.web_auth import WebAuth
from tgparser.config import get_secret

logger = logging.getLogger("tgparser")


class AuthScreen(Screen[None]):
    """Authentication screen."""

    BINDINGS: ClassVar = [
        Binding("escape", "go_back", "Back"),
        Binding("f5", "start_auth", "Start"),
    ]

    CSS = """
    AuthScreen {
        align: center middle;
    }

    #auth-container {
        width: 80%;
        height: 90%;
        max-width: 100;
        border: solid $primary;
        padding: 1;
    }

    #auth-title {
        text-style: bold;
        content-align: center top;
        margin-bottom: 1;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1;
    }

    .input-row {
        height: auto;
        margin-bottom: 1;
    }

    .input-row > Label {
        width: 22;
        padding-top: 1;
    }

    .input-row > Input {
        width: 1fr;
    }

    #auth-log {
        height: 8;
        min-height: 4;
        border: solid $surface;
        margin-top: 1;
    }

    #auth-actions {
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    #auth-actions Button {
        margin: 0 1;
        min-width: 20;
    }

    #status-message {
        height: auto;
        margin-top: 1;
        text-style: italic;
    }
    """

    auth_in_progress: reactive[bool] = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self._web_auth: WebAuth | None = None
        self._mtproto_auth: MTProtoAuth | None = None

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="auth-container"):
            yield Static("\\U0001f510 [bold]Authorization[/]", id="auth-title")

            with TabbedContent(initial="mtproto"):
                with TabPane("MTProto (API)", id="mtproto"):
                    with Vertical():
                        yield Static(
                            "[italic]Enter your Telegram API credentials.\\n"
                            "Get them at https://my.telegram.org/apps[/]",
                            classes="help-text",
                        )
                        with Horizontal(classes="input-row"):
                            yield Label("API ID:")
                            yield Input(placeholder="123456", id="api-id-input")
                        with Horizontal(classes="input-row"):
                            yield Label("API Hash:")
                            yield Input(
                                placeholder="1a2b3c4d...",
                                id="api-hash-input",
                                password=True,
                            )
                        with Horizontal(classes="input-row"):
                            yield Label("Phone Number:")
                            yield Input(
                                placeholder="+1234567890",
                                id="phone-input",
                            )
                        with Horizontal(classes="input-row"):
                            yield Label("Code (2FA):")
                            yield Input(
                                placeholder="Leave empty if not needed",
                                id="code-input",
                                password=True,
                            )
                        yield RichLog(id="auth-log", highlight=True, markup=True)

                with TabPane("Web (QR Code)", id="web"):
                    yield Static(
                        "[italic]Open web.telegram.org in a browser\\n"
                        "and scan the QR code with your phone.[/]",
                        classes="help-text",
                    )
                    yield RichLog(id="web-auth-log", highlight=True, markup=True)

            with Horizontal(id="auth-actions"):
                yield Button("\\u25b6 Start Auth", id="btn-auth-start", variant="success")
                yield Button("\\u2715 Cancel", id="btn-auth-cancel", variant="error")

            yield Static("", id="status-message")

    def on_mount(self) -> None:
        """Pre-fill credentials from .env if available."""
        api_id = get_secret("API_ID", "")
        api_hash = get_secret("API_HASH", "")
        phone = get_secret("PHONE", "")

        if api_id:
            self.query_one("#api-id-input", Input).value = api_id
        if api_hash:
            self.query_one("#api-hash-input", Input).value = api_hash
        if phone:
            self.query_one("#phone-input", Input).value = phone

    @work(exclusive=True)
    async def action_start_auth(self) -> None:
        """Start authentication."""
        if self.auth_in_progress:
            return

        self.auth_in_progress = True
        self.query_one("#status-message", Static).update(
            "\\u23f3 Authentication in progress..."
        )

        tabs = self.query_one(TabbedContent)
        active_tab = tabs.active

        try:
            if active_tab == "mtproto":
                await self._do_mtproto_auth()
            else:
                await self._do_web_auth()
        except Exception as exc:
            logger.exception("Auth failed")
            self.query_one("#status-message", Static).update(
                f"\\u274c Auth failed: {exc}"
            )
        finally:
            self.auth_in_progress = False

    async def _do_mtproto_auth(self) -> None:
        """Perform MTProto authentication."""
        api_id_str = self.query_one("#api-id-input", Input).value.strip()
        api_hash = self.query_one("#api-hash-input", Input).value.strip()
        phone = self.query_one("#phone-input", Input).value.strip()
        code = self.query_one("#code-input", Input).value.strip()

        if not api_id_str or not api_hash or not phone:
            self.query_one("#status-message", Static).update(
                "\\u274c Please fill in API ID, API Hash, and Phone Number."
            )
            return

        try:
            api_id = int(api_id_str)
        except ValueError:
            self.query_one("#status-message", Static).update(
                "\\u274c API ID must be a number."
            )
            return

        log = self.query_one("#auth-log", RichLog)
        log.write("\\U0001f504 Initializing MTProto authentication...")
        self._mtproto_auth = MTProtoAuth(api_id=api_id, api_hash=api_hash)

        async def progress_callback(msg: str) -> None:
            log.write(msg)

        self._mtproto_auth.progress_callback = progress_callback

        session = await self._mtproto_auth.authenticate(
            phone=phone,
            code=code if code else None,
        )

        if session:
            log.write("\\u2705 Authentication successful!")
            self.app.is_authenticated = True
            self.app.auth_type = "mtproto"
            self.query_one("#status-message", Static).update(
                "\\u2705 Authenticated via MTProto!"
            )
            await asyncio.sleep(1.5)
            self.dismiss(True)
        else:
            log.write("\\u274c Authentication failed.")
            self.query_one("#status-message", Static).update(
                "\\u274c Authentication failed. Check credentials."
            )

    async def _do_web_auth(self) -> None:
        """Perform Web (QR) authentication."""
        log = self.query_one("#web-auth-log", RichLog)
        log.write("\\U0001f504 Opening browser for QR authentication...")

        self._web_auth = WebAuth()

        if await self._web_auth.check_session():
            log.write("\\u2705 Existing web session found! Using it.")
            self.app.is_authenticated = True
            self.app.auth_type = "web"
            self.query_one("#status-message", Static).update(
                "\\u2705 Authenticated via existing web session!"
            )
            await asyncio.sleep(1)
            self.dismiss(True)
            return

        log.write("\\U0001f504 Launching browser for QR code...")
        success = await self._web_auth.authenticate()

        if success:
            log.write("\\u2705 Web authentication successful!")
            self.app.is_authenticated = True
            self.app.auth_type = "web"
            self.query_one("#status-message", Static).update(
                "\\u2705 Authenticated via QR code!"
            )
            await asyncio.sleep(1.5)
            self.dismiss(True)
        else:
            log.write("\\u274c Web authentication failed or was cancelled.")
            self.query_one("#status-message", Static).update(
                "\\u274c Web authentication failed."
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "btn-auth-start":
            self.action_start_auth()
        elif btn_id == "btn-auth-cancel":
            self.dismiss(False)

    def action_go_back(self) -> None:
        """Go back to the main screen."""
        self.dismiss(False)
''')


def write_parse_screen(screens):
    w(os.path.join(screens, 'parse_screen.py'), '''"""Parse screen - configure and run channel parsing."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    ProgressBar,
    RichLog,
    Select,
    Static,
)

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

    def __init__(self, channel: str = "", channel_type: str = "open") -> None:
        super().__init__()
        self._channel = channel
        self._channel_type = channel_type
        self._messages: list[Message] = []
        self._cancel_event = asyncio.Event()

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="parse-container"):
            yield Static("\\u25b6 [bold]Parse Channel[/]", id="parse-title")

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
                yield Button("\\u25b6 Start Parsing", id="btn-start", variant="success")
                yield Button("\\u23f9 Stop", id="btn-stop", variant="error")
                yield Button("\\u2715 Back", id="btn-back", variant="default")

            with Vertical(id="progress-section"):
                yield ProgressBar(id="progress-bar", total=100, show_eta=True)
                yield Static("0 messages parsed", id="progress-label")

            yield RichLog(id="parse-log", highlight=True, markup=True, wrap=True)
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
                "\\u274c Please enter a channel name or URL."
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
                    "\\u274c Invalid date format. Use YYYY-MM-DD."
                )
                return

        if date_to_str:
            try:
                date_to = datetime.strptime(date_to_str, "%Y-%m-%d")
            except ValueError:
                self.query_one("#status-message", Static).update(
                    "\\u274c Invalid date format. Use YYYY-MM-DD."
                )
                return

        self.is_parsing = True
        self._cancel_event.clear()
        self._messages = []

        log = self.query_one("#parse-log", RichLog)
        log.clear()
        log.write(
            f"\\U0001f504 Starting parsing of [bold]{channel}[/] ({channel_type})..."
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
            log.write("\\u23f9 Parsing cancelled.")
        except Exception as exc:
            logger.exception("Parsing failed")
            log.write(f"\\u274c Parsing error: {exc}")
            self.query_one("#status-message", Static).update(
                f"\\u274c Error: {exc}"
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
                    f"\\u2705 Parsing complete! {len(self._messages)} messages extracted."
                )
                self.query_one("#status-message", Static).update(
                    f"\\u2705 Done! {len(self._messages)} messages ready for export."
                )
            else:
                log.write("\\u26a0\\ufe0f No messages found.")
                self.query_one("#status-message", Static).update(
                    "\\u26a0\\ufe0f No messages found."
                )

    async def _parse_open(
        self,
        channel: str,
        limit: int,
        date_from: datetime | None,
        date_to: datetime | None,
        log: RichLog,
        progress_bar: ProgressBar,
    ) -> None:
        """Parse an open channel via MTProto."""
        api_id = get_secret("API_ID")
        api_hash = get_secret("API_HASH")

        if not api_id or not api_hash:
            log.write(
                "\\u274c API_ID and API_HASH must be set in .env or via Auth screen."
            )
            raise ValueError("Missing API credentials")

        auth = MTProtoAuth(api_id=int(api_id), api_hash=api_hash)
        client = await auth.get_client()
        if not client:
            log.write("\\u274c Not authenticated. Please run Auth first.")
            return

        parser = MTProtoParser(client)
        log.write("\\U0001f4e1 Connected to Telegram via MTProto...")

        async def progress_callback(current: int, total_: int) -> None:
            progress_bar.update(progress=current)
            self.query_one("#progress-label", Static).update(
                f"{current} messages parsed"
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
        log: RichLog,
        progress_bar: ProgressBar,
    ) -> None:
        """Parse a closed channel via web (Playwright)."""
        log.write("\\U0001f30d Launching browser for web parsing...")

        web_parser = WebParser()
        log.write("\\U0001f50d Initializing web parser...")

        async def progress_callback(current: int, total_: int) -> None:
            progress_bar.update(progress=current)
            self.query_one("#progress-label", Static).update(
                f"{current} messages parsed"
            )

        scroll_delay = get_setting("parsing", "scroll_delay_ms", default=1500)
        max_scroll = get_setting("parsing", "max_scroll_attempts", default=50)

        messages = await web_parser.parse_channel(
            channel_url=channel,
            limit=limit,
            scroll_delay_ms=scroll_delay,
            max_scroll_attempts=max_scroll,
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
                "\\u23f9 Stopping parsing..."
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "btn-start":
            self.action_start_parse()
        elif btn_id == "btn-stop":
            self.action_stop_parse()
        elif btn_id == "btn-back":
            self.action_go_back()

    def action_go_back(self) -> None:
        """Go back to the main screen."""
        self.dismiss(False)
''')


def main():
    base = r'd:\\Projects\\VibeCode\\VibeIDEProjects\\projects\\TgParser\\src\\tgparser\\gui'
    screens = os.path.join(base, 'screens')

    write_app(base)
    write_screens_init(screens)
    write_app_py(base)
    write_main_screen(screens)
    write_auth_screen(screens)
    write_parse_screen(screens)
    print('All GUI files written successfully.')


if __name__ == '__main__':
    main()