import re
from datetime import date, timedelta

from publisher import fitbit_sessions, gym, health_insights, health_panels

GOALS = {"workouts_per_week": 4, "active_zone_min_per_week": 150, "steps_per_day": 10000, "sleep_hours": 7.5}
START = date(2026, 9, 7)  # a Monday
ABBREVIATIONS = re.compile(r"\b(HRV|RHR|HR|bpm|AZM|SpO2|RMSSD|VO2|ms|min|h|hrs?)\b")


def _rows(n=21, hrv=lambda i: 90, sleep=lambda i: 7.5, readiness=lambda i: 60, steps=lambda i: 8000, **extra):
    return [{"date": (START + timedelta(days=i)).isoformat(), "hrv_ms": hrv(i), "resting_hr": 60,
             "sleep_hours": sleep(i), "readiness": readiness(i), "steps": steps(i), "active_zone_min": 30,
             **{k: f(i) for k, f in extra.items()}}
            for i in range(n)]


def _keys(out):
    return {i["key"]: i for i in out["insights"]}


# --- sessions & steps --------------------------------------------------------------------------------------

def test_detected_session_takes_the_name_of_an_overlapping_log():
    workouts = [{"date": "2026-10-02", "start": "20:16", "activity": "Workout", "minutes": "113", "source": "detected"},
                {"date": "2026-10-02", "start": "21:40", "activity": "Swim", "minutes": "19", "source": "logged"}]
    (s,) = fitbit_sessions.training_sessions(workouts)
    assert s["activity"] == "Swim" and s["minutes"] == "113"


def test_walks_and_stuck_logs_are_not_training_but_unmatched_logs_are():
    workouts = [{"date": "2026-09-29", "start": "18:00", "activity": "Walk", "minutes": "30", "source": "detected"},
                {"date": "2026-09-23", "start": "14:49", "activity": "Strength training", "minutes": "1479",
                 "avg_hr": "71", "source": "logged"},
                {"date": "2026-09-30", "start": "19:00", "activity": "Strength training", "minutes": "60",
                 "avg_hr": "110", "source": "logged"}]
    sessions = fitbit_sessions.training_sessions(workouts)
    assert [(s["date"], s["minutes"]) for s in sessions] == [("2026-09-30", "60")]


def test_steps_value_drops_low_wear_days_and_prefers_the_filled_in_estimate():
    assert fitbit_sessions.steps_value({"steps": 2000, "wear_hours": 4}) is None
    assert fitbit_sessions.steps_value({"steps": 8000, "steps_est": 9500, "wear_hours": 12}) == 9500
    assert fitbit_sessions.steps_value({"steps": 8000}) == 8000  # older rows without wear data


def test_week_uses_detected_sessions_and_trusted_steps():
    rows = [{"date": "2026-09-29", "steps": "3000", "wear_hours": "4"},
            {"date": "2026-09-30", "steps": "9000", "steps_est": "11000", "wear_hours": "12"}]
    workouts = [{"date": "2026-09-30", "start": "18:00", "activity": "Workout", "minutes": "60", "source": "detected"}]
    out = gym.build(rows, workouts, GOALS, today=date(2026, 10, 1))
    assert out["this_week"]["workouts"] == 1 and out["this_week"]["steps_avg"] == 11000
    assert out["steps_streak"] == 1  # the low-wear day is skipped, not counted as a miss


# --- panels ------------------------------------------------------------------------------------------------

def test_clock_formats_hours_past_midnight():
    assert health_panels.clock(25.5) == "1:30 AM" and health_panels.clock(23.25) == "11:15 PM"


def test_sleep_schedule_spread_and_debt():
    rows = _rows(n=8, sleep=lambda i: 6.5, bed_clock=lambda i: 23 if i % 2 else 26, wake_clock=lambda i: 9)
    panel = health_panels.sleep_schedule(rows, 7.5)
    assert panel["bedtime_spread_min"] == 90 and panel["sleep_debt_hours"] == 7.0


def test_training_load_bands():
    assert health_panels.training_load([{"date": "d", "load_ratio": 0.7}])["band"] == "under"
    assert health_panels.training_load([{"date": "d", "load_ratio": 1.1}])["band"] == "optimal"
    assert health_panels.training_load([{"date": "d", "load_ratio": 1.6}])["band"] == "very_high"


