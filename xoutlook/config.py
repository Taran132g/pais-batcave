"""Paths and constants for the X outlook run."""
from pathlib import Path

HOME = Path.home()
ROOT = Path(__file__).resolve().parents[1]

# The PAIS Playwright profile: Taran signs in to X here once, every run reuses the session.
PROFILE_DIR = HOME / "agentic_os/.browser_profile"

DATA_DIR = ROOT / "data/x_outlook"          # one JSON per run, newest = latest.json
LATEST_FILE = DATA_DIR / "latest.json"
STATE_FILE = DATA_DIR / "state.json"        # last successful run, so the next one reads only new posts
SHOT_DIR = DATA_DIR / "screenshots"         # saved when a profile yields no posts (layout change / logged out)

VAULT_DIR = HOME / "Library/Mobile Documents/iCloud~md~obsidian/Documents/Digital Brain/Money & Markets/X Market Outlook"

# Keep in sync with SOURCES in pais-site/cave/js/tabs/trading.js.
SOURCES = [
    {"name": "Dr. Profit", "handle": "DrProfitCrypto"},
    {"name": "DiligentPlane", "handle": "DiligentPlane"},
    {"name": "No Limit Gains", "handle": "NoLimitGains"},
    {"name": "Jason Pizzino", "handle": "jasonpizzino"},
    {"name": "Kevin Xu", "handle": "kevinxu"},
]

MAX_WINDOW_DAYS = 7      # first run, or after a long gap: never read further back than this
MAX_POSTS_PER_SOURCE = 40
MAX_SCROLLS = 12
SCROLL_PAUSE_MS = 1800   # human pace between scrolls
BETWEEN_PROFILES_MS = 4000

CLAUDE_BIN = "/opt/homebrew/bin/claude"
CLAUDE_MODEL = "sonnet"
CLAUDE_TIMEOUT_S = 300
