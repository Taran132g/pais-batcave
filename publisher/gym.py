"""Gym goal: workouts, active zone minutes, steps and sleep from Fitbit vs weekly targets."""
from datetime import date, timedelta

WEEKS_SHOWN = 8


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _week(rows, workouts, start: date) -> dict:
    end = start + timedelta(days=7)
    days = [r for r in rows if (d := _d(r["date"])) and start <= d < end]
    sessions = [w for w in workouts if (d := _d(w["date"])) and start <= d < end]
    return {
        "week": start.isoformat(),
        "workouts": len(sessions),
        "workout_minutes": sum(int(_num(w.get("minutes")) or 0) for w in sessions),
        "azm": sum(int(_num(r.get("active_zone_min")) or 0) for r in days),
        "steps_avg": _avg([_num(r.get("steps")) for r in days]),
        "sleep_avg": _avg([_num(r.get("sleep_hours")) for r in days]),
        "days_logged": len(days),
    }


def _steps_streak(rows, goal) -> int:
    streak = 0
    for r in reversed(rows):
        if (_num(r.get("steps")) or 0) >= goal:
            streak += 1
        else:
            break
    return streak


def build(rows: list[dict], workouts: list[dict], goals: dict, today: date | None = None) -> dict:
    today = today or date.today()
    if not rows and not workouts:
        return {"status": "awaiting data", "goals": goals}
    this_week = today - timedelta(days=today.weekday())
    weeks = [_week(rows, workouts, this_week - timedelta(weeks=i)) for i in range(WEEKS_SHOWN - 1, -1, -1)]
    current = weeks[-1]
    return {
        "status": "ok",
        "goals": goals,
        "latest": rows[-1] if rows else None,
        "this_week": current,
        "progress": {
            "workouts": current["workouts"] / goals["workouts_per_week"] if goals.get("workouts_per_week") else None,
            "azm": current["azm"] / goals["active_zone_min_per_week"] if goals.get("active_zone_min_per_week") else None,
            "steps": (current["steps_avg"] or 0) / goals["steps_per_day"] if goals.get("steps_per_day") else None,
            "sleep": (current["sleep_avg"] or 0) / goals["sleep_hours"] if goals.get("sleep_hours") else None,
        },
        "weeks": weeks,
        "steps_streak": _steps_streak(rows, goals.get("steps_per_day") or 10_000),
        "daily": rows[-30:],
        "workouts": sorted(workouts, key=lambda w: (w["date"], w.get("start", "")), reverse=True)[:15],
        "days_logged": len(rows),
    }
