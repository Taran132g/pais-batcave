"""Daily texts. `python -m cave.brief morning` (9:00 ET) and `python -m cave.brief evening` (20:00 ET).

Morning: yesterday across trading / applications / school / gym, then today's classes, what's due,
the next test and today's six applications. Evening: only if today's applications aren't all done.
Text builders are pure (unit-tested); main() gathers the data and sends via notify.
"""
import json
import sys
from datetime import date, datetime, time as dtime, timedelta

from . import canvas, config, daily_goal, notify
from .canvas import TZ, next_test
from .portfolio import portfolio

SITE = "getpais.company"
CAT_LABEL = {"finance": "FIN", "software": "SWE"}


def _money(v: float) -> str:
    return f"{'-' if v < 0 else ''}${abs(v):,.0f}" if abs(v) >= 100 else f"{'-' if v < 0 else ''}${abs(v):,.2f}"


def _signed(v: float) -> str:
    return f"{'+' if v >= 0 else '-'}{_money(abs(v))}"


def _t(iso: str) -> str:
    d = datetime.fromisoformat(iso).astimezone(TZ)
    return d.strftime("%-I:%M%p").lower().replace(":00", "")


def _clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return dtime(h, m).strftime("%-I:%M%p").lower().replace(":00", "")


def equity_change(samples: list, day: date) -> tuple[float, float] | None:
    """(start, end) whole-portfolio equity across `day` in ET, from the 20 s samples."""
    start = datetime.combine(day, dtime(), TZ).timestamp()
    end = start + 86400
    before = [v for t, v in samples if t < start]
    during = [v for t, v in samples if start <= t < end]
    if not during:
        return None
    return (before[-1] if before else during[0]), during[-1]


def trading_line(change: tuple[float, float] | None, port: dict | None) -> str:
    parts = []
    if change:
        a, b = change
        pct = (b / a - 1) * 100 if a else 0
        parts.append(f"{_money(b)} ({_signed(b - a)}, {pct:+.1f}%)")
    if port:
        parts.append(f"MTD {port['mtd_pct']:+.1f}% vs {port['target_pct']:g}% goal")
    return "Trading: " + (" · ".join(parts) if parts else "no readings")


def jobs_line(goal: dict, events: list[dict], day: date) -> str:
    todays = [e for e in events if datetime.fromisoformat(e["date"]).astimezone(TZ).date() == day]
    count = lambda stage: [e["company"] for e in todays if e["stage"] == stage]
    bits = [f"{goal['done']}/{goal['total']} daily apps" if goal.get("total") else "no daily list"]
    if count("submitted"):
        n = len(count("submitted"))
        bits.append(f"{n} confirmation{'s' * (n != 1)}")
    for stage, label in (("interview", "interview"), ("assessment", "OA"), ("offer", "OFFER")):
        if count(stage):
            bits.append(f"{label}: {', '.join(sorted(set(count(stage))))}")
    if count("rejected"):
        n = len(count("rejected"))
        bits.append(f"{n} rejection{'s' * (n != 1)}")
    return "Jobs: " + " · ".join(bits)


def school_line(ac: dict) -> str | None:
    if ac.get("status") != "ok":
        return None
    y = ac["yesterday"]
    bits = [f"{y['done']}/{y['due']} due items done" if y["due"] else "nothing was due"]
    if y["missed"]:
        bits.append("missed: " + ", ".join(y["missed"][:3]))
    if ac.get("missing"):
        bits.append(f"{ac['missing']} missing total")
    return "School: " + " · ".join(bits)


def gym_line(gym: dict) -> str | None:
    latest = (gym or {}).get("latest") if (gym or {}).get("status") == "ok" else None
    if not latest:
        return None
    bits = []
    if latest.get("steps") not in (None, ""):
        bits.append(f"{int(float(latest['steps'])):,} steps")
    if latest.get("sleep_hours") not in (None, ""):
        bits.append(f"{float(latest['sleep_hours']):.1f}h sleep")
    return f"Gym ({latest.get('date', '')[5:]}): " + " · ".join(bits) if bits else None


