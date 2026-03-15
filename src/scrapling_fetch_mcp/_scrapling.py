from contextlib import redirect_stdout
from os import devnull
from typing import Any, Callable, Optional


async def browse_url(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None
) -> Any:
    """
    Browse URL using scrapling fetcher.

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, max-stealth)
        page_action: Optional async function to run on page object
    """
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
