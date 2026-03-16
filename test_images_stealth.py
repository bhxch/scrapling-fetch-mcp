#!/usr/bin/env python3
"""Test image saving with stealth mode to ensure images are loaded"""
import asyncio
from pathlib import Path
import sys
import json
import re

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from scrapling_fetch_mcp._fetcher import fetch_page_impl


async def test_with_mode(mode: str, url: str):
    """Test with specific mode"""
    print(f"\n{'=' * 80}")
    print(f"Testing with mode: {mode}")
    print(f"URL: {url}")
    print(f"{'=' * 80}")

    temp_dir = Path(f"/tmp/test_scrapling_{mode}")
    temp_dir.mkdir(exist_ok=True)

    try:
        print(f"\n🌐 Fetching...")
        result = await fetch_page_impl(
            url=url,
            mode=mode,
            format="html",
            max_length=100000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        print(f"✅ Fetch successful! Result length: {len(result):,} chars")

        # Find saved directory
        save_dirs = list(temp_dir.glob("*_*"))
        if not save_dirs:
            print("❌ No save directory found!")
            return

        save_dir = sorted(save_dirs)[-1]
        print(f"📁 Save directory: {save_dir}")

        # Check for images directory
        images_dir = save_dir / "images"
        if images_dir.exists():
            image_files = list(images_dir.glob("*"))
            print(f"🖼️  Images saved: {len(image_files)}")

            if image_files:
                print(f"\n📷 Sample images:")
                for img in image_files[:5]:
                    print(f"  {img.name} ({img.stat().st_size:,} bytes)")
        else:
            print("⚠️  No images directory found")

        # Read mapping
        mapping_file = save_dir / "image_mapping.json"
        if mapping_file.exists():
            with open(mapping_file) as f:
                mapping = json.load(f)

            print(f"\n🗺️  Image mapping: {len(mapping)} images")

            if mapping:
                for i, item in enumerate(mapping[:5], 1):
                    print(f"  {i}. {Path(item['original_url']).name[:50]}")
                    print(f"     → {item['local_path']}")

        # Check HTML for modifications
        page_file = save_dir / "page.html"
        if page_file.exists():
            with open(page_file) as f:
                content = f.read()

            original_srcs = re.findall(r'data-original-src="([^"]+)"', content)
            local_refs = re.findall(r'src="images/[^"]+"', content)

            print(f"\n📝 HTML verification:")
            print(f"  data-original-src attributes: {len(original_srcs)}")
            print(f"  Local image references: {len(local_refs)}")

            # Check for any img tags
            img_tags = re.findall(r'<img[^>]+>', content)
            print(f"  Total <img> tags: {len(img_tags)}")

            if img_tags and not local_refs:
                print(f"\n  ⚠️  Sample unmodified img tags:")
                for tag in img_tags[:3]:
                    print(f"    {tag[:100]}")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Test with different modes"""

    # Use a simple page with known images
    test_url = "https://httpbin.org/image/png"

    print("Testing different fetch modes")
    print("=" * 80)

    # Test stealth mode (should load images)
    await test_with_mode("stealth", "https://en.wikipedia.org/wiki/Python")

    print("\n" + "=" * 80)
    print("✅ Test completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
