"""Label (and star what needs action) job + academic mail in Gmail, and keep a feed of academic mail.

Runs from job_runner every 15 min. Taran's PSU Outlook forwards into this Gmail, so class mail
(Canvas, Gradescope, professors) lands here next to job mail.
- Job mail = anything gmail_jobs classified (its cache is keyed by the same All Mail UIDs).
  Label PAIS/Jobs; star interview / assessment / offer.
- Academic mail = learning platforms, or psu.edu mail whose subject names a course or class work.
  Label PAIS/Academic; star grades and exam notices.
Only headers are fetched for academic candidates. Labels are only ever added, never removed.
"""
import email
import imaplib
import json
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

from . import config
from .auth import _read_env_value

STATE_FILE = config.ROOT / "data/mail_flags.json"
FEED_FILE = config.ROOT / "data/academic_mail.json"
JOBS_CACHE = config.ROOT / "data/gmail_jobs_cache.json"
LABEL_JOBS, LABEL_ACADEMIC = "PAIS/Jobs", "PAIS/Academic"
LOOKBACK_DAYS, FEED_DAYS, MAX_PER_RUN = 30, 14, 300

PLATFORMS = ("instructure.com", "gradescope.com", "piazza.com", "edstem.org", "zybooks.com", "pearson.com",
             "mheducation.com", "tophat.com", "webassign.net", "prairielearn.com", "campuswire.com", "perusall.com",
             "macmillanlearning.com", "wileyplus.com", "cengage.com", "turnitin.com", "kaltura.com")
SEARCH = (f"newer_than:{LOOKBACK_DAYS}d -category:promotions (to:psu.edu OR cc:psu.edu OR from:psu.edu OR "
          f"from:({' OR '.join(PLATFORMS)}) OR subject:(canvas OR gradescope OR homework OR midterm OR syllabus))")
COURSE = re.compile(r"\b([A-Z]{2,5}(?:-[A-Z]{1,3})?\s?\d{3}[A-Z]?)\b")
CLASS_WORDS = re.compile(r"\b(homework|hw\s?\d|assignment|lab\s?\d|quiz|exam|midterm|final exam|syllabus|lecture|"
                         r"recitation|office hours|grade[sd]?|graded|submission|project|course|class|canvas|"
                         r"gradescope|professor|instructor|\bTA\b|piazza)\b", re.I)
NOT_ACADEMIC = re.compile(r"newsletter|digest|webinar|career fair|handshake|athletics|ticket|donat|alumni|"
                          r"housing|dining|parking|survey|club|spsa|thon\b", re.I)
KINDS = [("grade", re.compile(r"\bgraded\b|grade(s)? (posted|released|available)|your (score|grade)|feedback (is )?available|results", re.I)),
         ("exam", re.compile(r"\b(exam|midterm|final|quiz)\b", re.I)),
         ("submission", re.compile(r"submission|submitted|successfully (turned|handed) in", re.I)),
         ("announcement", re.compile(r"announcement", re.I))]
STAR_KINDS = {"grade", "exam"}
STAR_JOB_STAGES = {"interview", "assessment", "offer"}


def _decode(v) -> str:
    try:
        return str(make_header(decode_header(v or "")))
    except (ValueError, LookupError):
        return v or ""


def classify(sender: str, subject: str, own: str) -> dict | None:
    """Pure: is this header academic, and what kind of academic message is it?"""
    name, addr = parseaddr(sender)
    addr = addr.lower()
    if addr == own.lower() or NOT_ACADEMIC.search(subject):
        return None
    domain = addr.rpartition("@")[2]
    platform = any(domain == p or domain.endswith("." + p) for p in PLATFORMS)
    course = COURSE.search(subject)
    if not (platform or course or CLASS_WORDS.search(subject)):
        return None
    if not platform and not (domain.endswith("psu.edu") or course):
        return None   # class words alone from a random sender (e.g. a "course" ad) aren't academic
    kind = next((k for k, rx in KINDS if rx.search(subject)), "update")
    return {"course": re.sub(r"(?<=[A-Z])(?=\d)", " ", course.group(1)) if course else "",
            "kind": kind, "from": name or addr, "subject": subject[:160]}


