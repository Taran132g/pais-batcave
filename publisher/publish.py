"""Build the PAIS snapshot on the Mac and push it to the Oracle box that serves getpais.company.

Run: .venv/bin/python -m publisher.publish [--dry-run]
Scheduled by LaunchAgent com.taran.pais-publish: every 5 min plus whenever an agent's output
lands (WatchPaths). Pushes only when the content changed (or every 45 min as a heartbeat).
"""
import argparse
import csv
import hashlib
import io
import json
import subprocess
import sys
import time
from datetime import datetime, timezone

from server import config
from server.sources import desktop_runs, fitbit, yubit
from server.sources.common import safe_read

from . import fund, gym, outlook, roi, yubit_brief

GOALS_FILE = config.ROOT / "goals.json"
OUT_FILE = config.ROOT / "snapshot.json"
PUSHED_HASH = config.ROOT / ".last_push"
FORCE_PUSH_S = 45 * 60  # keep the site's "last reported" fresh even when nothing changed
FITBIT_WORKOUTS = config.FITBIT_CSV.with_name("fitbit_workouts.csv")
OUTLOOK_DIR = config.ROOT / "data/x_outlook"  # written by xoutlook.run (Mon + Fri 9am)

ORACLE = "ubuntu@129.159.182.210"
ORACLE_KEY = config.HOME / ".ssh/oracle_pais.key"
REMOTE_DIR = "/home/ubuntu/pais-cave/data"
SSH_OPTS = ["-i", str(ORACLE_KEY), "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def _workouts() -> list[dict]:
    text = safe_read(FITBIT_WORKOUTS)
    return list(csv.DictReader(io.StringIO(text))) if text else []


def _section(name, fn, *args):
    """One broken source must not blank the whole site: record the error in its section."""
    try:
        return fn(*args)
    except Exception as exc:  # noqa: BLE001 - surfaced in the UI
        print(f"[publish] {name} failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"}


def _roi(goals):
    daily = desktop_runs.runs("daily-trading-assistant-open-positions", 5)
    latest_report = next((r["report"] for r in daily if r["status"] == "done"), "")
    return roi.build(yubit.snapshots(), latest_report, goals["roi"]["monthly_target_pct"],
                     transfers=goals["roi"].get("transfers"))


AI_NEWS_DIR = config.ROOT / "data/ai_news"   # written by scout/ai_news.py each morning


def _ai_news() -> dict:
    issues = sorted(AI_NEWS_DIR.glob("*.json"))
    return {"status": "ok", **json.loads(issues[-1].read_text())} if issues else {"status": "none"}


DEGREE_FILE = config.ROOT / "data/degree.json"   # hand-maintained degree audit + plan (private)


def _degree() -> dict:
    return {"status": "ok", **json.loads(DEGREE_FILE.read_text())} if DEGREE_FILE.exists() else {"status": "none"}


GRADES_FILE = config.ROOT / "data/grades.json"   # Canvas grades read in Taran's browser session (private)


def _grades() -> dict:
    return {"status": "ok", **json.loads(GRADES_FILE.read_text())} if GRADES_FILE.exists() else {"status": "none"}


EXIT_PLANS_FILE = config.ROOT / "data/exit_plans.json"   # exit options per open position (private)


def _exit_plans() -> dict:
    return {"status": "ok", **json.loads(EXIT_PLANS_FILE.read_text())} if EXIT_PLANS_FILE.exists() else {"status": "none"}


TRADE_NOTES_FILE = config.ROOT / "data/trade_notes.json"   # why Taran closed each trade (private)


def build_snapshot() -> dict:
    goals = json.loads(GOALS_FILE.read_text())
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "roi": _section("roi", _roi, goals),
        # "job" is computed on Oracle from Gmail (cave/job_runner.py), so the Mac doesn't scan Gmail.
        "gym": _section("gym", lambda: gym.build(fitbit.rows(), _workouts(), goals["gym"])),
        "outlook": _section("outlook", outlook.build, OUTLOOK_DIR),
        "yubit_brief": _section("yubit_brief", yubit_brief.build),   # 9am email's trading overview
        "ai_news": _section("ai_news", _ai_news),
        "degree": _section("degree", _degree),
        "grades": _section("grades", _grades),   # PSU blocks API tokens, so grades come from a browser sync
        "exit_plans": _section("exit_plans", _exit_plans),
        "fund": _section("fund", fund.build, TRADE_NOTES_FILE),   # trade.getpais.company Fund tab
    }


def _content_hash(snap: dict) -> str:
    body = {k: v for k, v in snap.items() if k != "generated_at"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def _should_push(digest: str) -> bool:
    if not PUSHED_HASH.exists():
        return True
    unchanged = PUSHED_HASH.read_text().strip() == digest
    fresh = time.time() - PUSHED_HASH.stat().st_mtime < FORCE_PUSH_S
    return not (unchanged and fresh)


def push(path) -> None:
    remote_tmp = f"{REMOTE_DIR}/snapshot.json.tmp"
    subprocess.run(["scp", *SSH_OPTS, str(path), f"{ORACLE}:{remote_tmp}"], check=True, timeout=60)
    subprocess.run(["ssh", *SSH_OPTS, ORACLE, f"chmod 600 {remote_tmp} && mv {remote_tmp} {REMOTE_DIR}/snapshot.json"],
                   check=True, timeout=30)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="build snapshot.json locally, don't push")
    args = ap.parse_args()
    snap = build_snapshot()
    tmp = OUT_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, separators=(",", ":")))
    tmp.replace(OUT_FILE)
    OUT_FILE.chmod(0o600)
    size_kb = OUT_FILE.stat().st_size // 1024
    digest = _content_hash(snap)
    if not args.dry_run and not _should_push(digest):
        return 0
    if args.dry_run:
        print(f"[publish] built {OUT_FILE} ({size_kb} KB), not pushed")
        return 0
    try:
        push(OUT_FILE)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"[publish] push to Oracle FAILED: {exc}", file=sys.stderr)
        return 1
    PUSHED_HASH.write_text(digest)
    print(f"[publish] {datetime.now():%F %T} pushed snapshot ({size_kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
