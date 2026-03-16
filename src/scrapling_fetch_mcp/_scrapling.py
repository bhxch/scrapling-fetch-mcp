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
        page_action: Optional async function that receives a route handler setup function
                     (signature: async def page_action(setup_routes: Callable))
    """
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        # If page_action is provided, inject it via monkey-patching
        # to set up route interception BEFORE navigation
        if page_action and mode in ("stealth", "max-stealth"):
            from scrapling.engines._browsers._base import AsyncSession

            # Store original method
            original_init_context = AsyncSession._initialize_context

            # Create wrapper that sets up context-level routes
            async def patched_init_context(self, config, ctx):
                """Patched _initialize_context that sets up routes before any pages are created"""
                # Call original initialization first
                result = await original_init_context(self, config, ctx)

                # Now call page_action with a function that sets up routes on the context
                # This happens BEFORE any page.goto(), so we can intercept all requests
                if page_action:
                    try:
                        # Pass a lambda that calls ctx.route
                        await page_action(lambda pattern, handler: ctx.route(pattern, handler))
                    except Exception:
                        pass  # Ignore errors in page_action

                return result

            # Monkey-patch the method
            AsyncSession._initialize_context = patched_init_context

            try:
                if mode == "stealth":
                    result = await StealthyFetcher.async_fetch(
                        url,
                        headless=True,
                        network_idle=True,
                    )
                else:  # max-stealth
                    result = await StealthyFetcher.async_fetch(
                        url,
                        headless=True,
                        block_webrtc=True,
                        network_idle=True,
                        disable_resources=False,
                        block_images=False,
                    )
            finally:
                # Restore original method
                AsyncSession._initialize_context = original_init_context

            return result
        else:
            # No page_action, use normal flow
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
