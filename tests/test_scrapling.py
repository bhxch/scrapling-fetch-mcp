"""Tests for scrapling wrapper"""
import pytest
from unittest.mock import AsyncMock, MagicMock

import scrapling_fetch_mcp._scrapling as scrapling_mod


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


class TestBrowseUrlGuard:
    def setup_method(self):
        scrapling_mod._guard = None

    def teardown_method(self):
        scrapling_mod._guard = None

    @pytest.mark.asyncio
    async def test_guard_in_flight_during_call(self, monkeypatch):
        scrapling_mod.init_guard(max_concurrent=2, acquire_timeout=1.0)
        seen = []

        async def fake_browse(url, mode, page_action=None):
            seen.append(scrapling_mod._guard.in_flight)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)

        result = await scrapling_mod.browse_url("http://x", "basic")
        assert result == "page"
        assert seen == [1]
        assert scrapling_mod._guard.in_flight == 0
        assert scrapling_mod._guard.total_acquired == 1

    @pytest.mark.asyncio
    async def test_no_guard_skips_limiting(self, monkeypatch):
        called = []

        async def fake_browse(url, mode, page_action=None):
            called.append(url)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)
        result = await scrapling_mod.browse_url("http://y", "basic")
        assert result == "page"
        assert scrapling_mod._guard is None
        assert called == ["http://y"]
