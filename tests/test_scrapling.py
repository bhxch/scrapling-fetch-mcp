"""Tests for scrapling wrapper"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_browse_url_with_page_action():
    """Test browse_url accepts page_action parameter"""
    from scrapling_fetch_mcp._scrapling import browse_url

    # Mock page_action function
    page_action_called = False

    async def test_page_action(page):
        nonlocal page_action_called
        page_action_called = True

    # This test will verify the parameter is accepted
    # We won't actually call browse_url as it requires real browser
    # Just verify the signature accepts the parameter
    import inspect
    sig = inspect.signature(browse_url)
    params = sig.parameters

    # Check if page_action parameter exists
    assert "page_action" in params
