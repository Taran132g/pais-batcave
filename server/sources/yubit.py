"""Yubit account snapshots (written by the daily/weekly desktop agents)."""
import json
from pathlib import Path

from .. import config


def _snapshot_files() -> list[Path]:
    files = {p.name: p for p in config.YUBIT_SNAPSHOTS.glob("yubit_nav_*.json")}
    # Runs not yet collected by nav_job still sit in the desktop session outputs.
    for p in config.DESKTOP_SESSIONS.glob("*/*/*/outputs/yubit_nav_*.json"):
        files.setdefault(p.name, p)
    return [files[name] for name in sorted(files)]


def _load(path: Path) -> dict | None:
    text = path.read_text()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        try:
            return json.loads(text[start:end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            return None


def snapshots() -> list[dict]:
    out = []
    for path in _snapshot_files():
        snap = _load(path)
        if snap:
            out.append(snap)
    return out


def summary() -> dict:
    snaps = snapshots()
    latest = snaps[-1] if snaps else None
    series = [{"t": s.get("as_of"), "equity": s.get("equity_usd")} for s in snaps if s.get("equity_usd") is not None]
    return {"latest": latest, "equity_series": series, "count": len(snaps)}
