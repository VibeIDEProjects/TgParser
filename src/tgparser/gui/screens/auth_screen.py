"""Authentication screen."""

from __future__ import annotations

import asyncio
import logging
from typing import ClassVar

logger = logging.getLogger(__name__)

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    Input,
    Label,
    Static,
    TabbedContent,
    TabPane,
)
from tgparser.gui.widgets.copyable_rich_log import CopyableRichLog

from tgparser.auth.mtproto_auth import MTProtoAuth
from tgparser.auth.web_auth import WebAuth, LOGIN_WAIT_TIMEOUT_S
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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._web_auth: WebAuth | None = None
        self._mtproto_auth: MTProtoAuth | None = None

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="auth-container"):
            yield Static("\U0001f510 [bold]Authorization[/]", id="auth-title")

            with TabbedContent(initial="mtproto"):
                with TabPane("MTProto (API)", id="mtproto"):
                    with Vertical():
                        yield Static(
                            "[italic]Enter your Telegram API credentials.\n"
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
                        yield CopyableRichLog(
                            id="auth-log",
                            highlight=True,
                            markup=True,
                        )

                with TabPane("Web (QR Code)", id="web"):
                    yield Static(
                        "[italic]Open web.telegram.org in a browser\n"
                        "and scan the QR code with your phone.[/]",
                        classes="help-text",
                    )
                    yield CopyableRichLog(
                        id="web-auth-log",
                        highlight=True,
                        markup=True,
                    )

            with Horizontal(id="auth-actions"):
                yield Button("\u25b6 Start Auth", id="btn-auth-start", variant="success")
                yield Button("\u2715 Cancel", id="btn-auth-cancel", variant="error")

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
            "\u23f3 Authentication in progress..."
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
                f"\u274c Auth failed: {exc}"
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
                "\u274c Please fill in API ID, API Hash, and Phone Number."
            )
            return

        try:
            api_id = int(api_id_str)
        except ValueError:
            self.query_one("#status-message", Static).update(
                "\u274c API ID must be a number."
            )
            return

        log = self.query_one("#auth-log", CopyableRichLog)
        log.write("\U0001f504 Initializing MTProto authentication...")
        self._mtproto_auth = MTProtoAuth(api_id=api_id, api_hash=api_hash)

        async def progress_callback(msg: str) -> None:
            log.write(msg)

        self._mtproto_auth.progress_callback = progress_callback

        session = await self._mtproto_auth.authenticate(
            phone=phone,
            code=code if code else None,
        )

        if session:
            log.write("\u2705 Authentication successful!")
            self.app.is_authenticated = True
            self.app.auth_type = "mtproto"
            self.query_one("#status-message", Static).update(
                "\u2705 Authenticated via MTProto!"
            )
            await asyncio.sleep(1.5)
            self.dismiss(True)
        else:
            log.write("\u274c Authentication failed.")
            self.query_one("#status-message", Static).update(
                "\u274c Authentication failed. Check credentials."
            )

    async def _do_web_auth(self) -> None:
        """Perform Web (QR) authentication."""
        log = self.query_one("#web-auth-log", CopyableRichLog)
        msg = "\U0001f504 Opening browser for QR authentication..."
        log.write(msg)
        logger.info(msg)

        self._web_auth = WebAuth()

        if await self._web_auth.check_session():
            msg = "\u2705 Existing web session found! Using it."
            log.write(msg)
            logger.info(msg)
            self.app.is_authenticated = True
            self.app.auth_type = "web"
            self.query_one("#status-message", Static).update(
                "\u2705 Authenticated via existing web session!"
            )
            await asyncio.sleep(1)
            self.dismiss(True)
            return

        msg = "\U0001f504 Launching browser for QR code..."
        log.write(msg)
        logger.info(msg)

        try:
            success = await asyncio.wait_for(
                self._web_auth.authenticate(), timeout=LOGIN_WAIT_TIMEOUT_S + 10
            )
        except asyncio.TimeoutError:
            logger.error("Web authentication timed out after 60 seconds.")
            msg = "\u274c Web authentication timed out."
            log.write(msg)
            self.query_one("#status-message", Static).update(msg)
            return
        except Exception as exc:
            logger.exception("Web authentication failed with exception.")
            msg = f"\u274c Web authentication failed: {exc}"
            log.write(msg)
            self.query_one("#status-message", Static).update(msg)
            return

        if success:
            msg = "\u2705 Web authentication successful!"
            log.write(msg)
            logger.info(msg)
            self.app.is_authenticated = True
            self.app.auth_type = "web"
            self.query_one("#status-message", Static).update(
                "\u2705 Authenticated via QR code!"
            )
            await asyncio.sleep(1.5)
            self.dismiss(True)
        else:
            msg = "\u274c Web authentication failed or was cancelled."
            log.write(msg)
            logger.warning(msg)
            self.query_one("#status-message", Static).update(
                "\u274c Web authentication failed."
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
