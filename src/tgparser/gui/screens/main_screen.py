"""Main screen - channel list and quick actions."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from tgparser.config import resolve_path

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
        # NOTE: Textual's add_columns() helper does not forward
        # ``key=...`` to add_column(), so the resulting ColumnKey
        # objects would all be ColumnKey(None).  Call add_column()
        # directly with an explicit key=label so update_cell() can
        # find the column by its label later.
        for label in ("Channel", "Type", "Last Parsed", "Messages"):
            self.add_column(label, key=label)
        self._channels: dict[str, dict] = {}

    def add_channel(
        self,
        name: str,
        channel_type: str,
        last_parsed: str = "\u2014",
        message_count: int = 0,
    ) -> None:
        """Add or update a channel row.

        The DataTable's ``_row_locations`` is the source of truth
        for whether a row already exists; the auxiliary
        ``self._channels`` dict can desync during rapid successive
        calls (e.g. ``on_mount`` followed by a btn-refresh click),
        so we consult the DataTable directly.
        """
        row_key = name
        if row_key in self._row_locations:
            # Row already exists — update cells in place.
            self.update_cell(row_key, "Last Parsed", last_parsed)
            self.update_cell(row_key, "Messages", str(message_count))
        else:
            # Brand new row — register in both the cache dict and
            # the DataTable.
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
        height: auto;
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
        with VerticalScroll(id="main-container"):
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
                    yield Button("\U0001f441 View Results", id="btn-view", variant="default")
                    yield Button("\U0001f4c2 Browse Output", id="btn-browse", variant="default")
                    yield Button("\U0001f504 Refresh", id="btn-refresh", variant="default")
                    yield Button("\u274c Exit", id="btn-exit", variant="error")

            yield Static("Ready. Press [bold underline]F1[/] for help.", id="status-bar")

    def on_mount(self) -> None:
        """Load channels on mount."""
        self._load_channels()

    def _load_channels(self) -> None:
        """Load previously parsed channels from storage.

        Recognises two export naming conventions:

        * ``<channel>_all.<fmt>``  — combined file produced by
          :func:`save_messages_incremental`.
        * ``<channel>_<YYYYMMDD_HHMMSS>.<fmt>``  — per-export
          timestamped file produced by :func:`save_messages`.

        All files for a channel are grouped together so the user
        sees one row per channel even when several exports exist.
        """
        output_dir = resolve_path("output_dir")
        if not output_dir.exists():
            return

        import re as _re
        table = self.query_one("#channel-table", ChannelTable)
        ts_re = _re.compile(r"^(.+)_(\d{8}_\d{6})$")
        by_channel: dict[str, list[Path]] = {}
        for path in output_dir.iterdir():
            if not path.is_file():
                continue
            name = path.name
            # Skip state files produced by save_messages_incremental.
            if name.endswith("_state.json"):
                continue
            chan: str | None = None
            for ext in ("json", "csv", "md"):
                if name.endswith(f"_all.{ext}"):
                    chan = name[: -len(f"_all.{ext}")]
                    break
                if name.endswith(f".{ext}"):
                    stem = name[: -len(f".{ext}")]
                    m = ts_re.match(stem)
                    if m:
                        chan = m.group(1)
                        break
            if chan is not None:
                by_channel.setdefault(chan, []).append(path)

        for chan, files in by_channel.items():
            # Prefer JSON for message counting
            json_file = next(
                (f for f in files if f.suffix == ".json"),
                None,
            )
            if json_file is not None:
                try:
                    with open(json_file, encoding="utf-8") as f:
                        data = json.load(f)
                    msg_count = len(data) if isinstance(data, list) else 0
                except (json.JSONDecodeError, OSError):
                    msg_count = 0
            else:
                # Estimate from the markdown file (count "## Message" lines).
                md_file = next((f for f in files if f.suffix == ".md"), None)
                if md_file is not None:
                    try:
                        text = md_file.read_text(encoding="utf-8")
                        msg_count = text.count("## Message #")
                    except OSError:
                        msg_count = 0
                else:
                    msg_count = 0

            latest = max(files, key=lambda f: f.stat().st_mtime)
            table.add_channel(
                name=chan,
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
        elif btn_id == "btn-view":
            self.action_export()
        elif btn_id == "btn-refresh":
            self._load_channels()
        elif btn_id == "btn-browse":
            self.app.open_files_screen()
            self.query_one("#status-bar", Static).update("\u2705 Channels refreshed.")
        elif btn_id == "btn-exit":
            self.app.exit()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle channel selection — open the result screen so the
        user sees the already-downloaded messages immediately.
        Parsing is still available through the [b]Parse Channel[/b]
        button for users that want to refresh the data.
        """
        channel_name = event.row_key.value
        if channel_name:
            self.app.current_channel = channel_name
            self.action_export()

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
        """Open result/export screen.

        If a channel has been selected in the table we use it;
        otherwise we fall back to the first channel currently in
        the table so the user can simply click \u201cView Results\u201d
        to see their data.
        """
        channel = self.app.current_channel
        if not channel:
            # Fall back to the first channel listed in the table.
            table = self.query_one("#channel-table", ChannelTable)
            if table.row_count:
                first_row_key = next(iter(table._row_locations))
                channel = (
                    first_row_key.value
                    if hasattr(first_row_key, "value")
                    else str(first_row_key)
                )
                self.app.current_channel = channel
        if channel:
            self.app.open_result_screen(channel)
        else:
            self.query_one("#status-bar", Static).update(
                "\u26a0\ufe0f No channels to view. Run a parse first."
            )

    def action_refresh_channels(self) -> None:
        """Refresh channel list."""
        self._load_channels()
        self.query_one("#status-bar", Static).update("\u2705 Channels refreshed.")
