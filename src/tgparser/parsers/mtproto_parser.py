"""Parser for open Telegram channels via MTProto (Telethon)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from telethon import errors, types
from telethon.client import TelegramClient
from telethon.tl.custom import Message as TgMessage

from tgparser.models.message import Message

logger = logging.getLogger("tgparser")


class MTProtoParser:
    """Extract messages from open Telegram channels using MTProto API.

    Uses an existing *authenticated* Telethon client.  Rate-limit errors
    (FloodWaitError) are handled with a sleep-and-retry inside the public
    ``parse`` method.
    """

    def __init__(self, client: TelegramClient) -> None:
        self._client = client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def parse(
        self,
        channel: str,
        limit: int = 100,
        *,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        offset_id: int = 0,
        max_retries: int = 3,
    ) -> list[Message]:
        """Fetch messages from *channel* and return our domain models.

        Args:
            channel: ``@username`` or invite hash.
            limit: Maximum number of messages to return.
            date_from: Only messages after this datetime (inclusive).
            date_to: Only messages before this datetime (inclusive).
            offset_id: Message ID to start pagination from (older than this).
            max_retries: How many times to retry on FloodWaitError.
        """
        results: list[Message] = []
        batch_limit = min(limit, 100)  # Telethon caps at 100 per call
        remaining = limit
        current_offset = offset_id

        for attempt in range(1, max_retries + 1):
            try:
                # Resolve channel entity (cached internally by Telethon).
                entity = await self._client.get_entity(channel)

                while remaining > 0:
                    batch = await self._fetch_batch(
                        entity=entity,
                        channel_name=self._normalize_channel(channel),
                        limit=min(remaining, batch_limit),
                        offset_id=current_offset,
                        date_from=date_from,
                        date_to=date_to,
                    )
                    if not batch:
                        break

                    results.extend(batch)
                    remaining -= len(batch)
                    # Paginate: messages are returned newest-first;
                    # next offset is the id of the oldest message in this batch.
                    current_offset = batch[-1].id

                return results

            except errors.rpcerrorlist.FloodWaitError as exc:
                delay = exc.seconds + 1
                if attempt == max_retries:
                    logger.error(
                        "FloodWaitError after %d retries: %s", max_retries, exc
                    )
                    raise
                logger.warning(
                    "FloodWait: sleeping %d s (attempt %d/%d)",
                    delay,
                    attempt,
                    max_retries,
                )
                await asyncio.sleep(delay)

        return results  # pragma: no cover – unreachable but keeps type-checker happy

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_batch(
        self,
        entity: types.InputPeerChannel | types.InputPeerChat,
        channel_name: str,
        limit: int,
        offset_id: int,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[Message]:
        """Single call to ``client.get_messages`` + conversion."""
        tg_messages = await self._client.get_messages(
            entity,
            limit=limit,
            offset_id=offset_id,
            offset_date=date_from,
            max_id=0,
            min_id=0,
        )

        # Ensure tg_messages is iterable (can be a single item or None).
        if tg_messages is None:
            return []
        if isinstance(tg_messages, TgMessage):
            tg_messages = [tg_messages]

        converted: list[Message] = []
        for tg_msg in tg_messages:
            msg = await self._to_message(tg_msg, channel_name)
            # Apply date-range filter client-side (Telethon's offset_date
            # is not perfectly precise for bidirectional filtering).
            if date_from is not None and msg.date < date_from:
                continue
            if date_to is not None and msg.date > date_to:
                continue
            converted.append(msg)

        return converted

    async def _to_message(
        self, tg_msg: TgMessage, channel_name: str
    ) -> Message:
        """Convert a Telethon :class:`Message` to our domain model."""
        media_urls: list[str] = []
        if tg_msg.media is not None:
            media_urls = self._extract_media_urls(tg_msg)

        # Author extraction precedence: post_author (signature) → sender first_name
        author: str | None = None
        if isinstance(tg_msg.post_author, str) and tg_msg.post_author:
            author = tg_msg.post_author
        elif tg_msg.sender_id is not None:
            try:
                sender = await tg_msg.get_sender()
                if sender is not None:
                    author = getattr(sender, "first_name", None) or getattr(
                        sender, "username", None
                    )
            except Exception:
                author = str(tg_msg.sender_id)

        # Reactions
        reactions: dict[str, int] | None = None
        if tg_msg.reactions is not None:
            reactions = {}
            for r in tg_msg.reactions.results:
                emoticon = (
                    r.reaction.emoticon
                    if hasattr(r.reaction, "emoticon")
                    else str(r.reaction)
                )
                reactions[emoticon] = r.count

        return Message(
            id=tg_msg.id,
            channel=channel_name,
            date=tg_msg.date.replace(tzinfo=UTC),
            author=author,
            text=tg_msg.text or "",
            media_urls=media_urls,
            reactions=reactions,
            is_forwarded=tg_msg.forward is not None,
            raw_source="mtproto",
        )

    # ------------------------------------------------------------------
    # Media helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_media_urls(tg_msg: TgMessage) -> list[str]:
        """Build a list of human-readable media descriptors for *tg_msg*.

        We do **not** download actual files here; we return file IDs and
        attributes that can be used to construct download URLs later.
        """
        urls: list[str] = []
        media = tg_msg.media

        if isinstance(media, types.MessageMediaPhoto):
            photo = media.photo
            if isinstance(photo, types.Photo) and photo.sizes:
                # Largest size is usually last.
                largest = photo.sizes[-1]
                urls.append(
                    f"photo:{photo.id}:{getattr(largest, 'w', '?')}"
                    f"x{getattr(largest, 'h', '?')}"
                )

        elif isinstance(media, types.MessageMediaDocument):
            doc = media.document
            if isinstance(doc, types.Document):
                name_parts: list[str] = []
                for attr in doc.attributes:
                    if isinstance(attr, types.DocumentAttributeFilename):
                        name_parts.append(attr.file_name)
                    elif isinstance(attr, types.DocumentAttributeVideo):
                        name_parts.append(f"video({attr.duration}s)")
                    elif isinstance(attr, types.DocumentAttributeAudio):
                        name_parts.append(
                            f"audio({attr.duration}s)" + (
                                f"-{attr.title}" if attr.title else ""
                            )
                        )
                name = "_".join(name_parts) if name_parts else f"doc:{doc.id}"
                urls.append(f"document:{doc.id}:{name}")

        elif isinstance(media, types.MessageMediaWebPage):
            wp = media.webpage
            if isinstance(wp, types.WebPage) and wp.url:
                urls.append(wp.url)

        return urls

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_channel(raw: str) -> str:
        """Strip leading @ if present, return uniform channel name."""
        return raw.lstrip("@")
