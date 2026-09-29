"""Oracle-side Job tab: scan Gmail and write data/job.json. Run by pais-cave-jobs.timer every 15 min
(the Gmail scan itself is cached/incremental, so real IMAP work happens at most every 30 min)."""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

from . import config

os.environ.setdefault("PAIS_GMAIL_ENV", str(config.LOCAL_ENV_FILE))
os.environ.setdefault("PAIS_GMAIL_CACHE", str(config.ROOT / "data/gmail_jobs_cache.json"))

from . import gmail_jobs, job  # noqa: E402  (env must be set before gmail_jobs reads its paths)

OUT = config.ROOT / "data/job.json"
EVENTS_OUT = config.ROOT / "data/job_events.json"   # recent events for the daily application goal
EVENTS_DAYS = 14


def main() -> int:
    goals = json.loads((config.ROOT / "goals.json").read_text())
    result = gmail_jobs.events()
    if "AUTHENTICATIONFAILED" in (result.get("error") or ""):
        result["error"] = "Gmail rejected the app password on the server. Update GMAIL_APP_PASSWORD in ~/pais-cave/.env."
    data = job.build(result, goals["job"])
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(OUT)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=EVENTS_DAYS)).isoformat()
    recent = [e for e in result.get("events", []) if e["date"] >= cutoff]
    tmp = EVENTS_OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(recent))
    tmp.chmod(0o600)
    tmp.replace(EVENTS_OUT)
    print(f"[jobs] {data.get('status')} · {data.get('counts', {}).get('applications', 0)} companies")
    return 0


if __name__ == "__main__":
    sys.exit(main())
