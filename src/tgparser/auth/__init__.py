"""Authentication modules — web QR and MTProto."""

from tgparser.auth.mtproto_auth import MTProtoAuth
from tgparser.auth.web_auth import WebAuth

__all__ = ["MTProtoAuth", "WebAuth"]
