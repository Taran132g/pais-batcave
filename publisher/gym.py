"""Gym goal: workouts (detected from heart rate), active zone minutes, steps and sleep from Fitbit vs weekly targets."""
from datetime import date, timedelta

from publisher import health_insights
from publisher.fitbit_sessions import MIN_WEAR_HOURS, steps_value, training_sessions

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


def _week(rows, sessions, start: date) -> dict:
    end = start + timedelta(days=7)
    days = [r for r in rows if (d := _d(r["date"])) and start <= d < end]
    training = [w for w in sessions if (d := _d(w["date"])) and start <= d < end]
    return {
        "week": start.isoformat(),
        "workouts": len(training),
        "workout_minutes": sum(int(_num(w.get("minutes")) or 0) for w in training),
        "azm": sum(int(_num(r.get("active_zone_min")) or 0) for r in days),
        "steps_avg": _avg([steps_value(r) for r in days]),
        "sleep_avg": _avg([_num(r.get("sleep_hours")) for r in days]),
        "days_logged": len(days),
    }


def _steps_streak(rows, goal) -> int:
    """Consecutive goal days, skipping days the band was off too long to count."""
    streak = 0
    for r in reversed(rows):
        steps = steps_value(r)
        if steps is None:
            continue
        if steps >= goal:
            streak += 1
        else:
            break
    return streak


def last_full_day(rows: list[dict], today: date) -> date:
    """Most recent day with real data. The export's final day is cut off when the export is made
    (little band time), so it's skipped; the meters then cover the 7 days ending here, not the calendar week."""
    for r in reversed(rows):
        wear = _num(r.get("wear_hours"))
        if (wear is None or wear >= MIN_WEAR_HOURS) and (d := _d(r["date"])):
            return d
    return max((d for r in rows if (d := _d(r["date"]))), default=today)


def build(rows: list[dict], workouts: list[dict], goals: dict, today: date | None = None) -> dict:
    today = today or date.today()
    if not rows and not workouts:
        return {"status": "awaiting data", "goals": goals}
    as_of = last_full_day(rows, today)
    sessions = training_sessions(workouts)
    week_start = as_of - timedelta(days=as_of.weekday())
    weeks = [_week(rows, sessions, week_start - timedelta(weeks=i)) for i in range(WEEKS_SHOWN - 1, -1, -1)]
    current = {**_week(rows, sessions, as_of - timedelta(days=6)), "end": as_of.isoformat()}
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
        "workouts": sorted(sessions, key=lambda w: (w["date"], w.get("start", "")), reverse=True)[:15],
        "coach": health_insights.build(rows, workouts, goals, today),
        "days_logged": len(rows),
    }
