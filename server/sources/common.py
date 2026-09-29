"""Shared helpers for data sources: safe reads, launchd status, cron next-run."""
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from .. import config


def safe_read(path: Path) -> str | None:
    """Read via `cat` with a timeout so an iCloud-evicted file can't hang the server."""
    if not path.exists():
        return None
    try:
        out = subprocess.run(["cat", str(path)], capture_output=True, timeout=config.READ_TIMEOUT_S, check=True)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None
    return out.stdout.decode("utf-8", errors="replace")


def tail_lines(path: Path, n: int = 20) -> list[str]:
    text = safe_read(path)
    return text.splitlines()[-n:] if text else []


def launchd_status(label: str) -> dict:
    try:
        out = subprocess.run(["launchctl", "print", f"gui/{os.getuid()}/{label}"],
                             capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return {"loaded": False}
    if out.returncode != 0:
        return {"loaded": False}
    info = {"loaded": True}
    for line in out.stdout.splitlines():
        key, sep, value = line.strip().partition(" = ")
        if key == "state":
            info["state"] = value
        elif key == "last exit code":
            info["last_exit"] = value
        elif key == "runs":
            info["runs"] = value
    return info


def _cron_field(spec: str, lo: int, hi: int) -> set[int]:
    values = set()
    for part in spec.split(","):
        step = 1
        if "/" in part:
            part, step_s = part.split("/")
            step = int(step_s)
        if part == "*":
            start, end = lo, hi
        elif "-" in part:
            start, end = map(int, part.split("-"))
        else:
            start = end = int(part)
        values.update(range(start, end + 1, step))
    return values


def cron_next(expr: str, now: datetime | None = None) -> datetime | None:
    """Next local fire time for a 5-field cron (minute hour dom month dow); None if unparseable."""
    fields = [f for f in expr.split() if not f.startswith("CRON_TZ=")]
    if len(fields) != 5:
        return None
    try:
        minutes, hours = _cron_field(fields[0], 0, 59), _cron_field(fields[1], 0, 23)
        doms, months = _cron_field(fields[2], 1, 31), _cron_field(fields[3], 1, 12)
        dows = {d % 7 for d in _cron_field(fields[4], 0, 7)}
    except ValueError:
        return None
    t = (now or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(366 * 24 * 60):
        cron_dow = (t.weekday() + 1) % 7  # cron: Sunday=0
        if (t.minute in minutes and t.hour in hours and t.day in doms
                and t.month in months and cron_dow in dows):
            return t
        t += timedelta(minutes=1)
    return None