def _read(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return default


def _write(path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data))
    tmp.chmod(0o600)
    tmp.replace(path)


def _label(imap, uids: list[str], label: str, star: bool = False) -> None:
    for i in range(0, len(uids), 100):
        chunk = ",".join(uids[i:i + 100])
        imap.uid("STORE", chunk, "+X-GM-LABELS", f'("{label}")')
        if star:
            imap.uid("STORE", chunk, "+FLAGS", "(\\Flagged)")


def run() -> dict:
    env = config.LOCAL_ENV_FILE
    own = _read_env_value(env, "GMAIL_ADDRESS") or ""
    password = "".join((_read_env_value(env, "GMAIL_APP_PASSWORD") or "").split())
    state = _read(STATE_FILE, {})
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
    try:
        imap.login(own, password)
        imap.select('"[Gmail]/All Mail"')   # writable: labels + stars
        validity = (imap.response("UIDVALIDITY")[1] or [b""])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity)
        if state.get("uidvalidity") != validity:
            state = {"uidvalidity": validity, "jobs": [], "academic": {}}
        done_jobs = set(state["jobs"])

        # jobs: reuse the job scanner's classification (same mailbox, same UIDs)
        jobs_cache = _read(JOBS_CACHE, {})
        job_events = {u: e for u, e in jobs_cache.get("uids", {}).items()
                      if e and jobs_cache.get("uidvalidity") == validity and u not in done_jobs}
        _label(imap, list(job_events), LABEL_JOBS)
        _label(imap, [u for u, e in job_events.items() if e["stage"] in STAR_JOB_STAGES], LABEL_JOBS, star=True)
        done_jobs |= set(job_events)

        # academic: headers only, each UID classified once
        imap.literal = SEARCH.encode()
        _, data = imap.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        seen = state["academic"]
        in_window = {u.decode() for u in (data[0] or b"").split()}
        todo = sorted((u for u in in_window if u not in seen), key=int)[-MAX_PER_RUN:]
        new = {}
        for i in range(0, len(todo), 50):
            _, parts = imap.uid("FETCH", ",".join(todo[i:i + 50]), "(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            for part in parts:
                if not isinstance(part, tuple):
                    continue
                uid = re.search(rb"UID (\d+)", part[0]).group(1).decode()
                h = email.message_from_bytes(part[1])
                hit = classify(_decode(h.get("From")), _decode(h.get("Subject")), own)
                if hit:
                    try:
                        hit["date"] = parsedate_to_datetime(h.get("Date")).astimezone(timezone.utc).isoformat()
                    except (TypeError, ValueError):
                        hit["date"] = datetime.now(timezone.utc).isoformat()
                new[uid] = hit
        academic = {u: e for u, e in new.items() if e}
        _label(imap, list(academic), LABEL_ACADEMIC)
        _label(imap, [u for u, e in academic.items() if e["kind"] in STAR_KINDS], LABEL_ACADEMIC, star=True)
        seen.update(new)
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass
    state["academic"] = {u: e for u, e in seen.items() if u in in_window}   # bounded to the 30-day search
    state["jobs"] = sorted(done_jobs, key=int)[-2000:]
    _write(STATE_FILE, state)
    feed_cutoff = (datetime.now(timezone.utc) - timedelta(days=FEED_DAYS)).isoformat()
    feed = sorted((e for e in state["academic"].values() if e and e["date"] >= feed_cutoff),
                  key=lambda e: e["date"], reverse=True)
    _write(FEED_FILE, feed)
    return {"jobs_labeled": len(job_events), "academic_new": len(academic), "academic_feed": len(feed)}
