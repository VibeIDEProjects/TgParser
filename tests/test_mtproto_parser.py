"""Tests for MTProtoParser — mocked Telethon interactions."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telethon import errors, types
from telethon.tl.custom import Message as TgMessage

from tgparser.models.message import Message
from tgparser.parsers.mtproto_parser import MTProtoParser

# ------------------------------------------------------------------
# Helpers — build mock Telethon messages
# ------------------------------------------------------------------

def _make_tg_message(
    msg_id: int = 1,
    text: str = "Hello",
    date: datetime | None = None,
    post_author: str | None = None,
    sender: MagicMock | None = None,
    media: types.TypeMessageMedia | None = None,
    reactions: types.MessageReactions | None = None,
    forward: types.MessageFwdHeader | None = None,
) -> MagicMock:
    """Build a MagicMock that mimics a Telethon Message."""
    if date is None:
        date = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)

    msg = MagicMock(spec=TgMessage, name=f"TgMessage-{msg_id}")
    msg.id = msg_id
    msg.text = text
    msg.date = date
    msg.post_author = post_author
    msg.sender_id = 123456
    msg.media = media
    msg.reactions = reactions
    msg.forward = forward

    # Mock get_sender() — returns sender MagicMock or raises
    if sender is not None:
        msg.get_sender = AsyncMock(return_value=sender)
    else:
        msg.get_sender = AsyncMock(return_value=None)

    return msg


def _make_sender(
    first_name: str | None = "John",
    username: str | None = "johndoe",
) -> MagicMock:
    """Build a mock sender/user."""
    sender = MagicMock()
    sender.first_name = first_name
    sender.username = username
    return sender


def _make_reactions(counts: dict[str, int]) -> types.MessageReactions:
    """Build a Telethon MessageReactions object."""
    results = []
    for emoticon, cnt in counts.items():
        reaction = types.ReactionEmoji(emoticon=emoticon)
        count_obj = types.ReactionCount(reaction=reaction, count=cnt)
        results.append(count_obj)
    return types.MessageReactions(results=results)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture
def mock_client() -> MagicMock:
    """Mock TelegramClient."""
    client = MagicMock(name="TelegramClient")
    client.get_entity = AsyncMock()
    client.get_messages = AsyncMock()
    client.disconnect = AsyncMock()
    return client


@pytest.fixture
def parser(mock_client: MagicMock) -> MTProtoParser:
    return MTProtoParser(client=mock_client)


# ------------------------------------------------------------------
# _to_message conversion
# ------------------------------------------------------------------

class TestToMessage:
    """Message conversion from Telethon → domain model."""

    @pytest.mark.asyncio
    async def test_basic_text(self, parser: MTProtoParser) -> None:
        tg_msg = _make_tg_message(msg_id=42, text="Hello world")
        result = await parser._to_message(tg_msg, "durov")

        assert isinstance(result, Message)
        assert result.id == 42
        assert result.channel == "durov"
        assert result.text == "Hello world"
        assert result.media_urls == []
        assert result.reactions is None
        assert result.is_forwarded is False
        assert result.raw_source == "mtproto"

    @pytest.mark.asyncio
    async def test_post_author(self, parser: MTProtoParser) -> None:
        tg_msg = _make_tg_message(post_author="Admin")
        result = await parser._to_message(tg_msg, "chan")
        assert result.author == "Admin"

    @pytest.mark.asyncio
    async def test_sender_fallback(self, parser: MTProtoParser) -> None:
        sender = _make_sender(first_name="Alice")
        tg_msg = _make_tg_message(post_author="", sender=sender)
        result = await parser._to_message(tg_msg, "chan")
        assert result.author == "Alice"

    @pytest.mark.asyncio
    async def test_sender_username_fallback(self, parser: MTProtoParser) -> None:
        sender = _make_sender(first_name=None, username="alice123")
        tg_msg = _make_tg_message(post_author="", sender=sender)
        result = await parser._to_message(tg_msg, "chan")
        assert result.author == "alice123"

    @pytest.mark.asyncio
    async def test_reactions(self, parser: MTProtoParser) -> None:
        reactions = _make_reactions({"👍": 5, "❤️": 2})
        tg_msg = _make_tg_message(reactions=reactions)
        result = await parser._to_message(tg_msg, "chan")
        assert result.reactions == {"👍": 5, "❤️": 2}

    @pytest.mark.asyncio
    async def test_forwarded(self, parser: MTProtoParser) -> None:
        fwd = types.MessageFwdHeader(
            date=datetime(2024, 1, 1),
            from_id=types.PeerChannel(channel_id=999),
        )
        tg_msg = _make_tg_message(forward=fwd)
        result = await parser._to_message(tg_msg, "chan")
        assert result.is_forwarded is True

    @pytest.mark.asyncio
    async def test_date_timezone(self, parser: MTProtoParser) -> None:
        # Telethon dates may be naive → should become UTC-aware
        dt = datetime(2025, 6, 1, 10, 30)
        tg_msg = _make_tg_message(date=dt)
        result = await parser._to_message(tg_msg, "chan")
        assert result.date.tzinfo == UTC


# ------------------------------------------------------------------
# _extract_media_urls
# ------------------------------------------------------------------

class TestExtractMediaUrls:
    """Media URL extraction."""

    def test_photo(self) -> None:
        photo_obj = types.Photo(
            id=12345,
            access_hash=0,
            file_reference=b"",
            date=datetime.now(),
            sizes=[types.PhotoSize(type="m", w=320, h=240, size=0)],
            dc_id=2,
        )
        media = types.MessageMediaPhoto(photo=photo_obj)
        tg_msg = _make_tg_message(media=media)
        result = MTProtoParser._extract_media_urls(tg_msg)
        assert len(result) == 1
        assert result[0].startswith("photo:12345:")

    def test_document(self) -> None:
        doc = types.Document(
            id=777,
            access_hash=0,
            file_reference=b"",
            date=datetime.now(),
            mime_type="application/pdf",
            size=1024,
            dc_id=2,
            attributes=[
                types.DocumentAttributeFilename(file_name="report.pdf"),
            ],
        )
        media = types.MessageMediaDocument(document=doc)
        tg_msg = _make_tg_message(media=media)
        result = MTProtoParser._extract_media_urls(tg_msg)
        assert len(result) == 1
        assert result[0] == "document:777:report.pdf"

    def test_webpage(self) -> None:
        wp = types.WebPage(
            id=1,
            url="https://example.com/article",
            display_url="example.com",
            hash=0,
        )
        media = types.MessageMediaWebPage(webpage=wp)
        tg_msg = _make_tg_message(media=media)
        result = MTProtoParser._extract_media_urls(tg_msg)
        assert result == ["https://example.com/article"]

    def test_no_media(self) -> None:
        tg_msg = _make_tg_message(media=None)
        result = MTProtoParser._extract_media_urls(tg_msg)
        assert result == []


# ------------------------------------------------------------------
# _normalize_channel
# ------------------------------------------------------------------

class TestNormalizeChannel:
    def test_strips_at(self) -> None:
        assert MTProtoParser._normalize_channel("@durov") == "durov"

    def test_preserves_no_at(self) -> None:
        assert MTProtoParser._normalize_channel("durov") == "durov"

    def test_preserves_invite_hash(self) -> None:
        assert MTProtoParser._normalize_channel("+abc123def") == "+abc123def"


# ------------------------------------------------------------------
# parse — integration with mocked client
# ------------------------------------------------------------------

class TestParse:
    """End-to-end parse() with mocked TelegramClient."""

    @pytest.mark.asyncio
    async def test_parse_single_batch(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        mock_entity = MagicMock(spec=types.InputPeerChannel)
        mock_client.get_entity.return_value = mock_entity

        msgs = [
            _make_tg_message(msg_id=100, text="First"),
            _make_tg_message(msg_id=99, text="Second"),
        ]
        mock_client.get_messages.return_value = msgs

        results = await parser.parse("testchan", limit=2)

        assert len(results) == 2
        assert results[0].text == "First"
        assert results[1].text == "Second"
        assert results[0].id == 100
        assert results[1].id == 99

    @pytest.mark.asyncio
    async def test_parse_empty_channel(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        mock_entity = MagicMock(spec=types.InputPeerChannel)
        mock_client.get_entity.return_value = mock_entity
        mock_client.get_messages.return_value = []

        results = await parser.parse("empty", limit=10)
        assert results == []

    @pytest.mark.asyncio
    async def test_parse_pagination(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        """Verify that pagination follows offset_id."""
        mock_entity = MagicMock(spec=types.InputPeerChannel)
        mock_client.get_entity.return_value = mock_entity

        # First batch: messages 200, 199 (limit=2 → batch fills, oldest id=199)
        batch1 = [
            _make_tg_message(msg_id=200, text="Msg200"),
            _make_tg_message(msg_id=199, text="Msg199"),
        ]
        # Second batch: messages 198, 197
        batch2 = [
            _make_tg_message(msg_id=198, text="Msg198"),
            _make_tg_message(msg_id=197, text="Msg197"),
        ]
        mock_client.get_messages.side_effect = [batch1, batch2]

        results = await parser.parse("chan", limit=4)

        assert len(results) == 4
        # get_messages called twice
        assert mock_client.get_messages.call_count == 2
        # Second call should have offset_id=199 (oldest from batch1)
        _, kwargs = mock_client.get_messages.call_args_list[1]
        assert kwargs["offset_id"] == 199

    @pytest.mark.asyncio
    async def test_parse_date_filter(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        """Messages outside the date range are filtered out."""
        mock_entity = MagicMock(spec=types.InputPeerChannel)
        mock_client.get_entity.return_value = mock_entity

        msgs = [
            _make_tg_message(
                msg_id=1,
                text="Old",
                date=datetime(2025, 3, 1, tzinfo=UTC),
            ),
            _make_tg_message(
                msg_id=2,
                text="New",
                date=datetime(2025, 6, 1, tzinfo=UTC),
            ),
            _make_tg_message(
                msg_id=3,
                text="Latest",
                date=datetime(2025, 9, 1, tzinfo=UTC),
            ),
        ]
        # Return msgs once, then empty to stop pagination loop
        mock_client.get_messages.side_effect = [msgs, []]

        date_from = datetime(2025, 4, 1, tzinfo=UTC)
        date_to = datetime(2025, 8, 1, tzinfo=UTC)

        results = await parser.parse("chan", limit=3, date_from=date_from, date_to=date_to)

        assert len(results) == 1
        assert results[0].text == "New"

    @pytest.mark.asyncio
    async def test_parse_flood_wait_retry(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        """FloodWaitError on get_entity → retry, then succeed."""
        mock_entity = MagicMock(spec=types.InputPeerChannel)

        # First call: FloodWaitError, second call: success
        mock_client.get_entity.side_effect = [
            errors.rpcerrorlist.FloodWaitError(None, 1),
            mock_entity,
        ]
        mock_client.get_messages.side_effect = [
            [_make_tg_message(msg_id=1, text="ok")],
        ]

        with patch.object(asyncio, "sleep", new_callable=AsyncMock) as mock_sleep:
            results = await parser.parse("chan", limit=1, max_retries=3)

        assert len(results) == 1
        assert results[0].text == "ok"
        mock_sleep.assert_called_once_with(2)  # seconds + 1

    @pytest.mark.asyncio
    async def test_parse_flood_wait_exhausted(
        self, parser: MTProtoParser, mock_client: MagicMock
    ) -> None:
        """FloodWaitError on every attempt → re-raises."""
        mock_client.get_entity.side_effect = errors.rpcerrorlist.FloodWaitError(None, 1)

        with patch.object(asyncio, "sleep", new_callable=AsyncMock):
            with pytest.raises(errors.rpcerrorlist.FloodWaitError):
                await parser.parse("chan", limit=1, max_retries=2)
