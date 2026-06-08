"""Result screen — view parsed messages and export them."""

from __future__ import annotations

import json as json_lib
import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from textual import work
from textual.app import ComposeResult
from textual.markup import escape
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import Screen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
)
from tgparser.gui.widgets.copyable_rich_log import CopyableRichLog

from tgparser.config import resolve_path
from tgparser.models import Message
from tgparser.storage import save_messages, save_messages_incremental, OutputFormat

logger = logging.getLogger("tgparser")


class ResultScreen(Screen[None]):
    """Screen for viewing parsed results and exporting data."""

    BINDINGS: ClassVar = [
        Binding("escape", "go_back", "Back"),
        Binding("f2", "export_json", "Export JSON"),
        Binding("f3", "export_csv", "Export CSV"),
        Binding("f4", "export_txt", "Export TXT"),
        Binding("f5", "export_sqlite", "Export SQLite"),
    ]

    CSS = """
    ResultScreen {
        align: center top;
    }

    #result-container {
        width: 95%;
        height: 100%;
        max-width: 140;
        border: solid $primary;
        padding: 1;
    }

	    #result-header {
	        align: left middle;
	        margin-bottom: 1;
	    }

	    #result-title {
	        text-style: bold;
	        content-align: center top;
	        margin-bottom: 1;
	    }

    #messages-table {
        height: 1fr;
        min-height: 10;
        border: solid $accent;
        margin-bottom: 1;
    }

    #messages-table > .datatable--header {
        background: $primary;
        color: $text;
    }

    #export-section {
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

    #export-actions {
        height: auto;
        align: center middle;
        margin-bottom: 1;
    }

    #export-actions Button {
        margin: 0 1;
        min-width: 18;
    }

    #export-log {
        height: 6;
        min-height: 4;
        border: solid $surface;
    }

    #status-message {
        height: auto;
        margin-top: 1;
        text-style: italic;
    }

    .hidden {
        display: none;
    }
    """

    export_in_progress: reactive[bool] = reactive(False)

    def __init__(self, channel: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._channel = channel
        self._messages: list[Message] = []

    def compose(self) -> ComposeResult:
        """Create child widgets."""
        with Container(id="result-container"):
            with Horizontal(id="result-header"):
                yield Button("\u2190 Back", id="btn-back-header", variant="default")
                yield Static("📋 [bold]Results & Export[/]", id="result-title")

            # Messages table
            yield DataTable(id="messages-table")

            # Export configuration
            with Vertical(id="export-section"):
                yield Static("[bold]Export Settings[/]")
                with Horizontal(classes="input-row"):
                    yield Label("Format:")
                    yield Select(
                        [(f.value, f.name) for f in OutputFormat],
                        prompt="Select format",
                        id="format-select",
                        value="json",
                        allow_blank=False,
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Output Path:")
                    yield Input(
                        placeholder=f"Leave empty for default ({resolve_path('output_dir')}/<channel>)",
                        id="output-path-input",
                    )
                with Horizontal(classes="input-row"):
                    yield Label("Incremental:")
                    yield Select(
                        [("false", "No (full export)"), ("true", "Yes (only new messages)")],
                        prompt="Select mode",
                        id="incremental-select",
                        value="false",
                        allow_blank=False,
                    )

            # Export actions
            with Horizontal(id="export-actions"):
                yield Button("💾 Export", id="btn-export", variant="primary")
                yield Button("🔄 Refresh Table", id="btn-refresh", variant="default")
                yield Button("✕ Back", id="btn-back", variant="default")

            # Log
            yield CopyableRichLog(
                id="export-log",
                highlight=True,
                markup=True,
                wrap=True,
            )
            yield Static("", id="status-message")

    def on_mount(self) -> None:
        """Load messages and populate the table."""
        self._load_messages()

    def _load_messages(self) -> None:
        """Load previously parsed messages from storage.

        Looks for the combined ``<channel>_all.json`` file produced by
        :func:`save_messages_incremental`.  Falls back to scanning
        ``<channel>/<timestamp>.json`` files in a sub-folder (legacy
        per-export layout).
        """
        # First try the in-memory store (set by the parse screen).
        stored_messages = getattr(self.app, "_last_parsed_messages", None)
        if stored_messages:
            self._messages = stored_messages
            self._populate_table()
            return

        out_root = resolve_path("output_dir")
        safe = self._channel.lstrip("@").replace("/", "_")
        json_file = out_root / f"{safe}_all.json"

        if not json_file.exists():
            # Legacy layout: per-export files in <channel>/ folder.
            legacy_dir = out_root / self._channel
            if legacy_dir.exists():
                legacy_files = list(legacy_dir.glob("*.json"))
                if legacy_files:
                    json_file = max(
                        legacy_files, key=lambda f: f.stat().st_mtime
                    )

        if not json_file.exists():
            self._messages = []
            self._populate_table()
            self._status = (
                f"ℹ️ No saved messages for @{self._channel} yet. "
                "Run a parse first."
            )
            self._render_status()
            return

        try:
            with open(json_file, encoding="utf-8") as f:
                data = json_lib.load(f)
            self._messages = [Message.from_dict(m) for m in data]
        except (json_lib.JSONDecodeError, OSError, KeyError, ValueError) as exc:
            logger.warning("Failed to load messages from %s: %s", json_file, exc)
            self._messages = []

        self._populate_table()

    def _populate_table(self) -> None:
        """Fill the DataTable with message data."""
        table = self.query_one("#messages-table", DataTable)
        table.clear()
        table.add_columns(
            "ID", "Date", "Author", "Text (preview)", "Media", "Reactions"
        )

        for msg in self._messages:
            text_preview = (
                msg.text[:60] + "..." if len(msg.text) > 60 else msg.text
            )
            media_count = str(len(msg.media_urls)) if msg.media_urls else "0"
            reactions_str = (
                ", ".join(f"{k}:{v}" for k, v in msg.reactions.items())[:30]
                if msg.reactions
                else ""
            )
            table.add_row(
                str(msg.id),
                msg.date.strftime("%Y-%m-%d %H:%M"),
                msg.author or "—",
                text_preview,
                media_count,
                reactions_str,
            )

        self.query_one("#status-message", Static).update(
            f"📊 {len(self._messages)} messages loaded for [bold]{self._channel}[/]"
        )

    def _get_output_path(self) -> Path:
        """Determine the output path."""
        path_input = self.query_one("#output-path-input", Input).value.strip()
        if path_input:
            p = Path(path_input).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        out = resolve_path("output_dir") / self._channel
        out.mkdir(parents=True, exist_ok=True)
        return out

    def _get_format(self) -> OutputFormat:
        """Get the selected output format."""
        fmt = self.query_one("#format-select", Select).value
        return OutputFormat(fmt)

    def _get_incremental(self) -> bool:
        """Check if incremental mode is selected."""
        return self.query_one("#incremental-select", Select).value == "true"

    @work(exclusive=True)
    async def action_export(self) -> None:
        """Export messages in the selected format."""
        if self.export_in_progress or not self._messages:
            return

        self.export_in_progress = True
        log = self.query_one("#export-log", CopyableRichLog)
        log.clear()
        log.write("💾 Starting export...")

        output_path = self._get_output_path()
        fmt = self._get_format()
        incremental = self._get_incremental()

        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if incremental:
                saved_count = save_messages_incremental(
                    messages=self._messages,
                    channel=self._channel,
                    output_dir=output_path.parent,
                    fmt=fmt,
                )
            else:
                saved_count = save_messages(
                    messages=self._messages,
                    channel=self._channel,
                    output_dir=output_path.parent,
                    fmt=fmt,
                )

            log.write(f"✅ Exported {saved_count} messages to {output_path}")
            log.write(
                f"   Format: {fmt.value.upper()}, Incremental: {incremental}"
            )
            self.query_one("#status-message", Static).update(
                f"✅ Exported {saved_count} messages to {output_path}"
            )

        except Exception as exc:
            logger.exception("Export failed")
            log.write(f"❌ Export error: {exc}")
            self.query_one("#status-message", Static).update(
                f"❌ Export failed: {exc}"
            )

        self.export_in_progress = False

    def action_export_json(self) -> None:
        """Quick export as JSON."""
        self.query_one("#format-select", Select).value = "json"
        self.action_export()

    def action_export_csv(self) -> None:
        """Quick export as CSV."""
        self.query_one("#format-select", Select).value = "csv"
        self.action_export()

    def action_export_txt(self) -> None:
        """Quick export as TXT."""
        self.query_one("#format-select", Select).value = "txt"
        self.action_export()

    def action_export_sqlite(self) -> None:
        """Quick export as SQLite."""
        self.query_one("#format-select", Select).value = "sqlite"
        self.action_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        btn_id = event.button.id
        if btn_id == "btn-export":
            self.action_export()
        elif btn_id == "btn-refresh":
            self._load_messages()
        elif btn_id == "btn-back" or btn_id == "btn-back-header":
            self.action_go_back()

    def action_go_back(self) -> None:
        """Go back to the main screen."""
        self.dismiss(False)
