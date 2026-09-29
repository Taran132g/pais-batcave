import sys
from pathlib import Path

import pyotp
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "oracle"))

from cave import app as cave_app  # noqa: E402
from cave import config as cave_config  # noqa: E402
from cave.auth import Authenticator  # noqa: E402

SECRET = pyotp.random_base32()


@pytest.fixture
def client(monkeypatch, tmp_path):
    snap = tmp_path / "snapshot.json"
    snap.write_text('{"roi": {"mtd_pct": 42.1}, "agents": []}')
    monkeypatch.setattr(cave_config, "SNAPSHOT_FILE", snap)
    monkeypatch.setattr(cave_app, "auth", Authenticator(totp_secret=SECRET, key=b"c" * 32))
    return TestClient(cave_app.app, base_url="https://testserver")


def test_snapshot_requires_login(client):
    assert client.get("/snapshot").status_code == 401


def test_login_then_snapshot(client):
    ok = client.post("/login", json={"code": pyotp.TOTP(SECRET).now()})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("httponly", "secure", "samesite=strict", "path=/api/cave"))
    client.cookies.set("pais_session", ok.cookies.get("pais_session"))
    body = client.get("/snapshot").json()
    assert body["roi"]["mtd_pct"] == 42.1 and "stale" in body


def test_wrong_code_rejected(client):
    code = pyotp.TOTP(SECRET).now()
    wrong = str((int(code) + 1) % 1_000_000).zfill(6)
    assert client.post("/login", json={"code": wrong}).status_code == 401


def test_background_requires_login(client):
    assert client.get("/bg/bunker").status_code == 401
    ok = client.post("/login", json={"code": pyotp.TOTP(SECRET).now()})
    client.cookies.set("pais_session", ok.cookies.get("pais_session"))
    res = client.get("/bg/bunker")
    assert res.status_code == 200 and res.headers["content-type"] == "image/webp"
    assert "private" in res.headers["cache-control"]
    assert client.get("/bg/nope").status_code == 404


def test_daily_mark_requires_login_and_known_job(client, monkeypatch, tmp_path):
    from cave import daily_goal
    lists = tmp_path / "daily_jobs"
    lists.mkdir()
    (lists / "2026-09-29.json").write_text('{"jobs": [{"category": "finance", "company": "Fulton Bank", "role": "Intern", "url": "https://a"}]}')
    monkeypatch.setattr(daily_goal, "LIST_DIR", lists)
    monkeypatch.setattr(daily_goal, "MARKS_FILE", tmp_path / "marks.json")
    monkeypatch.setattr(daily_goal, "EVENTS_FILE", tmp_path / "events.json")
    body = {"date": "2026-09-29", "url": "https://a", "done": True}
    assert client.post("/daily/mark", json=body).status_code == 401
    ok = client.post("/login", json={"code": pyotp.TOTP(SECRET).now()})
    client.cookies.set("pais_session", ok.cookies.get("pais_session"))
    res = client.post("/daily/mark", json=body).json()
    assert res["done"] == 1 and res["complete"] and res["jobs"][0]["via"] == "marked"
    assert client.post("/daily/mark", json={**body, "url": "https://evil"}).status_code == 404
    assert client.post("/daily/mark", json={**body, "done": False}).json()["done"] == 0
