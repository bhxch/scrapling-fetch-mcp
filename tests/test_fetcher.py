"""Tests for fetcher functions"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


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
