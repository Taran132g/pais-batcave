"""Text Taran via Twilio; if the carrier blocks it, email the same message so nothing is lost.

Why the email fallback: US carriers drop SMS from numbers without A2P 10DLC / toll-free
verification (Twilio errors 30034 / 30032). Until registration clears, every text would
vanish silently, so we wait for the final delivery status and fall back to Gmail SMTP.

Settings live in ~/pais-cave/.env (600): TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM,
NOTIFY_TO_PHONE, NOTIFY_EMAIL (defaults to GMAIL_ADDRESS), GMAIL_ADDRESS, GMAIL_APP_PASSWORD.
"""
import smtplib
import time
from email.message import EmailMessage

import httpx

from . import config
from .auth import _read_env_value

TWILIO_API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages"
FINAL_OK = {"delivered", "sent"}          # "sent" = handed to carrier; carriers that don't report stay here
FINAL_BAD = {"undelivered", "failed", "canceled"}
POLL_S, POLL_TRIES = 5, 12                # up to a minute for the carrier verdict
MAX_SMS_CHARS = 1500                      # ~10 segments; Twilio's hard cap is 1600


def _env(key: str) -> str:
    return _read_env_value(config.LOCAL_ENV_FILE, key) or ""


def _twilio(to: str, body: str) -> tuple[bool, str]:
    sid, token, sender = _env("TWILIO_ACCOUNT_SID"), _env("TWILIO_AUTH_TOKEN"), _env("TWILIO_FROM")
    if not (sid and token and sender and to):
        return False, "Twilio not configured"
    url = TWILIO_API.format(sid=sid)
    with httpx.Client(auth=(sid, token), timeout=20) as http:
        res = http.post(f"{url}.json", data={"To": to, "From": sender, "Body": body[:MAX_SMS_CHARS]})
        if res.status_code >= 300:
            return False, f"Twilio HTTP {res.status_code}: {res.json().get('message', '')}"
        msg_sid, status = res.json()["sid"], res.json()["status"]
        for _ in range(POLL_TRIES):
            if status in FINAL_BAD or status == "delivered":
                break
            time.sleep(POLL_S)
            msg = http.get(f"{url}/{msg_sid}.json").json()
            status = msg["status"]
        if status in FINAL_BAD:
            return False, f"SMS {status} (Twilio error {msg.get('error_code')})"
        return status in FINAL_OK, f"SMS {status}"


def _email(subject: str, body: str) -> tuple[bool, str]:
    user, password = _env("GMAIL_ADDRESS"), _env("GMAIL_APP_PASSWORD")
    to = _env("NOTIFY_EMAIL") or user
    if not (user and password):
        return False, "Gmail not configured"
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, password)
        smtp.send_message(msg)
    return True, f"emailed {to}"


def send(subject: str, body: str) -> str:
    """Text first; email if the text didn't land. Returns a one-line outcome for the journal."""
    try:
        ok, detail = _twilio(_env("NOTIFY_TO_PHONE"), body)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        ok, detail = False, f"Twilio error: {type(exc).__name__}"
    if ok:
        return detail
    try:
        _, mail = _email(subject, f"{body}\n\n(Sent by email because the text failed: {detail})")
    except (smtplib.SMTPException, OSError) as exc:
        mail = f"email failed too: {type(exc).__name__}"
    return f"{detail} -> {mail}"
