"""Modal screen for previewing exported messages.

Supports two rendering modes:

* **Markdown** — when the file ends with ``.md``/``.markdown`` or the format
  is ``"md"``/``"markdown"``.  Uses :class:`textual.widgets.Markdown`
  inside a :class:`VerticalScroll` so the user can browse long histories
  with PageUp/PageDown/arrow keys/mouse wheel.
* **Plain text** — for ``.json``/``.csv``/``.txt``.  Renders the file
  verbatim inside a :class:`Static` widget wrapped in
  :class:`VerticalScroll`.

Usage from the parent screen::

    self.app.push_screen(
        PreviewScreen(file_path=Path("..."), fmt="md"),
    )
"""
from __future__ import annotations

import logging
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

logger = logging.getLogger("tgparser")


_MD_SUFFIXES = {".md", ".markdown"}
_MD_FORMATS = {"md", "markdown"}


class PreviewScreen(ModalScreen[None]):
    """Read-only preview of an exported file with keyboard navigation."""

    BINDINGS: list[Binding] = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
        Binding("home", "scroll_home", "Top"),
        Binding("end", "scroll_end", "Bottom"),
        Binding("pagedown", "scroll_pagedown", "Page Down"),
        Binding("pageup", "scroll_pageup", "Page Up"),
    ]

    DEFAULT_CSS = """
    PreviewScreen {
        align: center middle;
    }

    #preview-container {
        width: 95%;
        height: 95%;
        background: $surface;
        border: thick $primary;
        padding: 1;
    }

    #preview-header {
        height: 3;
        margin-bottom: 1;
    }

    #preview-title {
        width: 1fr;
        content-align: left middle;
        text-style: bold;
    }

    #preview-body {
        height: 1fr;
        border: solid $primary;
    }

    #preview-static {
        padding: 1 2;
    }

    #preview-footer {
        height: 3;
        margin-top: 1;
        align-horizontal: right;
    }

    #preview-footer Button {
        min-width: 16;
        min-height: 3;
    }
    """

    def __init__(
        self,
        file_path: Path,
        fmt: str = "",
        name: str | None = None,
        id: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id)
        self._file_path = Path(file_path)
        self._fmt = fmt

    # ----- compose --------------------------------------------------------

    def compose(self) -> ComposeResult:
        with Vertical(id="preview-container"):
            with Horizontal(id="preview-header"):
                yield Static(
                    f"[bold]\U0001f4d6 Preview:[/] {self._file_path.name}",
                    id="preview-title",
                )
                yield Button("\u2715 Close", id="btn-preview-close", variant="error")

            with VerticalScroll(id="preview-body"):
                if self._is_markdown():
                    # Markdown() will display the file directly.
                    yield Markdown()
                else:
                    yield Static(self._read_text(), id="preview-static")

            with Horizontal(id="preview-footer"):
                yield Static(
                    "[dim]Esc/q: close \u2022 PgUp/PgDn: scroll \u2022 Home/End: jump[/]",
                    id="preview-hint",
                )

    # ----- lifecycle ------------------------------------------------------

    def on_mount(self) -> None:
        if self._is_markdown():
            md = self.query_one(Markdown)
            try:
                md.document.update(self._read_text())
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Failed to render markdown preview: %s", exc)
        self.query_one("#preview-body", VerticalScroll).focus()

    # ----- helpers --------------------------------------------------------

    def _is_markdown(self) -> bool:
        if self._fmt.lower() in _MD_FORMATS:
            return True
        return self._file_path.suffix.lower() in _MD_SUFFIXES

    def _read_text(self) -> str:
        try:
            return self._file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"[red]Failed to read {self._file_path}:[/] {exc}"

    # ----- actions --------------------------------------------------------

    def action_close(self) -> None:
        self.dismiss(None)

    def action_scroll_home(self) -> None:
        self.query_one("#preview-body", VerticalScroll).scroll_home(animate=False)

    def action_scroll_end(self) -> None:
        self.query_one("#preview-body", VerticalScroll).scroll_end(animate=False)

    def action_scroll_pagedown(self) -> None:
        self.query_one("#preview-body", VerticalScroll).scroll_page_down(animate=False)

    def action_scroll_pageup(self) -> None:
        self.query_one("#preview-body", VerticalScroll).scroll_page_up(animate=False)

    # ----- events ---------------------------------------------------------

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-preview-close":
            self.action_close()
