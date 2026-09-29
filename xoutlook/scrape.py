"""Read recent posts from each source's X profile through Taran's logged-in PAIS browser profile.

Read-only: it opens profile pages and scrolls at a human pace. It never likes, posts, or follows.
Run with the system python (/opt/homebrew/bin/python3), which has Playwright + Chromium installed.
"""
import os
from datetime import datetime
from pathlib import Path

from . import config

# Runs in the page: one dict per post card currently rendered in the timeline.
_EXTRACT_JS = r"""
() => [...document.querySelectorAll('article[data-testid="tweet"]')].map(a => {
  const ctx = a.querySelector('[data-testid="socialContext"]');
  const texts = [...a.querySelectorAll('[data-testid="tweetText"]')].map(t => t.innerText.trim());
  const time = a.querySelector('time');
  const link = time ? time.closest('a') : null;
  const author = a.querySelector('[data-testid="User-Name"] a[href^="/"]');
  const replyTo = [...a.querySelectorAll('div')].find(d => d.childElementCount <= 3 && /^Replying to/.test(d.innerText || ''));
  return {
    context: ctx ? ctx.innerText.trim() : '',
    text: texts[0] || '',
    quoted: texts[1] || '',
    time: time ? time.getAttribute('datetime') : null,
    url: link ? link.href : null,
    author: author ? author.getAttribute('href').replace(/^\//, '').split('/')[0] : '',
    replying_to: replyTo ? replyTo.innerText.replace(/^Replying to\s*/, '').trim() : '',
    has_media: !!a.querySelector('[data-testid="tweetPhoto"], video'),
  };
})
"""


def keep_post(raw: dict, handle: str, since: datetime) -> bool:
    """The source's own posts (incl. self-threads) newer than `since`; no reposts or replies to others."""
    if not raw.get("time") or not raw.get("url"):
        return False
    if raw.get("author", "").lower() != handle.lower():
        return False  # a repost shows the original author
    if "reposted" in raw.get("context", "").lower():
        return False
    replying_to = raw.get("replying_to", "").lower()
    if replying_to and f"@{handle.lower()}" not in replying_to:
        return False
    return parse_time(raw["time"]) > since


def parse_time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def clean_post(raw: dict) -> dict:
    return {"time": raw["time"], "url": raw["url"].split("?")[0], "text": raw["text"],
            "quoted": raw.get("quoted", ""), "has_media": bool(raw.get("has_media"))}


def clear_stale_lock(profile: Path) -> None:
    """Chromium leaves a SingletonLock ('HOST-PID') behind when killed; a dead PID blocks every launch."""
    try:
        target = os.readlink(profile / "SingletonLock")
    except OSError:
        return
    tail = target.rsplit("-", 1)[-1]
    if not tail.isdigit():
        return
    try:
        os.kill(int(tail), 0)
        raise RuntimeError("The PAIS browser profile is in use by another PAIS browser. Try again when it closes.")
    except ProcessLookupError:
        for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
            (profile / name).unlink(missing_ok=True)


def is_logged_in(ctx) -> bool:
    return any(c["name"] == "auth_token" for c in ctx.cookies("https://x.com"))


def _read_profile(page, src: dict, since: datetime) -> dict:
    handle = src["handle"]
    page.goto(f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=45_000)
    try:
        page.wait_for_selector('article[data-testid="tweet"]', timeout=20_000)
    except Exception:  # noqa: BLE001 - reported with a screenshot below
        pass
    posts: dict[str, dict] = {}
    for _ in range(config.MAX_SCROLLS):
        reached_older = False
        for raw in page.evaluate(_EXTRACT_JS):
            if keep_post(raw, handle, since):
                posts.setdefault(raw["url"].split("?")[0], clean_post(raw))
            elif raw.get("time") and "pinned" not in raw.get("context", "").lower() \
                    and raw.get("author", "").lower() == handle.lower() and parse_time(raw["time"]) <= since:
                reached_older = True  # timeline is newest-first; an old non-pinned post means we're done
        if reached_older or len(posts) >= config.MAX_POSTS_PER_SOURCE:
            break
        page.mouse.wheel(0, 2200)
        page.wait_for_timeout(config.SCROLL_PAUSE_MS)
    result = {**src, "posts": sorted(posts.values(), key=lambda p: p["time"], reverse=True)[:config.MAX_POSTS_PER_SOURCE]}
    if not page.query_selector('article[data-testid="tweet"]'):
        config.SHOT_DIR.mkdir(parents=True, exist_ok=True)
        shot = config.SHOT_DIR / f"{handle}-{datetime.now():%Y%m%d-%H%M}.png"
        page.screenshot(path=str(shot))
        result["error"] = f"No posts rendered on the profile page (screenshot: {shot.name})."
    return result


def read_sources(since: datetime, headless: bool = True) -> list[dict]:
    """[{name, handle, posts: [...], error?}] for every source. Raises if the profile isn't logged in to X."""
    from playwright.sync_api import sync_playwright

    clear_stale_lock(config.PROFILE_DIR)
    out = []
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(config.PROFILE_DIR), headless=headless, viewport={"width": 1280, "height": 1000},
            args=["--no-first-run", "--no-default-browser-check"])
        try:
            if not is_logged_in(ctx):
                raise RuntimeError("Not signed in to X in the PAIS browser profile. Run: python3 -m xoutlook.login")
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            for i, src in enumerate(config.SOURCES):
                if i:
                    page.wait_for_timeout(config.BETWEEN_PROFILES_MS)
                try:
                    out.append(_read_profile(page, src, since))
                except Exception as exc:  # noqa: BLE001 - one bad profile must not sink the run
                    out.append({**src, "posts": [], "error": f"{type(exc).__name__}: {exc}"})
        finally:
            ctx.close()
    return out
