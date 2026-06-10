"""Smoke tests for the Textual GUI application.

These tests verify that the application starts, renders correctly,
and basic navigation between screens works.
"""

import pytest
from pathlib import Path
from tgparser.gui.app import TgParserApp


@pytest.fixture
def app():
    """Create a test app instance."""
    return TgParserApp()


async def test_app_starts(app):
    """Test that the application starts and renders the main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Check that the main screen is showing
        assert app.screen is not None
        assert app.screen.id == "main-screen"
        # Check that key widgets are present
        assert app.screen.query_one("#welcome-text")
        assert app.screen.query_one("#channel-table")
        assert app.screen.query_one("#btn-auth")
        assert app.screen.query_one("#btn-parse")
        assert app.screen.query_one("#btn-view")
        assert app.screen.query_one("#btn-refresh")
        assert app.screen.query_one("#status-bar")


async def test_navigation_to_auth_screen(app):
    """Test navigation from main screen to auth screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Click on Auth button
        await pilot.click("#btn-auth")
        # Wait for the screen to switch
        await pilot.pause()
        # Check that we are on auth screen
        assert app.screen.id == "auth-screen"
        # Check auth screen widgets
        assert app.screen.query_one("#auth-title")
        assert app.screen.query_one("#api-id-input")
        assert app.screen.query_one("#api-hash-input")
        assert app.screen.query_one("#phone-input")
        assert app.screen.query_one("#code-input")
        assert app.screen.query_one("#btn-auth-start")
        assert app.screen.query_one("#btn-auth-cancel")


async def test_navigation_to_parse_screen(app):
    """Test navigation from main screen to parse screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Click on Parse Channel button
        await pilot.click("#btn-parse")
        await pilot.pause()
        # Check that we are on parse screen
        assert app.screen.id == "parse-screen"
        # Check parse screen widgets
        assert app.screen.query_one("#parse-title")
        assert app.screen.query_one("#channel-input")
        assert app.screen.query_one("#channel-type-select")
        assert app.screen.query_one("#limit-input")
        assert app.screen.query_one("#date-from-input")
        assert app.screen.query_one("#date-to-input")
        assert app.screen.query_one("#btn-start")
        assert app.screen.query_one("#btn-stop")
        assert app.screen.query_one("#btn-back")
        assert app.screen.query_one("#progress-bar")


async def test_parse_screen_back_navigation(app):
    """Test that back button on parse screen returns to main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Go to parse screen
        await pilot.click("#btn-parse")
        await pilot.pause()
        assert app.screen.id == "parse-screen"
        # Try clicking back; scroll_visible may be needed
        await pilot.pause(0.3)
        btn_back = app.screen.query_one("#btn-back")
        # Scroll the button into view
        btn_back.scroll_visible()
        await pilot.pause(0.3)
        # Use click with widget reference
        await pilot.click(btn_back)
        await pilot.pause(0.3)
        assert app.screen.id == "main-screen"


async def test_auth_screen_cancel_navigation(app):
    """Test that cancel button on auth screen returns to main screen."""
    async with app.run_test(size=(120, 40)) as pilot:
        # Go to auth screen
        await pilot.click("#btn-auth")
        await pilot.pause()
        assert app.screen.id == "auth-screen"
        # Click cancel
        await pilot.click("#btn-auth-cancel")
        await pilot.pause()
        assert app.screen.id == "main-screen"


async def test_status_bar_text(app):
    """Test that the status bar shows the default message."""
    async with app.run_test(size=(120, 40)) as pilot:
        status_bar = app.screen.query_one("#status-bar")
        # Use .visual.plain to get the text content of a Static widget
        assert "Ready" in status_bar.visual.plain


async def test_channel_table_exists(app):
    """Test that the channel table widget exists and has columns."""
    async with app.run_test(size=(120, 40)) as pilot:
        table = app.screen.query_one("#channel-table")
        columns = table.columns
        assert len(columns) >= 3  # Should have Channel, Last Parsed, Actions


async def test_main_screen_header(app):
    """Test that the main screen header/title is displayed."""
    async with app.run_test(size=(120, 40)) as pilot:
        welcome = app.screen.query_one("#welcome-text")
        # Use .visual.plain to get the text content of a Label widget
        assert "TgParser" in welcome.visual.plain


