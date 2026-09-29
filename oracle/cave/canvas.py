"""Academics tab + daily texts: Canvas (psu.instructure.com) grades, homework, tests and schedule.

Read-only Canvas API with Taran's personal access token (CANVAS_TOKEN in ~/pais-cave/.env).
Class meeting times aren't in Canvas, so the weekly timetable comes from ~/pais-cave/classes.json.
`build()` is pure (no network) so it's unit-tested; `fetch()` does the HTTP.
"""
import json
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import config
from .auth import _read_env_value

TZ = ZoneInfo("America/New_York")
DEFAULT_BASE = "https://psu.instructure.com"
PAST_DAYS, AHEAD_DAYS = 14, 75
CALENDAR_DAYS = 42
WEEKDAYS = "MTWRFSU"   # registrar letters: R = Thursday, U = Sunday

TEST_WORDS = re.compile(r"\b(exam|midterm|mid-term|final|quiz|test|prelim)\b", re.I)
NOT_A_TEST = re.compile(r"\b(practice|review|study guide|solutions?|key|makeup request|survey|corrections?)\b", re.I)
EXAM_WORDS = re.compile(r"\b(exam|midterm|mid-term|final|prelim)\b", re.I)
COURSE_CODE = re.compile(r"\b([A-Z]{1,5}(?:-[A-Z]{1,3})?\s?\d{3}[A-Z]?)\b")
WORK_TYPES = {"assignment", "quiz", "discussion_topic", "assessment_request"}


# ---------- pure ----------

def short_code(course: dict) -> str:
    for text in (course.get("course_code") or "", course.get("name") or ""):
        m = COURSE_CODE.search(text)
        if m:
            return re.sub(r"(?<=[A-Z])(?=\d)", " ", m.group(1))
    return course.get("course_code") or course.get("name") or "Course"


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(TZ)


def _grade(course: dict) -> dict:
    enr = next((e for e in course.get("enrollments") or [] if e.get("type") in ("student", "StudentEnrollment")), {})
    return {"score": enr.get("computed_current_score"), "grade": enr.get("computed_current_grade")}


def _is_test(title: str, kind: str) -> str | None:
    if NOT_A_TEST.search(title) or not TEST_WORDS.search(title) and kind != "quiz":
        return None
    return "exam" if EXAM_WORDS.search(title) else "quiz"


def _item(p: dict, codes: dict, base: str) -> dict | None:
    plannable = p.get("plannable") or {}
    due = _local(plannable.get("due_at") or plannable.get("todo_date") or p.get("plannable_date"))
    if due is None:
        return None
    subs = p.get("submissions") or {}
    done = bool(subs.get("submitted") or subs.get("excused") or (p.get("planner_override") or {}).get("marked_complete"))
    url = p.get("html_url") or ""
    return {
        "course": codes.get(p.get("course_id")) or p.get("context_name") or "",
        "title": plannable.get("title") or plannable.get("name") or "Untitled",
        "type": p.get("plannable_type"), "due": due.isoformat(),
        "url": url if url.startswith("http") else f"{base}{url}",
        "done": done, "missing": bool(subs.get("missing")) and not done,
        "graded": bool(subs.get("graded")), "points": plannable.get("points_possible"),
    }


def classes_on(day: date, timetable: list[dict]) -> list[dict]:
    letter = WEEKDAYS[day.weekday()]
    todays = [c for c in timetable if letter in (c.get("days") or "").upper()]
    return sorted(todays, key=lambda c: c.get("start") or "")


def build(courses: list[dict], planner: list[dict], events: list[dict], timetable: list[dict],
          now: datetime, base: str = DEFAULT_BASE) -> dict:
    today = now.astimezone(TZ).date()
    codes = {c["id"]: short_code(c) for c in courses}
    items = [i for i in (_item(p, codes, base) for p in planner) if i]
    tests = []
    for i in items:
        kind = _is_test(i["title"], i["type"] or "")
        if kind:
            tests.append({**i, "kind": kind})
    for e in events:  # instructor calendar events (exams are often posted this way)
        start = _local(e.get("start_at"))
        kind = _is_test(e.get("title") or "", "")
        if start and kind:
            tests.append({"course": codes.get(_course_id(e.get("context_code"))) or e.get("context_name") or "",
                          "title": e["title"], "type": "event", "due": start.isoformat(), "url": e.get("html_url") or "",
                          "kind": kind, "location": e.get("location_name") or "", "done": False, "missing": False})
    tests = _dedupe(sorted(tests, key=lambda t: t["due"]))
    upcoming_tests = [t for t in tests if _local(t["due"]).date() >= today]
    work = [i for i in items if i["type"] in WORK_TYPES]
    exams = {(t["course"], t["title"], t["due"]) for t in tests if t["kind"] == "exam"}
    todo = sorted((i for i in work if (i["course"], i["title"], i["due"]) not in exams and not i["done"] and (_local(i["due"]).date() >= today or i["missing"])),
                  key=lambda i: (not i["missing"], i["due"]))
    grades = sorted(({"course": codes[c["id"]], "name": c.get("name") or "", **_grade(c)} for c in courses),
                    key=lambda g: g["course"])
    return {
        "status": "ok", "fetched_at": now.isoformat(), "today": today.isoformat(),
        "grades": grades, "todo": todo, "tests": upcoming_tests,
        "missing": sum(i["missing"] for i in work),
        "timetable": timetable, "classes_today": classes_on(today, timetable),
        "calendar": _calendar(today, work, upcoming_tests),
        "yesterday": _yesterday(today, work),
    }


