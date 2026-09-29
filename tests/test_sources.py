import json
from datetime import datetime

from server import config
from server.sources import desktop_runs
from server.sources.common import cron_next


def test_cron_next_daily_and_weekly():
    now = datetime(2026, 9, 28, 13, 0)  # Monday
    assert cron_next("0 8 * * *", now) == datetime(2026, 9, 29, 8, 0)
    assert cron_next("30 14 * * 5", now) == datetime(2026, 10, 2, 14, 30)
    assert cron_next("CRON_TZ=America/New_York 50 11 * * 1-5", now) == datetime(2026, 9, 29, 11, 50)
    assert cron_next("garbage", now) is None


def _make_run(account, name, task, created_ms, result=None, error=None):
    meta = {"scheduledTaskId": task, "createdAt": str(created_ms), "lastActivityAt": str(created_ms + 60000)}
    if error:
        meta["error"] = error
    (account / f"{name}.json").write_text(json.dumps(meta))
    folder = account / name
    folder.mkdir()
    lines = [json.dumps({"type": "assistant", "message": {}})]
    if result is not None:
        lines.append(json.dumps({"type": "result", "result": result, "is_error": False, "duration_ms": 120000}))
    (folder / "audit.jsonl").write_text("\n".join(lines) + "\n")


def test_runs_reads_final_report_newest_first(tmp_path, monkeypatch):
    account = tmp_path / "acct" / "org"
    account.mkdir(parents=True)
    (account / "scheduled-tasks.json").write_text(json.dumps({"scheduledTasks": [
        {"id": "daily", "cronExpression": "0 8 * * *", "enabled": True}]}))
    _make_run(account, "local_a", "daily", 1_000, result="## Brief\nall good")
    _make_run(account, "local_b", "daily", 2_000, error="Unable to start session")
    _make_run(account, "local_c", "other", 3_000, result="not mine")
    monkeypatch.setattr(config, "DESKTOP_SESSIONS", tmp_path)

    runs = desktop_runs.runs("daily")
    assert [r["status"] for r in runs] == ["failed", "done"]
    assert runs[1]["report"].startswith("## Brief")
    assert runs[1]["duration_s"] == 120
    assert runs[0]["error"] == "Unable to start session"
    assert desktop_runs.schedules()["daily"]["next_run"] is not None
