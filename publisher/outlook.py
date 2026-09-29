"""Trading tab's "Market outlook" card: the latest X outlook run plus a short bias history."""
import json
from pathlib import Path

HISTORY_RUNS = 6  # three weeks of Mon/Fri runs


def build(data_dir: Path) -> dict:
    latest_file = data_dir / "latest.json"
    if not latest_file.exists():
        return {"status": "awaiting data"}
    latest = json.loads(latest_file.read_text())
    runs = sorted(p for p in data_dir.glob("20*.json"))[-HISTORY_RUNS:]
    history = []
    for path in reversed(runs):
        try:
            run = json.loads(path.read_text())
        except json.JSONDecodeError:
            continue
        history.append({"until": run["until"], "overall": (run.get("overall") or {}).get("bias"),
                        "sources": {s["handle"]: s.get("bias") for s in run.get("sources", [])}})
    if "overall" not in latest:  # only a failed attempt so far
        return {"status": "error", "last_attempt": latest.get("last_attempt"), "history": history}
    return {**latest, "history": history}
