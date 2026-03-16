"""Integration tests for content saving

Note: These tests require network access.
They may be skipped in environments without network access.
"""
import pytest
from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_real_webpage(temp_dir):
    """Test saving a real webpage with images using max-stealth mode"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    # Use Wikipedia page which has images
    url = "https://en.wikipedia.org/wiki/Python"

    result = await fetch_page_impl(
        url=url,
        mode="max-stealth",  # Use max-stealth to enable image interception
        format="html",
        max_length=50000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return content
    assert "METADATA:" in result
    assert len(result) > 1000  # Should have substantial content

    # Should create save directory
    save_dirs = list(temp_dir.glob("en.wikipedia.org_*"))
    assert len(save_dirs) >= 1

    save_dir = sorted(save_dirs)[-1]  # Get the most recent one

    # Should have required files
    assert (save_dir / "page.html").exists(), "page.html should exist"
    assert (save_dir / "metadata.json").exists(), "metadata.json should exist"
    assert (save_dir / "image_mapping.json").exists(), "image_mapping.json should exist"

    # Check metadata
    import json
    with open(save_dir / "metadata.json") as f:
        metadata = json.load(f)

    assert metadata["url"] == url
    assert "fetch_time" in metadata
    assert metadata["format"] == "html"

    # Check if images were saved
    images_dir = save_dir / "images"
    # Note: The number of images saved depends on the page structure and browser behavior
    # We just verify the structure is correct, not specific image counts


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_webpage_markdown(temp_dir):
    """Test saving webpage as markdown with images"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    url = "https://en.wikipedia.org/wiki/Python"

    result = await fetch_page_impl(
        url=url,
        mode="max-stealth",
        format="markdown",
        max_length=50000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return markdown
    assert "METADATA:" in result

    # Should create .md file
    save_dirs = list(temp_dir.glob("en.wikipedia.org_*"))
    save_dir = sorted(save_dirs)[-1]

    assert (save_dir / "page.md").exists(), "page.md should exist"
    assert not (save_dir / "page.html").exists(), "page.html should not exist when format is markdown"

    # Check if markdown file has content
    md_content = (save_dir / "page.md").read_text()
    assert len(md_content) > 1000, "Markdown file should have substantial content"

