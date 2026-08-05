from contextlib import redirect_stdout
from os import devnull
from typing import Any, Callable, Optional

from scrapling_fetch_mcp._concurrency import ConcurrencyGuard

_guard: Optional[ConcurrencyGuard] = None


def init_guard(max_concurrent: int, acquire_timeout: float) -> None:
    """Initialize the global concurrency guard. Call once at server startup."""
    global _guard
    _guard = ConcurrencyGuard(max_concurrent, acquire_timeout)


async def _do_browse(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None,
) -> Any:
    """Actual scrapling fetch (extracted from browse_url)."""
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        if mode == "basic":
            return await AsyncFetcher.get(url, stealthy_headers=True)
        elif mode == "stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                page_action=page_action,
            )
        elif mode == "max-stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                block_webrtc=True,
                network_idle=True,
                disable_resources=False,
                block_images=False,
                page_action=page_action,
            )
        else:
            raise ValueError(f"Unknown mode: {mode}")


async def browse_url(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None
) -> Any:
    """
    Browse URL using scrapling fetcher, gated by the global concurrency guard
    when initialized (see :func:`init_guard`).

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, max-stealth)
        page_action: Optional async callable that receives the Playwright ``page``
                     object (scrapling's native ``page_action`` contract) for
                     automation such as image capture. Only stealth/max-stealth
                     modes pass it through; basic mode ignores it.
    """
    if _guard is None:
        return await _do_browse(url, mode, page_action)
    async with _guard:
        return await _do_browse(url, mode, page_action)
