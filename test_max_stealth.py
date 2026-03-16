#!/usr/bin/env python3
"""Test with max-stealth mode to ensure images are loaded"""
import asyncio
from pathlib import Path
import sys
import json
import re

sys.path.insert(0, str(Path(__file__).parent / "src"))

from scrapling_fetch_mcp._fetcher import fetch_page_impl


async def test_max_stealth():
    """Test with max-stealth mode (loads images)"""
    print("=" * 80)
    print("Testing with MAX-STEALTH mode (images should load)")
    print("=" * 80)

    temp_dir = Path("/tmp/test_scrapling_maxstealth")
    temp_dir.mkdir(exist_ok=True)

    url = "https://en.wikipedia.org/wiki/Python"

    try:
        print(f"\n🌐 Fetching: {url}")
        print(f"Mode: max-stealth (block_images=False)")

        result = await fetch_page_impl(
            url=url,
            mode="max-stealth",
            format="html",
            max_length=100000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        print(f"\n✅ Fetch successful!")
        print(f"Result length: {len(result):,} characters")

        # Find saved directory
        save_dirs = list(temp_dir.glob("en.wikipedia.org_*"))
        if not save_dirs:
            print("❌ No save directory found!")
            return

        save_dir = sorted(save_dirs)[-1]
        print(f"\n📁 Save directory: {save_dir}")

        # Check directory structure
        print(f"\n📂 Saved files:")
        for item in save_dir.iterdir():
            if item.is_file():
                print(f"  {item.name} ({item.stat().st_size:,} bytes)")
            elif item.is_dir():
                file_count = len(list(item.glob("*")))
                print(f"  {item.name}/ ({file_count} files)")

        # Check images directory
        images_dir = save_dir / "images"
        if images_dir.exists():
            image_files = list(images_dir.glob("*"))
            print(f"\n🖼️  Images saved: {len(image_files)}")

            if image_files:
                # Group by extension
                by_ext = {}
                for img in image_files:
                    ext = img.suffix.lower()
                    if ext not in by_ext:
                        by_ext[ext] = []
                    by_ext[ext].append(img)

                print(f"\n📊 Image types:")
                for ext, files in sorted(by_ext.items()):
                    total_size = sum(f.stat().st_size for f in files)
                    print(f"  {ext or 'no ext'}: {len(files)} files, {total_size:,} bytes total")

                print(f"\n📷 Sample images:")
                for img in sorted(image_files, key=lambda x: x.stat().st_size, reverse=True)[:10]:
                    print(f"  {img.name} ({img.stat().st_size:,} bytes)")
        else:
            print("\n⚠️  No images directory!")

        # Read image mapping
        mapping_file = save_dir / "image_mapping.json"
        if mapping_file.exists():
            with open(mapping_file) as f:
                mapping = json.load(f)

            print(f"\n🗺️  Image mapping: {len(mapping)} entries")

            if mapping:
                print(f"\nSample mappings:")
                for i, item in enumerate(mapping[:8], 1):
                    filename = Path(item['original_url']).name
                    print(f"  {i}. {filename[:60]}")
                    print(f"     {item['local_path']}")

        # Check HTML modifications
        page_file = save_dir / "page.html"
        if page_file.exists():
            with open(page_file) as f:
                content = f.read()

            original_srcs = re.findall(r'data-original-src="([^"]+)"', content)
            local_refs = re.findall(r'src="images/[^"]+"', content)
            img_tags = re.findall(r'<img[^>]+>', content)

            print(f"\n📝 HTML verification:")
            print(f"  Total size: {len(content):,} characters")
            print(f"  <img> tags: {len(img_tags)}")
            print(f"  data-original-src: {len(original_srcs)}")
            print(f"  Local src refs: {len(local_refs)}")

            # Show sample of modified tags
            if local_refs:
                modified_tags = [tag for tag in img_tags if 'src="images/' in tag]
                print(f"\n✅ Sample modified <img> tags:")
                for tag in modified_tags[:3]:
                    print(f"  {tag[:120]}")

            # Check if any images weren't modified
            unmodified = [tag for tag in img_tags if 'src="images/' not in tag and 'src="' in tag]
            if unmodified:
                print(f"\n⚠️  Unmodified <img> tags: {len(unmodified)}")
                for tag in unmodified[:3]:
                    src_match = re.search(r'src="([^"]+)"', tag)
                    if src_match:
                        print(f"  {src_match.group(1)[:80]}")

        # Validate some saved images
        if images_dir.exists() and image_files:
            print(f"\n✅ Image validation:")
            valid = 0
            for img in image_files[:10]:
                try:
                    with open(img, 'rb') as f:
                        header = f.read(16)

                    is_valid = False
                    img_type = "unknown"

                    if header[:8] == b'\x89PNG\r\n\x1a\n':
                        img_type = "PNG"
                        is_valid = True
                    elif header[:2] == b'\xff\xd8':
                        img_type = "JPEG"
                        is_valid = True
                    elif header[:4] == b'GIF8':
                        img_type = "GIF"
                        is_valid = True
                    elif header[:4] == b'RIFF':
                        img_type = "WebP"
                        is_valid = True
                    elif header[:5] == b'<?xml' or b'<svg' in header[:100]:
                        img_type = "SVG"
                        is_valid = True

                    if is_valid:
                        valid += 1
                        print(f"  ✓ {img.name[:40]} - {img_type}")
                    else:
                        print(f"  ? {img.name[:40]} - unknown format")

                except Exception as e:
                    print(f"  ✗ {img.name[:40]} - error: {e}")

            print(f"\n  {valid}/{min(10, len(image_files))} images validated")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    await test_max_stealth()

    print("\n" + "=" * 80)
    print("✅ Max-stealth test completed!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
