"""SMS-sized overview of the daily Yubit trading assistant's report, for the 9am text.

The report is long (goal tracker, scoreboards, news, positions, exit plans). When a new one
appears, `claude -p` condenses it once; the result is cached so the 5-minute publisher doesn't
re-summarize. Runs on the Mac because Oracle's claude login is rejected.
"""
import hashlib
import json
import os
import subprocess

from server import config
from server.sources import desktop_runs

TASK_ID = "daily-trading-assistant-open-positions"
CACHE = config.ROOT / "data/yubit_brief.json"
CLAUDE = os.environ.get("CLAUDE_BIN", "/opt/homebrew/bin/claude")
MAX_CHARS = 420
PROMPT = (
    "Below is today's report from my Yubit trading assistant. Write a text-message overview of at most "
    f"{MAX_CHARS} characters, plain text, no markdown, no emoji. Cover: (1) the market news that matters for my "
    "positions, (2) each open position in a few words (symbol, direction, P&L or status, any suggested action or "
    "stop), (3) month-to-date vs my 20% goal in one clause. If the report says the run failed or couldn't reach "
    "Yubit, say that in one sentence and what I need to do. Output only the overview.\n\nREPORT:\n"
)


def _summarize(text: str) -> str:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}   # bill the subscription
    proc = subprocess.run([CLAUDE, "-p", PROMPT + text[:30000], "--model", "haiku"], capture_output=True,
                          text=True, timeout=180, env=env, cwd=str(config.ROOT))
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-300:]}")
    return " ".join(proc.stdout.split())[:MAX_CHARS + 80]


def build() -> dict:
    report = desktop_runs.first_report(TASK_ID)
    if not report or not report["text"]:
        return {"status": "no report", "started": report and report["started"]}
    digest = hashlib.sha256(report["text"].encode()).hexdigest()
    try:
        cached = json.loads(CACHE.read_text())
    except (OSError, json.JSONDecodeError):
        cached = {}
    if cached.get("digest") == digest:
        return cached["brief"]
    brief = {"status": "ok", "started": report["started"], "run_ok": report["ok"], "summary": _summarize(report["text"])}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"digest": digest, "brief": brief}))
    return brief
