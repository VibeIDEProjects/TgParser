"""Channel parsers — open (Telethon) and closed (Playwright + BS4)."""

from tgparser.parsers.mtproto_parser import MTProtoParser
from tgparser.parsers.web_parser import WebParser

__all__ = ["MTProtoParser", "WebParser"]
