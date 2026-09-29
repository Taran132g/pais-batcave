"""Oracle-side settings for the getpais.company PAIS API (served under /api/cave via Vercel)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST, PORT = "127.0.0.1", 8155   # nginx proxies https://api.<ip>.nip.io/cave/ -> here

# The live QUANT_OS trading dashboard's secret: same authenticator entry as that login.
TOTP_ENV_FILE = Path.home() / "Automated-Trading-Bot/.env"
SESSION_KEY_FILE = ROOT / ".session_key"
LOCAL_ENV_FILE = ROOT / ".env"   # TEMP_PASSCODE_SHA256 / TEMP_PASSCODE_EXPIRES (unix time); never in git
SESSION_DAYS = 30
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 300

SNAPSHOT_FILE = ROOT / "data/snapshot.json"
STALE_AFTER_S = 3600
COOKIE_PATH = "/api/cave"

COINBASE_KEY_FILE = ROOT / ".coinbase_key.json"   # CDP view-only key (600); never in git
