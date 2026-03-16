#!/usr/bin/env python3
"""Direct test of scrapling page_action"""
import asyncio
from pathlib import Path
from contextlib import redirect_stdout
from os import devnull

# Directly test scrapling's page_action
async def test_scrapling_direct():
    print("Testing scrapling page_action directly")
    print("=" * 80)

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import StealthyFetcher

        intercepted_urls = []

        async def my_page_action(page):
            """Custom page action"""
            print(">>> page_action called! <<<", flush=True)  # Force print

            async def handle_route(route):
                url = route.request.url
                intercepted_urls.append(url)
                print(f">>> Intercepted: {url} <<<", flush=True)
                await route.continue_()

            # Intercept ALL requests
            await page.route("**/*", handle_route)
            print(f">>> Route registered <<<", flush=True)

        # Fetch with page_action
        print("\nFetching https://httpbin.org/html with page_action...", flush=True)

    # Redirect only scrapling's output, keep our prints
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        result = await StealthyFetcher.async_fetch(
            "https://httpbin.org/html",
            headless=True,
            network_idle=True,
            block_images=False,
            page_action=my_page_action,
        )

    print(f"\nFetch completed!")
    print(f"Intercepted {len(intercepted_urls)} requests:")
    for url in intercepted_urls[:10]:
        print(f"  {url}")

    if len(intercepted_urls) > 10:
        print(f"  ... and {len(intercepted_urls) - 10} more")

    print(f"\nPage HTML length: {len(result.html_content)} chars")


asyncio.run(test_scrapling_direct())
