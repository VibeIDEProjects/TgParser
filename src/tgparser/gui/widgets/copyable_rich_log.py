"""A RichLog that keeps a copy of its text for easy clipboard access."""

from textual.widgets import RichLog


class CopyableRichLog(RichLog):
    """A RichLog that stores all written lines in a list for later retrieval."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._log_lines: list[str] = []

    def write(self, text: str) -> None:
        """Write text to the log and store it in the internal buffer."""
        super().write(text)
        self._log_lines.append(text)

    def clear(self) -> None:
        """Clear the log and the internal buffer."""
        super().clear()
        self._log_lines.clear()

    def copy_text(self) -> str:
        """Return all logged text as a single string."""
        return "\n".join(self._log_lines)
