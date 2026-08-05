"""Tests for fetcher functions"""
import asyncio

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


class TestFetchPageWrapper:
    """Tests for fetch_page_wrapper middleware function."""

    @pytest.mark.asyncio
    async def test_format_none_resolves_to_default(self):
        """When format=None, wrapper should use config.default_format."""
        from scrapling_fetch_mcp._fetcher import fetch_page_wrapper

        mock_impl = AsyncMock(return_value="METADATA: {} dummy content")
        mock_config = MagicMock()
        mock_config.default_format = "airead"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_page_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
        ):
            await fetch_page_wrapper(
                url="https://example.com",
                mode="basic",
                format=None,
                max_length=8000,
                start_index=0,
            )

        mock_impl.assert_called_once()
        # fetch_page_impl(url, mode, format, max_length, start_index, ...)
        # Positional: args[0]=url, args[1]=mode, args[2]=format
        call = mock_impl.call_args
        assert call.args[0] == "https://example.com"  # url
        assert call.args[1] == "basic"                 # mode
        assert call.args[2] == "airead"                # format

    @pytest.mark.asyncio
    async def test_format_explicit_not_overridden(self):
        """When format is explicitly set, wrapper should not override it."""
        from scrapling_fetch_mcp._fetcher import fetch_page_wrapper

        mock_impl = AsyncMock(return_value="METADATA: {} dummy content")
        mock_config = MagicMock()
        mock_config.default_format = "airead"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_page_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
        ):
            await fetch_page_wrapper(
                url="https://example.com",
                mode="basic",
                format="markdown",
                max_length=8000,
                start_index=0,
            )

        mock_impl.assert_called_once()
        # fetch_page_impl(url, mode, format, max_length, start_index, ...)
        # Positional: args[0]=url, args[1]=mode, args[2]=format
        call = mock_impl.call_args
        assert call.args[0] == "https://example.com"  # url
        assert call.args[1] == "basic"                 # mode
        assert call.args[2] == "markdown"              # format

    @pytest.mark.asyncio
    async def test_error_handling_preserves_exceptions(self):
        """Exceptions from impl should be re-raised after logging."""
        from scrapling_fetch_mcp._fetcher import fetch_page_wrapper

        mock_impl = AsyncMock(side_effect=RuntimeError("fetch failed"))
        mock_config = MagicMock()
        mock_config.default_format = "markdown"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_page_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
            pytest.raises(RuntimeError, match="fetch failed"),
        ):
            await fetch_page_wrapper(
                url="https://example.com",
                mode="basic",
                format="markdown",
                max_length=8000,
                start_index=0,
            )

    @pytest.mark.asyncio
    async def test_scraping_dir_converted_to_path(self):
        """scraping_dir string should be converted to Path before passing to impl."""
        from scrapling_fetch_mcp._fetcher import fetch_page_wrapper

        mock_impl = AsyncMock(return_value="METADATA: {} dummy content")
        mock_config = MagicMock()
        mock_config.default_format = "markdown"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_page_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
        ):
            await fetch_page_wrapper(
                url="https://example.com",
                mode="basic",
                format="markdown",
                max_length=8000,
                start_index=0,
                save_content=True,
                scraping_dir="/custom/path/",
            )

        mock_impl.assert_called_once()
        # scraping_dir is passed as keyword arg to fetch_page_impl
        call = mock_impl.call_args
        assert isinstance(call.kwargs["scraping_dir"], Path)
        assert call.kwargs["scraping_dir"] == Path("/custom/path/")
        assert call.kwargs["save_content"] is True


class TestFetchPatternWrapper:
    """Tests for fetch_pattern_wrapper middleware function."""

    @pytest.mark.asyncio
    async def test_airead_fallback_to_markdown(self):
        """When format=None and config default is airead, should fallback to markdown."""
        from scrapling_fetch_mcp._fetcher import fetch_pattern_wrapper

        mock_impl = AsyncMock(return_value="METADATA: {} matched content")
        mock_config = MagicMock()
        mock_config.default_format = "airead"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_pattern_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
        ):
            await fetch_pattern_wrapper(
                url="https://example.com",
                search_pattern=r"hello",
                mode="basic",
                format=None,
                max_length=8000,
            )

        mock_impl.assert_called_once()
        # fetch_pattern_impl(url, search_pattern, mode, format, max_length, context_chars)
        # Positional: args[0]=url, args[1]=search_pattern, args[2]=mode, args[3]=format
        call = mock_impl.call_args
        assert call.args[0] == "https://example.com"  # url
        assert call.args[1] == r"hello"               # search_pattern
        assert call.args[2] == "basic"                # mode
        assert call.args[3] == "markdown"             # format (fallback from airead)

    @pytest.mark.asyncio
    async def test_explicit_format_not_fallback(self):
        """When format is explicitly set, it should not be overridden or fallback."""
        from scrapling_fetch_mcp._fetcher import fetch_pattern_wrapper

        mock_impl = AsyncMock(return_value="METADATA: {} matched content")
        mock_config = MagicMock()
        mock_config.default_format = "airead"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_pattern_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
        ):
            await fetch_pattern_wrapper(
                url="https://example.com",
                search_pattern=r"hello",
                mode="basic",
                format="markdown",
                max_length=8000,
            )

        mock_impl.assert_called_once()
        # fetch_pattern_impl(url, search_pattern, mode, format, max_length, context_chars)
        # Positional: args[0]=url, args[1]=search_pattern, args[2]=mode, args[3]=format
        call = mock_impl.call_args
        assert call.args[0] == "https://example.com"  # url
        assert call.args[1] == r"hello"               # search_pattern
        assert call.args[2] == "basic"                # mode
        assert call.args[3] == "markdown"             # format (explicit, no fallback)

    @pytest.mark.asyncio
    async def test_error_handling_preserves_exceptions(self):
        """Exceptions from impl should be re-raised after logging."""
        from scrapling_fetch_mcp._fetcher import fetch_pattern_wrapper

        mock_impl = AsyncMock(side_effect=RuntimeError("test error"))
        mock_config = MagicMock()
        mock_config.default_format = "markdown"

        with (
            patch("scrapling_fetch_mcp._fetcher.fetch_pattern_impl", mock_impl),
            patch("scrapling_fetch_mcp._fetcher.config", mock_config),
            pytest.raises(RuntimeError, match="test error"),
        ):
            await fetch_pattern_wrapper(
                url="https://example.com",
                search_pattern="test",
                mode="basic",
                format="markdown",
                max_length=8000,
                context_chars=200,
            )