def today_lines(ac: dict, today: date) -> list[str]:
    classes = ac.get("classes_today") or []
    lines = ["Classes: " + (" | ".join(f"{_clock(c['start'])} {c['course']}" + (f" ({c['room']})" if c.get("room") else "")
                                       for c in classes) if classes else "none today")]
    if ac.get("status") == "no_token":
        lines.append("Canvas not connected yet (add CANVAS_TOKEN).")
        return lines
    if ac.get("status") != "ok":
        return lines
    due = [i for i in ac["todo"] if datetime.fromisoformat(i["due"]).date() == today]
    lines.append("Due today: " + (" | ".join(f"{i['course']} {i['title']} {_t(i['due'])}" for i in due) if due else "nothing"))
    soon = [i for i in ac["todo"] if today < datetime.fromisoformat(i["due"]).date() <= today + timedelta(days=3)]
    if soon:
        lines.append(f"Next 3 days: {len(soon)} more (" + ", ".join(f"{i['course']} {i['title']}" for i in soon[:3]) + ")")
    t = next_test(ac.get("tests") or [])
    if t:
        d = datetime.fromisoformat(t["due"]).date()
        n = (d - today).days
        lines.append(f"Next test: {t['course']} {t['title']} · {d.strftime('%a %b %-d')} ({'TODAY' if n == 0 else f'{n}d'})")
    else:
        lines.append("Next test: none on Canvas")
    return lines


def jobs_list(goal: dict) -> list[str]:
    return [f"{'✓' if j['done'] else '•'} {CAT_LABEL.get(j.get('category'), '')} {j['company']} - {j['role']}"
            for j in goal.get("jobs", [])]


def morning_text(today: date, yesterday_bits: list[str | None], ac: dict, goal_today: dict) -> str:
    lines = [f"PAIS · {today.strftime('%a %b %-d')}", "", "YESTERDAY", *[b for b in yesterday_bits if b], "", "TODAY",
             *today_lines(ac, today), ""]
    if goal_today.get("total"):
        lines += [f"Apply today ({goal_today['done']}/{goal_today['total']}):", *jobs_list(goal_today),
                  f"Links + Claude prompt: {SITE} > JOB"]
    else:
        lines.append("Today's 6 jobs aren't scouted yet (Mac asleep?). Check the JOB tab later.")
    return "\n".join(lines)


def evening_text(goal: dict) -> str | None:
    if goal.get("complete"):
        return None
    if not goal.get("total"):
        return "PAIS 8pm: no job list was scouted today (the Mac scout never ran, maybe it was asleep all day)."
    left = [j for j in goal["jobs"] if not j["done"]]
    return "\n".join([f"PAIS 8pm: {goal['done']}/{goal['total']} applications done. Still open:",
                      *(f"• {CAT_LABEL.get(j.get('category'), '')} {j['company']} - {j['role']}" for j in left),
                      f"Finish in Claude in Chrome ({SITE} > JOB has the prompt)."])


# ---------- I/O ----------

def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _academics() -> dict:
    return _read(config.ROOT / "data/academics.json", None) or canvas.fetch()


def morning(now: datetime) -> str:
    today, yday = now.date(), now.date() - timedelta(days=1)
    snap = _read(config.SNAPSHOT_FILE, {})
    try:
        port = portfolio(snap.get("roi") or {})
    except Exception:  # noqa: BLE001 - the text still goes out without the goal line
        port = None
    samples = [tuple(p) for p in _read(config.ROOT / "data/intraday.json", []) if isinstance(p, list)]
    ac = _academics()
    events = _read(daily_goal.EVENTS_FILE, [])
    bits = [trading_line(equity_change(samples, yday), port), jobs_line(daily_goal.for_day(yday), events, yday),
            school_line(ac), gym_line(snap.get("gym") or {})]
    return morning_text(today, bits, ac, daily_goal.for_day(today))


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "morning"
    now = datetime.now(TZ)
    dry = "--dry" in argv
    if mode == "morning":
        subject, text = f"PAIS brief {now:%b %-d}", morning(now)
    elif mode == "evening":
        subject, text = "PAIS: applications not done", evening_text(daily_goal.for_day(now.date()))
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 2
    if not text:
        print(f"[brief] {mode}: nothing to send (goal complete)")
        return 0
    print(text)
    print(f"[brief] {mode}: {'dry run' if dry else notify.send(subject, text)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
