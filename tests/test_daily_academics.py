import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scout"))

from cave import brief, canvas, daily_goal  # noqa: E402
from cave.canvas import TZ  # noqa: E402
import daily_jobs  # noqa: E402

NOW = datetime(2026, 9, 29, 8, 55, tzinfo=TZ)  # a Tuesday
COURSES = [
    {"id": 1, "name": "STAT 319: Elem Math Stat", "course_code": "SP26 STAT 319 001",
     "enrollments": [{"type": "student", "computed_current_score": 91.2, "computed_current_grade": "A-"}]},
    {"id": 2, "name": "Machine Learning", "course_code": "CMPSC448 002", "enrollments": [{"type": "student"}]},
]


def planner(course_id, title, due, kind="assignment", subs=None):
    return {"course_id": course_id, "plannable_type": kind, "plannable": {"title": title, "due_at": due},
            "html_url": f"/courses/{course_id}/assignments/9", "submissions": subs or {}}


PLANNER = [
    planner(1, "HW 4", "2026-09-30T03:59:00Z"),                                    # Tue 11:59pm ET
    planner(2, "Lab 2", "2026-09-29T03:59:00Z", subs={"missing": True}),           # yesterday, missing
    planner(2, "Lab 1", "2026-09-29T03:00:00Z", subs={"submitted": True}),         # yesterday, done
    planner(1, "Midterm 1", "2026-10-08T13:00:00Z", kind="quiz"),
    planner(1, "Midterm 1 practice exam", "2026-10-05T13:00:00Z", kind="quiz"),
    planner(2, "Quiz 3", "2026-10-02T13:00:00Z", kind="quiz"),
]
TIMETABLE = [{"course": "STAT 319", "days": "TR", "start": "10:35", "end": "11:50", "room": "Thomas 102"},
             {"course": "CMPSC 448", "days": "MWF", "start": "09:05", "end": "09:55"}]


def test_short_codes():
    assert canvas.short_code(COURSES[0]) == "STAT 319"
    assert canvas.short_code(COURSES[1]) == "CMPSC 448"
    assert canvas.short_code({"course_code": "A-I 370 001"}) == "A-I 370"


def test_build_academics():
    ac = canvas.build(COURSES, PLANNER, [], TIMETABLE, NOW)
    assert [g["course"] for g in ac["grades"]] == ["CMPSC 448", "STAT 319"]
    assert ac["grades"][1]["score"] == 91.2
    assert ac["todo"][0]["title"] == "Lab 2" and ac["todo"][0]["missing"]   # missing first
    assert "Midterm 1" not in [t["title"] for t in ac["todo"]]           # exams live in the test calendar
    assert "Midterm 1" not in [t["title"] for t in ac["todo"]]           # exams live in the test calendar
    assert "Lab 1" not in [t["title"] for t in ac["todo"]]
    assert [t["title"] for t in ac["tests"]] == ["Quiz 3", "Midterm 1"]      # practice exam excluded
    assert canvas.next_test(ac["tests"])["title"] == "Midterm 1"           # exam beats the nearer quiz
    assert [c["course"] for c in ac["classes_today"]] == ["STAT 319"]
    assert ac["yesterday"] == {"due": 2, "done": 1, "missed": ["Lab 2"]}
    assert len(ac["calendar"]) == canvas.CALENDAR_DAYS and ac["calendar"][0]["date"] == "2026-09-28"


def test_exam_from_calendar_event():
    ev = [{"title": "Exam 1 (in class)", "start_at": "2026-10-06T14:35:00Z", "context_code": "course_1"}]
    ac = canvas.build(COURSES, [], ev, [], NOW)
    assert ac["tests"][0]["course"] == "STAT 319" and ac["tests"][0]["kind"] == "exam"


JOBS = [{"category": "finance", "company": "Fulton Bank", "role": "Analyst Intern", "url": "https://a"},
        {"category": "software", "company": "Vanguard Group", "role": "SWE Intern", "url": "https://b"}]


def test_goal_matches_gmail_and_manual_marks():
    events = [{"date": "2026-09-29T15:00:00+00:00", "stage": "submitted", "company": "Vanguard"},
              {"date": "2026-09-28T15:00:00+00:00", "stage": "submitted", "company": "Fulton Bank"}]  # wrong day
    s = daily_goal.status(date(2026, 9, 29), JOBS, events, {})
    assert [j["done"] for j in s["jobs"]] == [False, True] and s["jobs"][1]["via"] == "email"
    s = daily_goal.status(date(2026, 9, 29), JOBS, events, {"2026-09-29": ["https://a"]})
    assert s["complete"] and s["done"] == 2


def test_company_matching_is_not_too_loose():
    assert daily_goal.same_company("JPMorgan Chase & Co.", "JPMorganChase")
    assert not daily_goal.same_company("Citi", "Citizens Bank")  # too short to substring-match


def test_evening_text_only_when_incomplete():
    done = daily_goal.status(date(2026, 9, 29), JOBS, [], {"2026-09-29": ["https://a", "https://b"]})
    assert brief.evening_text(done) is None
    half = daily_goal.status(date(2026, 9, 29), JOBS, [], {"2026-09-29": ["https://a"]})
    text = brief.evening_text(half)
    assert "1/2" in text and "Vanguard" in text and "Fulton" not in text


def test_morning_text_sections():
    ac = canvas.build(COURSES, PLANNER, [], TIMETABLE, NOW)
    goal = daily_goal.status(date(2026, 9, 29), JOBS, [], {})
    samples = [(datetime(2026, 9, 27, 23, tzinfo=TZ).timestamp(), 1000.0),
               (datetime(2026, 9, 28, 12, tzinfo=TZ).timestamp(), 1030.0),
               (datetime(2026, 9, 28, 23, tzinfo=TZ).timestamp(), 1050.0)]
    change = brief.equity_change(samples, date(2026, 9, 28))
    assert change == (1000.0, 1050.0)
    line = brief.trading_line(change, {"mtd_pct": 12.34, "target_pct": 20})
    assert "+$50.00" in line and "+5.0%" in line and "MTD +12.3%" in line
    text = brief.morning_text(date(2026, 9, 29), [line, brief.school_line(ac)], ac, goal)
    assert "10:35am STAT 319 (Thomas 102)" in text
    assert "Due today: STAT 319 HW 4 11:59pm" in text
    assert "Next test: STAT 319 Midterm 1 · Thu Oct 8 (9d)" in text
    assert "Apply today (0/2)" in text and "FIN Fulton Bank - Analyst Intern" in text
    assert "missed: Lab 2" in text


def test_scout_pick_tops_up_per_category():
    found = [{"category": "finance", "company": f"Bank{i}", "role": "r", "url": f"https://f{i}"} for i in range(5)]
    found += [{"category": "software", "company": "Bank0", "role": "r", "url": "https://dup"}]  # company repeat
    picked = daily_jobs.pick(found, [])
    assert [j["company"] for j in picked] == ["Bank0", "Bank1", "Bank2"]
    assert daily_jobs.shortfall(picked) == {"software": daily_jobs.ASK_PER_CATEGORY}


def test_scout_parse_ignores_prose_and_bad_rows():
    raw = 'Here you go:\n```json\n[{"category":"finance","company":"X","url":"https://x"},{"category":"other","company":"Y","url":"https://y"}]\n```'
    assert [j["company"] for j in daily_jobs.parse_jobs(raw)] == ["X"]
