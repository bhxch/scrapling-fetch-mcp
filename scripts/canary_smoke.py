"""Real stealth-mode smoke fetch for the daily dependency canary.

Unit tests mock the browser stack away, so only a live fetch can catch
breakage from a new camoufox browser release or a playwright driver
mismatch. It runs against a deliberately static target (IANA's
example.com) with one retry; exit 0 means the stealth path works end
to end: browser present, supported, launchable, and able to load a page.
"""
import asyncio
import sys

TARGET_URL = "https://example.com/"
EXPECTED_TEXT = "Example Domain"


async def _smoke_once() -> bool:
    from scrapling.fetchers import StealthyFetcher

    page = await StealthyFetcher.async_fetch(
        TARGET_URL,
        headless=True,
        google_search=False,
    )
    body = page.body
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if page.status != 200:
        print(f"unexpected status {page.status} for {TARGET_URL}")
        return False
    if EXPECTED_TEXT not in body:
        print(f"expected text {EXPECTED_TEXT!r} missing from response body")
        return False
    return True


async def main() -> int:
    for attempt in range(1, 3):
        try:
            if await _smoke_once():
                print(f"canary smoke ok: stealth fetch of {TARGET_URL} succeeded")
                return 0
        except Exception as exc:  # noqa: BLE001 - report every failure mode
            print(f"canary smoke attempt {attempt} failed: {exc!r}")
        else:
            print(f"canary smoke attempt {attempt}: content check failed")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
