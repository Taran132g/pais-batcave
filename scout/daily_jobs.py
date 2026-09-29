"""Morning scout: pick today's 6 applications (3 finance + 3 software) and push them to Oracle.

Runs on the Mac (LaunchAgent com.taran.pais-dailyjobs, 7:00 and again on wake) because `claude -p`
works here on Taran's subscription; Oracle's CLI login is rejected. Idempotent per day: once
today's list exists and is on Oracle, later runs exit immediately.

Oracle then (a) shows the list on the JOB tab, (b) ticks jobs off when Gmail confirmations
arrive, (c) texts at 9am with the list and at 8pm if any are still open.
"""
import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path.home() / "agentic_os"))

TZ = ZoneInfo("America/New_York")
ROOT = Path(__file__).resolve().parents[1]
LOCAL_DIR = ROOT / "data/daily_jobs"
HOST = "ubuntu@129.159.182.210"
SSH_KEY = str(Path.home() / ".ssh/oracle_pais.key")
REMOTE_DIR = "pais-cave/data/daily_jobs"
PER_CATEGORY = 3
ASK_PER_CATEGORY = 6          # over-ask: dead/closed URLs get dropped by the HTTP check
CLAUDE = os.environ.get("CLAUDE_BIN", "/opt/homebrew/bin/claude")
CLAUDE_TIMEOUT_S = 1200

PROFILE_FILE = Path.home() / "agentic_os/application_profile.md"
PROFILE_END = "### Cover letter"   # everything above this is form-fill facts

CATEGORIES = {
    "finance": ("Summer 2027 FINANCE internships: investment banking, sales & trading / markets, asset or wealth "
                "management, corporate finance, private equity/credit analyst, fintech business/finance roles, and "
                "technology or quant-analyst programs at banks and asset managers."),
    "software": ("Summer 2027 SOFTWARE ENGINEERING or AI/ML ENGINEERING internships or co-ops (backend, full-stack, "
                 "data, ML). Internships only, no new-grad or full-time."),
}


def _ssh(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", HOST, cmd],
                          capture_output=True, text=True, timeout=timeout)


def already_applied() -> list[str]:
    """Companies to skip: everything Gmail says Taran applied to, prior daily lists, and the vault pipeline."""
    names: set[str] = set()
    try:
        res = _ssh("cat ~/pais-cave/data/job.json")
        names |= {c["company"] for c in json.loads(res.stdout).get("companies", [])}
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        pass
    for f in LOCAL_DIR.glob("*.json"):
        try:
            names |= {j["company"] for j in json.loads(f.read_text())["jobs"]}
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    try:
        from tools import job_sheet
        names |= {r["company"] for r in job_sheet.rows() if r.get("company")}
    except Exception:  # noqa: BLE001 - vault may be mid-sync; the other sources still apply
        pass
    return sorted(n.strip() for n in names if n and n.strip())


def build_prompt(today: str, categories: dict[str, int], avoid: list[str]) -> str:
    wanted = "\n".join(f'- category "{c}": {n} roles. {CATEGORIES[c]}' for c, n in categories.items())
    return (
        f"You are a job scout for Taranveer Singh, a Penn State AI Engineering student (B.S., graduating May 2028; Python, "
        f"AWS, React, ML; co-founded an AI startup; trading-bot and DeFi experience). Today is {today}.\n"
        f"Use WebSearch to find currently OPEN postings for:\n{wanted}\n\n"
        f"Do NOT include any of these companies (already applied or queued): {', '.join(avoid[:150]) or 'none'}.\n"
        "Optimize for a realistic interview chance, not prestige: favour mid-size firms, regional banks, asset "
        "managers, insurers, fintechs, funded startups and companies that recruit at Penn State or in the "
        "Philadelphia / Pittsburgh area. At most one household-name firm per category.\n"
        "Each posting must have a DIRECT application URL (Workday, Greenhouse, Lever, Ashby, iCIMS or the "
        "company's own career site), not LinkedIn/Indeed/Handshake. An automated HTTP check drops dead links "
        "afterwards, so get the exact posting URL right.\n\n"
        'Output ONLY a JSON array, no prose: [{"category":"finance|software","company":"","role":"",'
        '"location":"","url":"","posted":"YYYY-MM-DD or \\"\\"","why":"<one short reason it fits>"}]'
    )


