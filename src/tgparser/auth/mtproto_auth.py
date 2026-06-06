"""MTProto (Telethon) phone-code authentication for open channels."""

from pathlib import Path

from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError,
)

from tgparser.config import get_secret, get_setting
from tgparser.utils import logger


class MTProtoAuth:
    """Authenticate via MTProto (Telethon) — phone number + code.

    Uses api_id/api_hash from .env or config secrets.
    Session is persisted as a Telethon .session file.
    """

    def __init__(
        self,
        api_id: int | None = None,
        api_hash: str | None = None,
        phone: str | None = None,
        session_dir: str | Path | None = None,
    ) -> None:
        self.api_id = api_id or int(get_secret("TG_API_ID") or 0)
        self.api_hash = api_hash or get_secret("TG_API_HASH") or ""
        self.phone = phone or get_secret("TG_PHONE") or ""

        if not self.api_id or not self.api_hash:
            raise ValueError(
                "MTProto credentials missing. "
                "Set TG_API_ID and TG_API_HASH in .env or pass explicitly."
            )

        session_dir = Path(
            session_dir or get_setting("session_dir", default="data/sessions/")
        )
        session_dir.mkdir(parents=True, exist_ok=True)
        self.session_file = session_dir / "mtproto.session"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def login(self, force: bool = False) -> TelegramClient:
        """Authenticate via phone code, persist session, return client.

        If a valid session exists and force=False, reuses it.
        Raises on authentication failure.
        """
        client = TelegramClient(
            str(self.session_file),
            self.api_id,
            self.api_hash,
        )

        if not force and self.is_session_valid():
            logger.info("Valid MTProto session found — reusing.")
            client.connect()
            return client

        logger.info("Starting MTProto authentication for %s...", self.phone)
        client.connect()

        if not client.is_user_authorized():
            client.send_code_request(self.phone)
            logger.info("Verification code sent to %s.", self.phone)

            code = self._prompt_code()
            try:
                client.sign_in(self.phone, code)
            except SessionPasswordNeededError:
                # 2FA enabled — ask for password
                password = self._prompt_password()
                client.sign_in(password=password)

        logger.info(
            "MTProto authentication successful — session saved to %s",
            self.session_file,
        )
        return client

    def is_session_valid(self) -> bool:
        """Check whether a persisted .session file exists and can connect."""
        if not self.session_file.exists():
            return False
        try:
            client = TelegramClient(
                str(self.session_file),
                self.api_id,
                self.api_hash,
            )
            client.connect()
            authorized = client.is_user_authorized()
            client.disconnect()
            return authorized
        except Exception as exc:
            logger.debug("Session validity check failed: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Prompt helpers (interactive console input)
    # ------------------------------------------------------------------

    def _prompt_code(self) -> str:
        """Read verification code from stdin with timeout."""
        for _ in range(3):
            try:
                code = input("Enter the verification code from Telegram: ").strip()
                if code:
                    return code
            except (EOFError, KeyboardInterrupt):
                raise
        raise ValueError("No verification code provided after 3 attempts.")

    def _prompt_password(self) -> str:
        """Read 2FA password from stdin."""
        import getpass

        for _ in range(3):
            try:
                password = getpass.getpass("Enter your 2FA password: ").strip()
                if password:
                    return password
            except (EOFError, KeyboardInterrupt):
                raise
        raise ValueError("No 2FA password provided after 3 attempts.")
