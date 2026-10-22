"""Data for the Gym tab's detail panels: sleep schedule, training load, cardio fitness, skin temperature, wear time.

Ideas borrowed from what Whoop/Oura/open-source Fitbit dashboards surface (sleep consistency, sleep debt,
acute:chronic load, temperature deviation), computed only from fields the Google Health export actually has.
"""
from statistics import mean, pstdev

from publisher.fitbit_sessions import low_wear_days, num, steps_value

SCHEDULE_NIGHTS = 14
DEBT_NIGHTS = 7
TEMP_BASELINE_NIGHTS = 14
FITNESS_WINDOW_DAYS = 30
# Google's training-load bands (acute 7-day load / chronic 28-day load).
LOAD_BANDS = [(0.8, "under", "Below your usual load"), (1.3, "optimal", "In your productive range"),
              (1.5, "high", "Ramping up fast"), (float("inf"), "very_high", "Big spike: injury and burnout risk")]


def _vals(rows, key):
    return [(r["date"], v) for r in rows if (v := num(r.get(key))) is not None]


def _avg(values, dp=1):
    vals = [v for v in values if v is not None]
    return round(mean(vals), dp) if vals else None


def clock(hours):
    """25.5 -> '1:30 AM'."""
    if hours is None:
        return None
    total = round(hours * 60) % (24 * 60)
    h, m = divmod(total, 60)
    return f"{(h % 12) or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


def sleep_schedule(rows, goal_hours) -> dict | None:
    nights = [r for r in rows if num(r.get("bed_clock")) is not None][-SCHEDULE_NIGHTS:]
    if len(nights) < 3:
        return None
    beds, wakes = [num(r["bed_clock"]) for r in nights], [num(r["wake_clock"]) for r in nights if r.get("wake_clock")]
    recent = [num(r.get("sleep_hours")) for r in rows[-DEBT_NIGHTS:] if num(r.get("sleep_hours")) is not None]
    debt = round(sum(max(0, goal_hours - h) for h in recent), 1) if recent else None
    return {
        "avg_bedtime": clock(mean(beds)), "avg_wake": clock(mean(wakes)) if wakes else None,
        "bedtime_spread_min": round(pstdev(beds) * 60) if len(beds) > 1 else 0,
        "sleep_debt_hours": debt, "debt_nights": len(recent), "goal_hours": goal_hours,
        "nights": [{"date": r["date"], "bed": clock(num(r["bed_clock"])), "wake": clock(num(r.get("wake_clock"))),
                    "bed_clock": num(r["bed_clock"]), "wake_clock": num(r.get("wake_clock")),
                    "hours": num(r.get("sleep_hours"))} for r in nights],
    }


def training_load(rows) -> dict | None:
    series = _vals(rows, "load_ratio")
    if not series:
        return None
    date, ratio = series[-1]
    key, label = next((k, lbl) for limit, k, lbl in LOAD_BANDS if ratio < limit)
    return {"date": date, "ratio": round(ratio, 2), "band": key, "label": label,
            "history": [{"date": d, "ratio": round(v, 2)} for d, v in series[-28:]]}


def cardio_fitness(rows) -> dict | None:
    series = _vals(rows, "vo2max")
    if not series:
        return None
    latest = series[-1][1]
    window = series[-FITNESS_WINDOW_DAYS:]
    return {"latest": round(latest, 1), "change": round(latest - window[0][1], 1), "since": window[0][0],
            "history": [{"date": d, "value": round(v, 1)} for d, v in window]}


def skin_temperature(rows) -> dict | None:
    series = _vals(rows, "skin_temp_c")
    if len(series) < 5:
        return None
    date, last = series[-1]
    baseline = mean(v for _, v in series[-TEMP_BASELINE_NIGHTS - 1:-1])
    return {"date": date, "deviation_c": round(last - baseline, 2), "baseline_c": round(baseline, 2),
            "history": [{"date": d, "deviation_c": round(v - baseline, 2)} for d, v in series[-TEMP_BASELINE_NIGHTS:]]}


def wear(rows, window=14) -> dict | None:
    recent = rows[-window:]
    hours = [num(r.get("wear_hours")) for r in recent if num(r.get("wear_hours")) is not None]
    if not hours:
        return None
    trusted = [steps_value(r) for r in recent]
    return {"avg_hours_worn": round(mean(hours), 1), "days": len(hours),
            "days_left_out": len(low_wear_days(recent)),
            "steps_recorded_avg": _avg((num(r.get("steps")) for r in recent), 0),
            "steps_estimated_avg": _avg(trusted, 0)}


def build(rows, goals) -> dict:
    return {"sleep_schedule": sleep_schedule(rows, goals.get("sleep_hours") or 7.5), "training_load": training_load(rows),
            "cardio_fitness": cardio_fitness(rows), "skin_temperature": skin_temperature(rows), "wear": wear(rows)}