import scrapling_fetch_mcp._fetcher as fetcher_mod
from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
from scrapling_fetch_mcp._fetcher import (
    fetch_page_wrapper,
    fetch_pattern_wrapper,
    fetch_page_impl,
    fetch_pattern_impl,
)


class TestWrapperConcurrencyError:
    def setup_method(self):
        config.set_disable_url_rewrite(True)

    @pytest.mark.asyncio
    async def test_page_wrapper_propagates_concurrency_error(self, monkeypatch):
        async def boom(*a, **k):
            raise ConcurrencyLimitError("busy")

        monkeypatch.setattr(fetcher_mod, "browse_url", boom)
        with pytest.raises(ConcurrencyLimitError):
            await fetch_page_wrapper("http://x", "basic", "markdown", 1000, 0)

    @pytest.mark.asyncio
    async def test_pattern_wrapper_propagates_concurrency_error(self, monkeypatch):
        async def boom(*a, **k):
            raise ConcurrencyLimitError("busy")

        monkeypatch.setattr(fetcher_mod, "browse_url", boom)
        with pytest.raises(ConcurrencyLimitError):
            await fetch_pattern_wrapper("http://x", "pattern", "basic", "markdown", 1000)


class TestFetchTimeout:
    def setup_method(self):
        config.set_disable_url_rewrite(True)
        config.set_fetch_timeout(0.05)  # 50ms

    def teardown_method(self):
        config.set_fetch_timeout(60.0)

    @pytest.mark.asyncio
    async def test_page_impl_timeout(self, monkeypatch):
        async def slow(*a, **k):
            await asyncio.sleep(1)
            return "page"

        monkeypatch.setattr(fetcher_mod, "browse_url", slow)
        with pytest.raises(TimeoutError):
            await fetch_page_wrapper("http://x", "basic", "markdown", 1000, 0)

    @pytest.mark.asyncio
    async def test_pattern_impl_timeout(self, monkeypatch):
        async def slow(*a, **k):
            await asyncio.sleep(1)
            return "page"

        monkeypatch.setattr(fetcher_mod, "browse_url", slow)
        with pytest.raises(TimeoutError):
            await fetch_pattern_wrapper("http://x", "pat", "basic", "markdown", 1000)


class TestProgressReporting:
    """Tests for MCP Context-based progress reporting in impl functions.

    When a ctx (mcp Context) is passed, impl functions report progress at
    key stages (before browse, after browse, on completion) so that the
    MCP server can emit progress notifications acting as liveness heartbeats
    for long-running fetches.
    """

    def setup_method(self):
        config.set_disable_url_rewrite(True)
        # Ensure cache miss so browse_url is exercised end-to-end
        config.cache.clear_all()

    @pytest.mark.asyncio
    async def test_page_impl_reports_progress(self, monkeypatch):
        """fetch_page_impl reports progress at >=2 stages when ctx is provided."""
        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body>x</body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        ctx = AsyncMock()
        await fetch_page_impl("http://x", "basic", "markdown", 1000, 0, ctx=ctx)
        assert ctx.report_progress.called
        # At least: before browse + after browse / completion
        assert ctx.report_progress.call_count >= 2

    @pytest.mark.asyncio
    async def test_page_impl_no_ctx_does_not_raise(self, monkeypatch):
        """fetch_page_impl works normally when ctx is None (default)."""
        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body>x</body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        # No ctx= passed; should not raise
        result = await fetch_page_impl("http://x", "basic", "markdown", 1000, 0)
        assert "METADATA:" in result

    @pytest.mark.asyncio
    async def test_pattern_impl_reports_progress(self, monkeypatch):
        """fetch_pattern_impl reports progress when ctx is provided."""
        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body>hello world</body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        ctx = AsyncMock()
        await fetch_pattern_impl(
            "http://x", "hello", "basic", "markdown", 1000, 200, ctx=ctx
        )
        assert ctx.report_progress.called

    @pytest.mark.asyncio
    async def test_wrapper_forwards_ctx_to_impl(self, monkeypatch):
        """fetch_page_wrapper forwards ctx to fetch_page_impl."""
        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body>x</body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        ctx = AsyncMock()
        await fetch_page_wrapper(
            "http://x", "basic", "markdown", 1000, 0, ctx=ctx
        )
        assert ctx.report_progress.called

