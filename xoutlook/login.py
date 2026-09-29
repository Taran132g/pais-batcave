"""One-time: open X's sign-in page in the PAIS browser profile so Taran can log in. Closes itself once signed in.

Run: /opt/homebrew/bin/python3 -m xoutlook.login
"""
import sys
import time

from . import config, scrape

WAIT_S = 15 * 60


def main() -> int:
    from playwright.sync_api import sync_playwright

    scrape.clear_stale_lock(config.PROFILE_DIR)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            str(config.PROFILE_DIR), headless=False, viewport={"width": 1280, "height": 900},
            args=["--no-first-run", "--no-default-browser-check"])
        try:
            if scrape.is_logged_in(ctx):
                print("[xoutlook] Already signed in to X in the PAIS profile.")
                return 0
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto("https://x.com/i/flow/login")
            print("[xoutlook] Sign in to X in the browser window. It closes by itself once you're in.", flush=True)
            deadline = time.time() + WAIT_S
            while time.time() < deadline:
                if scrape.is_logged_in(ctx):
                    time.sleep(3)  # let X finish writing its cookies
                    print("[xoutlook] Signed in. The Mon/Fri run will use this session.", flush=True)
                    return 0
                if not ctx.pages:
                    print("[xoutlook] The window was closed before sign-in finished.", file=sys.stderr)
                    return 1
                time.sleep(3)
            print("[xoutlook] Timed out waiting for sign-in.", file=sys.stderr)
            return 1
        finally:
            try:
                ctx.close()
            except Exception:  # noqa: BLE001 - the browser may already be gone
                pass


if __name__ == "__main__":
    sys.exit(main())
