"""Job-search status straight from Gmail: submissions, assessments, interviews, rejections, offers.

Read-only IMAP (BODY.PEEK never marks mail read). Uses the same app password as
agentic_os/email_triage.py. Only sender, subject, date and the derived stage leave
the Mac; message bodies are read locally to classify and then discarded.
"""
import email
import email.message
import imaplib
import json
import re
import time
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.utils import parseaddr, parsedate_to_datetime

import os
from pathlib import Path

# Defaults are the Mac paths; the Oracle runner points these at ~/pais-cave via env vars.
ENV_FILE = Path(os.environ.get("PAIS_GMAIL_ENV", Path.home() / "agentic_os/.env"))
CACHE_FILE = Path(os.environ.get("PAIS_GMAIL_CACHE", Path.home() / "pais-batcave/gmail_jobs_cache.json"))
CACHE_TTL_S = 30 * 60
LOOKBACK_DAYS = 180
BODY_BYTES = 3000
MAX_MESSAGES = 600
FETCH_BATCH = 25

SEARCH = (
    f'newer_than:{LOOKBACK_DAYS}d -category:promotions ('
    'subject:(application OR applying OR applied OR candidacy OR interview OR assessment OR offer '
    'OR "next steps" OR hackerrank OR codesignal OR internship) '
    'OR from:(greenhouse.io OR lever.co OR myworkday.com OR myworkdayjobs.com OR ashbyhq.com '
    'OR smartrecruiters.com OR icims.com OR jobvite.com OR hackerrank.com OR codesignal.com))'
)

# Job boards / newsletters: listings, not your applications.
NOISE_SENDERS = re.compile(r"jobalerts|jobs-noreply@linkedin|handshake|indeed|glassdoor|ziprecruiter|"
                           r"themuse|simplify|wellfound|newsletter|digest|substack", re.I)

# Checked in priority order: the furthest stage an email implies wins.
# Interview/assessment only count as explicit invitations, never "if selected for an interview..." boilerplate.
OFFER = re.compile(r"\boffer (letter|of employment)|pleased to (extend|offer)|congratulations[^.]{0,80}offer", re.I)
REJECTED = re.compile(r"unfortunately|not (to )?(be )?mov(e|ing) forward|other candidates|decided to (pursue|proceed with)|"
                      r"position has been filled|no longer (under )?consider|will not be (proceeding|moving)|regret to inform", re.I)
INTERVIEW_SUBJECT = re.compile(r"(?<!no )\binterview|phone screen|superday|hirevue", re.I)
INTERVIEW_BODY = re.compile(r"invit\w* you to (an? |a |your )?(\w+ )?(interview|superday|phone screen|video|virtual|on-?site)|"
                            r"(schedule|book) (an? |your )?(\w+ )?(interview|phone screen|call)|interview invitation|"
                            r"complete (a|an|your|the) [\w ]{0,25}interview|select a time|your availability for|"
                            r"move you forward to|advance you to|next round", re.I)
ASSESSMENT = re.compile(r"assessment|hackerrank|codesignal|coding challenge|online test|\bOA\b|technical challenge", re.I)
SUBMITTED = re.compile(r"thank(s| you) for (applying|your application|your interest)|application (received|submitted|confirmation)|"
                       r"we('ve| have) received your (job )?application|received your (job )?application|your application (to|for|at|with)|"
                       r"started your job application", re.I)
CONDITIONAL = re.compile(r"\b(if|should|may|might|in the event|once we)\b", re.I)
NOISE_SUBJECTS = re.compile(r"hackathon|hackprinceton|\bno interview\b|newsletter", re.I)
STAGE_RANK = {name: i for i, name in enumerate(["submitted", "assessment", "interview", "rejected", "offer"])}

ATS_DOMAINS = re.compile(r"myworkday|workday|successfactors|icims|greenhouse|lever\.co|ashbyhq|smartrecruiters|jobvite|"
                         r"taleo|oraclecloud|eightfold|avature|brassring", re.I)
NAME_NOISE = re.compile(r"\b(workday|notifications?|people services|human resources|talent( acquisition)?|recruiting|"
                        r"recruitment|careers?|university|campus|hiring|jobs?|do ?not ?reply|donotreply|no[- ]?reply|"
                        r"system administrator|autoreply|hr|human res\w*|team|greenhouse|lever|ashby|smartrecruiters)\b|[_()]|@.*$", re.I)
SUBJECT_COMPANY = re.compile(r"(?i:applying|application|interest|interview|candidacy|career)\s+(?i:to|at|with|in)\s+"
                             r"(?:the\s+)?([A-Z][\w&.'\- ]{1,40}?)(?=[!.,:|\-–]|\s+(?:has|is|was|for)\b|\s+\(|$)")
