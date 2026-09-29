import pyotp
import pytest

from server import config
from server.auth import Authenticator

SECRET = pyotp.random_base32()


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def auth(clock):
    return Authenticator(totp_secret=SECRET, key=b"k" * 32, clock=clock)


def code_at(t):
    return pyotp.TOTP(SECRET).at(t)


def test_accepts_current_code(auth, clock):
    assert auth.verify_code(code_at(clock.t))


def test_rejects_replayed_code(auth, clock):
    code = code_at(clock.t)
    assert auth.verify_code(code)
    assert not auth.verify_code(code)


def test_rejects_malformed_and_wrong_codes(auth, clock):
    assert not auth.verify_code("12ab56")
    assert not auth.verify_code("")
    wrong = str((int(code_at(clock.t)) + 1) % 1_000_000).zfill(6)
    assert not auth.verify_code(wrong)


def test_locks_out_after_repeated_failures(auth, clock):
    for _ in range(config.LOGIN_MAX_FAILS):
        auth.verify_code("000000" if code_at(clock.t) != "000000" else "111111")
    assert auth.locked_for() > 0
    clock.t += config.LOGIN_WINDOW_S + 1
    assert auth.locked_for() == 0


def test_session_token_round_trip_and_expiry(auth, clock):
    token = auth.issue()
    assert auth.valid(token)
    clock.t += config.SESSION_DAYS * 86400 + 1
    assert not auth.valid(token)


def test_tampered_token_rejected(auth):
    body, sig = auth.issue().rsplit(".", 1)
    assert not auth.valid(f"{body}x.{sig}")
    assert not auth.valid(f"{body}.{'0' * len(sig)}")
    assert not auth.valid(None)


def test_temp_passcode_works_until_expiry(clock):
    import hashlib
    a = Authenticator(totp_secret=SECRET, key=b"k" * 32, clock=clock,
                      temp_passcode_sha256=hashlib.sha256(b"JORDAN").hexdigest(), temp_passcode_expires=clock.t + 60)
    assert a.verify_code("JORDAN") and a.verify_code("jordan")
    assert not a.verify_code("JORDAM")
    clock.t += 61
    assert not a.verify_code("JORDAN")
