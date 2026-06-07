"""Main Textual application for TgParser GUI."""

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
        self.push_screen(MainScreen(id="main-screen"))

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
                    "[bold]TgParser v0.1.0[/]\n\n"
                    "Telegram Channel Parser\n"
                    "Extract messages from open (MTProto) \n"
                    "and closed (web) Telegram channels.\n\n"
                    "Press any key to close."
                )

            def on_key(self) -> None:
                self.dismiss()

        self.push_screen(AboutScreen())

    def open_auth_screen(self) -> None:
        """Navigate to the authentication screen."""
        from tgparser.gui.screens.auth_screen import AuthScreen
        self.push_screen(AuthScreen(id="auth-screen"))

    def open_parse_screen(self, channel: str, channel_type: str = "open") -> None:
        """Navigate to the parsing screen."""
        from tgparser.gui.screens.parse_screen import ParseScreen
        self.push_screen(ParseScreen(id="parse-screen", channel=channel, channel_type=channel_type))

    def open_result_screen(self, channel: str) -> None:
        """Navigate to the result/export screen."""
        from tgparser.gui.screens.result_screen import ResultScreen
        self.push_screen(ResultScreen(id="result-screen", channel=channel))


def run_gui() -> None:
    """Entry point for the GUI."""
    app = TgParserApp()
    app.run()


if __name__ == "__main__":
    run_gui()
