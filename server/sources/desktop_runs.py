"""Claude desktop scheduled tasks: schedules and each run's final report.

Each run is a session folder with <id>.json metadata (scheduledTaskId, timestamps)
and audit.jsonl whose final `{"type":"result"}` line holds the report text.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .. import config
from .common import cron_next

TAIL_BYTES = 4_000_000  # final result line sits at the end; don't read whole transcripts


def _account_dirs() -> list[Path]:
    return [p for p in config.DESKTOP_SESSIONS.glob("*/*") if p.is_dir() and (p / "scheduled-tasks.json").exists()]


def schedules() -> dict:
    out = {}
    for account in _account_dirs():
        try:
            data = json.loads((account / "scheduled-tasks.json").read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for task in data.get("scheduledTasks", []):
            nxt = cron_next(task.get("cronExpression", "")) if task.get("enabled") else None
            out[task["id"]] = {
                "cron": task.get("cronExpression"),
                "enabled": task.get("enabled", False),
                "last_run": task.get("lastRunAt"),
                "next_run": nxt.isoformat() if nxt else None,
            }
    return out


def _final_result(audit: Path) -> dict | None:
    try:
        size = audit.stat().st_size
        with audit.open("rb") as fh:
            fh.seek(max(0, size - TAIL_BYTES))
            lines = fh.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        if '"result"' not in line:  # cheap prefilter before parsing
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") != "result":
            continue
        return {"text": entry.get("result") or "", "ok": not entry.get("is_error"),
                "duration_s": round((entry.get("duration_ms") or 0) / 1000)}
    return None


def _ms_to_iso(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def runs(task_id: str, limit: int = 10) -> list[dict]:
    """Newest-first runs of one scheduled task, with the final report when finished."""
    found = []
    for account in _account_dirs():
        for meta_path in account.glob("local_*.json"):
            try:
                meta = json.loads(meta_path.read_text())
            except (OSError, json.JSONDecodeError):
                continue
            if meta.get("scheduledTaskId") != task_id:
                continue
            found.append((int(meta.get("createdAt") or 0), meta, meta_path.with_suffix("")))
    found.sort(key=lambda x: x[0], reverse=True)
    out = []
    for created, meta, folder in found[:limit]:
        result = _final_result(folder / "audit.jsonl")
        status = "done" if result and result["ok"] else "failed" if result or meta.get("error") else "no report"
        out.append({
            "started": _ms_to_iso(created),
            "finished": _ms_to_iso(meta.get("lastActivityAt")),
            "status": status,
            "error": meta.get("error"),
            "duration_s": result["duration_s"] if result else None,
            "report": result["text"] if result else "",
        })
    return out
