"""Integration tests for WebAuth — mocked Playwright interaction."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tgparser.auth.web_auth import WebAuth


@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def web_auth(tmp_session_dir: Path) -> WebAuth:
    return WebAuth(session_dir=tmp_session_dir, headless=False, slow_mo=0)


class TestSessionPersistence:
    """Session file read/write tests — no browser needed."""

    def test_load_session_none_when_no_file(self, web_auth: WebAuth) -> None:
        assert web_auth.load_session() is None

    def test_is_session_valid_false_when_no_file(self, web_auth: WebAuth) -> None:
        assert not web_auth.is_session_valid()

    def test_load_session_returns_data(self, web_auth: WebAuth) -> None:
        session_data = {
            "cookies": [{"name": "stel_ssid", "value": "abc123", "domain": ".telegram.org"}],
            "local_storage": {"dc": "2"},
            "saved_at": 1234567890.0,
        }
        web_auth.session_file.write_text(json.dumps(session_data), encoding="utf-8")
        loaded = web_auth.load_session()
        assert loaded is not None
        assert len(loaded["cookies"]) == 1
        assert loaded["local_storage"]["dc"] == "2"

    def test_load_session_handles_corrupted_file(self, web_auth: WebAuth) -> None:
        web_auth.session_file.write_text("not valid json {{{", encoding="utf-8")
        assert web_auth.load_session() is None


class TestLoginFlow:
    """Tests for the login() orchestration — mocked Playwright."""

    @patch("tgparser.auth.web_auth.sync_playwright")
    def test_login_skips_when_session_valid(self, mock_pw: MagicMock, web_auth: WebAuth) -> None:
        session_data = {
            "cookies": [{"name": "x", "value": "y"}],
            "local_storage": {},
            "saved_at": 1,
        }
        web_auth.session_file.write_text(json.dumps(session_data), encoding="utf-8")

        result = web_auth.login()
        assert result is True
        mock_pw.assert_not_called()

    @patch("tgparser.auth.web_auth.sync_playwright")
    def test_login_force_browser_even_with_session(
        self, mock_pw: MagicMock, web_auth: WebAuth
    ) -> None:
        session_data = {
            "cookies": [{"name": "x", "value": "y"}],
            "local_storage": {},
            "saved_at": 1,
        }
        web_auth.session_file.write_text(json.dumps(session_data), encoding="utf-8")

        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "stel_ssid", "value": "test"}
        ]
        mock_page.evaluate.return_value = {}  # localStorage extraction → empty dict
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw.return_value.start.return_value = mock_pw_instance

        result = web_auth.login(force=True)
        assert result is True
        mock_pw.assert_called_once()

    @patch("tgparser.auth.web_auth.sync_playwright")
    def test_login_success_path(self, mock_pw: MagicMock, web_auth: WebAuth) -> None:
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_context.cookies.return_value = [
            {"name": "stel_ssid", "value": "test"}
        ]
        mock_page.evaluate.return_value = {}  # localStorage extraction → empty dict
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw.return_value.start.return_value = mock_pw_instance

        result = web_auth.login()
        assert result is True
        assert web_auth.is_session_valid()

        mock_page.goto.assert_any_call(
            "https://web.telegram.org/k/", wait_until="domcontentloaded"
        )
        mock_browser.close.assert_called_once()
        mock_pw_instance.stop.assert_called_once()

    @patch("tgparser.auth.web_auth.sync_playwright")
    def test_login_timeout_returns_false(
        self, mock_pw: MagicMock, web_auth: WebAuth
    ) -> None:
        from playwright.sync_api import TimeoutError as PwTimeout

        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_context.pages = [mock_page]
        mock_browser.new_context.return_value = mock_context
        mock_context.new_page.return_value = mock_page
        mock_page.wait_for_selector.side_effect = PwTimeout(
            "Timeout 120000ms exceeded"
        )

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium.launch.return_value = mock_browser
        mock_pw.return_value.start.return_value = mock_pw_instance

        result = web_auth.login()
        assert result is False
        mock_browser.close.assert_called_once()


class TestRestoreSession:
    """Tests for restore_session() with mocked context."""

    def test_restore_session_no_file(self, web_auth: WebAuth) -> None:
        mock_context = MagicMock()
        result = web_auth.restore_session(mock_context)
        assert result is False
        mock_context.add_cookies.assert_not_called()

    def test_restore_session_adds_cookies(self, web_auth: WebAuth) -> None:
        session_data = {
            "cookies": [
                {
                    "name": "stel_ssid",
                    "value": "abc",
                    "domain": ".telegram.org",
                }
            ],
            "local_storage": {},
            "saved_at": 1,
        }
        web_auth.session_file.write_text(json.dumps(session_data), encoding="utf-8")

        mock_context = MagicMock()
        result = web_auth.restore_session(mock_context)
        assert result is True
        mock_context.add_cookies.assert_called_once_with(session_data["cookies"])

    def test_restore_session_empty_cookies(self, web_auth: WebAuth) -> None:
        session_data = {"cookies": [], "local_storage": {}, "saved_at": 1}
        web_auth.session_file.write_text(json.dumps(session_data), encoding="utf-8")

        mock_context = MagicMock()
        result = web_auth.restore_session(mock_context)
        assert result is False
