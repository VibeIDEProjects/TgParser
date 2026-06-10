"""End-to-end test: does Textual actually deliver '#' to an Input?

We use ``pilot.press`` which goes through the real driver path.
If the Input receives ``#`` here, the bug is in the console/terminal,
not in Textual itself.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App, ComposeResult
from textual.widgets import Input


class ProbeApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.received: list[str] = []

    def compose(self) -> ComposeResult:
        yield Input(id="probe", value="")

    def on_key(self, event) -> None:  # type: ignore[no-untyped-def]
        self.received.append(
            f"key={event.key!r} char={event.character!r} printable={event.is_printable}"
        )


async def test_hash_via_pilot_press() -> None:
    """``pilot.press('#')`` must reach the Input."""
    app = ProbeApp()
    async with app.run_test() as pilot:
        probe = app.query_one("#probe", Input)
        probe.focus()
        await pilot.press("#")
        await pilot.pause()
        assert probe.value == "#", (
            f"Expected '#' in value, got {probe.value!r}.\n"
            f"Received key events: {app.received}"
        )


async def test_hash_via_paste() -> None:
    """Paste event containing '#' must be inserted verbatim."""
    from textual.events import Paste

    app = ProbeApp()
    async with app.run_test() as pilot:
        probe = app.query_one("#probe", Input)
        probe.focus()
        url = "https://web.telegram.org/a/#-1003929682471"
        probe.post_message(Paste(url))
        await pilot.pause()
        assert probe.value == url, (
            f"Expected {url!r}, got {probe.value!r}"
        )
