"""Daily application goal: today's list (3 finance + 3 software, scouted on the Mac each morning)
and which ones are done.

A job counts as done when either (a) Gmail shows a "thanks for applying" confirmation from that
company on that day, or (b) Taran ticked it on the JOB tab (data/daily_marks.json).
"""
import json
import re
from datetime import date, datetime

from . import config

try:
    from .gmail_jobs import CORP_SUFFIX
except ImportError:  # pragma: no cover
    CORP_SUFFIX = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company|group|plc)\b\.?", re.I)

from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
LIST_DIR = config.ROOT / "data/daily_jobs"
MARKS_FILE = config.ROOT / "data/daily_marks.json"
EVENTS_FILE = config.ROOT / "data/job_events.json"
MIN_MATCH = 4


def _words(name: str) -> list[str]:
    words = re.findall(r"[a-z0-9]+", CORP_SUFFIX.sub(" ", (name or "").lower().replace("&", " ")))
    return [w for w in words if w != "the"]


def same_company(a: str, b: str) -> bool:
    """'JPMorgan Chase & Co.' == 'JPMorganChase', 'Vanguard' == 'The Vanguard Group'; 'Citi' != 'Citizens Bank'."""
    x, y = _words(a), _words(b)
    if not x or not y:
        return False
    if "".join(x) == "".join(y):
        return True
    short, long_ = sorted((x, y), key=len)
    return long_[:len(short)] == short and len("".join(short)) >= MIN_MATCH


def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def status(day: date, jobs: list[dict], events: list[dict], marks: dict) -> dict:
    """Pure: which of the day's jobs are done, and how."""
    day_iso = day.isoformat()
    applied_today = [e for e in events if e.get("stage") == "submitted"
                     and datetime.fromisoformat(e["date"]).astimezone(TZ).date() == day]
    manual = set(marks.get(day_iso, []))
    rows = []
    for j in jobs:
        via = None
        if j["url"] in manual:
            via = "marked"
        elif any(same_company(j["company"], e["company"]) for e in applied_today):
            via = "email"
        rows.append({**j, "done": via is not None, "via": via})
    done = sum(r["done"] for r in rows)
    return {"date": day_iso, "jobs": rows, "done": done, "total": len(rows),
            "complete": bool(rows) and done == len(rows)}


def for_day(day: date) -> dict:
    listing = _read(LIST_DIR / f"{day.isoformat()}.json", None)
    if not listing:
        return {"date": day.isoformat(), "jobs": [], "done": 0, "total": 0, "complete": False, "missing_list": True}
    out = status(day, listing.get("jobs", []), _read(EVENTS_FILE, []), _read(MARKS_FILE, {}))
    return {**out, "scouted_at": listing.get("scouted_at"), "claude_prompt": listing.get("claude_prompt", "")}


def set_mark(day: date, url: str, done: bool) -> dict:
    listing = _read(LIST_DIR / f"{day.isoformat()}.json", {}) or {}
    if url not in {j["url"] for j in listing.get("jobs", [])}:
        raise KeyError("not on that day's list")
    marks = _read(MARKS_FILE, {})
    urls = set(marks.get(day.isoformat(), []))
    (urls.add if done else urls.discard)(url)
    marks[day.isoformat()] = sorted(urls)
    tmp = MARKS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(marks))
    tmp.replace(MARKS_FILE)
    return for_day(day)
