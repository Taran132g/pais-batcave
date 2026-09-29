"""Refresh data/academics.json from Canvas. Run by pais-cave-canvas.timer every 30 minutes."""
import json
import sys

import httpx

from . import canvas, config

OUT = config.ROOT / "data/academics.json"


def main() -> int:
    try:
        data = canvas.fetch()
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        hint = "Canvas rejected the token; make a new one and update CANVAS_TOKEN." if code == 401 else f"Canvas HTTP {code}"
        data = {"status": "error", "error": hint, "timetable": canvas.load_timetable()}
    except httpx.HTTPError as exc:
        data = {"status": "error", "error": f"Canvas unreachable: {type(exc).__name__}", "timetable": canvas.load_timetable()}
    if data.get("status") == "error" and OUT.exists():  # keep the last good pull, flag it
        last = json.loads(OUT.read_text())
        if last.get("status") == "ok":
            data = {**last, "warning": data["error"]}
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(OUT)
    print(f"[academics] {data.get('status')} · {len(data.get('todo', []))} to-do · {len(data.get('tests', []))} tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
