"""Internship pipeline: reuses agentic_os tools/job_sheet.py (vault note = source of truth)."""
import sys
from collections import Counter

from .. import config

if str(config.AGENTIC_OS) not in sys.path:
    sys.path.insert(0, str(config.AGENTIC_OS))

from tools import job_sheet  # noqa: E402

STATUSES = job_sheet.STATUSES


def summary() -> dict:
    data = job_sheet.rows()
    return {"rows": data, "statuses": STATUSES, "counts": dict(Counter(r["status"] for r in data))}


def set_status(url: str, status: str) -> bool:
    if status not in STATUSES:
        raise ValueError(f"Unknown status: {status}")
    return job_sheet.set_status(url, status)
