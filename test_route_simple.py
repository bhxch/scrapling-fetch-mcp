#!/usr/bin/env python3
"""Test with explicit route handling"""
import asyncio
from pathlib import Path
from contextlib import redirect_stdout
from os import devnull

async def test_explicit_route():
    """Test with explicit image route"""
    print("Testing with explicit route handling")
    print("=" * 80)

    temp_dir = Path("/tmp/test_explicit_route")
    temp_dir.mkdir(exist_ok=True)

    intercepted = []

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import StealthyFetcher

        async def page_action_with_logging(page):
            print(">>> Page action called! <<<", flush=True)

            # Try multiple route patterns
            patterns = [
                "**/*.png",
                "**/*.jpg",
                "**/*.jpeg",
                "**/*.gif",
                "**/*.svg",
                "**/*.webp",
                "**/*",
            ]

            async def handler(route):
                url = route.request.url
                resource_type = route.request.resource_type

                print(f">>> Intercepted: {url} (type: {resource_type}) <<<", flush=True)
                intercepted.append((url, resource_type))

                # Continue the request
                await route.continue_()

            # Register for all requests
            await page.route("**/*", handler)
            print(f">>> Registered route handler for **/* <<<", flush=True)

    print("\nFetching https://httpbin.org/image/png...")
    print("This page returns a PNG image directly\n")

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        try:
            result = await StealthyFetcher.async_fetch(
                "https://httpbin.org/image/png",
                headless=True,
                block_images=False,  # Important: don't block images
                page_action=page_action_with_logging,
            )

            print(f"Fetch successful!")
            print(f"HTML content length: {len(result.html_content)}")

        except Exception as e:
            print(f"Error: {e}")

    print(f"\nIntercepted {len(intercepted)} requests:")
    for url, rtype in intercepted[:20]:
        print(f"  [{rtype}] {url}")

asyncio.run(test_explicit_route())
