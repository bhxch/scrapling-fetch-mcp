#!/usr/bin/env python3
"""Manual integration test for content saving feature"""
import asyncio
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from scrapling_fetch_mcp._fetcher import fetch_page_impl


async def test_httpbin():
    """Test with httpbin.org (has images and reliable)"""
    print("=" * 60)
    print("Testing with httpbin.org/html")
    print("=" * 60)

    temp_dir = Path("/tmp/test_scrapling")
    temp_dir.mkdir(exist_ok=True)

    try:
        result = await fetch_page_impl(
            url="https://httpbin.org/html",
            mode="basic",
            format="markdown",
            max_length=50000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        print(f"\n✅ Fetch successful!")
        print(f"Result length: {len(result)} characters")

        # Find saved directory
        save_dirs = list(temp_dir.glob("httpbin.org_*"))
        if save_dirs:
            save_dir = save_dirs[-1]
            print(f"\n📁 Save directory: {save_dir}")

            # Check files
            files = list(save_dir.glob("*"))
            print(f"\n📄 Saved files:")
            for f in files:
                if f.is_file():
                    print(f"  - {f.name} ({f.stat().st_size} bytes)")
                elif f.is_dir():
                    print(f"  - {f.name}/")
                    subfiles = list(f.glob("*"))
                    for sf in subfiles:
                        print(f"    - {sf.name} ({sf.stat().st_size} bytes)")

            # Read metadata
            import json
            metadata_file = save_dir / "metadata.json"
            if metadata_file.exists():
                with open(metadata_file) as mf:
                    metadata = json.load(mf)
                print(f"\n📊 Metadata:")
                print(json.dumps(metadata, indent=2))

            # Read image mapping
            mapping_file = save_dir / "image_mapping.json"
            if mapping_file.exists():
                with open(mapping_file) as mf:
                    mapping = json.load(mf)
                print(f"\n🗺️  Image mapping ({len(mapping)} images):")
                for item in mapping[:5]:  # Show first 5
                    print(f"  {item['original_url'][:50]} -> {item['local_path']}")
                if len(mapping) > 5:
                    print(f"  ... and {len(mapping) - 5} more")

            # Check if content has local paths
            page_file = save_dir / "page.md"
            if page_file.exists():
                with open(page_file) as pf:
                    content = pf.read()
                print(f"\n📝 Content preview (first 500 chars):")
                print(content[:500])

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def test_example_com():
    """Test with example.com (simple, no images)"""
    print("\n" + "=" * 60)
    print("Testing with example.com")
    print("=" * 60)

    temp_dir = Path("/tmp/test_scrapling")
    temp_dir.mkdir(exist_ok=True)

    try:
        result = await fetch_page_impl(
            url="https://example.com",
            mode="basic",
            format="html",
            max_length=10000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        print(f"\n✅ Fetch successful!")
        print(f"Result length: {len(result)} characters")

        # Find saved directory
        save_dirs = list(temp_dir.glob("example.com_*"))
        if save_dirs:
            save_dir = save_dirs[-1]
            print(f"\n📁 Save directory: {save_dir}")

            # Check files
            files = list(save_dir.glob("*"))
            print(f"\n📄 Saved files:")
            for f in files:
                if f.is_file():
                    print(f"  - {f.name} ({f.stat().st_size} bytes)")
                elif f.is_dir():
                    print(f"  - {f.name}/")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()


async def main():
    """Run all tests"""
    await test_example_com()
    await test_httpbin()

    print("\n" + "=" * 60)
    print("✅ Manual integration tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
