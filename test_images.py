#!/usr/bin/env python3
"""Test image saving with a webpage that has images"""
import asyncio
from pathlib import Path
import sys
import json

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from scrapling_fetch_mcp._fetcher import fetch_page_impl


async def test_wikipedia():
    """Test with a Wikipedia page that has images"""
    print("=" * 80)
    print("Testing image saving with Wikipedia")
    print("=" * 80)

    temp_dir = Path("/tmp/test_scrapling_images")
    temp_dir.mkdir(exist_ok=True)

    # Use Python Wikipedia page - has logo and other images
    url = "https://en.wikipedia.org/wiki/Python_(programming_language)"

    try:
        print(f"\n🌐 Fetching: {url}")
        result = await fetch_page_impl(
            url=url,
            mode="basic",
            format="html",
            max_length=100000,  # Larger to get more content
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        print(f"\n✅ Fetch successful!")
        print(f"Result length: {len(result)} characters")

        # Find saved directory
        save_dirs = list(temp_dir.glob("en.wikipedia.org_*"))
        if not save_dirs:
            print("❌ No save directory found!")
            return

        save_dir = sorted(save_dirs)[-1]
        print(f"\n📁 Save directory: {save_dir}")

        # Check directory structure
        print(f"\n📂 Directory structure:")
        for item in save_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(save_dir)
                size = item.stat().st_size
                print(f"  {rel_path} ({size:,} bytes)")

        # Read metadata
        metadata_file = save_dir / "metadata.json"
        if metadata_file.exists():
            with open(metadata_file) as f:
                metadata = json.load(f)
            print(f"\n📊 Metadata:")
            for key, value in metadata.items():
                print(f"  {key}: {value}")

        # Read image mapping
        mapping_file = save_dir / "image_mapping.json"
        if mapping_file.exists():
            with open(mapping_file) as f:
                mapping = json.load(f)

            print(f"\n🗺️  Image mapping ({len(mapping)} images saved):")
            for i, item in enumerate(mapping[:10], 1):
                print(f"  {i}. {item['original_url'][:70]}")
                print(f"     → {item['local_path']}")

            if len(mapping) > 10:
                print(f"  ... and {len(mapping) - 10} more images")

        # Check if images directory exists and has files
        images_dir = save_dir / "images"
        if images_dir.exists():
            image_files = list(images_dir.glob("*"))
            print(f"\n🖼️  Images directory: {len(image_files)} files")

            # Show some image file details
            print(f"\n📷 Sample images:")
            for img_file in image_files[:5]:
                size = img_file.stat().st_size
                print(f"  {img_file.name} ({size:,} bytes)")

        # Read a snippet of the HTML to verify local paths
        page_file = save_dir / "page.html"
        if page_file.exists():
            with open(page_file) as f:
                content = f.read()

            print(f"\n📝 HTML content verification:")
            print(f"  Total size: {len(content):,} characters")

            # Check for data-original-src attributes
            import re
            original_srcs = re.findall(r'data-original-src="([^"]+)"', content)
            print(f"  Images with data-original-src: {len(original_srcs)}")

            # Check for local image paths
            local_refs = re.findall(r'src="images/[^"]+"', content)
            print(f"  Local image references: {len(local_refs)}")

            # Show a sample
            if original_srcs:
                print(f"\n  Sample original URLs:")
                for url in original_srcs[:3]:
                    print(f"    {url[:80]}")

            if local_refs:
                print(f"\n  Sample local references:")
                for ref in local_refs[:3]:
                    print(f"    {ref}")

        # Verify images can be opened (basic validation)
        if images_dir.exists():
            print(f"\n✅ Image file validation:")
            valid_count = 0
            for img_file in image_files[:10]:  # Check first 10
                try:
                    with open(img_file, 'rb') as f:
                        header = f.read(16)
                        # Check common image magic numbers
                        if (header[:8] == b'\x89PNG\r\n\x1a\n' or  # PNG
                            header[:2] == b'\xff\xd8' or           # JPEG
                            header[:4] == b'GIF8' or               # GIF
                            header[:4] == b'RIFF'):                # WebP
                            valid_count += 1
                            print(f"  ✓ {img_file.name} - valid image")
                except Exception as e:
                    print(f"  ✗ {img_file.name} - error: {e}")

            if valid_count > 0:
                print(f"\n  {valid_count}/{min(10, len(image_files))} images validated")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    await test_wikipedia()

    print("\n" + "=" * 80)
    print("✅ Image saving test completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
