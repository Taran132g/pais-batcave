"""Canvas Calendar Feed (.ics) → the same shapes the Canvas API gives canvas.build().

PSU doesn't let students create API tokens, but every student has a private calendar feed URL
(Canvas → Calendar → Calendar Feed). It carries every assignment/quiz due date and calendar
event for all courses, but no grades and no submission status.
"""
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
BRACKET = re.compile(r"\s*\[([^\[\]]+)\]\s*$")
COURSE_IN_URL = re.compile(r"course_(\d+)")


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _unescape(v: str) -> str:
    return v.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\").strip()


def _when(params: str, value: str) -> str | None:
    """ICS date/datetime → ISO 8601 with offset. All-day dates count as 11:59pm local (Canvas convention)."""
    try:
        if "VALUE=DATE" in params and "T" not in value:
            d = datetime.strptime(value, "%Y%m%d")
            return d.replace(hour=23, minute=59, tzinfo=TZ).isoformat()
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()
        tzid = re.search(r"TZID=([^;:]+)", params)
        return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=ZoneInfo(tzid.group(1)) if tzid else TZ).isoformat()
    except (ValueError, KeyError):
        return None


def _events(text: str) -> list[dict]:
    out, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                out.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            cur[name.upper()] = (params, value)
    return out


def parse(text: str) -> tuple[list[dict], list[dict], list[dict]]:
    """Returns (courses, planner_items, calendar_events) in Canvas-API shapes."""
    courses: dict[str, dict] = {}
    planner, events = [], []
    for ev in _events(text):
        summary = _unescape(ev.get("SUMMARY", ("", ""))[1])
        m = BRACKET.search(summary)
        course_name = m.group(1) if m else ""
        title = BRACKET.sub("", summary) or "Untitled"
        url = ev.get("URL", ("", ""))[1]
        cid_match = COURSE_IN_URL.search(url)
        course_id = f"course_{cid_match.group(1)}" if cid_match else (course_name or None)
        if course_id and course_name:
            courses.setdefault(course_id, {"id": course_id, "course_code": course_name, "name": course_name})
        params, value = ev.get("DTSTART", ("", ""))
        when = _when(params, value)
        if not when:
            continue
        uid = ev.get("UID", ("", ""))[1]
        if "assignment" in uid:
            planner.append({"course_id": course_id, "plannable_type": "assignment", "context_name": course_name,
                            "plannable": {"title": title, "due_at": when}, "html_url": url, "submissions": {}})
        else:
            events.append({"title": title, "start_at": when, "context_code": course_id, "context_name": course_name,
                           "html_url": url, "location_name": _unescape(ev.get("LOCATION", ("", ""))[1])})
    return list(courses.values()), planner, events
