#!/usr/bin/env python3
"""Test page_action with file logging"""
import asyncio
from pathlib import Path
from contextlib import redirect_stdout
from os import devnull
import sys

async def test_with_file_logging():
    """Test with logging to file"""
    log_file = Path("/tmp/scrapling_debug.log")

    print(f"Testing page_action with file logging")
    print(f"Log file: {log_file}")
    print("=" * 80)

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling import StealthyFetcher

        async def page_action_log_to_file(page):
            # Log to file to avoid buffering issues
            with open(log_file, "a") as f:
                f.write(">>> PAGE_ACTION CALLED! <<<\n")
                f.write(f"Page URL: {page.url}\n")
                f.flush()

            intercepted_count = [0]  # Use list to allow modification in closure

            async def handler(route):
                intercepted_count[0] += 1
                url = route.request.url
                rtype = route.request.resource_type

                with open(log_file, "a") as f:
                    f.write(f"Request #{intercepted_count[0]}: {url} ({rtype})\n")
                    f.flush()

                await route.continue_()

            # Register route
            await page.route("**/*", handler)

            with open(log_file, "a") as f:
                f.write(f"Route handler registered\n")
                f.flush()

    # Clear log file
    log_file.write_text("")

    print("\nFetching https://httpbin.org/html...")

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        result = await StealthyFetcher.async_fetch(
            "https://httpbin.org/html",
            headless=True,
            block_images=False,
            disable_resources=False,  # Don't disable any resources
            page_action=page_action_log_to_file,
        )

    print(f"Fetch complete!")
    print(f"HTML length: {len(result.html_content)} chars\n")

    # Read log file
    if log_file.exists():
        log_content = log_file.read_text()
        if log_content:
            print(f"Log file content:")
            print(log_content)
        else:
            print("❌ Log file is empty - page_action was NOT called!")
    else:
        print("❌ Log file doesn't exist!")


asyncio.run(test_with_file_logging())
