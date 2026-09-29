"""Fitbit data from the Takeout importer's canonical CSV."""
import csv
import io

from .. import config
from .common import safe_read, tail_lines


def _num(value: str):
    try:
        f = float(value)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def rows() -> list[dict]:
    text = safe_read(config.FITBIT_CSV)
    if not text:
        return []
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        clean = {"date": row.pop("date")}
        clean.update({k: _num(v) for k, v in row.items() if v not in ("", None) and _num(v) is not None})
        out.append(clean)
    return out


def summary() -> dict:
    data = rows()
    return {
        "days": len(data),
        "rows": data[-120:],
        "dashboard_ready": config.FITBIT_DASHBOARD.exists(),
        "log": tail_lines(config.FITBIT_LOG, 8),
    }
