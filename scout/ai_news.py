"""Morning AI newsletter for the JOB tab: 6 stories from the last ~2 days, each with why it matters
to Taran, plus one thing to learn. Runs on the Mac (LaunchAgent com.taran.pais-ainews, 6:30 + hourly,
no-op once today's issue exists); the publisher ships the newest issue in snapshot.json.
"""
import json
import re
import sys
from datetime import datetime

from daily_jobs import ROOT, TZ, claude_web, verify

OUT_DIR = ROOT / "data/ai_news"
STORIES = 6
KEEP_ISSUES = 14

PROMPT = """You are the editor of a short daily AI newsletter for Taranveer Singh: a Penn State AI Engineering student
(graduating May 2028) hunting Summer 2027 AI/ML and software internships, who also trades crypto and stocks. Today is {today}.

Use WebSearch to find the {n} most important AI stories published in the last 48 hours (widen to 72 hours only if needed).
Cover a spread: new models or products, research, industry moves and funding, developer tools, policy, and AI hiring or
the AI job market. Skip rumours, listicles and repeats of these recent headlines: {recent}.

For each story give the ORIGINAL source URL (company blog, paper, or a major outlet), not an aggregator.
Write plainly, like a smart friend, with no hype and no em dashes.

Output ONLY this JSON, no prose:
{{"headline": "<one-line theme of the day>",
  "stories": [{{"topic": "models|research|industry|tools|policy|jobs", "title": "", "source": "", "url": "",
               "published": "YYYY-MM-DD", "summary": "<2 sentences on what happened>",
               "why": "<1 sentence on why it matters for Taranveer: skills to learn, interview talking point, companies hiring, or market impact>"}}],
  "learn": {{"title": "<one concept or tool to learn today>", "why": "<1 sentence>", "url": "<good free resource>"}}}}"""


def parse_issue(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", re.sub(r"```(?:json)?", "", raw), re.S)
    try:
        issue = json.loads(m.group(0)) if m else None
    except json.JSONDecodeError:
        return None
    if not isinstance(issue, dict):
        return None
    stories = [s for s in issue.get("stories") or [] if isinstance(s, dict) and s.get("title")
               and str(s.get("url", "")).startswith("https://")]
    if not stories:
        return None
    learn = issue.get("learn") if isinstance(issue.get("learn"), dict) else None
    return {"headline": str(issue.get("headline") or ""), "stories": stories, "learn": learn}


def recent_titles() -> list[str]:
    titles = []
    for f in sorted(OUT_DIR.glob("*.json"))[-3:]:
        try:
            titles += [s["title"] for s in json.loads(f.read_text())["stories"]]
        except (OSError, json.JSONDecodeError, KeyError):
            continue
    return titles


def main() -> int:
    today = datetime.now(TZ).date().isoformat()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{today}.json"
    if path.exists():
        return 0
    issue = parse_issue(claude_web(PROMPT.format(today=today, n=STORIES, recent="; ".join(recent_titles()) or "none")))
    if not issue:
        print("[ai-news] no usable issue; will retry next run", file=sys.stderr)
        return 1
    issue["stories"] = verify(issue["stories"])   # drops dead links (fails open on our own network errors)
    issue.update(date=today, generated_at=datetime.now(TZ).isoformat())
    path.write_text(json.dumps(issue, indent=1))
    for old in sorted(OUT_DIR.glob("*.json"))[:-KEEP_ISSUES]:
        old.unlink()
    print(f"[ai-news] {today}: {len(issue['stories'])} stories · {issue['headline']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