MERGE_MIN = 4
CORP_SUFFIX = re.compile(r"\b(inc|llc|ltd|co|corp|corporation|company|group|plc)\b\.?", re.I)


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", text)


def _explicit(pattern: re.Pattern, text: str) -> bool:
    """True if some sentence states it outright (not 'if you are selected...')."""
    return any(pattern.search(sent) and not CONDITIONAL.search(sent) for sent in _sentences(text))


def classify(subject: str, body: str) -> str | None:
    if NOISE_SUBJECTS.search(subject or ""):
        return None
    text = f"{subject}. {body}"
    if OFFER.search(text):
        return "offer"
    if REJECTED.search(text):
        return "rejected"
    # The subject line is the sender's own label for the email, so it outranks body wording.
    if INTERVIEW_SUBJECT.search(subject or ""):
        return "interview"
    if ASSESSMENT.search(subject or ""):
        return "assessment"
    if _explicit(INTERVIEW_BODY, body):
        return "interview"
    if _explicit(ASSESSMENT, body):
        return "assessment"
    if SUBMITTED.search(text):
        return "submitted"
    return None


def _clean_name(name: str) -> str:
    if " - " in name:
        name = name.rsplit(" - ", 1)[-1]  # "Recruiter Name - Company"
    name = NAME_NOISE.sub(" ", name)
    return re.sub(r"\s{2,}", " ", name).strip(" -|,.")


PERSONAL_DOMAINS = re.compile(r"gmail|outlook|hotmail|yahoo|icloud|proton", re.I)


def _looks_like_person(name: str, domain: str) -> bool:
    """'CARLY CYR' from ibm.com is a recruiter, not a company; the domain names the company."""
    words = name.split()
    base = _norm(domain.split(".")[-2]) if domain.count(".") else ""
    return (2 <= len(words) <= 3 and all(w.isalpha() for w in words) and bool(base)
            and not PERSONAL_DOMAINS.search(domain) and not _norm(name).startswith(base[:3]))


NOT_A_COMPANY = re.compile(r"^(my|my ?workday|workday|greenhouse(-mail)?|teamtailor(-mail)?|talent ?acquisition|notify|"
                           r"notifications?|unknown|lever|ashby|icims|smartrecruiters|successfactors)$|"
                           r"\b(intern(ship)?s?|summer 20\d\d|software|engineer\w*|developer|position|role|analyst)\b", re.I)


def _usable(name: str | None) -> bool:
    return bool(name) and len(name) >= 2 and not NOT_A_COMPANY.search(name)


def company_of(sender_name: str, sender_addr: str, subject: str) -> str:
    """First usable of: subject ("applying to X"), cleaned sender name, ATS tenant, sender domain."""
    local, _, domain = (sender_addr or "").lower().partition("@")
    match = SUBJECT_COMPANY.search(subject or "")
    candidates = [match.group(1).strip() if match else None]
    name = _clean_name(sender_name or "")
    if not (_looks_like_person(name, domain) and not ATS_DOMAINS.search(domain)):
        candidates.append(name)
    if ATS_DOMAINS.search(domain):
        tenant = local.split("+")[0]
        if tenant and not re.fullmatch(r"no-?reply|notifications?|globalhr|jobs|careers|ta_no-reply|x", tenant):
            candidates.append(tenant.upper() if len(tenant) <= 4 else tenant.capitalize())
    else:
        parts = domain.split(".")
        base = parts[-2] if len(parts) >= 2 else ""
        base = re.sub(r"(hr|careers|jobs|recruiting)$", "", base) or base
        candidates.append(base.upper() if len(base) <= 3 else base.capitalize())
    return next((c for c in candidates if _usable(c)), "Unknown")


def _decode(value) -> str:
    try:
        return str(make_header(decode_header(value or "")))
    except (ValueError, LookupError):
        return value or ""


def _body_text(msg: email.message.Message) -> str:
    part = next((p for p in msg.walk() if p.get_content_type() == "text/plain"), None) or \
        next((p for p in msg.walk() if p.get_content_type() == "text/html"), None)
    if part is None:
        return ""
    raw = part.get_payload(decode=True) or b""
    text = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
    return re.sub(r"<[^>]+>|\s+", " ", text)[:BODY_BYTES]


def _creds() -> tuple[str, str]:
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        key, sep, val = line.partition("=")
        if sep:
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values["GMAIL_ADDRESS"], "".join(values["GMAIL_APP_PASSWORD"].split())


