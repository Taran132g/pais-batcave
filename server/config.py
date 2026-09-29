"""Paths and constants. Everything PAIS reads lives on this Mac; nothing is copied elsewhere."""
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static"

HOST = "127.0.0.1"  # never bind publicly: this app exposes personal finance + health data
PORT = 8150

# Same authenticator secret as the QUANT_OS trading site, so one app entry covers both.
TOTP_ENV_FILE = HOME / "Automated-Trading-Bot/.env"
SESSION_KEY_FILE = ROOT / ".session_key"
SESSION_DAYS = 30
LOGIN_MAX_FAILS = 5
LOGIN_WINDOW_S = 300

VAULT = HOME / "Library/Mobile Documents/iCloud~md~obsidian/Documents/Digital Brain"
AGENTIC_OS = HOME / "agentic_os"
FITBIT_CSV = VAULT / "Fitness/Health Tracking/Data/fitbit_daily.csv"
FITBIT_DASHBOARD = HOME / "fitbit-import/dashboard.html"
FITBIT_LOG = HOME / "fitbit-import/auto_import.log"

YUBIT_SNAPSHOTS = HOME / "Automated-Trading-Bot/yubit_snapshots"
NAV_JOB_LOG = HOME / "Automated-Trading-Bot/nav_job.log"

CLAUDE_SUPPORT = HOME / "Library/Application Support/Claude"
DESKTOP_SESSIONS = CLAUDE_SUPPORT / "local-agent-mode-sessions"

READ_TIMEOUT_S = 20  # iCloud-evicted vault files can hang a plain read
