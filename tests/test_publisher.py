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
    out = gym.build(rows, workouts, goals, today=date(2026, 10, 12))
    # Meters cover the 7 days ending at the export's last day (Sep 22-28), not the calendar week of `today`.
    assert out["this_week"]["end"] == "2026-09-28"
    assert out["this_week"]["workouts"] == 1 and out["this_week"]["azm"] == 70
    assert out["progress"]["workouts"] == 0.25
    assert out["steps_streak"] == 2
    assert gym.build([], [], goals)["status"] == "awaiting data"


def test_roi_history_uses_resolved_month_start_for_current_month():
    snaps = [{"as_of": "2026-09-28T12:00:00Z", "equity_usd": 1000.0}]
    out = roi.build(snaps, "Month-start total balance was $800.00", 20, today=date(2026, 9, 28))
    assert out["history"][-1] == {"month": "2026-09", "start": 800.0, "end": 1000.0,
                                     "start_source": "morning brief", "return_pct": 25.0, "transfers_out": 0.0}


def test_month_history_prefers_stated_month_start_over_first_reading():
    from publisher.roi import monthly_history
    snaps = [{"as_of": "2026-09-28T12:00:00Z", "equity_usd": 1256.14},                                  # no month-start field
             {"as_of": "2026-09-29T16:00:00Z", "equity_usd": 1241.33, "month_start_balance": 884.28},
             {"as_of": "2026-09-30T12:00:00Z", "equity_usd": 1177.67, "month_start_balance": 887.09},
             {"as_of": "2026-10-02T15:00:00Z", "equity_usd": 1071.55}]
    sep, oct_ = monthly_history(snaps)
    assert (sep["start"], sep["end"], sep["start_source"]) == (887.09, 1177.67, "stated")
    assert sep["return_pct"] == 32.76
    assert (oct_["start"], oct_["start_source"]) == (1071.55, "first reading")


def test_roi_adds_back_profit_moved_to_coinbase():
    from datetime import date
    from publisher import roi
    snaps = [{"as_of": "2026-10-12T03:40:01Z", "equity_usd": 1431.91, "wallet_balance": 989.87, "month_start_balance": 1057.44}]
    transfers = [{"date": "2026-10-08", "from": "yubit", "to": "coinbase", "amount": 300}]
    out = roi.build(snaps, "", 20, today=date(2026, 10, 12), transfers=transfers)
    assert out["transfers_out"] == 300
    assert out["mtd_pct"] == round((1731.91 / 1057.44 - 1) * 100, 2)
    assert out["history"][-1]["return_pct"] == out["mtd_pct"]


def test_net_out_counts_money_received_as_negative():
    from publisher import roi
    t = [{"date": "2026-10-08", "from": "yubit", "to": "coinbase", "amount": 300}]
    assert roi.net_out(t, "2026-10", "coinbase") == -300
    assert roi.net_out(t, "2026-09", "yubit") == 0


def test_grades_section_reads_browser_sync_file(tmp_path, monkeypatch):
    from publisher import publish
    f = tmp_path / "grades.json"
    monkeypatch.setattr(publish, "GRADES_FILE", f)
    assert publish._grades() == {"status": "none"}
    f.write_text('{"synced_at": "2026-10-18T18:15:00-04:00", "grades": [{"course": "CMPSC 448", "score": 83.33, "grade": "B"}]}')
    out = publish._grades()
    assert out["status"] == "ok" and out["grades"][0]["course"] == "CMPSC 448"


def test_withdrawals_out_of_the_portfolio_are_tracked_per_account_and_overall():
    snaps = [{"as_of": "2026-10-12T12:00:00Z", "equity_usd": 1400.0, "wallet_balance": 1400.0,
              "month_start_balance": 1000.0}]
    transfers = [{"date": "2026-10-08", "from": "yubit", "to": "coinbase", "amount": 300},
                 {"date": "2026-10-17", "from": "coinbase", "to": "external", "amount": 250}]
    out = roi.build(snaps, "", 20, today=date(2026, 10, 20), transfers=transfers)
    assert out["transfers_out"] == 300               # Yubit: sent 300 to Coinbase
    assert out["coinbase_transfers_out"] == -50      # Coinbase: got 300, sent 250 away
    assert out["external_out"] == 250                # left the portfolio: the combined return adds it back
