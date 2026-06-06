"""Message data model."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Message:
    """Unified message model for both open and closed channel parsing."""

    id: int
    channel: str
    date: datetime
    text: str
    author: str | None = None
    media_urls: list[str] = field(default_factory=list)
    reactions: dict[str, int] | None = None
    is_forwarded: bool = False
    raw_source: str = "unknown"  # "mtproto" | "web"

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return {
            "id": self.id,
            "channel": self.channel,
            "date": self.date.isoformat(),
            "author": self.author,
            "text": self.text,
            "media_urls": self.media_urls,
            "reactions": self.reactions,
            "is_forwarded": self.is_forwarded,
            "raw_source": self.raw_source,
        }
