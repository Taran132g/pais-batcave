from publisher.gmail_jobs import by_company, classify, company_of


def test_classify_stages_with_priority():
    assert classify("Thank you for applying to Citadel", "") == "submitted"
    assert classify("Your application", "Unfortunately we will not be moving forward") == "rejected"
    assert classify("Next steps: HackerRank assessment", "") == "assessment"
    assert classify("Interview invitation - Jane Street", "") == "interview"
    assert classify("Complete a JPMorganChase video interview", "") == "interview"
    assert classify("Update", "We would like to invite you to a virtual interview next week.") == "interview"
    assert classify("Offer", "We are pleased to extend an offer") == "offer"
    assert classify("Weekly digest", "10 new jobs for you") is None


def test_conditional_interview_language_is_not_an_interview():
    body = "Thanks for applying! If you are selected for an interview, a recruiter will reach out to schedule an interview."
    assert classify("Thanks for applying!", body) == "submitted"
    assert classify("[No Interview] Video Recorder Role", "Apply here") is None
    assert classify("We've got it!", "Should your background match, we may invite you to interview.") is None


def test_company_names_from_real_ats_senders():
    assert company_of("Human Resources", "blueorigin@myworkday.com", "Thank You for Applying to Blue Origin!") == "Blue Origin"
    assert company_of("No Reply Manulife", "manulife@myworkday.com", "Candidate Home") == "Manulife"
    assert company_of("RTX Workday Notifications", "globalhr@myworkday.com", "Application Received") == "RTX"
    assert company_of("", "stryker@myworkday.com", "Thanks!") == "Stryker"
    assert company_of("Maik Forreiter - Axpo Group", "x@axpo.com", "Your application for the position of Software Developer Intern") == "Axpo Group"
    assert company_of("Western Digital", "notifications@smartrecruiters.com", "Your job application at Western Digital has updates.") == "Western Digital"
    assert company_of("Charles Schwab Corporation @ icims", "schwab+autoreply@talent.icims.com", "You've started") == "Charles Schwab Corporation"
    assert company_of("Greenhouse", "no-reply@us.greenhouse-mail.io", "Thank you for applying to Hudson River Trading!") == "Hudson River Trading"


def test_by_company_merges_name_variants_and_keeps_final_rejection():
    evts = [
        {"date": "2026-08-01T00:00:00+00:00", "stage": "submitted", "company": "JPMorgan Chase & Co.", "subject": "Received"},
        {"date": "2026-08-05T00:00:00+00:00", "stage": "interview", "company": "JPMorganChase", "subject": "Video interview"},
        {"date": "2026-08-02T00:00:00+00:00", "stage": "assessment", "company": "General Dynamics", "subject": "OA"},
        {"date": "2026-08-09T00:00:00+00:00", "stage": "rejected", "company": "General Dynamics", "subject": "Update"},
        {"date": "2026-08-03T00:00:00+00:00", "stage": "submitted", "company": "General Motors", "subject": "Thanks"},
    ]
    rows = {r["company"]: r for r in by_company(evts)}
    assert len(rows) == 3
    jpm = next(r for r in rows.values() if r["company"].startswith("JPMorgan"))
    assert jpm["stage"] == "interview" and jpm["emails"] == 2
    assert rows["General Dynamics"]["stage"] == "rejected" and rows["General Dynamics"]["reached"] == "assessment"


def test_subject_decides_assessment_over_body_interview_words():
    assert classify("Action Required: IBM Coding Assessment for completion", "Complete the interview portion later.") == "assessment"


def test_recruiter_person_name_falls_back_to_company_domain():
    assert company_of("CARLY CYR", "carly.cyr@ibm.com", "RE: Co-Op Availability") == "IBM"
    assert company_of("Epic Human Resources", "hr@epic.com", "Response") == "Epic"


def test_role_titles_and_ats_names_are_not_companies():
    assert company_of("", "micron@myworkday.com", "Your application for Software Engineering Intern") == "Micron"
    assert company_of("MyWorkday", "cox@myworkday.com", "Thanks for applying!") == "COX"
    assert company_of("Greenhouse", "no-reply@us.greenhouse-mail.io", "Security code") == "Unknown"
    assert company_of("", "x@careers.teamtailor-mail.com", "Summer 2027") == "Unknown"