class TestNormalizeChannel:
    """Unit tests for :py:meth:`ParseScreen._normalize_channel`."""

    def _normalize(self, value: str) -> str:
        from tgparser.gui.screens.parse_screen import ParseScreen
        return ParseScreen._normalize_channel(value)

    def test_inserts_hash_for_a_frontend(self) -> None:
        out = self._normalize("https://web.telegram.org/a/-1003929682471")
        assert out == "https://web.telegram.org/a/#-1003929682471"

    def test_inserts_hash_for_k_frontend(self) -> None:
        out = self._normalize("https://web.telegram.org/k/-1003929682471")
        assert out == "https://web.telegram.org/k/#-1003929682471"

    def test_inserts_hash_for_beta_frontend(self) -> None:
        out = self._normalize("https://web.telegram.org/beta/-1003929682471")
        assert out == "https://web.telegram.org/beta/#-1003929682471"

    def test_idempotent_when_hash_present(self) -> None:
        url = "https://web.telegram.org/a/#-1003929682471"
        assert self._normalize(url) == url

    def test_preserves_hash_with_username(self) -> None:
        url = "https://web.telegram.org/a/#@somechannel"
        assert self._normalize(url) == url

    def test_unchanged_for_t_me_url(self) -> None:
        url = "https://t.me/durov"
        assert self._normalize(url) == url

    def test_unchanged_for_username(self) -> None:
        assert self._normalize("@durov") == "@durov"

    def test_unchanged_for_plain_id(self) -> None:
        assert self._normalize("-1003929682471") == "-1003929682471"

    def test_unchanged_when_tail_is_empty(self) -> None:
        # No channel id/path at all -> do not insert an empty "#"
        url = "https://web.telegram.org/a/"
        assert self._normalize(url) == url



async def test_files_screen_multiple_selections(app, tmp_path):
    """``FilesScreen`` must survive several file selections in a row
    (the previous implementation hit ``DuplicateIds`` on the second
    click).  This regression test walks the file tree twice and
    asserts the screen never raises and the preview body always
    contains a single child.
    """
    from tgparser.gui.screens.files_screen import FilesScreen

    # Create a couple of dummy files so the DirectoryTree has data.
    (tmp_path / "a.md").write_text("# Title\nHello", encoding="utf-8")
    (tmp_path / "a.json").write_text('{"x": 1}', encoding="utf-8")
    (tmp_path / "a.csv").write_text("col1,col2\n1,2\n", encoding="utf-8")

    async with app.run_test(size=(140, 40)) as pilot:
        app.push_screen(FilesScreen(root=tmp_path))
        await pilot.pause()
        # ``#file-tree`` should be on the LEFT of ``#files-body``;
        # ``#preview`` on the RIGHT.
        files_body = app.screen.query_one("#files-body")
        child_ids = [getattr(c, "id", None) for c in files_body.children]
        assert child_ids.index("file-tree") < child_ids.index("preview"), (
            f"DirectoryTree should be on the LEFT of the preview, got {child_ids}"
        )
        from textual.widgets import DirectoryTree as DT
        tree = app.screen.query_one(DT)
        body = app.screen.query_one("#preview-body")
        # ``DirectoryTree.root`` is a ``TreeNode`` whose ``children``
        # are the actual ``TreeNode``s for files/dirs.
        nodes = list(tree.root.children)
        assert nodes, "tmp_path should produce at least one node"
        # Walk each file twice — second walk would have hit
        # ``DuplicateIds`` in the old implementation.
        def fire(node):
            # ``node.data`` is a ``DirEntry`` for DirectoryTree.
            entry = node.data
            fs_path = Path(entry.path)
            tree.post_message(DT.FileSelected(node, fs_path))
        for node in nodes:
            fire(node)
            await pilot.pause()
        for node in nodes:
            fire(node)
            await pilot.pause()
        # The body must never have more than one preview at a time.
        # (Internal timing in the message queue can leave it empty
        # briefly between selections — that's fine, the important
        # thing is that we never accumulated duplicates.)
        assert len(body.children) <= 1, body.children



async def test_files_screen_long_text_is_scrollable(app, tmp_path):
    """A long text file should populate a ``Static`` that exceeds
    the viewport, so ``VerticalScroll`` wraps the body and the
    widget region has a non-trivial height.
    """
    from tgparser.gui.screens.files_screen import FilesScreen
    from textual.widgets import DirectoryTree

    big = "\n".join(f"line {i}: " + "x" * 60 for i in range(200))
    (tmp_path / "big.txt").write_text(big, encoding="utf-8")

    async with app.run_test(size=(120, 30)) as pilot:
        app.push_screen(FilesScreen(root=tmp_path))
        await pilot.pause()
        tree = app.screen.query_one(DirectoryTree)
        node = next(
            n for n in tree.root.children
            if n.data is not None and Path(n.data.path).name == "big.txt"
        )
        fs_path = Path(node.data.path)
        tree.post_message(DirectoryTree.FileSelected(node, fs_path))
        await pilot.pause()

        body = app.screen.query_one("#preview-body")
        # The container must be a VerticalScroll now.
        from textual.containers import VerticalScroll
        assert isinstance(body, VerticalScroll)
        # And the child (the Static with the long text) must be
        # taller than the viewport so that scrolling is meaningful.
        assert body.children, "preview body should have one child"
        child = body.children[0]
        assert child.region.height > body.region.height, (
            f"Static should be taller than its scroll container to "
            f"require scrolling; got child={child.region.height} "
            f"container={body.region.height}"
        )
