"""Unit tests for MTProtoAuth — mocked Telethon."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tgparser.auth.mtproto_auth import MTProtoAuth


@pytest.fixture
def tmp_session_dir(tmp_path: Path) -> Path:
    return tmp_path / "sessions"


@pytest.fixture
def mtproto_auth(tmp_session_dir: Path) -> MTProtoAuth:
    return MTProtoAuth(
        api_id=12345,
        api_hash="abcde12345",
        phone="+79001234567",
        session_dir=tmp_session_dir,
    )


class TestInit:
    """Constructor and credential validation."""

    def test_raises_without_credentials(self, tmp_session_dir: Path) -> None:
        with patch("tgparser.auth.mtproto_auth.get_secret", return_value=None):
            with pytest.raises(ValueError, match="MTProto credentials missing"):
                MTProtoAuth(session_dir=tmp_session_dir)

    def test_creates_session_dir(self, mtproto_auth: MTProtoAuth, tmp_session_dir: Path) -> None:
        assert tmp_session_dir.exists()


class TestSessionValidity:
    """Session existence and validity checks."""

    def test_is_session_valid_false_when_no_file(self, mtproto_auth: MTProtoAuth) -> None:
        assert not mtproto_auth.is_session_valid()

    def test_is_session_valid_true_when_authorized(
        self, mtproto_auth: MTProtoAuth
    ) -> None:
        # Create empty session file first
        mtproto_auth.session_file.write_text("")

        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = True

        with patch(
            "tgparser.auth.mtproto_auth.TelegramClient",
            return_value=mock_client,
        ):
            assert mtproto_auth.is_session_valid()
            mock_client.connect.assert_called_once()
            mock_client.disconnect.assert_called_once()

    def test_is_session_valid_false_when_not_authorized(
        self, mtproto_auth: MTProtoAuth
    ) -> None:
        mtproto_auth.session_file.write_text("")

        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = False

        with patch(
            "tgparser.auth.mtproto_auth.TelegramClient",
            return_value=mock_client,
        ):
            assert not mtproto_auth.is_session_valid()

    def test_is_session_valid_false_on_connection_error(
        self, mtproto_auth: MTProtoAuth
    ) -> None:
        mtproto_auth.session_file.write_text("")

        with patch(
            "tgparser.auth.mtproto_auth.TelegramClient",
            side_effect=ConnectionError("No network"),
        ):
            assert not mtproto_auth.is_session_valid()


class TestLoginFlow:
    """Login orchestration — mocked Telethon."""

    @patch("tgparser.auth.mtproto_auth.TelegramClient")
    def test_login_reuses_valid_session(
        self, mock_tc: MagicMock, mtproto_auth: MTProtoAuth
    ) -> None:
        mtproto_auth.session_file.write_text("")

        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = True
        mock_tc.return_value = mock_client

        result = mtproto_auth.login()
        # connect() called during is_session_valid() + login() = 2 times
        assert mock_client.connect.call_count >= 1
        # Should NOT send code
        mock_client.send_code_request.assert_not_called()
        assert result is mock_client

    @patch("tgparser.auth.mtproto_auth.TelegramClient")
    def test_login_forces_new_auth(
        self, mock_tc: MagicMock, mtproto_auth: MTProtoAuth
    ) -> None:
        mtproto_auth.session_file.write_text("")

        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = False
        mock_tc.return_value = mock_client

        # Patch prompts to avoid blocking
        with patch.object(mtproto_auth, "_prompt_code", return_value="12345"):
            result = mtproto_auth.login(force=True)
            mock_client.send_code_request.assert_called_once()
            mock_client.sign_in.assert_called_once_with(
                mtproto_auth.phone, "12345"
            )
            assert result is mock_client

    @patch("tgparser.auth.mtproto_auth.TelegramClient")
    def test_login_first_time(
        self, mock_tc: MagicMock, mtproto_auth: MTProtoAuth
    ) -> None:
        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = False
        mock_tc.return_value = mock_client

        with patch.object(mtproto_auth, "_prompt_code", return_value="67890"):
            result = mtproto_auth.login()
            mock_client.send_code_request.assert_called_once_with(
                mtproto_auth.phone
            )
            mock_client.sign_in.assert_called_once_with(
                mtproto_auth.phone, "67890"
            )
            assert result is mock_client

    @patch("tgparser.auth.mtproto_auth.TelegramClient")
    def test_login_with_2fa(
        self, mock_tc: MagicMock, mtproto_auth: MTProtoAuth
    ) -> None:
        from telethon.errors.rpcerrorlist import SessionPasswordNeededError

        mock_client = MagicMock()
        mock_client.is_user_authorized.return_value = False

        # Raise 2FA on first call (code sign_in), succeed on second (password sign_in)
        def _two_step_sign_in(*args, **kwargs):
            if "password" not in kwargs:
                raise SessionPasswordNeededError(request=MagicMock())
            return None

        mock_client.sign_in.side_effect = _two_step_sign_in
        mock_tc.return_value = mock_client

        with patch.object(
            mtproto_auth, "_prompt_code", return_value="11111"
        ), patch.object(
            mtproto_auth, "_prompt_password", return_value="mypassword"
        ):
            result = mtproto_auth.login()
            # sign_in was called with code first → 2FA error → sign_in(password=...)
            mock_client.sign_in.assert_any_call(mtproto_auth.phone, "11111")
            mock_client.sign_in.assert_any_call(password="mypassword")
            assert result is mock_client
