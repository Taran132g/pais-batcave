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
    samples = [(datetime(2026, 9, 27, 23, tzinfo=TZ).timestamp(), 1000.0),
               (datetime(2026, 9, 28, 23, tzinfo=TZ).timestamp(), 1050.0)]
    assert brief.equity_change(samples, date(2026, 9, 28)) == (1000.0, 1050.0)
    yb = {"status": "ok", "started": "2026-09-29T12:10:00+00:00", "summary": "BTC short +$110, watch PCE Wed."}
    text = brief.morning_text(date(2026, 9, 29), yb, ac)
    assert "TRADING\nBTC short +$110, watch PCE Wed." in text
    assert "10:35am STAT 319 (Thomas 102)" in text and "Due today: STAT 319 HW 4 11:59pm" in text
    assert "Next test: STAT 319 Midterm 1 · Thu Oct 8 (9d)" in text
    assert "jobs" not in text                                                    # daily scout retired 2026-10-14
    assert "Fulton" not in text and "YESTERDAY" not in text
    stale = brief.morning_text(date(2026, 9, 30), yb, ac)
    assert "No Yubit report today yet" in stale
    assert "hasn't reported yet" in brief.trading_overview({"status": "no report"}, date(2026, 9, 29))


def test_scout_pick_tops_up_per_category():
    found = [{"category": "finance", "company": f"Bank{i}", "role": "r", "url": f"https://f{i}"} for i in range(5)]
    found += [{"category": "software", "company": "Bank0", "role": "r", "url": "https://dup"}]  # company repeat
    picked = daily_jobs.pick(found, [])
    assert [j["company"] for j in picked] == ["Bank0", "Bank1", "Bank2"]
    assert daily_jobs.shortfall(picked) == {"software": daily_jobs.ASK_PER_CATEGORY}


def test_scout_parse_ignores_prose_and_bad_rows():
    raw = 'Here you go:\n```json\n[{"category":"finance","company":"X","url":"https://x"},{"category":"other","company":"Y","url":"https://y"}]\n```'
    assert [j["company"] for j in daily_jobs.parse_jobs(raw)] == ["X"]


FEED = """BEGIN:VCALENDAR\r
VERSION:2.0\r
BEGIN:VEVENT\r
DTSTART:20260930T035900Z\r
SUMMARY:HW 4 [STAT 319 001: Elem Mathematical\r
  Statistics]\r
UID:event-assignment-111\r
URL;VALUE=URI:https://psu.instructure.com/calendar?include_contexts=course_1&month=09#assignment_111\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261002\r
SUMMARY:Quiz 3 [CMPSC 448 002]\r
UID:event-assignment-222\r
URL;VALUE=URI:https://psu.instructure.com/calendar?include_contexts=course_2#assignment_222\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;TZID=America/New_York:20261008T103500\r
SUMMARY:Midterm 1 (in class) [STAT 319 001: Elem Mathematical Statistics]\r
UID:event-calendar-event-333\r
LOCATION:Thomas 102\r
URL;VALUE=URI:https://psu.instructure.com/calendar?include_contexts=course_1#calendar_event_333\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_calendar_feed_mode():
    ac = canvas.from_feed(FEED, TIMETABLE, NOW)
    assert ac["source"] == "feed" and ac["grades"] == [] and ac["missing"] is None and ac["yesterday"] is None
    assert [(i["course"], i["title"]) for i in ac["todo"]] == [("STAT 319", "HW 4"), ("CMPSC 448", "Quiz 3")]
    assert ac["todo"][1]["due"].startswith("2026-10-02T23:59")                  # all-day = due end of day
    exam = canvas.next_test(ac["tests"])
    assert (exam["course"], exam["title"], exam["kind"]) == ("STAT 319", "Midterm 1 (in class)", "exam")
    assert exam["due"].startswith("2026-10-08T10:35")
    text = brief.morning_text(date(2026, 9, 29), None, ac)
    assert "Due today: STAT 319 HW 4 11:59pm" in text and "Next test: STAT 319 Midterm 1 (in class)" in text
    assert brief.school_line(ac) is None                                         # no submission data → no fake 0/N


def test_aliases_and_projects():
    merged = {"id": 9, "name": "Section Merge: Elem.Mathematical Statistics(319-002)"}
    assert canvas.short_code(merged, {merged["name"]: "STAT 319"}) == "STAT 319"
    assert canvas._is_test("Midterm Project (Deadline: Oct 11)", "assignment") is None


def test_sms_stays_in_gsm_alphabet():
    from cave import notify
    text = notify.gsm("PAIS · Tue\n✓ FIN Fulton – Intern\n• SWE “Duo” … 🚀")
    assert text == 'PAIS - Tue\n+ FIN Fulton - Intern\n- SWE "Duo" ... '
    assert all(c in notify.GSM_BASIC for c in text)


def test_academic_mail_classifier():
    from cave.mail_flags import classify
    own = "taran.impact@gmail.com"
    g = classify("Gradescope <no-reply@gradescope.com>", "Your submission to Homework 2 has been graded", own)
    assert g["kind"] == "grade"
    c = classify('"Smith, Jane" <jxs1@psu.edu>', "STAT 319 Midterm 1 room change", own)
    assert (c["course"], c["kind"]) == ("STAT 319", "exam")
    assert classify("Canvas <notifications@instructure.com>", "Recent Canvas Notifications", own)["kind"] == "update"
    assert classify('"Doe, Alex" <axd5@psu.edu>', "Re: Scheduling Meeting", own) is None       # SPSA, not class
    assert classify("PSU Athletics <x@psu.edu>", "Football tickets for your class", own) is None
    assert classify("Udemy <deals@udemy.com>", "New course: master Python", own) is None           # ad, not class
    assert classify(own, "HW 3 notes", own) is None


def test_inbox_line():
    feed = [{"date": "2026-09-28T15:00:00+00:00", "kind": "grade", "course": "A-I 370", "from": "Gradescope", "subject": "graded"},
            {"date": "2026-09-28T16:00:00+00:00", "kind": "exam", "course": "STAT 319", "from": "x", "subject": "Midterm"},
            {"date": "2026-09-28T17:00:00+00:00", "kind": "update", "course": "", "from": "Canvas", "subject": "x"},
            {"date": "2026-09-20T17:00:00+00:00", "kind": "grade", "course": "Old", "from": "x", "subject": "x"}]
    assert brief.inbox_line(feed, date(2026, 9, 28)) == "School mail: 1 grade posted (A-I 370) · exam notice: STAT 319 · 1 other"
    assert brief.inbox_line(feed, date(2026, 9, 27)) is None


def test_ai_news_parse():
    import ai_news
    raw = 'Sure!\n```json\n{"headline": "Agents everywhere", "stories": [{"title": "A", "url": "https://x.com/a", "summary": "s"},' \
          ' {"title": "B", "url": "http://insecure"}, {"url": "https://no-title"}], "learn": {"title": "RAG", "why": "w", "url": "https://r"}}\n```'
    issue = ai_news.parse_issue(raw)
    assert issue["headline"] == "Agents everywhere" and [s["title"] for s in issue["stories"]] == ["A"]
    assert issue["learn"]["title"] == "RAG"
    assert ai_news.parse_issue("no json here") is None
