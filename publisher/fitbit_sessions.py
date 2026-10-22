"""Which workouts count, and which step numbers to trust.

Workouts: Taran usually doesn't start/stop sessions on the band, so the importer detects them from heart rate
(source=detected). A manually logged session that overlaps a detected one just names it ("Swim", "Sport");
a logged session with nothing detected still counts unless it was obviously left running.

Steps: days the band was worn under 8 waking hours are dropped; other days use the importer's estimate that
fills band-off gaps at that day's own step rate (steps_est), falling back to raw steps for older rows.
"""
from datetime import datetime, timedelta

MIN_WEAR_HOURS = 8
STUCK_SESSION_MIN = 180        # a logged session longer than this with a low heart rate was never stopped
STUCK_SESSION_MAX_HR = 100
NOT_TRAINING = {"walk"}        # walks count toward steps, not toward gym sessions


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def is_stuck(w: dict) -> bool:
    minutes, hr = num(w.get("minutes")) or 0, num(w.get("avg_hr"))
    return w.get("source") != "detected" and minutes > STUCK_SESSION_MIN and (hr is None or hr < STUCK_SESSION_MAX_HR)


def _span(w: dict):
    try:
        start = datetime.fromisoformat(f"{w['date']}T{w.get('start') or '00:00'}")
    except ValueError:
        return None
    return start, start + timedelta(minutes=num(w.get("minutes")) or 0)


def _overlaps(a, b) -> bool:
    return a and b and a[0] < b[1] and b[0] < a[1]


def training_sessions(workouts: list[dict]) -> list[dict]:
    """Detected sessions (named by any overlapping log) + logged sessions nothing was detected for."""
    detected = [w for w in workouts if w.get("source") == "detected"
                and (w.get("activity") or "").lower() not in NOT_TRAINING]
    logged = [w for w in workouts if w.get("source") != "detected"
              and (w.get("activity") or "").lower() not in NOT_TRAINING
              and not is_stuck(w) and (num(w.get("minutes")) or 0) > 0]
    out = []
    for d in detected:
        match = next((lg for lg in logged if _overlaps(_span(d), _span(lg))), None)
        out.append({**d, "activity": match["activity"] if match else d.get("activity"), "named_by_log": bool(match)})
    claimed = {id(lg) for d in detected for lg in logged if _overlaps(_span(d), _span(lg))}
    out += [{**lg, "named_by_log": True} for lg in logged if id(lg) not in claimed]
    return sorted(out, key=lambda w: (w["date"], w.get("start") or ""))


def stuck_logs(workouts: list[dict]) -> list[dict]:
    return [w for w in workouts if is_stuck(w)]


def steps_value(row: dict):
    """Trusted steps for a day, or None when the band was off too long to say."""
    wear = num(row.get("wear_hours"))
    if wear is not None and wear < MIN_WEAR_HOURS:
        return None
    return num(row.get("steps_est")) if row.get("steps_est") not in (None, "") else num(row.get("steps"))


def low_wear_days(rows: list[dict]) -> list[str]:
    return [r["date"] for r in rows if (w := num(r.get("wear_hours"))) is not None and w < MIN_WEAR_HOURS]
