#!/usr/bin/env python3
"""Test route interception BEFORE navigation by modifying scrapling's session"""
import asyncio
from pathlib import Path
from contextlib import redirect_stdout
from os import devnull

async def test_route_before_navigation():
    """Test by monkey-patching scrapling to add routes before navigation"""
    print("Testing route interception BEFORE navigation")
    print("=" * 80)

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        # Import scrapling
        from scrapling.fetchers import StealthyFetcher
        from scrapling.engines._browsers._stealth import AsyncStealthySession
        from scrapling.engines._browsers._base import AsyncSession

        # Store original method
        original_init_context = AsyncSession._initialize_context

        intercepted_images = []

        # Create custom initialization that adds route handler
        async def custom_init_context(self, config, ctx):
            """Custom context initialization that adds image interception"""
            print(">>> Custom _initialize_context called!", flush=True)

            # Set up route handler at CONTEXT level (before any pages are created)
            async def handle_image_route(route):
                url = route.request.url
                resource_type = route.request.resource_type

                if resource_type == "image":
                    print(f">>> Intercepted image: {url}", flush=True)
                    intercepted_images.append(url)

                    # Fetch the image
                    response = await route.fetch()
                    body = await response.body()
                    print(f"   Size: {len(body)} bytes", flush=True)

                    # Fulfill with the response
                    await route.fulfill(response=response)
                else:
                    await route.continue_()

            # Register route for images at context level
            await ctx.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,bmp}", handle_image_route)
            print(">>> Context-level route handler registered!", flush=True)

            # Call original initialization
            return await original_init_context(self, config, ctx)

        # Monkey-patch the method
        AsyncSession._initialize_context = custom_init_context

    print("\nFetching https://en.wikipedia.org/wiki/Python...")
    print("(Monkey-patched to add route interception before navigation)\n")

    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        result = await StealthyFetcher.async_fetch(
            "https://en.wikipedia.org/wiki/Python",
            headless=True,
            block_images=False,
            disable_resources=False,
        )

    print(f"Fetch complete!")
    print(f"HTML length: {len(result.html_content)} chars\n")

    print(f"Intercepted {len(intercepted_images)} images:")
    for img in intercepted_images[:10]:
        print(f"  {img}")

    if len(intercepted_images) > 10:
        print(f"  ... and {len(intercepted_images) - 10} more")

    # Restore original method
    AsyncSession._initialize_context = original_init_context


asyncio.run(test_route_before_navigation())