def _course_id(context_code: str | None) -> int | None:
    m = re.fullmatch(r"course_(\d+)", context_code or "")
    return int(m.group(1)) if m else None


def _dedupe(tests: list[dict]) -> list[dict]:
    seen, out = set(), []
    for t in tests:
        key = (t["course"], t["title"].lower(), t["due"][:10])
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out


def _calendar(today: date, work: list[dict], tests: list[dict]) -> list[dict]:
    """Six weeks from this Monday: every due date and test, one row per day (empty days included)."""
    start = today - timedelta(days=today.weekday())
    days = {start + timedelta(days=n): [] for n in range(CALENDAR_DAYS)}
    test_keys = {(t["course"], t["title"], t["due"]) for t in tests}
    for t in tests:
        d = _local(t["due"]).date()
        if d in days:
            days[d].append({"kind": t["kind"], "course": t["course"], "title": t["title"]})
    for i in work:
        d = _local(i["due"]).date()
        if d in days and (i["course"], i["title"], i["due"]) not in test_keys:
            days[d].append({"kind": "done" if i["done"] else "due", "course": i["course"], "title": i["title"]})
    return [{"date": d.isoformat(), "items": v} for d, v in days.items()]


def _yesterday(today: date, work: list[dict]) -> dict:
    y = today - timedelta(days=1)
    due = [i for i in work if _local(i["due"]).date() == y]
    return {"due": len(due), "done": sum(i["done"] for i in due), "missed": [i["title"] for i in due if not i["done"]]}


def next_test(tests: list[dict]) -> dict | None:
    """Prefer the next real exam; fall back to the next quiz."""
    return next((t for t in tests if t["kind"] == "exam"), None) or (tests[0] if tests else None)


# ---------- network ----------

def _get_all(http: httpx.Client, url: str, params: dict) -> list[dict]:
    out, next_url, first = [], url, True
    while next_url:
        res = http.get(next_url, params=params if first else None)
        res.raise_for_status()
        out.extend(res.json())
        next_url, first = res.links.get("next", {}).get("url"), False
    return out


def load_timetable() -> list[dict]:
    path = config.ROOT / "classes.json"
    try:
        return json.loads(path.read_text()).get("classes", [])
    except (OSError, json.JSONDecodeError):
        return []


def fetch(now: datetime | None = None) -> dict:
    now = now or datetime.now(TZ)
    token = _read_env_value(config.LOCAL_ENV_FILE, "CANVAS_TOKEN")
    base = (_read_env_value(config.LOCAL_ENV_FILE, "CANVAS_BASE_URL") or DEFAULT_BASE).rstrip("/")
    timetable = load_timetable()
    if not token:
        return {"status": "no_token", "timetable": timetable,
                "classes_today": classes_on(now.date(), timetable)}
    start = (now - timedelta(days=PAST_DAYS)).date().isoformat()
    end = (now + timedelta(days=AHEAD_DAYS)).date().isoformat()
    with httpx.Client(base_url=f"{base}/api/v1", headers={"Authorization": f"Bearer {token}"}, timeout=30) as http:
        courses = _get_all(http, "/courses", {"enrollment_state": "active", "include[]": ["total_scores", "term"],
                                              "per_page": 50})
        courses = [c for c in courses if c.get("id") and not c.get("access_restricted_by_date")]
        planner = _get_all(http, "/planner/items", {"start_date": start, "end_date": end, "per_page": 100})
        contexts = [f"course_{c['id']}" for c in courses][:10]   # Canvas caps context_codes at 10
        events = _get_all(http, "/calendar_events", {"type": "event", "start_date": start, "end_date": end,
                                                     "context_codes[]": contexts, "per_page": 100}) if contexts else []
    return build(courses, planner, events, timetable, now, base)
