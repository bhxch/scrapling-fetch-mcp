"""Integration tests for content saving

Note: These tests require network access and proper SSL certificates.
They may be skipped in environments without network access.
"""
import pytest
from pathlib import Path


@pytest.mark.integration
@pytest.mark.skip(reason="Requires network access and SSL certificates")
@pytest.mark.asyncio
async def test_save_real_webpage(temp_dir):
    """Test saving a real webpage with images"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    # Use a simple, reliable test page
    url = "https://example.com"

    result = await fetch_page_impl(
        url=url,
        mode="basic",
        format="html",
        max_length=10000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return content
    assert "METADATA:" in result

    # Should create save directory
    save_dirs = list(temp_dir.glob("example.com_*"))
    assert len(save_dirs) == 1

    save_dir = save_dirs[0]

    # Should have required files
    assert (save_dir / "page.html").exists()
    assert (save_dir / "metadata.json").exists()
    assert (save_dir / "image_mapping.json").exists()

    # Check metadata
    import json
    with open(save_dir / "metadata.json") as f:
        metadata = json.load(f)

    assert metadata["url"] == url
    assert "fetch_time" in metadata
    assert metadata["format"] == "html"


@pytest.mark.integration
@pytest.mark.skip(reason="Requires network access and SSL certificates")
@pytest.mark.asyncio
async def test_save_webpage_markdown(temp_dir):
    """Test saving webpage as markdown"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    url = "https://example.com"

    result = await fetch_page_impl(
        url=url,
        mode="basic",
        format="markdown",
        max_length=10000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return markdown
    assert "METADATA:" in result

    # Should create .md file
    save_dirs = list(temp_dir.glob("example.com_*"))
    save_dir = save_dirs[0]

    assert (save_dir / "page.md").exists()
    assert not (save_dir / "page.html").exists()
