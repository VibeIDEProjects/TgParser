"""TgParser — Telegram channel parser."""

try:
    from importlib.metadata import version, PackageNotFoundError
    __version__ = version("tgparser-cli")
except PackageNotFoundError:
    __version__ = "0.0.0"
