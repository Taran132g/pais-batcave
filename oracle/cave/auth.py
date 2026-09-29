"""Authenticator-app (TOTP) login -> signed, HttpOnly session cookie.

Hardening: rate-limited attempts, no code reuse inside its validity window,
constant-time signature checks, secrets read from disk (never in source).
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import deque

import pyotp

from . import config

COOKIE = "pais_session"


def _read_env_value(path, key: str) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip() == key:
            return value.strip().strip('"').strip("'")
    return None


def _session_key() -> bytes:
    path = config.SESSION_KEY_FILE
    if not path.exists():
        path.write_bytes(secrets.token_bytes(32))
        os.chmod(path, 0o600)
    return path.read_bytes()


class Authenticator:
    def __init__(self, totp_secret: str | None = None, key: bytes | None = None, clock=time.time,
                 temp_passcode_sha256: str | None = None, temp_passcode_expires: float | None = None):
        secret = totp_secret or _read_env_value(config.TOTP_ENV_FILE, "TOTP_SECRET")
        if not secret:
            raise RuntimeError(f"TOTP_SECRET not found in {config.TOTP_ENV_FILE}")
        self._totp = pyotp.TOTP(secret)
        self._key = key or _session_key()
        self._clock = clock
        self._fails: deque[float] = deque()
        self._used_counters: set[int] = set()
        # Optional temporary passcode (letters/digits), stored only as a SHA-256 hash, with a hard expiry.
        self._temp_hash = (temp_passcode_sha256 or "").lower() or None
        self._temp_expires = temp_passcode_expires

    # --- login -------------------------------------------------------------
    def locked_for(self) -> int:
        now = self._clock()
        while self._fails and now - self._fails[0] > config.LOGIN_WINDOW_S:
            self._fails.popleft()
        if len(self._fails) < config.LOGIN_MAX_FAILS:
            return 0
        return int(config.LOGIN_WINDOW_S - (now - self._fails[0])) + 1

    def _temp_ok(self, code: str) -> bool:
        if not self._temp_hash or not self._temp_expires or self._clock() > self._temp_expires:
            return False
        digest = hashlib.sha256(code.upper().encode()).hexdigest()
        return hmac.compare_digest(digest, self._temp_hash)

    def verify_code(self, code: str) -> bool:
        code = (code or "").strip()
        if self._temp_ok(code):
            return True
        if not (code.isdigit() and len(code) == 6):
            self._fails.append(self._clock())
            return False
        now = self._clock()
        for drift in (-1, 0, 1):
            counter = int(now // 30) + drift
            if counter in self._used_counters:
                continue
            if hmac.compare_digest(self._totp.at(counter * 30), code):
                self._used_counters = {c for c in self._used_counters if c >= counter - 2} | {counter}
                return True
        self._fails.append(now)
        return False

    # --- sessions ----------------------------------------------------------
    def issue(self) -> str:
        body = base64.urlsafe_b64encode(json.dumps({"exp": int(self._clock()) + config.SESSION_DAYS * 86400}).encode())
        return f"{body.decode()}.{self._sign(body)}"

    def valid(self, token: str | None) -> bool:
        if not token or "." not in token:
            return False
        body, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(self._sign(body.encode()), sig):
            return False
        try:
            return json.loads(base64.urlsafe_b64decode(body))["exp"] > self._clock()
        except (ValueError, KeyError):
            return False

    def _sign(self, body: bytes) -> str:
        return hmac.new(self._key, body, hashlib.sha256).hexdigest()
