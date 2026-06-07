"""Main screen - channel list and quick actions."""

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

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.add_columns("Channel", "Type", "Last Parsed", "Messages")
        self._channels: dict[str, dict] = {}

    def add_channel(
        self,
        name: str,
        channel_type: str,
        last_parsed: str = "\u2014",
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
                    "[bold]TgParser \u2014 Telegram Channel Parser[/]\n"
                    "Manage your channels, parse messages, and export data.",
                    id="welcome-text",
                )
                yield Rule()

            yield ChannelTable(id="channel-table")

            with Vertical(id="actions-panel"):
                yield Static("[bold]Quick Actions[/]", classes="section-title")
                with Horizontal():
                    yield Button("\U0001f510 Auth", id="btn-auth", variant="primary")
                    yield Button("\u25b6 Parse Channel", id="btn-parse", variant="success")
                    yield Button("\U0001f4cb Export Results", id="btn-export", variant="default")
                    yield Button("\U0001f504 Refresh", id="btn-refresh", variant="default")

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
            self.query_one("#status-bar", Static).update("\u2705 Channels refreshed.")

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
            self.app.push_screen(ParseScreen(id="parse-screen", channel=""))

    def action_export(self) -> None:
        """Open result/export screen."""
        channel = self.app.current_channel
        if channel:
            self.app.open_result_screen(channel)
        else:
            self.query_one("#status-bar", Static).update(
                "\u26a0\ufe0f Select a channel first from the table above."
            )

    def action_refresh_channels(self) -> None:
        """Refresh channel list."""
        self._load_channels()
        self.query_one("#status-bar", Static).update("\u2705 Channels refreshed.")
