"""The roster: every automated agent Taran runs, with live status where the Mac can see it."""
from . import desktop_runs, fitbit
from .. import config
from .common import launchd_status, tail_lines

SITE_STEP = "getpais.company refreshes automatically when the run's output lands"

ROSTER = [
    {"id": "daily-yubit", "name": "Daily Yubit Agent", "codename": "ORACLE", "goal": "trading",
     "kind": "desktop", "task_id": "daily-trading-assistant-open-positions", "schedule": "Daily 8:00 AM",
     "what": "Daily audit of your Yubit account against the 20% monthly goal.",
     "how": ["Claude desktop task opens Yubit read-only in your Chrome",
             "Pulls equity, positions and the full trade ledger",
             "MTD return vs 20%, category scoreboard, risk per trade, exit options",
             "Saves the day's NAV snapshot: one new point on the Trading equity graph",
             SITE_STEP]},
    {"id": "fitbit", "name": "Fitbit Agent", "codename": "VITALS", "goal": "gym",
     "kind": "desktop", "task_id": "weekly-yubit-nav-report", "label": "com.taran.fitbit-import",
     "log": config.FITBIT_LOG, "schedule": "Fridays 2:30 PM",
     # Same scheduled task used to be the Yubit audit; only count runs since it became the Fitbit sync.
     "history_since": "2026-09-28T23:00:00+00:00",
     "what": "Pulls your Fitbit data every week and feeds the Gym tab.",
     "how": ["Claude desktop task downloads last week's Fitbit export from Google Takeout",
             "Requests the next export so one is always ready",
             "Your Mac imports the zip: daily metrics plus every logged workout",
             SITE_STEP]},
    {"id": "internships", "name": "Internship Scout", "codename": "RECON", "goal": "job",
     "kind": "cloud", "schedule": "Weekdays 11:50 AM ET + daily watchlist 9 AM ET",
     "what": "Finds Summer 2027 internships and preps applications for you to submit.",
     "how": ["Claude routine searches Penn State-heavy recruiters and job boards",
             "Fills applications in Chrome and stops before submit",
             "Oracle watchlist pings Telegram when a watched bank opens a req",
             "Job tab tracks results straight from Gmail: confirmations, OAs, interviews, offers"]},
]


def _desktop(agent: dict, schedules: dict) -> dict:
    sched = schedules.get(agent["task_id"], {})
    history = [r for r in desktop_runs.runs(agent["task_id"], limit=8)
               if (r["started"] or "") >= agent.get("history_since", "")]
    last = history[0] if history else None
    return {
        "cron": sched.get("cron"), "enabled": sched.get("enabled"), "next_run": sched.get("next_run"),
        "status": last["status"] if last else "never run",
        "last_run": last["started"] if last else None,
        "report": last["report"] if last else "",
        "history": [{k: h[k] for k in ("started", "status", "duration_s")} for h in history],
    }


def _launchd(agent: dict) -> dict:
    status = launchd_status(agent["label"])
    healthy = status.get("loaded") and status.get("last_exit") in (None, "0", "(never exited)")
    extra = {"days": fitbit.summary()["days"]} if agent["id"] == "fitbit" else {}
    return {
        "enabled": status.get("loaded", False),
        "status": "armed" if healthy else "fault" if status.get("loaded") else "offline",
        "log": tail_lines(agent["log"], 12), **extra,
    }


def roster() -> list[dict]:
    schedules = desktop_runs.schedules()
    out = []
    for agent in ROSTER:
        base = {k: v for k, v in agent.items() if k not in ("log",)}
        base["log"] = None
        if agent["kind"] == "desktop":
            base.update(_desktop(agent, schedules))
            if agent.get("label"):
                importer = _launchd(agent)
                base.update({"importer": importer["status"], "log": importer["log"], "days": importer.get("days")})
        elif agent["kind"] == "launchd":
            base.update(_launchd(agent))
        else:
            base.update({"status": "cloud", "enabled": True})
        out.append(base)
    return out
