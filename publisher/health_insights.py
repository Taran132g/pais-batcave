"""Coach's read for the Gym tab: turns the Fitbit daily rows + workouts into ranked, actionable findings.

Every insight is computed from Taran's own numbers (recent days vs his baseline, his weekday patterns, what his
readiness does after short sleep) and is skipped when there isn't enough data. Wording is plain English with
no abbreviations, because the page is read at a glance.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import StatisticsError, correlation, mean

from publisher import health_panels
from publisher.fitbit_sessions import num, steps_value, training_sessions

RECENT_DAYS = 7
MIN_BASELINE_DAYS = 7
MIN_PAIRS = 8                  # minimum day-pairs before a correlation is worth reporting
HRV_DROP_PCT = 10              # % below baseline that counts as a real recovery dip
RHR_RISE_BPM = 2.5
SHORT_SLEEP_H = 7.0
GOOD_SLEEP_H = 7.5
WEAK_NIGHT_GAP_H = 0.6         # a weekday night this far below the average is a pattern worth fixing
BEDTIME_SPREAD_MIN = 60        # bedtime swinging more than this night to night hurts sleep quality
SLEEP_DEBT_H = 3
FEVER_SIGNAL_C = 0.5           # nightly skin temperature this far above normal is an early illness signal
LOW_WEAR_DAYS = 3
WALK_STEPS_PER_20_MIN = 2_400
TONE_ORDER = {"act": 0, "watch": 1, "good": 2}
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _d(s) -> date | None:
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def _avg(values):
    vals = [v for v in values if v is not None]
    return round(mean(vals), 1) if vals else None


def _day(iso: str) -> str:
    """'2026-09-07' -> 'Sep 7'."""
    d = _d(iso)
    return f"{d:%b} {d.day}" if d else iso


def _insight(key, tone, title, finding, action) -> dict:
    return {"key": key, "tone": tone, "title": title, "finding": finding, "action": action}


def recovery(rows) -> dict | None:
    """Last 7 days vs everything before them, for the three recovery markers."""
    if len(rows) < RECENT_DAYS + MIN_BASELINE_DAYS:
        return None
    base, recent = rows[:-RECENT_DAYS], rows[-RECENT_DAYS:]
    out = {}
    for metric in ("hrv_ms", "resting_hr", "readiness"):
        b, r = _avg(num(x.get(metric)) for x in base), _avg(num(x.get(metric)) for x in recent)
        if b and r:
            out[metric] = {"baseline": b, "recent": r, "change_pct": round((r - b) / b * 100, 1)}
    return out or None


def _recovery_insight(rec) -> dict | None:
    if not rec or "hrv_ms" not in rec:
        return None
    hrv, rhr = rec["hrv_ms"], rec.get("resting_hr")
    rhr_up = rhr and rhr["recent"] - rhr["baseline"] >= RHR_RISE_BPM
    if -hrv["change_pct"] >= HRV_DROP_PCT or rhr_up:
        rhr_txt = (f", and your resting heart rate rose from {rhr['baseline']:.0f} to {rhr['recent']:.0f} beats per minute"
                   if rhr_up else "")
        return _insight("recovery", "act", "Your body is under-recovered",
                        f"Heart rate variability (higher means more recovered) averaged {hrv['recent']:.0f} milliseconds "
                        f"over your last 7 days, down {abs(hrv['change_pct']):.0f}% from your normal "
                        f"{hrv['baseline']:.0f}{rhr_txt}. That pattern means fatigue, stress or short sleep is piling up.",
                        "Take a lighter week: keep lifting but drop one set per exercise, skip all-out cardio, and get "
                        f"8 hours in bed until heart rate variability is back above about {hrv['baseline'] * 0.95:.0f}. "
                        "Go easy on alcohol and late meals; both lower it overnight.")
    return _insight("recovery", "good", "Recovery is holding steady",
                    f"Heart rate variability is {hrv['recent']:.0f} milliseconds vs your normal {hrv['baseline']:.0f}.",
                    "You have room to push training this week.")


def _sleep_lever(rows) -> dict | None:
    pairs = [(s, r) for x in rows if (s := num(x.get("sleep_hours"))) is not None
             and (r := num(x.get("readiness"))) is not None]
    if len(pairs) < MIN_PAIRS:
        return None
    try:
        rho = correlation(*zip(*pairs))
    except StatisticsError:  # one side never varied, so there's no relationship to report
        return None
    good = _avg(r for s, r in pairs if s >= GOOD_SLEEP_H)
    short = _avg(r for s, r in pairs if s < SHORT_SLEEP_H)
    if rho < 0.3 or good is None or short is None:
        return None
    return _insight("sleep_lever", "watch", "Sleep is your biggest lever",
                    f"Your Daily Readiness averages {good:.0f} after {GOOD_SLEEP_H:g} or more hours of sleep, but only "
                    f"{short:.0f} after less than {SHORT_SLEEP_H:g} hours. Nothing else you track moves it as much.",
                    f"Protect {GOOD_SLEEP_H:g} hours: count back from your earliest class and set that as lights-out.")


def _weak_night(rows) -> dict | None:
    """Sleep is logged on the wake-up date, so the night belongs to the day before."""
    by_night = defaultdict(list)
    for x in rows:
        if (d := _d(x["date"])) and (s := num(x.get("sleep_hours"))) is not None:
            by_night[(d - timedelta(days=1)).weekday()].append(s)
    overall = _avg(s for v in by_night.values() for s in v)
    nights = {k: _avg(v) for k, v in by_night.items() if len(v) >= 2}
    if not nights or overall is None:
        return None
    worst = min(nights, key=nights.get)
    if overall - nights[worst] < WEAK_NIGHT_GAP_H:
        return None
    wake = WEEKDAYS[(worst + 1) % 7]
    ready = _avg(num(x.get("readiness")) for x in rows if (d := _d(x["date"])) and d.weekday() == (worst + 1) % 7)
    ready_txt = f", and your {wake} Daily Readiness averages {ready:.0f}" if ready else ""
    return _insight("weak_night", "act", f"{WEEKDAYS[worst]} nights are your weak spot",
                    f"You sleep {nights[worst]:.1f} hours on {WEEKDAYS[worst]} nights vs {overall:.1f} hours on "
                    f"average{ready_txt}.",
                    f"Set a {WEEKDAYS[worst]} wind-down alarm and move anything late earlier. Make {wake} a lighter "
                    "training day.")


def _schedule(panel) -> list[dict]:
    if not panel:
        return []
    out = []
    spread = panel["bedtime_spread_min"]
    if spread > BEDTIME_SPREAD_MIN:
        out.append(_insight("schedule", "act", "Your bedtime moves around a lot",
                            f"Over the last {len(panel['nights'])} nights your bedtime varied by about {spread} minutes "
                            f"either side of {panel['avg_bedtime']}. An irregular schedule lowers sleep quality even "
                            "when total hours look fine.",
                            f"Pick one lights-out (around {panel['avg_bedtime']} fits your current habits) and stay "
                            "within 30 minutes of it, weekends included."))
    debt = panel["sleep_debt_hours"]
    if debt is not None and debt >= SLEEP_DEBT_H:
        out.append(_insight("debt", "watch", f"You're {debt:g} hours short on sleep this week",
                            f"Added up over your last {panel['debt_nights']} nights against a {panel['goal_hours']:g}-hour "
                            "goal.",
                            "Pay it back gradually: 30 to 45 extra minutes a night for a few nights, not one long lie-in."))
    return out


def _training(workouts, goals, as_of) -> dict | None:
    since = as_of - timedelta(weeks=4)
    sessions = [w for w in training_sessions(workouts) if (d := _d(w["date"])) and d > since]
    per_week, target = len(sessions) / 4, goals.get("workouts_per_week") or 4
    if per_week >= target:
        return _insight("consistency", "good", "Training consistency is on target",
                        f"{len(sessions)} sessions in the last 4 weeks.", "Keep the routine.")
    return _insight("consistency", "act", "Train more consistently",
                    f"Your heart rate shows {len(sessions)} workouts in the last 4 weeks (about {per_week:.1f} a week) "
                    f"vs your goal of {target}. These are detected automatically, so you don't need to start a "
                    "workout on the band.",
                    f"Block {target} fixed gym slots in your calendar (for example Monday, Wednesday, Friday, Saturday). "
                    "Keep the band on so they register.")


def _load(panel) -> dict | None:
    if not panel:
        return None
    ratio = panel["ratio"]
    if panel["band"] == "under":
        return _insight("load", "watch", "Training load is drifting down",
                        f"This week's training load is {ratio:g} times your 4-week average, below the 0.8 to 1.3 range "
                        "where fitness builds.", "Add one more session or lengthen your usual ones a little.")
    if panel["band"] in ("high", "very_high"):
        return _insight("load", "act", "Training load jumped",
                        f"This week's training load is {ratio:g} times your 4-week average. Spikes above 1.3 raise "
                        "injury and burnout risk.", "Hold steady for a week before adding more.")
    return None


def _temperature(panel) -> dict | None:
    if not panel or panel["deviation_c"] < FEVER_SIGNAL_C:
        return None
    return _insight("temperature", "act", "Your skin temperature is running hot",
                    f"On your most recent night ({_day(panel['date'])}) it was {panel['deviation_c']:+.1f} °C above your normal. This often shows up a day or two "
                    "before you feel sick, or after alcohol or a late heavy meal.",
                    "Take an easy day, hydrate, and sleep early. If it stays high for 2 or more nights, rest fully.")


def _wear(panel) -> dict | None:
    if not panel or panel["days_left_out"] < LOW_WEAR_DAYS:
        return None
    return _insight("wear", "watch", "Wear the band more to get accurate numbers",
                    f"{panel['days_left_out']} of the last {panel['days']} days had less than 8 waking hours of data, so "
                    "they're left out of your step averages.",
                    "Charge it during a shower or while sitting at a desk, then put it straight back on.")


def _steps(rows, goals) -> dict | None:
    goal = goals.get("steps_per_day") or 10_000
    avg = _avg(steps_value(x) for x in rows[-14:])
    if avg is None:
        return None
    if avg >= goal:
        return _insight("steps", "good", "Steps are on target",
                        f"About {avg:,.0f} a day over the last 2 weeks, counting only days you wore the band and "
                        "filling in short gaps at your own pace.", "Keep it up.")
    by_day = defaultdict(list)
    for x in rows:
        if (d := _d(x["date"])) and (s := steps_value(x)) is not None:
            by_day[d.weekday()].append(s)
    low = sorted((k for k, v in by_day.items() if len(v) >= 2), key=lambda k: mean(by_day[k]))[:2]
    gap = goal - avg
    walks = max(1, round(gap / WALK_STEPS_PER_20_MIN))
    low_txt = " and ".join(f"{WEEKDAYS[k]}s ({mean(by_day[k]):,.0f})" for k in low)
    return _insight("steps", "watch", f"{gap:,.0f} steps a day short of {goal:,}",
                    f"About {avg:,.0f} a day over the last 2 weeks. Your lowest days are {low_txt}.",
                    f"Add {walks} twenty-minute walk{'s' if walks > 1 else ''} on those days.")


def _azm(rows, goals) -> dict | None:
    goal = goals.get("active_zone_min_per_week") or 150
    weekly = _avg(num(x.get("active_zone_min")) for x in rows[-28:])
    if weekly is None:
        return None
    weekly *= 7
    if weekly >= goal:
        return _insight("azm", "good", "Cardio volume is strong",
                        f"About {weekly:.0f} active zone minutes a week (minutes with your heart rate in a "
                        f"fat-burn zone or higher) vs the {goal}-minute health guideline.",
                        "You don't need more cardio. Put that effort into training consistency and sleep.")
    return _insight("azm", "watch", "Cardio is below the guideline",
                    f"About {weekly:.0f} active zone minutes a week vs the {goal}-minute guideline.",
                    "Two brisk 30-minute sessions (bike, incline walk, swim) cover most of the gap.")


def _fitness(panel) -> dict | None:
    if not panel or abs(panel["change"]) < 1:
        return None
    up = panel["change"] > 0
    return _insight("fitness", "good" if up else "watch",
                    "Cardio fitness is improving" if up else "Cardio fitness slipped",
                    f"Your cardio fitness score (VO2 max: how much oxygen your body can use) is {panel['latest']:g}, "
                    f"{'up' if up else 'down'} {abs(panel['change']):g} since {_day(panel['since'])}.",
                    "Keep doing what you're doing." if up else "One harder interval session a week brings it back up.")


def build(rows: list[dict], workouts: list[dict], goals: dict, today: date | None = None) -> dict:
    # Takeout data lags up to a week, so windows end at the last logged day, not the calendar date.
    as_of = max((d for r in rows if (d := _d(r["date"]))), default=today or date.today())
    panels = health_panels.build(rows, goals)
    rec = recovery(rows)
    candidates = [_recovery_insight(rec), _weak_night(rows), *_schedule(panels["sleep_schedule"]), _sleep_lever(rows),
                  _training(workouts, goals, as_of), _load(panels["training_load"]),
                  _temperature(panels["skin_temperature"]), _steps(rows, goals), _wear(panels["wear"]),
                  _azm(rows, goals), _fitness(panels["cardio_fitness"])]
    insights = sorted((i for i in candidates if i), key=lambda i: TONE_ORDER[i["tone"]])
    return {"recovery": rec, "insights": insights, "panels": panels}
