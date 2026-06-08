"""CLI entry point — Click-based commands."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

import click

from tgparser import __version__
from tgparser.auth import MTProtoAuth, WebAuth
from tgparser.config import get_setting, resolve_path
from tgparser.models.message import Message
from tgparser.parsers import MTProtoParser, WebParser
from tgparser.storage import (
    save_messages,
    save_messages_incremental,
)
from tgparser.utils import setup_logging

logger = logging.getLogger("tgparser")

# Shared output-format choices
_FMT_CHOICES = ["json", "csv", "txt", "sqlite"]


@click.group()
@click.version_option(version=__version__, prog_name="tgparser")
@click.option("--debug", is_flag=True, help="Enable debug logging.")
def main(debug: bool = False) -> None:
    """TgParser — Telegram channel message extractor.

    Parse open channels via MTProto (Telethon) and closed channels
    via web Telegram (Playwright + BeautifulSoup).
    """
    from logging import DEBUG, INFO

    level = DEBUG if debug else INFO
    setup_logging(level=level)


# ------------------------------------------------------------------
# auth
# ------------------------------------------------------------------


@main.command()
@click.option(
    "--type",
    "auth_type",
    type=click.Choice(["web", "mtproto"]),
    default="web",
    help="Authentication method (default: web QR).",
)
@click.option(
    "--force",
    is_flag=True,
    help="Force re-authentication even if a valid session exists.",
)
def auth(auth_type: str, force: bool) -> None:
    """Authorize and save session.

    Opens a browser window with Telegram Web login page.
    Scan the QR code with your phone to authenticate.
    Session is saved for future reuse.
    """
    if auth_type == "web":
        web_auth = WebAuth()
        click.echo("Opening browser for QR authentication...")
        click.echo(
            "Scan the QR code with your phone "
            "(Telegram → Settings → Devices → Link Desktop Device)."
        )

        success = web_auth.login(force=force)
        if success:
            click.echo("✅ Authentication successful — session saved.")
        else:
            click.echo("❌ Authentication failed. Check logs for details.", err=True)
            raise SystemExit(1)
    elif auth_type == "mtproto":
        try:
            mtproto = MTProtoAuth()
        except ValueError as exc:
            click.echo(
                f"❌ {exc}\nCopy .env.example → .env and fill in TG_API_ID, "
                "TG_API_HASH from https://my.telegram.org/apps",
                err=True,
            )
            raise SystemExit(1) from exc

        if not force and mtproto.is_session_valid():
            click.echo("✅ Valid MTProto session already exists — no re-auth needed.")
            return

        try:
            client = mtproto.login(force=force)
            click.echo("✅ MTProto authentication successful — session saved.")
            client.disconnect()
        except Exception as exc:
            click.echo(f"❌ MTProto auth failed: {exc}", err=True)
            raise SystemExit(1) from exc


# ------------------------------------------------------------------
# parse (group with subcommands)
# ------------------------------------------------------------------


@main.group()
def parse() -> None:
    """Parse messages from a Telegram channel."""
    pass


def _common_output_options(cmd: click.Group) -> click.Group:
    """Decorator adding --format, --output-dir, --db-path, --incremental."""
    cmd = cmd
    cmd = click.option(
        "--format",
        "output_fmt",
        type=click.Choice(_FMT_CHOICES),
        default=None,
        help="Output format (default: from config.yaml).",
    )(cmd)
    cmd = click.option(
        "--output-dir",
        default=None,
        type=click.Path(file_okay=False, writable=True),
        help="Directory for output files (default: from config.yaml).",
    )(cmd)
    cmd = click.option(
        "--db-path",
        default=None,
        type=click.Path(file_okay=True, writable=True),
        help="Path to SQLite database (required for --format sqlite).",
    )(cmd)
    cmd = click.option(
        "--incremental",
        is_flag=True,
        help="Only save messages newer than the last saved ID for this channel.",
    )(cmd)
    return cmd


@parse.command("open")
@click.argument("channel")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Max messages to fetch (default: from config.yaml).",
)
@click.option(
    "--date-from",
    default=None,
    type=str,
    help="Only messages after this ISO date (YYYY-MM-DD).",
)
@click.option(
    "--date-to",
    default=None,
    type=str,
    help="Only messages before this ISO date (YYYY-MM-DD).",
)
@click.option(
    "--offset-id",
    default=0,
    type=int,
    help="Message ID to start fetching from (pagination).",
)
@click.option(
    "--format",
    "output_fmt",
    type=click.Choice(_FMT_CHOICES),
    default=None,
    help="Output format (default: from config.yaml).",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False, writable=True),
    help="Directory for output files (default: from config.yaml).",
)
@click.option(
    "--db-path",
    default=None,
    type=click.Path(file_okay=True, writable=True),
    help="Path to SQLite database (required for --format sqlite).",
)
@click.option(
    "--incremental",
    is_flag=True,
    help="Only save messages newer than the last saved ID for this channel.",
)
def parse_open(
    channel: str,
    limit: int | None,
    output_fmt: str | None,
    output_dir: str | None,
    date_from: str | None,
    date_to: str | None,
    offset_id: int,
    db_path: str | None,
    incremental: bool,
) -> None:
    """Parse an OPEN Telegram channel via MTProto API.

    CHANNEL — channel username (e.g. @durov) or invite hash.
    """
    effective_limit = limit or int(get_setting("message_limit", "100"))
    effective_fmt = output_fmt or get_setting("output_format", "json")
    if output_dir:
        effective_dir = Path(output_dir).expanduser()
        effective_dir.mkdir(parents=True, exist_ok=True)
    else:
        effective_dir = resolve_path("output_dir")

    # Parse date filters
    df: datetime | None = None
    dt: datetime | None = None
    if date_from:
        df = datetime.fromisoformat(date_from).replace(tzinfo=UTC)
    if date_to:
        dt = datetime.fromisoformat(date_to).replace(tzinfo=UTC)

    click.echo(
        f"📡 Parsing open channel '{channel}' "
        f"(limit={effective_limit}, format={effective_fmt})"
        + (", incremental" if incremental else "")
        + "..."
    )

    # Run async parse in sync entry point
    asyncio.run(
        _run_parse_open(
            channel=channel,
            limit=effective_limit,
            fmt=effective_fmt,
            output_dir=effective_dir,
            date_from=df,
            date_to=dt,
            offset_id=offset_id,
            db_path=Path(db_path) if db_path else None,
            incremental=incremental,
        )
    )


@parse.command("closed")
@click.argument("url")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Max messages to fetch (default: from config.yaml).",
)
@click.option(
    "--format",
    "output_fmt",
    type=click.Choice(_FMT_CHOICES),
    default=None,
    help="Output format (default: from config.yaml).",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False, writable=True),
    help="Directory for output files (default: from config.yaml).",
)
@click.option(
    "--db-path",
    default=None,
    type=click.Path(file_okay=True, writable=True),
    help="Path to SQLite database (required for --format sqlite).",
)
@click.option(
    "--incremental",
    is_flag=True,
    help="Only save messages newer than the last saved ID for this channel.",
)
def parse_closed(
    url: str,
    limit: int | None,
    output_fmt: str | None,
    output_dir: str | None,
    db_path: str | None,
    incremental: bool,
) -> None:
    """Parse a CLOSED Telegram channel via web Telegram.

    URL — channel link, e.g. https://t.me/durov or https://t.me/durov/123.
    """
    effective_limit = limit or int(get_setting("message_limit", "100"))
    effective_fmt = output_fmt or get_setting("output_format", "json")
    effective_dir = output_dir or get_setting("output_dir", "data/output")

    click.echo(
        f"🌐 Parsing closed channel '{url}' "
        f"(limit={effective_limit}, format={effective_fmt})"
        + (", incremental" if incremental else "")
        + "..."
    )

    asyncio.run(
        _run_parse_closed(
            url=url,
            limit=effective_limit,
            fmt=effective_fmt,
            output_dir=effective_dir,
            db_path=Path(db_path) if db_path else None,
            incremental=incremental,
        )
    )


# ------------------------------------------------------------------
# export (convert already-parsed data)
# ------------------------------------------------------------------


@main.command()
@click.argument("input_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--format",
    "output_fmt",
    type=click.Choice(_FMT_CHOICES),
    default="csv",
    help="Target format (default: csv).",
)
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(file_okay=False, writable=True),
    help="Output directory (default: from config or same as input).",
)
@click.option(
    "--db-path",
    default=None,
    type=click.Path(file_okay=True, writable=True),
    help="Path to SQLite database (for --format sqlite).",
)
def export(
    input_path: str,
    output_fmt: str,
    output_dir: str | None,
    db_path: str | None,
) -> None:
    """Convert a previously saved JSON / CSV / TXT file into another format.

    Reads messages from INPUT_PATH, detects the source format
    from the file extension, and writes them in the requested --format.
    """
    import csv
    import json

    inp = Path(input_path)
    click.echo(f"📂 Reading messages from {inp} …")

    # Detect source format
    ext = inp.suffix.lower()
    messages = []

    if ext == ".json":
        with inp.open(encoding="utf-8") as fh:
            raw = json.load(fh)
        for item in raw:
            messages.append(_dict_to_message(item))
    elif ext == ".csv":
        with inp.open(encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                messages.append(_dict_to_message(row))
    elif ext == ".txt":
        # naive TXT reading — parse the structured text format
        messages = _parse_txt(inp)
    else:
        click.echo(f"❌ Unsupported input format: {ext}", err=True)
        raise SystemExit(1)

    if not messages:
        click.echo("ℹ️  No messages found in input file.")
        return

    effective_dir = output_dir or inp.parent

    result = save_messages(
        messages=messages,
        output_dir=effective_dir,
        channel_name=inp.stem.split("_")[0],  # heuristic
        fmt=output_fmt,
        db_path=Path(db_path) if db_path else None,
    )
    if result:
        click.echo(f"✅ Exported {len(messages)} messages → {result}")
    else:
        click.echo(f"✅ Exported {len(messages)} messages → sqlite:{db_path or 'default.db'}")


# ------------------------------------------------------------------
# Async helpers
# ------------------------------------------------------------------


async def _run_parse_open(
    channel: str,
    limit: int,
    fmt: str,
    output_dir: str,
    date_from: datetime | None,
    date_to: datetime | None,
    offset_id: int,
    db_path: Path | None,
    incremental: bool,
) -> None:
    """Connect via MTProto, parse, save, and disconnect."""
    try:
        mtproto_auth = MTProtoAuth()
    except ValueError as exc:
        click.echo(f"❌ {exc}", err=True)
        raise SystemExit(1) from exc

    if not mtproto_auth.is_session_valid():
        click.echo(
            "❌ No valid MTProto session. Run 'tgparser auth --type mtproto' first.",
            err=True,
        )
        raise SystemExit(1)

    client = mtproto_auth.login(force=False)  # reuse existing session

    try:
        parser = MTProtoParser(client)
        messages = await parser.parse(
            channel=channel,
            limit=limit,
            date_from=date_from,
            date_to=date_to,
            offset_id=offset_id,
        )

        if not messages:
            click.echo("ℹ️  No messages found (channel may be empty or inaccessible).")
        else:
            if incremental:
                filepath = save_messages_incremental(
                    messages=messages,
                    output_dir=output_dir,
                    channel_name=channel,
                    fmt=fmt,
                    db_path=db_path,
                )
            else:
                filepath = save_messages(
                    messages=messages,
                    output_dir=output_dir,
                    channel_name=channel,
                    fmt=fmt,
                    db_path=db_path,
                )

            if filepath:
                click.echo(f"✅ Parsed {len(messages)} messages → {filepath}")
            else:
                click.echo(f"✅ Parsed {len(messages)} messages — no new data.")
    finally:
        await client.disconnect()


async def _run_parse_closed(
    url: str,
    limit: int,
    fmt: str,
    output_dir: str,
    db_path: Path | None,
    incremental: bool,
) -> None:
    """Use WebParser (Playwright) to parse a closed channel."""
    try:
        web_parser = WebParser()
        messages = await web_parser.parse(url=url, limit=limit)
    except Exception as exc:
        click.echo(f"❌ Web parse failed: {exc}", err=True)
        raise SystemExit(1) from exc
    finally:
        if "web_parser" in locals():
            await web_parser.close()

    if not messages:
        click.echo("ℹ️  No messages found (channel may be empty or inaccessible).")
    else:
        if incremental:
            filepath = save_messages_incremental(
                messages=messages,
                output_dir=output_dir,
                channel_name=url.rstrip("/").rsplit("/", 1)[-1],
                fmt=fmt,
                db_path=db_path,
            )
        else:
            filepath = save_messages(
                messages=messages,
                output_dir=output_dir,
                channel_name=url.rstrip("/").rsplit("/", 1)[-1],
                fmt=fmt,
                db_path=db_path,
            )
        if filepath:
            click.echo(f"✅ Parsed {len(messages)} messages → {filepath}")
        else:
            click.echo(f"✅ Parsed {len(messages)} messages — no new data.")


# ------------------------------------------------------------------
# Format conversion helpers
# ------------------------------------------------------------------


def _dict_to_message(d: dict) -> Message:
    """Convert a plain dict back to a Message object (for export)."""
    from tgparser.models.message import Message

    media_raw = d.get("media_urls", "") or ""
    reactions_raw = d.get("reactions", "") or ""

    # media_urls could be a pipe-separated string (CSV) or a JSON list (JSON)
    if isinstance(media_raw, list):
        media_urls: list[str] = media_raw
    elif media_raw and media_raw not in ("[]", ""):
        media_urls = media_raw.split("|")
    else:
        media_urls = []

    # reactions could be a JSON string or already a dict
    if isinstance(reactions_raw, dict):
        reactions: dict[str, int] = reactions_raw
    elif reactions_raw and reactions_raw.startswith("{"):
        reactions = json.loads(reactions_raw)
    else:
        reactions = {}

    return Message(
        id=int(d["id"]) if d.get("id") else 0,
        channel=d.get("channel", ""),
        date=datetime.fromisoformat(d["date"]) if d.get("date") else datetime.now(UTC),
        author=d.get("author") or None,
        text=d.get("text", ""),
        media_urls=media_urls,
        reactions=reactions,
        is_forwarded=d.get("is_forwarded", "") in ("True", "true", "1", "yes"),
        raw_source=d.get("raw_source", ""),
    )


def _parse_txt(path: Path) -> list[Message]:
    """Naive parser for the TXT format produced by _write_txt."""

    from tgparser.models.message import Message

    text = path.read_text(encoding="utf-8")
    blocks = text.strip().split("\n\n--- Message #")

    messages: list[Message] = []
    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        # Reconstruct the message id from the first line
        header = lines[0].strip()
        if header.startswith("--- Message #"):
            mid = int(header.removeprefix("--- Message #").removesuffix(" ---"))
        else:
            mid = 0

        # Extract metadata lines until blank line, then text
        meta: dict[str, str] = {}
        text_lines: list[str] = []
        in_text = False
        for line in lines[1:]:
            if not in_text:
                if line.strip() == "":
                    in_text = True
                    continue
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip().lower()] = val.strip()
            else:
                text_lines.append(line)

        channel = meta.get("channel", "")
        date_str = meta.get("date", "")
        author = meta.get("author", "—")
        if author == "—":
            author = None
        media_raw = meta.get("media", "")
        reactions_raw = meta.get("reactions", "")

        # Parse date
        dt: datetime
        try:
            dt = datetime.fromisoformat(date_str)
        except (ValueError, TypeError):
            dt = datetime.now(UTC)

        # Parse media
        media_urls: list[str] = []
        if media_raw:
            media_urls = [u.strip() for u in media_raw.split(",") if u.strip()]

        # Parse reactions
        reactions: dict[str, int] = {}
        if reactions_raw:
            for part in reactions_raw.split(","):
                part = part.strip()
                if ":" in part:
                    k, v = part.split(":", 1)
                    with contextlib.suppress(ValueError):
                        reactions[k.strip()] = int(v.strip())

        messages.append(
            Message(
                id=mid,
                channel=channel,
                date=dt,
                author=author,
                text="\n".join(text_lines).strip(),
                media_urls=media_urls,
                reactions=reactions,
                is_forwarded="forwarded" in meta.get("forwarded", "").lower(),
                raw_source="txt_export",
            )
        )
    return messages



@main.command(name="gui", help="Launch the graphical user interface (Textual TUI).")
def gui_cmd():
    """Launch the GUI interface using Textual."""
    try:
        from tgparser.gui import run_gui
        run_gui()
    except ImportError as e:
        click.echo(f"Error: GUI dependencies not installed. Run: pip install textual\\n{e}", err=True)
        raise SystemExit(1)


@main.command(name="init", help="Ensure 'tgparser' is accessible from any terminal.")
@click.option("--auto", is_flag=True, help="Automatically add PATH entry (no prompts).")
def init_cmd(auto: bool) -> None:
    """Check if the tgparser Scripts folder is in PATH and help add it."""
    import os
    import platform
    import subprocess
    import sys

    system = platform.system()

    # Determine scripts directory
    if system == "Windows":
        scripts_dir = os.path.join(
            os.environ.get("APPDATA", ""),
            "Python",
            f"Python{sys.version_info.major}{sys.version_info.minor}",
            "Scripts",
        )
    else:
        scripts_dir = os.path.expanduser("~/.local/bin")

    if not os.path.isdir(scripts_dir):
        click.echo(
            f"⚠️  Scripts folder not found at:\n    {scripts_dir}",
            err=True,
        )
        raise SystemExit(1)

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    if scripts_dir in path_dirs:
        click.echo(f"✅ Scripts folder is already in PATH:\n    {scripts_dir}")
        return

    click.echo(f"📁 Scripts folder:\n    {scripts_dir}")
    click.echo("❌ This folder is NOT in your PATH.")
    click.echo("    The 'tgparser' command won't work until added.")

    if auto:
        _add_to_path_auto(system, scripts_dir)
        return

    if system == "Windows":
        click.echo("\nTo add it manually, run this command in PowerShell:")
        click.echo(
            f'\n    [Environment]::SetEnvironmentVariable('
            f'"Path", $env:Path + ";{scripts_dir}", "User")\n'
        )
        click.echo("Then restart your terminal.")
    else:
        click.echo("\nAdd this to ~/.bashrc (or ~/.zshrc):")
        click.echo(f'\n    export PATH="$HOME/.local/bin:$PATH"\n')
        click.echo("Then run: source ~/.bashrc")

    if click.confirm("\nAutomatically add it now?", default=False):
        _add_to_path_auto(system, scripts_dir)


def _add_to_path_auto(system: str, scripts_dir: str) -> None:
    """Add scripts_dir to user PATH automatically."""
    import os
    import subprocess

    if system == "Windows":
        try:
            current_path = os.environ.get("PATH", "")
            new_path = f"{current_path};{scripts_dir}" if current_path else scripts_dir
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    f'[Environment]::SetEnvironmentVariable("Path", "{new_path}", "User")',
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            click.echo("✅ Path added. Restart your terminal.")
        except subprocess.CalledProcessError as exc:
            click.echo(f"❌ Failed: {exc}")
            raise SystemExit(1) from exc
    else:
        rc_file = os.path.expanduser("~/.bashrc")
        if not os.path.isfile(rc_file):
            rc_file = os.path.expanduser("~/.zshrc")
        if not os.path.isfile(rc_file):
            rc_file = os.path.expanduser("~/.profile")
        line = f'\nexport PATH="$HOME/.local/bin:$PATH"\n'
        try:
            with open(rc_file, "a") as f:
                f.write(line)
            click.echo(f"✅ Added to {rc_file}. Run 'source {rc_file}' or restart.")
        except OSError as exc:
            click.echo(f"❌ Failed: {exc}")
            raise SystemExit(1) from exc


if __name__ == "__main__":
    main()