"""Unit tests for web_parser."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from bs4 import BeautifulSoup

from tgparser.auth.web_auth import WebAuth
from tgparser.parsers.web_parser import (
    WebParser,
    _detect_forwarded,
    _extract_author,
    _extract_date,
    _extract_id,
    _extract_media_urls,
    _extract_text,
    _parse_human_date,
)

# Sample HTML fragments
SAMPLE_MSG = '<div class="bubble"><div class="message-text">Hello, world!</div><span class="time" data-timestamp="1700000000">12:34 PM</span></div>'
SAMPLE_MSG_AUTHOR = '<div class="bubble"><div class="sender-name">Alice</div><div class="message-text">Check this out</div><time datetime="2024-01-15T09:30:00+00:00">09:30</time></div>'
SAMPLE_MSG_MEDIA = '<div class="bubble"><div class="message-text">Look</div><img src="https://cdn.telegram.org/photo1.jpg" /><video src="video.mp4"></video><a class="preview-link" href="https://example.com/article">R</a></div>'
SAMPLE_MSG_FWD = '<div class="bubble is-forwarded"><div class="forwarded">Forwarded from Orig</div><div class="message-text">Interesting</div></div>'
SAMPLE_MSG_EMPTY = '<div class="bubble"><div class="bubble-content"></div></div>'


@pytest.fixture
def mock_web_auth() -> WebAuth:
    auth = MagicMock(spec=WebAuth)
    auth.is_session_valid.return_value = True
    auth.restore_session.return_value = True
    return auth


class TestExtractId:
    def test_from_data_message_id(self) -> None:
        soup = BeautifulSoup('<div data-message-id="12345">text</div>', "html.parser")
        msg_id = _extract_id(soup.div)
        assert isinstance(msg_id, int)
        assert msg_id >= 0
        assert _extract_id(soup.div) == msg_id

    def test_different_messages_different_ids(self) -> None:
        a = BeautifulSoup('<div data-message-id="111">A</div>', "html.parser").div
        b = BeautifulSoup('<div data-message-id="222">B</div>', "html.parser").div
        assert _extract_id(a) != _extract_id(b)


class TestExtractText:
    def test_from_message_text_class(self) -> None:
        soup = BeautifulSoup('<div><span class="message-text">Hello</span></div>', "html.parser")
        assert _extract_text(soup.div) == "Hello"

    def test_empty_returns_none(self) -> None:
        soup = BeautifulSoup("<div class='bubble'></div>", "html.parser")
        assert _extract_text(soup.div) is None

    def test_multiline_text(self) -> None:
        soup = BeautifulSoup('<div><div class="message-text">Line 1\nLine 2</div></div>', "html.parser")
        assert _extract_text(soup.div) == "Line 1\nLine 2"


class TestExtractAuthor:
    def test_from_peer_title(self) -> None:
        soup = BeautifulSoup('<div><span class="peer-title">Channel</span></div>', "html.parser")
        assert _extract_author(soup.div) == "Channel"

    def test_from_sender_name(self) -> None:
        soup = BeautifulSoup('<div><span class="sender-name">Bob</span></div>', "html.parser")
        assert _extract_author(soup.div) == "Bob"

    def test_no_author_returns_none(self) -> None:
        soup = BeautifulSoup("<div>Just text</div>", "html.parser")
        assert _extract_author(soup.div) is None


class TestExtractDate:
    def test_from_time_datetime_attr(self) -> None:
        soup = BeautifulSoup('<div><time datetime="2024-06-01T12:00:00+00:00">12:00</time></div>', "html.parser")
        dt = _extract_date(soup.div)
        assert dt == datetime(2024, 6, 1, 12, 0, tzinfo=UTC)

    def test_from_data_timestamp(self) -> None:
        soup = BeautifulSoup('<div><span class="time" data-timestamp="1717200000">12:00 PM</span></div>', "html.parser")
        dt = _extract_date(soup.div)
        assert dt == datetime.fromtimestamp(1717200000, tz=UTC)

    def test_no_date_returns_none(self) -> None:
        soup = BeautifulSoup("<div>No date here</div>", "html.parser")
        assert _extract_date(soup.div) is None


class TestParseHumanDate:
    def test_time_only(self) -> None:
        dt = _parse_human_date("12:34")
        assert dt is not None
        assert dt.hour == 12
        assert dt.minute == 34

    def test_time_with_ampm(self) -> None:
        dt = _parse_human_date("09:15 PM")
        assert dt is not None
        assert dt.hour == 21

    def test_full_date(self) -> None:
        dt = _parse_human_date("Jan 15, 2024")
        assert dt is not None
        assert dt.year == 2024

    def test_garbage_returns_none(self) -> None:
        assert _parse_human_date("not a date !!!") is None


class TestExtractMediaUrls:
    def test_extracts_images(self) -> None:
        soup = BeautifulSoup('<div><img src="https://cdn.telegram.org/img1.jpg" /><img src="https://cdn.telegram.org/img2.png" /></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert len(urls) == 2

    def test_skips_emoji_images(self) -> None:
        soup = BeautifulSoup('<div><img class="emoji" src="emoji.png" /><img src="real.jpg" /></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert len(urls) == 1

    def test_skips_data_uris(self) -> None:
        soup = BeautifulSoup('<div><img src="data:image/png;base64,abc123" /></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert len(urls) == 0

    def test_extracts_videos(self) -> None:
        soup = BeautifulSoup('<div><video src="video.mp4"></video><video><source src="video2.webm" /></video></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert "video.mp4" in urls
        assert "video2.webm" in urls

    def test_extracts_links(self) -> None:
        soup = BeautifulSoup('<div><a class="preview-link" href="https://example.com">Link</a></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert "https://example.com" in urls

    def test_deduplicates(self) -> None:
        soup = BeautifulSoup('<div><img src="dup.jpg" /><img src="dup.jpg" /></div>', "html.parser")
        urls = _extract_media_urls(soup.div)
        assert len(urls) == 1

    def test_no_media_returns_empty(self) -> None:
        soup = BeautifulSoup("<div>Text only</div>", "html.parser")
        assert _extract_media_urls(soup.div) == []


class TestDetectForwarded:
    def test_detects_forwarded_class(self) -> None:
        soup = BeautifulSoup('<div class="is-forwarded"><span class="forwarded">Fwd</span></div>', "html.parser")
        assert _detect_forwarded(soup.div) is True

    def test_detects_text_pattern(self) -> None:
        soup = BeautifulSoup("<div>Forwarded from Original Channel</div>", "html.parser")
        assert _detect_forwarded(soup.div) is True

    def test_normal_message_not_forwarded(self) -> None:
        soup = BeautifulSoup("<div>Hello world</div>", "html.parser")
        assert _detect_forwarded(soup.div) is False


class TestWebParserInit:
    def test_defaults(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        # config.yaml has headless: false
        assert parser._headless is False
        assert parser._timeout_ms == 30_000

    def test_overrides(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth, headless=True, slow_mo=200)
        assert parser._headless is True
        assert parser._slow_mo == 200


class TestWebParserSessionValidation:
    def test_raises_if_no_session(self, mock_web_auth: WebAuth) -> None:
        mock_web_auth.is_session_valid.return_value = False
        parser = WebParser(mock_web_auth)
        with pytest.raises(RuntimeError, match="No valid web session"):
            parser.parse("@test_channel")

    def test_raises_if_session_restore_fails(self, mock_web_auth: WebAuth) -> None:
        mock_web_auth.restore_session.return_value = False
        parser = WebParser(mock_web_auth)
        with pytest.raises(RuntimeError, match="Failed to restore"):
            with patch("tgparser.parsers.web_parser.sync_playwright") as mock_pw:
                mock_pw.return_value.start.return_value = mock_pw
                mock_pw.chromium.launch.return_value = MagicMock()
                parser.parse("@test_channel")


class TestExtractHash:
    def test_username(self) -> None:
        assert WebParser._extract_hash("@test_channel") == "test_channel"
    def test_tme_url(self) -> None:
        assert WebParser._extract_hash("https://t.me/durov") == "durov"
    def test_tme_invite(self) -> None:
        assert WebParser._extract_hash("https://t.me/+abc123") == "+abc123"
    def test_web_url(self) -> None:
        assert WebParser._extract_hash("https://web.telegram.org/k/#@chat") == "@chat"
    def test_plain(self) -> None:
        assert WebParser._extract_hash("mychannel") == "mychannel"


class TestParseMessageElement:
    def test_parses_simple_message(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is not None
        assert msg.text == "Hello, world!"
        assert msg.raw_source == "web"
        assert msg.channel == "test"

    def test_parses_message_with_author(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG_AUTHOR, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is not None
        assert msg.author == "Alice"
        assert msg.text == "Check this out"
        assert msg.date == datetime(2024, 1, 15, 9, 30, tzinfo=UTC)

    def test_parses_message_with_media(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG_MEDIA, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is not None
        assert len(msg.media_urls) == 3

    def test_detects_forwarded(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG_FWD, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is not None
        assert msg.is_forwarded is True

    def test_empty_message_returns_none(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG_EMPTY, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is None

    def test_to_dict_serializable(self, mock_web_auth: WebAuth) -> None:
        parser = WebParser(mock_web_auth)
        soup = BeautifulSoup(SAMPLE_MSG, "html.parser")
        el = soup.select_one(".bubble")
        msg = parser._parse_message_element(el, channel_name="test")
        assert msg is not None
        d = msg.to_dict()
        assert d["text"] == "Hello, world!"
        assert d["raw_source"] == "web"
        assert "date" in d
