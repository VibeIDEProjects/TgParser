"""Unit tests for ``tgparser.utils``."""

from __future__ import annotations

from tgparser.utils import sanitize_dir_name


class TestSanitizeDirName:
    def test_keeps_plain_username(self) -> None:
        assert sanitize_dir_name("@durov") == "@durov"

    def test_keeps_plain_id(self) -> None:
        assert sanitize_dir_name("-1003929682471") == "-1003929682471"

    def test_strips_scheme_and_replaces_slashes(self) -> None:
        out = sanitize_dir_name("https://web.telegram.org/a/-1003929682471")
        assert out == "web.telegram.org_a_-1003929682471"
        # No forbidden characters
        for ch in '<>:"/\\|?*':
            assert ch not in out

    def test_replaces_hash_with_dash(self) -> None:
        out = sanitize_dir_name("https://web.telegram.org/a/#-1003929682471")
        # Slashes turn into underscores, the "#" itself turns into "-".
        # Between them we get "a_#" -> "a_-" after collapse.
        assert out == "web.telegram.org_a_--1003929682471"
        assert "#" not in out

    def test_handles_k_frontend(self) -> None:
        out = sanitize_dir_name("https://web.telegram.org/k/-100123")
        assert out == "web.telegram.org_k_-100123"

    def test_handles_beta_frontend(self) -> None:
        out = sanitize_dir_name("https://web.telegram.org/beta/-100123")
        assert out == "web.telegram.org_beta_-100123"

    def test_replaces_backslashes(self) -> None:
        out = sanitize_dir_name("a\\b\\c")
        assert out == "a_b_c"
        assert "\\" not in out

    def test_replaces_colon_in_non_url(self) -> None:
        out = sanitize_dir_name("12:30:45")
        # colons forbidden in Windows paths
        assert ":" not in out
        assert out == "12_30_45"

    def test_replaces_other_windows_forbidden(self) -> None:
        out = sanitize_dir_name("a<b>c|d?e*f\"g")
        for ch in '<>"|?*':
            assert ch not in out

    def test_strips_control_chars(self) -> None:
        out = sanitize_dir_name("foo\x00bar\x1fbaz")
        for i in range(0x20):
            assert chr(i) not in out

    def test_collapses_repeated_underscores(self) -> None:
        out = sanitize_dir_name("a___b")
        assert out == "a_b"

    def test_strips_trailing_spaces_and_dots(self) -> None:
        out = sanitize_dir_name("foo.  ")
        assert out == "foo"
        out = sanitize_dir_name("bar..")
        assert out == "bar"

    def test_truncates_long_names(self) -> None:
        long = "a" * 250
        out = sanitize_dir_name(long, max_length=80)
        assert len(out) <= 80

    def test_empty_returns_fallback(self) -> None:
        assert sanitize_dir_name("") == "untitled"

    def test_only_forbidden_returns_fallback(self) -> None:
        assert sanitize_dir_name("////") == "untitled"

    def test_only_dots_returns_fallback(self) -> None:
        # ``..`` is path-traversal; we should not produce it as a folder name
        assert sanitize_dir_name("..") == "untitled"
        assert sanitize_dir_name("...") == "untitled"
