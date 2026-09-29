import json
from datetime import datetime, timezone

import pytest

from publisher import outlook
from xoutlook import run, scrape, summarize

SINCE = datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 29, 13, 0, tzinfo=timezone.utc)


def _raw(**kw):
    base = {"context": "", "text": "BTC looks strong", "quoted": "", "time": "2026-09-28T10:00:00.000Z",
            "url": "https://x.com/DrProfitCrypto/status/1?s=20", "author": "DrProfitCrypto",
            "replying_to": "", "has_media": False}
    return {**base, **kw}


def test_keep_post_accepts_own_recent_post():
    assert scrape.keep_post(_raw(), "DrProfitCrypto", SINCE)


@pytest.mark.parametrize("override", [
    {"context": "Dr. Profit reposted", "author": "someoneelse"},
    {"author": "someoneelse"},
    {"replying_to": "@elonmusk"},
    {"time": "2026-09-20T10:00:00.000Z"},
    {"time": None},
])
def test_keep_post_rejects_reposts_replies_and_old_posts(override):
    assert not scrape.keep_post(_raw(**override), "DrProfitCrypto", SINCE)


def test_keep_post_keeps_self_thread_replies():
    assert scrape.keep_post(_raw(replying_to="@DrProfitCrypto"), "drprofitcrypto", SINCE)


def test_clean_post_strips_query_string():
    assert scrape.clean_post(_raw())["url"] == "https://x.com/DrProfitCrypto/status/1"


def test_window_start_uses_last_success_capped_at_seven_days():
    assert run.window_start(NOW, {}) == datetime(2026, 9, 22, 13, 0, tzinfo=timezone.utc)
    assert run.window_start(NOW, {"last_success": SINCE.isoformat()}) == SINCE
    assert run.window_start(NOW, {"last_success": "2026-08-01T00:00:00+00:00"}).day == 22


def _sources():
    post = {"time": "2026-09-28T10:00:00Z", "url": "https://x.com/DrProfitCrypto/status/1",
            "text": "Expect BTC 58k retest", "quoted": "", "has_media": False}
    return [{"name": "Dr. Profit", "handle": "DrProfitCrypto", "posts": [post]},
            {"name": "Kevin Xu", "handle": "kevinxu", "posts": []},
            {"name": "Jason Pizzino", "handle": "jasonpizzino", "posts": [], "error": "No posts rendered"}]


REPLY = """```json
{"overall": {"bias": "bearish", "summary": "Short-term caution.", "agree": "", "disagree": ""},
 "sources": [{"handle": "@DrProfitCrypto", "bias": "bearish", "summary": "Expects a 58k retest.",
   "levels": ["BTC 58k"], "quotes": [{"text": "Expect BTC 58k retest", "url": "https://x.com/DrProfitCrypto/status/1"},
   {"text": "bad", "url": "https://evil.example/x"}]}]}
```"""


def test_build_prompt_includes_only_sources_with_posts():
    prompt = summarize.build_prompt(_sources(), "a", "b")
    assert "@DrProfitCrypto" in prompt and "Expect BTC 58k retest" in prompt
    assert "@kevinxu" not in prompt


def test_parse_reply_validates_and_drops_non_x_quote_links():
    data = summarize.parse_reply(REPLY)
    assert data["overall"]["bias"] == "bearish"
    assert [q["url"] for q in data["sources"][0]["quotes"]] == ["https://x.com/DrProfitCrypto/status/1"]


def test_parse_reply_rejects_bad_shape():
    with pytest.raises(ValueError):
        summarize.parse_reply('{"overall": {"bias": "moon"}, "sources": []}')
    with pytest.raises(ValueError):
        summarize.parse_reply("no json here")


def test_build_outlook_merges_every_source_in_order():
    out = run.build_outlook(_sources(), SINCE, NOW, ask=lambda prompt: REPLY)
    rows = {s["handle"]: s for s in out["sources"]}
    assert [s["handle"] for s in out["sources"]] == ["DrProfitCrypto", "kevinxu", "jasonpizzino"]
    assert rows["DrProfitCrypto"]["bias"] == "bearish" and rows["DrProfitCrypto"]["levels"] == ["BTC 58k"]
    assert rows["kevinxu"]["bias"] is None and "No new posts" in rows["kevinxu"]["summary"]
    assert rows["jasonpizzino"]["error"] == "No posts rendered"
    assert out["post_count"] == 1


def test_build_outlook_skips_claude_when_nobody_posted():
    quiet = [{**s, "posts": []} for s in _sources()]
    out = run.build_outlook(quiet, SINCE, NOW, ask=lambda prompt: pytest.fail("claude should not be called"))
    assert out["post_count"] == 0 and out["overall"]["bias"] is None


def test_vault_note_lists_sources_and_quotes():
    note = run.vault_note(run.build_outlook(_sources(), SINCE, NOW, ask=lambda prompt: REPLY))
    assert "## Overall: bearish" in note and "BTC 58k" in note and "(https://x.com/DrProfitCrypto/status/1)" in note


def test_publisher_outlook_section(tmp_path):
    assert outlook.build(tmp_path)["status"] == "awaiting data"
    for day, bias in (("2026-09-25-1300", "bullish"), ("2026-09-29-1300", "bearish")):
        run_data = {"until": f"{day[:10]}T13:00:00+00:00", "overall": {"bias": bias},
                    "sources": [{"handle": "DrProfitCrypto", "bias": bias}]}
        (tmp_path / f"{day}.json").write_text(json.dumps(run_data))
    (tmp_path / "latest.json").write_text((tmp_path / "2026-09-29-1300.json").read_text())
    out = outlook.build(tmp_path)
    assert out["overall"]["bias"] == "bearish"
    assert [h["overall"] for h in out["history"]] == ["bearish", "bullish"]


def test_publisher_outlook_reports_first_run_failure(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps({"last_attempt": {"at": "x", "error": "Not signed in"}}))
    assert outlook.build(tmp_path)["status"] == "error"
