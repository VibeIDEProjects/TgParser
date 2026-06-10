"""File browser + preview screen.

Layout:  ``DirectoryTree`` on the **left**, file preview on the
**right**.  The preview is format-aware:

* ``.md``/``.markdown``  -> rendered Markdown
* ``.json``              -> syntax-highlighted JSON
* ``.csv``               -> ``DataTable``
* ``.txt``/``.log`` etc. -> monospaced text
* images                 -> metadata placeholder
* anything else          -> hex preview of the first chunk
"""

from __future__ import annotations

import csv
import json
import mimetypes
from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    DataTable,
    DirectoryTree,
    Footer,
    Header,
    Markdown,
    Static,
)

from tgparser.config import resolve_path


_MARKDOWN_EXT = {".md", ".markdown"}
_JSON_EXT = {".json"}
_CSV_EXT = {".csv"}
_TEXT_EXT = {
    ".txt", ".log", ".py", ".js", ".ts", ".html", ".css",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".sh",
}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".svg"}

_PREVIEW_LIMIT = 200_000  # bytes; load at most this much into the UI


class FilesScreen(Screen[None]):
    """Browse the output directory and preview the selected file."""

    BINDINGS: list[Binding] = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("ctrl+r", "refresh_tree", "Refresh"),
    ]

    DEFAULT_CSS = """
    FilesScreen {
        layout: vertical;
    }
    #files-body {
        layout: horizontal;
        width: 100%;
        height: 1fr;
    }
    #file-tree {
        width: 35%;
        min-width: 25;
        border: round $primary;
    }
    #preview {
        width: 1fr;
        height: 1fr;
        border: round $secondary;
        padding: 1 2;
        layout: vertical;
    }
    #preview-title {
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
        height: auto;
    }
    #preview-body {
        width: 100%;
        height: 1fr;
        padding: 0 1;
    }
    #preview-body > Static {
        width: 100%;
        height: auto;
    }
    #preview-body > Markdown {
        width: 100%;
        height: auto;
    }
    #preview-body > DataTable {
        width: 100%;
        height: 1fr;
    }
    #status-line {
        dock: bottom;
        height: 1;
        background: $boost;
        color: $text;
        padding: 0 2;
    }
    """

    def __init__(self, root: Path | None = None) -> None:
        super().__init__(id="files-screen")
        self._root = root or resolve_path("output_dir")
        self._current_file: Path | None = None

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="files-body"):
            yield DirectoryTree(str(self._root), id="file-tree")
            with Vertical(id="preview"):
                yield Static("Select a file from the tree", id="preview-title")
                # Persistent container whose children are swapped on
                # every selection.  Holding a *static* id on the
                # container (and never on its children) avoids the
                # "DuplicateIds" issue we saw earlier.
                yield VerticalScroll(
                    Static(
                        "Choose any file to see its contents.",
                        id="preview-placeholder",
                    ),
                    id="preview-body",
                )
        yield Static("", id="status-line")
        yield Footer()

    def on_mount(self) -> None:
        if not self._root.exists():
            self.query_one("#status-line", Static).update(
                f"\u26a0\ufe0f Output directory not found: {self._root}"
            )

    # ------------------------------------------------------------------
    # Tree selection -> preview
    # ------------------------------------------------------------------
    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        path = Path(str(event.path))
        if path.is_dir():
            return  # We only preview files.
        self._current_file = path
        self._render_preview(path)

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render_preview(self, path: Path) -> None:
        title = self.query_one("#preview-title", Static)
        body = self.query_one("#preview-body", VerticalScroll)
        # Remove every child currently inside the body container.
        for child in list(body.children):
            child.remove()

        try:
            size = path.stat().st_size
        except OSError as exc:
            title.update(f"\u26a0\ufe0f {path.name}")
            body.mount(Static(f"Cannot stat file: {exc}"))
            return

        ext = path.suffix.lower()
        title.update(
            f"\U0001f4c4 {path.name}  \u00b7  {self._human_size(size)}"
        )
        self._set_status(f"Previewing {path}")

        if ext in _MARKDOWN_EXT:
            self._render_markdown(body, path, size)
        elif ext in _JSON_EXT:
            self._render_json(body, path, size)
        elif ext in _CSV_EXT:
            self._render_csv(body, path, size)
        elif ext in _IMAGE_EXT:
            self._render_image(body, path, size)
        elif ext in _TEXT_EXT or self._looks_like_text(path):
            self._render_text(body, path, size)
        else:
            self._render_hex(body, path, size)

    # -- per-format previews -------------------------------------------
    def _render_markdown(self, body: VerticalScroll, path: Path, size: int) -> None:
        try:
            text = self._read_limited(path)
        except OSError as exc:
            body.mount(Static(f"Cannot read: {exc}"))
            return
        try:
            body.mount(Markdown(text))
        except Exception as exc:  # noqa: BLE001
            body.mount(Static(f"Markdown render failed: {exc}"))

    def _render_json(self, body: VerticalScroll, path: Path, size: int) -> None:
        try:
            raw = self._read_limited(path)
            data = json.loads(raw)
            pretty = json.dumps(data, indent=2, ensure_ascii=False)
        except (OSError, ValueError) as exc:
            body.mount(Static(f"Cannot read JSON: {exc}"))
            return
        # Wrap a Rich Syntax renderable in a Textual ``Static``
        # widget.  ``Static`` accepts a Rich renderable via its
        # ``renderable`` kwarg, which gives us colour-highlighted
        # JSON without leaving the widget tree.
        try:
            from rich.syntax import Syntax
            renderable = Syntax(
                pretty, "json", theme="monokai",
                word_wrap=False, indent_guides=True,
            )
            body.mount(Static(renderable))
        except Exception:  # noqa: BLE001
            body.mount(Static(pretty))

    def _render_csv(self, body: VerticalScroll, path: Path, size: int) -> None:
        try:
            with path.open("r", encoding="utf-8", newline="") as f:
                rows = list(csv.reader(f))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            body.mount(Static(f"Cannot read CSV: {exc}"))
            return
        if not rows:
            body.mount(Static("(empty CSV)"))
            return
        table: DataTable = DataTable(zebra_stripes=True)
        table.add_columns(*rows[0])
        for row in rows[1:50]:
            table.add_row(*row)
        body.mount(table)

    def _render_image(self, body: VerticalScroll, path: Path, size: int) -> None:
        mime, _ = mimetypes.guess_type(str(path))
        body.mount(
            Static(
                f"Image preview is not available in this Textual build.\n\n"
                f"  Path: {path}\n"
                f"  Type: {mime or path.suffix.lstrip('.').upper()}\n"
                f"  Size: {self._human_size(size)}\n\n"
                f"Open the file in your system's image viewer to see it."
            )
        )

    def _render_text(self, body: VerticalScroll, path: Path, size: int) -> None:
        try:
            text = self._read_limited(path)
        except (OSError, UnicodeDecodeError) as exc:
            self._render_hex(body, path, size)
            return
        truncated = (
            f"\n\n[... truncated at {self._human_size(_PREVIEW_LIMIT)} ...]"
            if size > _PREVIEW_LIMIT else ""
        )
        body.mount(Static(text + truncated))

    def _render_hex(self, body: VerticalScroll, path: Path, size: int) -> None:
        try:
            with path.open("rb") as f:
                chunk = f.read(_PREVIEW_LIMIT)
        except OSError as exc:
            body.mount(Static(f"Cannot read: {exc}"))
            return
        lines: list[str] = []
        for offset in range(0, min(len(chunk), 4096), 16):
            block = chunk[offset:offset + 16]
            hex_part = " ".join(f"{b:02x}" for b in block)
            ascii_part = "".join(
                chr(b) if 32 <= b < 127 else "." for b in block
            )
            lines.append(f"{offset:08x}  {hex_part:<47}  {ascii_part}")
        note = (
            f"\n[... only first "
            f"{self._human_size(len(chunk))} of {self._human_size(size)} shown ...]"
        )
        body.mount(Static("\n".join(lines) + note))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _read_limited(self, path: Path) -> str:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return f.read(_PREVIEW_LIMIT)

    @staticmethod
    def _human_size(n: int) -> str:
        units = ("B", "KB", "MB", "GB", "TB")
        size = float(n)
        for unit in units:
            if size < 1024.0:
                return f"{size:,.1f} {unit}"
            size /= 1024.0
        return f"{size:,.1f} PB"

    def _looks_like_text(self, path: Path) -> bool:
        try:
            with path.open("rb") as f:
                sample = f.read(2048)
        except OSError:
            return False
        if not sample:
            return True
        text_chars = sum(
            1 for b in sample
            if b in (9, 10, 13) or 32 <= b < 127 or b >= 0xC0
        )
        return text_chars / len(sample) > 0.85

    def _set_status(self, text: str) -> None:
        try:
            self.query_one("#status-line", Static).update(text)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def action_refresh_tree(self) -> None:
        tree = self.query_one(DirectoryTree)
        tree.reload()
        self._set_status("\u2705 Tree refreshed")
