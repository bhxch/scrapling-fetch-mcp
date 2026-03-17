"""Tests for fetcher functions"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


def test_convert_with_markitdown(sample_html):
    """Test HTML to Markdown conversion with markitdown"""
    from scrapling_fetch_mcp._fetcher import _convert_with_markitdown

    result = _convert_with_markitdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_convert_with_markdownify(sample_html):
    """Test HTML to Markdown conversion with markdownify"""
    from scrapling_fetch_mcp._fetcher import _convert_with_markdownify

    result = _convert_with_markdownify(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_markitdown(sample_html, monkeypatch):
    """Test _html_to_markdown uses markitdown when configured"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markitdown
    config.set_markdown_converter("markitdown")

    result = _html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_markdownify(sample_html, monkeypatch):
    """Test _html_to_markdown uses markdownify when configured"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markdownify
    config.set_markdown_converter("markdownify")

    result = _html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_explicit_converter(sample_html):
    """Test _html_to_markdown with explicit converter parameter"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown

    result = _html_to_markdown(sample_html, converter="markdownify")

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_invalid_converter(sample_html):
    """Test _html_to_markdown raises error for invalid converter"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown

    with pytest.raises(ValueError, match="Unknown converter"):
        _html_to_markdown(sample_html, converter="invalid")


@pytest.mark.asyncio
async def test_fetch_page_impl_with_save_content(temp_dir):
    """Test fetch_page_impl with save_content enabled"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    # Mock browse_url to return a fake response
    mock_response = MagicMock()
    mock_response.html_content = "<html><body><h1>Test</h1></body></html>"

    with patch("scrapling_fetch_mcp._fetcher.browse_url", new_callable=AsyncMock) as mock_browse:
        mock_browse.return_value = mock_response

        result = await fetch_page_impl(
            url="https://example.com",
            mode="max-stealth",
            format="html",
            max_length=10000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        # Should return content
        assert "METADATA:" in result
        assert "Test" in result

        # browse_url should be called with page_action
        assert mock_browse.called
        call_kwargs = mock_browse.call_args.kwargs
        assert "page_action" in call_kwargs
        assert callable(call_kwargs["page_action"])
