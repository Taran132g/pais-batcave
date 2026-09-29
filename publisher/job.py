"""Job goal: Summer 2027 internship progress, measured from Gmail (confirmations, OAs, interviews, results)."""
from collections import Counter
from datetime import date, datetime, timedelta

try:
    from .gmail_jobs import STAGE_RANK, by_company
except ImportError:  # vendored flat on Oracle
    from gmail_jobs import STAGE_RANK, by_company

WEEKS_SHOWN = 12
RECENT_EVENTS = 15


def _day(iso: str) -> date:
    return datetime.fromisoformat(iso).date()


def build(gmail: dict, goals: dict, today: date | None = None) -> dict:
    today = today or date.today()
    deadline = date.fromisoformat(goals["deadline"]) if goals.get("deadline") else None
    base = {
        "target": goals.get("target"), "deadline": goals.get("deadline"),
        "days_to_deadline": (deadline - today).days if deadline else None,
        "goals": {k: goals.get(k) for k in ("applications_goal", "interviews_goal", "offers_goal")},
    }
    if gmail.get("error"):
        return {**base, "status": "gmail_error", "error": gmail["error"]}
    events = gmail.get("events", [])
    companies = by_company(events)
    reached = lambda stage: sum(STAGE_RANK[r["reached"]] >= STAGE_RANK[stage] or r["stage"] == "offer" for r in companies)
    this_week = today - timedelta(days=today.weekday())
    weeks = [this_week - timedelta(weeks=i) for i in range(WEEKS_SHOWN - 1, -1, -1)]
    first_contact = Counter(_day(r["first"]) - timedelta(days=_day(r["first"]).weekday()) for r in companies)
    return {
        **base, "status": "ok", "scanned_at": gmail.get("scanned_iso"),
        "counts": {
            "applications": len(companies),
            "assessments": reached("assessment"),
            "interviews": reached("interview"),
            "offers": sum(r["stage"] == "offer" for r in companies),
            "rejections": sum(r["stage"] == "rejected" for r in companies),
            "active": sum(r["stage"] not in ("rejected", "offer") for r in companies),
        },
        "applied_this_week": first_contact.get(this_week, 0),
        "weekly": [{"week": w.isoformat(), "applied": first_contact.get(w, 0)} for w in weeks],
        "companies": companies[:60],
        "recent": events[:RECENT_EVENTS],
    }
