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


@pytest.mark.asyncio
async def test_stealth_fetch_uses_configured_timeout(monkeypatch):
    """stealth/max-stealth 应把 fetch_timeout(秒)转成毫秒传给 camoufox"""
    from scrapling_fetch_mcp._config import config

    captured = {}

    async def fake_fetch(url, **kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.status = 200
        resp.body = b"<html></html>"
        resp.html_content = "<html></html>"
        return resp

    monkeypatch.setattr(
        "scrapling.fetchers.StealthyFetcher.async_fetch", fake_fetch)

    original = config.fetch_timeout
    try:
        config.set_fetch_timeout(45)
        await scrapling_mod._do_browse("http://x", "stealth")
        assert captured["timeout"] == 45000
        await scrapling_mod._do_browse("http://x", "max-stealth")
        assert captured["timeout"] == 45000
    finally:
        config.set_fetch_timeout(original)


class TestMarkdownContentNegotiation:
    """basic 模式的 Accept: text/markdown 协商探测"""

    def _make_response(self, content_type=None, body=b"# Hello"):
        # SimpleNamespace 而非 MagicMock:未附加的属性 getattr 必须拿到 None
        from types import SimpleNamespace
        resp = SimpleNamespace()
        resp.body = body
        headers = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        resp.headers = headers
        resp.html_content = "<html><body>wrapped</body></html>"
        return resp

    @pytest.mark.asyncio
    async def test_basic_request_sends_markdown_accept_header(self, monkeypatch):
        """basic 模式请求应带内容协商 Accept 头"""
        captured = {}

        async def fake_get(url, **kwargs):
            captured.update(kwargs)
            return self._make_response()

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        await scrapling_mod._do_browse("http://x", "basic")

        accept = captured["headers"]["Accept"]
        assert "text/markdown" in accept
        assert "text/html" in accept  # 未命中时可回退

    @pytest.mark.asyncio
    async def test_markdown_response_body_attached(self, monkeypatch):
        """响应为 text/markdown 时,原始 body 应挂到 markdown_content"""
        async def fake_get(url, **kwargs):
            return self._make_response(content_type="text/markdown; charset=utf-8",
                                       body=b"# Real Markdown\n\ntext")

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) == "# Real Markdown\n\ntext"

    @pytest.mark.asyncio
    async def test_html_response_not_attached(self, monkeypatch):
        """普通 HTML 响应不应附加 markdown_content"""
        async def fake_get(url, **kwargs):
            return self._make_response(content_type="text/html; charset=utf-8")

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) is None

    @pytest.mark.asyncio
    async def test_missing_content_type_header_tolerated(self, monkeypatch):
        """响应无 Content-Type 时不应抛错"""
        async def fake_get(url, **kwargs):
            return self._make_response()

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) is None