def test_skin_temperature_deviation_is_against_previous_nights():
    rows = _rows(n=8, skin_temp_c=lambda i: 34.6 if i == 7 else 34.0)
    assert health_panels.skin_temperature(rows)["deviation_c"] == 0.6


# --- insights ----------------------------------------------------------------------------------------------

def test_flags_hrv_drop_against_baseline_as_action():
    rows = _rows(hrv=lambda i: 90 if i < 14 else 70)
    out = health_insights.build(rows, [], GOALS, today=START + timedelta(days=21))
    rec = _keys(out)["recovery"]
    assert rec["tone"] == "act" and "70 milliseconds" in rec["finding"]
    assert out["recovery"]["hrv_ms"]["change_pct"] == -22.2
    assert out["insights"][0]["tone"] == "act"  # actions sort first


def test_stable_recovery_reads_as_good():
    out = health_insights.build(_rows(), [], GOALS, today=START + timedelta(days=21))
    assert _keys(out)["recovery"]["tone"] == "good"


def test_sleep_lever_compares_readiness_after_long_vs_short_nights():
    rows = _rows(sleep=lambda i: 8 if i % 2 else 6, readiness=lambda i: 70 if i % 2 else 45)
    lever = _keys(health_insights.build(rows, [], GOALS))["sleep_lever"]
    assert "70" in lever["finding"] and "45" in lever["finding"]


def test_weak_night_attributes_sleep_to_the_night_before_wake_date():
    rows = _rows(sleep=lambda i: 5.5 if (START + timedelta(days=i)).weekday() == 4 else 7.8)
    weak = _keys(health_insights.build(rows, [], GOALS))["weak_night"]
    assert weak["title"].startswith("Thursday nights") and "Friday Daily Readiness" in weak["finding"]


def test_irregular_bedtime_and_hot_night_become_actions():
    rows = _rows(bed_clock=lambda i: 23 if i % 2 else 26, wake_clock=lambda i: 9,
                 skin_temp_c=lambda i: 35.0 if i == 20 else 34.0)
    keys = _keys(health_insights.build(rows, [], GOALS))
    assert keys["schedule"]["tone"] == "act" and keys["temperature"]["tone"] == "act"


def test_steps_gap_names_lowest_weekdays():
    rows = _rows(steps=lambda i: 4000 if (START + timedelta(days=i)).weekday() == 1 else 9000)
    steps = _keys(health_insights.build(rows, [], GOALS))["steps"]
    assert "Tuesdays" in steps["finding"] and steps["tone"] == "watch"


def test_too_little_data_yields_no_recovery_read():
    out = health_insights.build(_rows(n=5), [], GOALS)
    assert out["recovery"] is None and "recovery" not in _keys(out)


def test_insight_text_has_no_abbreviations():
    rows = _rows(hrv=lambda i: 90 if i < 14 else 70, sleep=lambda i: 8 if i % 2 else 6,
                 readiness=lambda i: 70 if i % 2 else 45, bed_clock=lambda i: 23 if i % 2 else 26,
                 wake_clock=lambda i: 9, skin_temp_c=lambda i: 35.0 if i == 20 else 34.0,
                 vo2max=lambda i: 50 + i * 0.1, load_ratio=lambda i: 1.6, wear_hours=lambda i: 5 if i % 3 else 12)
    for i in health_insights.build(rows, [], GOALS)["insights"]:
        text = " ".join((i["title"], i["finding"], i["action"]))
        assert not ABBREVIATIONS.search(text.replace("VO2 max:", "")), text


def test_meters_skip_the_exports_cut_off_final_day():
    rows = [{"date": "2026-10-05", "steps": "9000", "active_zone_min": "60", "wear_hours": "14"},
            {"date": "2026-10-06", "steps": "1180", "active_zone_min": "0", "wear_hours": "1.5"}]
    out = gym.build(rows, [], GOALS, today=date(2026, 10, 12))
    assert out["this_week"]["end"] == "2026-10-05" and out["this_week"]["azm"] == 60