def run_claude(prompt: str) -> list[dict]:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # bill the subscription
    proc = subprocess.run([CLAUDE, "-p", prompt, "--model", "sonnet", "--allowedTools", "WebSearch,WebFetch",
                           "--dangerously-skip-permissions"], capture_output=True, text=True,
                          timeout=CLAUDE_TIMEOUT_S, env=env, cwd=str(ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"claude exited {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}")
    return parse_jobs(proc.stdout)


def parse_jobs(raw: str) -> list[dict]:
    m = re.search(r"\[.*\]", re.sub(r"```(?:json)?", "", raw), re.S)
    try:
        items = json.loads(m.group(0)) if m else []
    except json.JSONDecodeError:
        return []
    return [j for j in items if isinstance(j, dict) and j.get("category") in CATEGORIES
            and str(j.get("url", "")).startswith("http") and j.get("company")]


def pick(jobs: list[dict], have: list[dict], per_category: int = PER_CATEGORY) -> list[dict]:
    """Top up `have` to per_category per category from `jobs`, one role per company, no repeat URLs."""
    out = list(have)
    seen_co = {j["company"].lower() for j in out}
    seen_url = {j["url"] for j in out}
    for j in jobs:
        if sum(x["category"] == j["category"] for x in out) >= per_category:
            continue
        if j["company"].lower() in seen_co or j["url"] in seen_url:
            continue
        out.append({k: j.get(k, "") for k in ("category", "company", "role", "location", "url", "posted", "why")})
        seen_co.add(j["company"].lower())
        seen_url.add(j["url"])
    return sorted(out, key=lambda j: list(CATEGORIES).index(j["category"]))


def shortfall(jobs: list[dict]) -> dict[str, int]:
    return {c: ASK_PER_CATEGORY for c in CATEGORIES if sum(j["category"] == c for j in jobs) < PER_CATEGORY}


def verify(jobs: list[dict]) -> list[dict]:
    try:
        from tools.url_verify import filter_open
    except ImportError:
        return jobs
    kept, dropped = filter_open(jobs)
    for j in dropped:
        print(f"[daily-jobs] dropped closed link: {j['company']} {j['url']}", flush=True)
    return kept


def chrome_prompt(jobs: list[dict]) -> str:
    """The instructions Taran pastes into Claude in Chrome. Served only behind the site login (has PII)."""
    try:
        profile = PROFILE_FILE.read_text().split(PROFILE_END)[0].strip()
    except OSError:
        profile = "(application_profile.md unavailable: ask me for any detail you need)"
    listing = "\n".join(f"{i}. [{j['category']}] {j['company']} - {j['role']} ({j.get('location', '')}): {j['url']}"
                         for i, j in enumerate(jobs, 1))
    return (
        "Apply to these internship postings for me, one at a time, each in its own tab.\n\n"
        f"{listing}\n\n"
        "For each posting: open the link, click Apply, and fill in every field accurately using my profile below. "
        "If a site needs an account, create one with my email or sign in with Google if offered. Upload my resume "
        "when asked (ask me to attach the file if you can't). Answer short questions honestly from the profile; "
        "never invent experience. Before the final Submit, show me a one-line summary and wait for my OK. "
        "If a posting is closed or broken, tell me and move to the next one. At the end, list which ones were "
        "submitted.\n\n"
        f"MY PROFILE\n{profile}"
    )


def push(path: Path) -> None:
    _ssh(f"mkdir -p ~/{REMOTE_DIR} && chmod 700 ~/{REMOTE_DIR}")
    subprocess.run(["scp", "-i", SSH_KEY, "-q", "-o", "BatchMode=yes", str(path), f"{HOST}:{REMOTE_DIR}/{path.name}"],
                   check=True, timeout=60)


def on_oracle(name: str) -> bool:
    try:
        return _ssh(f"test -s ~/{REMOTE_DIR}/{name}").returncode == 0
    except subprocess.SubprocessError:
        return False


def main() -> int:
    today = datetime.now(TZ).date().isoformat()
    LOCAL_DIR.mkdir(parents=True, exist_ok=True)
    path = LOCAL_DIR / f"{today}.json"
    if path.exists():
        if not on_oracle(path.name):
            push(path)
            print(f"[daily-jobs] re-pushed {path.name}")
        return 0
    avoid = already_applied()
    jobs: list[dict] = []
    for attempt in range(2):
        need = shortfall(jobs)
        if not need:
            break
        found = verify(run_claude(build_prompt(today, need, avoid + [j["company"] for j in jobs])))
        jobs = pick(found, jobs)
        print(f"[daily-jobs] attempt {attempt + 1}: {len(jobs)} jobs", flush=True)
    if not jobs:
        print("[daily-jobs] scout found nothing usable; will retry on the next run", file=sys.stderr)
        return 1
    payload = {"date": today, "scouted_at": datetime.now(TZ).isoformat(), "jobs": jobs,
               "claude_prompt": chrome_prompt(jobs)}
    path.write_text(json.dumps(payload, indent=1))
    push(path)
    try:  # keep the vault Job Pipeline in step (the old Fill button works off it)
        from tools import job_sheet
        job_sheet.append_jobs(jobs)
    except Exception as exc:  # noqa: BLE001 - pipeline sync is best-effort
        print(f"[daily-jobs] vault pipeline not updated: {exc}", flush=True)
    for j in jobs:
        print(f"  {j['category']:8} {j['company']} - {j['role']}  {j['url']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
