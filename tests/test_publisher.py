from datetime import date

from publisher import gym, job, roi


def test_roi_uses_snapshot_month_start_and_flags_hit():
    snaps = [{"as_of": "2026-09-28T12:00:00Z", "equity_usd": 1256.14, "month_start_balance": 883.73, "positions": []}]
    out = roi.build(snaps, "", 20, today=date(2026, 9, 28))
    assert out["mtd_pct"] == 42.14
    assert out["target_balance"] == 1060.48
    assert out["remaining_usd"] == 0 and out["hit"] is True
    assert out["month_start_source"] == "snapshot"


def test_roi_falls_back_to_morning_brief_text():
    snaps = [{"as_of": "2026-09-28T12:00:00Z", "equity_usd": 1000.0}]
    brief = "Month-start total balance (futures + CFD) was $800.00; you're now at ..."
    out = roi.build(snaps, brief, 20, today=date(2026, 9, 28))
    assert out["month_start"] == 800.0 and out["month_start_source"] == "morning brief"
    assert out["mtd_pct"] == 25.0


def test_roi_no_data():
    assert roi.build([], "", 20)["status"] == "no data"


def test_job_counts_from_gmail_events():
    events = [
        {"date": "2026-09-22T15:00:00+00:00", "stage": "submitted", "company": "Acme", "subject": "Thanks for applying"},
        {"date": "2026-09-10T15:00:00+00:00", "stage": "submitted", "company": "Beta", "subject": "Received"},
        {"date": "2026-09-12T15:00:00+00:00", "stage": "interview", "company": "Beta", "subject": "Interview"},
        {"date": "2026-09-20T15:00:00+00:00", "stage": "rejected", "company": "Beta", "subject": "Update"},
    ]
    out = job.build({"events": events}, {"deadline": "2027-03-31", "applications_goal": 150}, today=date(2026, 9, 28))
    c = out["counts"]
    assert (c["applications"], c["interviews"], c["rejections"], c["active"]) == (2, 1, 1, 1)
    assert out["weekly"][-2] == {"week": "2026-09-21", "applied": 1}
    assert out["days_to_deadline"] == 184


def test_job_reports_gmail_error():
    out = job.build({"error": "login failed"}, {"deadline": "2027-03-31"}, today=date(2026, 9, 28))
    assert out["status"] == "gmail_error" and out["days_to_deadline"] == 184


def test_gym_week_progress_and_streak():
    rows = [{"date": "2026-09-26", "steps": "12000", "active_zone_min": "40", "sleep_hours": "7"},
            {"date": "2026-09-28", "steps": "11000", "active_zone_min": "30", "sleep_hours": "8"}]
    workouts = [{"date": "2026-09-28", "start": "18:00", "activity": "Weights", "minutes": "60"}]
    goals = {"workouts_per_week": 4, "active_zone_min_per_week": 150, "steps_per_day": 10000, "sleep_hours": 7.5}
    out = gym.build(rows, workouts, goals, today=date(2026, 9, 29))
    assert out["this_week"]["workouts"] == 1 and out["this_week"]["azm"] == 30
    assert out["progress"]["workouts"] == 0.25
    assert out["steps_streak"] == 2
    assert gym.build([], [], goals)["status"] == "awaiting data"


def test_roi_history_uses_resolved_month_start_for_current_month():
    snaps = [{"as_of": "2026-09-28T12:00:00Z", "equity_usd": 1000.0}]
    out = roi.build(snaps, "Month-start total balance was $800.00", 20, today=date(2026, 9, 28))
    assert out["history"][-1] == {"month": "2026-09", "start": 800.0, "end": 1000.0, "return_pct": 25.0}