def _event_from(raw: bytes, own_addr: str) -> dict | None:
    msg = email.message_from_bytes(raw)
    name, sender = parseaddr(_decode(msg.get("From")))
    if NOISE_SENDERS.search(sender) or sender.lower() == own_addr.lower():
        return None
    subject = _decode(msg.get("Subject"))
    stage = classify(subject, _body_text(msg))
    if not stage:
        return None
    try:
        when = parsedate_to_datetime(msg.get("Date")).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None
    return {"date": when, "stage": stage, "company": company_of(name, sender, subject),
            "subject": subject[:160], "from": name or sender}


def _load_cache() -> dict:
    try:
        return json.loads(CACHE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _save_cache(cache: dict) -> None:
    tmp = CACHE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cache))
    tmp.chmod(0o600)
    tmp.replace(CACHE_FILE)


def scan(cache: dict) -> dict:
    """Incremental: each message is fetched and classified once, keyed by UID; progress is saved per batch."""
    addr, password = _creds()
    seen: dict = cache.get("uids", {}) if cache.get("uidvalidity") else {}
    imap = imaplib.IMAP4_SSL("imap.gmail.com", 993, timeout=60)
    try:
        imap.login(addr, password)
        imap.select('"[Gmail]/All Mail"', readonly=True)
        validity = (imap.response("UIDVALIDITY")[1] or [b""])[0]
        validity = validity.decode() if isinstance(validity, bytes) else str(validity)
        if cache.get("uidvalidity") != validity:
            seen = {}  # mailbox UIDs were reset: start over
        imap.literal = SEARCH.encode()  # sent as an IMAP literal: the query contains quotes
        _, data = imap.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        uids = [u.decode() for u in (data[0] or b"").split()][-MAX_MESSAGES:]
        todo = [u for u in uids if u not in seen]
        for i in range(0, len(todo), FETCH_BATCH):
            batch = todo[i:i + FETCH_BATCH]
            _, parts = imap.uid("FETCH", ",".join(batch), "(UID BODY.PEEK[])")
            for part in parts:
                if not isinstance(part, tuple):
                    continue
                uid = re.search(rb"UID (\d+)", part[0])
                if uid:
                    seen[uid.group(1).decode()] = _event_from(part[1], addr)
            _save_cache({**cache, "uidvalidity": validity, "uids": seen})
        keep = set(uids)
        return {"uidvalidity": validity, "uids": {u: e for u, e in seen.items() if u in keep}}
    finally:
        try:
            imap.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def events(force: bool = False) -> dict:
    """Cached, incremental Gmail scan. Failures are cached too so a dead password isn't retried constantly."""
    cache = _load_cache()
    if not force and time.time() - cache.get("scanned_at", 0) < CACHE_TTL_S:
        return _view(cache)
    try:
        cache = {**scan(cache), "error": None}
    except (imaplib.IMAP4.error, OSError, KeyError) as exc:
        cache = {**_load_cache(), "error": str(exc)}
    cache.update(scanned_at=time.time(), scanned_iso=datetime.now(timezone.utc).isoformat())
    _save_cache(cache)
    return _view(cache)


def _view(cache: dict) -> dict:
    evts = sorted((e for e in cache.get("uids", {}).values() if e), key=lambda e: e["date"], reverse=True)
    out = {"events": evts, "scanned_iso": cache.get("scanned_iso")}
    if cache.get("error") and not evts:
        out["error"] = cache["error"]
    return out


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", CORP_SUFFIX.sub("", name.lower()))


def _merge_key(name: str, rows: dict) -> str:
    """'JPMorgan Chase & Co.' and 'JPMorganChase' are one company; 'General Dynamics' and 'General Motors' are not."""
    key = _norm(name) or name.lower()
    for existing in rows:
        short, long_ = sorted((existing, key), key=len)
        if len(short) >= MERGE_MIN and long_.startswith(short):
            return existing
    return key


def by_company(evts: list[dict]) -> list[dict]:
    """One row per company: its furthest stage (a later rejection overrides an interview)."""
    rows: dict[str, dict] = {}
    for e in sorted(evts, key=lambda x: x["date"]):
        key = _merge_key(e["company"], rows)
        row = rows.setdefault(key, {"company": e["company"], "stage": e["stage"], "first": e["date"],
                                    "last": e["date"], "subject": e["subject"], "emails": 0, "reached": "submitted"})
        row["emails"] += 1
        if e["stage"] not in ("rejected",) and STAGE_RANK[e["stage"]] > STAGE_RANK[row["reached"]]:
            row["reached"] = e["stage"]  # furthest stage ever reached, even if later rejected
        row["last"], row["subject"] = e["date"], e["subject"]
        if e["stage"] in ("rejected", "offer") or STAGE_RANK[e["stage"]] > STAGE_RANK[row["stage"]]:
            row["stage"] = e["stage"]
    return sorted(rows.values(), key=lambda r: r["last"], reverse=True)
