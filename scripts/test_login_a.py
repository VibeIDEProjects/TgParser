"""Test new 3-stage login flow on /a/ frontend with detailed logs."""
import sys
import time
import json

from tgparser.auth.web_auth import WebAuth
from playwright.sync_api import sync_playwright

sys.stdout.reconfigure(line_buffering=True)

# Inspect existing session
wa = WebAuth()
print("session file:", wa.session_file, flush=True)
data = json.loads(wa.session_file.read_text())
print("cookies count:", len(data.get("cookies", [])))
print("LS keys:", list(data.get("local_storage", {}).keys()))

# Force re-auth
wa2 = WebAuth()
print("valid before:", wa2.is_session_valid(), flush=True)
# Don't supply password — test the manual-entry fallback

# Custom: I'll go through stages manually to see what fails
try:
    ok = wa2.login(force=True)
    print("LOGIN OK:", ok, flush=True)
    print("valid after:", wa2.is_session_valid(), flush=True)
except Exception as e:
    import traceback
    traceback.print_exc()
    print("LOGIN ERR:", repr(e), flush=True)
