"""Tests for fetcher functions"""
import asyncio

import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


def test_convert_with_markitdown(sample_html):
    """Test HTML to Markdown conversion with markitdown"""
    from scrapling_fetch_mcp._html_converter import convert_with_markitdown

    result = convert_with_markitdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_convert_with_markdownify(sample_html):
    """Test HTML to Markdown conversion with markdownify"""
    from scrapling_fetch_mcp._html_converter import convert_with_markdownify

    result = convert_with_markdownify(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_markitdown(sample_html, monkeypatch):
    """Test html_to_markdown uses markitdown when configured"""
    from scrapling_fetch_mcp._html_converter import html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markitdown
    config.set_markdown_converter("markitdown")

    result = html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_markdownify(sample_html, monkeypatch):
    """Test html_to_markdown uses markdownify when configured"""
    from scrapling_fetch_mcp._html_converter import html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markdownify
    config.set_markdown_converter("markdownify")

    result = html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_with_explicit_converter(sample_html):
    """Test html_to_markdown with explicit converter parameter"""
    from scrapling_fetch_mcp._html_converter import html_to_markdown

    result = html_to_markdown(sample_html, converter="markdownify")

    assert "# Test Page" in result
    assert "Some text content" in result


def test_html_to_markdown_invalid_converter(sample_html):
    """Test html_to_markdown raises error for invalid converter"""
    from scrapling_fetch_mcp._html_converter import html_to_markdown

    with pytest.raises(ValueError, match="Unknown converter"):
        html_to_markdown(sample_html, converter="invalid")


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

    @pytest.mark.asyncio
    async def test_progress_failure_does_not_abort_fetch(self, monkeypatch):
        """A failing report_progress (e.g. disconnected SSE) must not abort the fetch."""
        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body>x</body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        ctx = AsyncMock()
        ctx.report_progress.side_effect = RuntimeError("session gone")
        result = await fetch_page_impl("http://x", "basic", "markdown", 1000, 0, ctx=ctx)
        assert "METADATA" in result  # fetch completed despite progress failure



class TestAireadCascadeFallback:
    """airead: 策略空输出时的全文 Markdown 兜底"""

    @pytest.mark.asyncio
    async def test_empty_strategy_output_falls_back_to_full_page(self, monkeypatch):
        """策略抽不出正文(输出空白)时,应回退全页 Markdown 转换而非返回空"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

        class EmptyStrategy(ExtractorStrategy):
            def extract(self, html, url):
                return ""

        async def fake_browse(*a, **k):
            page = MagicMock()
            page.html_content = "<html><body><h1>Fallback Title</h1><p>body text</p></body></html>"
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        monkeypatch.setattr(fetcher_mod.URLMatcher, "match", lambda self, url: "empty_stub")
        monkeypatch.setattr(
            fetcher_mod.StrategyFactory, "get_strategy",
            classmethod(lambda cls, name, config_path=None: EmptyStrategy()),
        )

        # 关闭仲裁:本测试只验证"空 → 全文兜底"这一段(Jina 仲裁单独测)
        from scrapling_fetch_mcp._config import config
        original_disabled = config.jina_arbiter_disabled
        config.set_jina_arbiter_disabled(True)
        try:
            result = await fetcher_mod._extract_with_airead(
                "<html><body><h1>Fallback Title</h1><p>body text</p></body></html>",
                "https://example.com/page",
            )
        finally:
            config.set_jina_arbiter_disabled(original_disabled)

        assert "Fallback Title" in result
        assert "body text" in result


class TestNegotiatedMarkdownPassthrough:
    """内容协商命中(basic 模式边缘直出 Markdown)时的管线直通"""

    def setup_method(self):
        from scrapling_fetch_mcp._config import config
        config.cache.clear_all()

    def _fake_page(self):
        from types import SimpleNamespace
        page = SimpleNamespace()
        page.html_content = "<html><body><h1>Wrapped</h1></body></html>"
        page.markdown_content = "# Edge Markdown\n\nnative body"
        return page

    @pytest.mark.asyncio
    async def test_markdown_format_uses_negotiated_content(self, monkeypatch):
        """format=markdown 时直接返回边缘 Markdown,不再本地转换"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod

        async def fake_browse(*a, **k):
            return self._fake_page()

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl("http://x", "basic", "markdown", 5000, 0)

        assert "# Edge Markdown" in result
        assert "native body" in result
        assert "Wrapped" not in result  # 未走本地转换

    @pytest.mark.asyncio
    async def test_airead_format_postprocesses_negotiated_content(self, monkeypatch):
        """format=airead 时对边缘 Markdown 做统一后处理"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod

        async def fake_browse(*a, **k):
            return self._fake_page()

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl("http://x", "basic", "airead", 5000, 0)

        assert "# Edge Markdown" in result

    @pytest.mark.asyncio
    async def test_html_format_still_uses_html(self, monkeypatch):
        """format=html 不受协商影响,仍返回 HTML"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod

        async def fake_browse(*a, **k):
            return self._fake_page()

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl("http://x", "basic", "html", 5000, 0)

        assert "<html><body><h1>Wrapped</h1></body></html>" in result

    @pytest.mark.asyncio
    async def test_page_without_markdown_content_uses_local_pipeline(self, monkeypatch):
        """页面不带 markdown_content(stealth 或未命中)时走原管线"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from types import SimpleNamespace

        page = SimpleNamespace()
        page.html_content = "<html><body><h1>Local</h1></body></html>"

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl("http://x", "basic", "markdown", 5000, 0)

        assert "Local" in result


class TestPageMetadata:
    """METADATA 携带 title/author/date/description 页面元数据"""

    def test_extract_from_og_tags(self):
        from scrapling_fetch_mcp._fetcher import _extract_page_metadata
        html = """<html><head>
            <meta property="og:title" content="OG Title">
            <meta property="og:description" content="Page summary">
            <meta name="author" content="Alice">
            <meta property="article:published_time" content="2026-01-15">
        </head><body><p>x</p></body></html>"""
        md = _extract_page_metadata(html)
        assert md == {
            "title": "OG Title",
            "description": "Page summary",
            "author": "Alice",
            "date": "2026-01-15",
        }

    def test_title_falls_back_to_title_tag(self):
        from scrapling_fetch_mcp._fetcher import _extract_page_metadata
        html = "<html><head><title>Plain Title</title></head><body></body></html>"
        md = _extract_page_metadata(html)
        assert md["title"] == "Plain Title"
        assert "author" not in md  # 拿不到的键不出现

    def test_negotiated_markdown_uses_frontmatter(self):
        from scrapling_fetch_mcp._fetcher import _extract_page_metadata
        md_text = "---\ntitle: Edge Post\ndescription: From frontmatter\n---\n\n# Edge Post\n"
        md = _extract_page_metadata("<html><body>wrapped</body></html>", md_text)
        assert md["title"] == "Edge Post"
        assert md["description"] == "From frontmatter"

    def test_broken_html_tolerated(self):
        from scrapling_fetch_mcp._fetcher import _extract_page_metadata
        assert _extract_page_metadata("") == {}

    @pytest.mark.asyncio
    async def test_fetch_page_metadata_in_output(self, monkeypatch):
        """fetch_page 返回的 METADATA JSON 应包含页面元数据"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace
        import json as _json

        config.cache.clear_all()
        page = SimpleNamespace()
        page.html_content = (
            "<html><head><title>Meta Page</title></head>"
            "<body><h1>Body</h1></body></html>"
        )

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl("http://meta-x", "basic", "markdown", 5000, 0)

        meta_line = result.split("\n\n", 1)[0]
        metadata = _json.loads(meta_line.removeprefix("METADATA: "))
        assert metadata["title"] == "Meta Page"


class TestMarkdownSlimming:
    """no_links / no_images 内容瘦身"""

    SLIM_MD = (
        "# Doc\n\nSee [guide](https://docs.example.com/long/path?q=1) and "
        "<https://auto.example.com>.\n\n"
        "![arch diagram](https://example.com/img/arch.png)\n\n"
        "[1]: https://ref.example.com\n\n"
        "```python\nlink = '[keep](https://in.code.example)'\n```"
    )

    def test_strip_links_keeps_text_and_code(self):
        from scrapling_fetch_mcp._markdown_postprocessor import strip_markdown_links
        out = strip_markdown_links(self.SLIM_MD)

        assert "[guide](https://docs.example.com" not in out
        assert "See guide and" in out  # 链接文本保留
        assert "https://auto.example.com" not in out  # autolink 移除
        assert "https://ref.example.com" not in out  # 引用定义移除
        assert "'[keep](https://in.code.example)'" in out  # 代码块原样

    def test_strip_images_keeps_code(self):
        from scrapling_fetch_mcp._markdown_postprocessor import strip_markdown_images
        out = strip_markdown_images(self.SLIM_MD)

        assert "arch diagram" not in out
        assert "arch.png" not in out
        assert "'[keep](https://in.code.example)'" in out

    def test_slimming_disabled_by_default(self):
        from scrapling_fetch_mcp._markdown_postprocessor import apply_markdown_slimming
        out = apply_markdown_slimming(self.SLIM_MD)
        assert out == self.SLIM_MD

    @pytest.mark.asyncio
    async def test_fetch_page_no_links(self, monkeypatch):
        """no_links/no_images 在截断前生效,返回内容不含 URL 标记"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        config.cache.clear_all()
        page = SimpleNamespace()
        page.html_content = (
            "<html><body><p>Read the <a href='https://x.example.com/docs'>manual</a>.</p>"
            "<img src='https://x.example.com/a.png' alt='photo'></body></html>"
        )

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl(
            "http://slim-x", "basic", "markdown", 5000, 0, no_links=True, no_images=True
        )

        assert "https://x.example.com" not in result
        assert "manual" in result

    @pytest.mark.asyncio
    async def test_fetch_page_html_format_unaffected(self, monkeypatch):
        """format=html 时瘦身参数不生效"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        config.cache.clear_all()
        page = SimpleNamespace()
        page.html_content = "<html><body><a href='https://y.example.com'>link</a></body></html>"

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetch_page_impl(
            "http://slim-y", "basic", "html", 5000, 0, no_links=True
        )

        assert "https://y.example.com" in result


class TestRefreshBypassCache:
    """refresh=True 绕过缓存强制重抓"""

    def _make_page(self, marker):
        from types import SimpleNamespace
        page = SimpleNamespace()
        page.html_content = f"<html><body><h1>{marker}</h1></body></html>"
        return page

    @pytest.mark.asyncio
    async def test_refresh_refetches_and_rewrites_cache(self, monkeypatch):
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config

        config.cache.clear_all()
        calls = []

        async def fake_browse(*a, **k):
            calls.append(1)
            return self._make_page(f"v{len(calls)}")

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)

        first = await fetch_page_impl("http://refresh-x", "basic", "markdown", 5000, 0)
        assert len(calls) == 1

        # 默认行为:命中缓存,不再发起抓取
        again = await fetch_page_impl("http://refresh-x", "basic", "markdown", 5000, 0)
        assert len(calls) == 1
        assert "v1" in again

        # refresh=True:绕过缓存重新抓取,并把新结果写回缓存
        fresh = await fetch_page_impl("http://refresh-x", "basic", "markdown", 5000, 0, refresh=True)
        assert len(calls) == 2
        assert "v2" in fresh

        # 之后的默认调用拿到的是 refresh 写回的新缓存
        after = await fetch_page_impl("http://refresh-x", "basic", "markdown", 5000, 0)
        assert len(calls) == 2
        assert "v2" in after

    @pytest.mark.asyncio
    async def test_pattern_refresh_bypasses_cache(self, monkeypatch):
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config

        config.cache.clear_all()
        calls = []

        async def fake_browse(*a, **k):
            calls.append(1)
            return self._make_page("pattern target")

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)

        await fetch_pattern_impl("http://refresh-p", "target", "basic", "markdown", 5000, 50)
        await fetch_pattern_impl("http://refresh-p", "target", "basic", "markdown", 5000, 50)
        assert len(calls) == 1  # 第二次命中缓存

        await fetch_pattern_impl("http://refresh-p", "target", "basic", "markdown", 5000, 50, refresh=True)
        assert len(calls) == 2


class TestJinaArbitration:
    """Jina 按需仲裁:本地结果可疑(空/过短)才外发,比有效字数取优"""

    def _stub_strategies(self, monkeypatch, local_result, jina_result):
        """同时 mock 掉策略路由与 Jina 仲裁者,记录 Jina 是否被调用"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

        class StubLocal(ExtractorStrategy):
            def extract(self, html, url):
                return local_result

        class StubJina(ExtractorStrategy):
            remote = True
            calls = 0

            def extract(self, html, url):
                StubJina.calls += 1
                return jina_result

        StubJina.calls = 0

        def fake_get_strategy(cls, name, config_path=None):
            return StubJina() if name == "jina" else StubLocal()

        monkeypatch.setattr(fetcher_mod.StrategyFactory, "get_strategy", classmethod(fake_get_strategy))
        monkeypatch.setattr(fetcher_mod.URLMatcher, "match", lambda self, url: "stub")
        return StubJina

    SHORT_LOCAL = "short"  # 5 个有效字符,低于默认阈值 500
    LONG_JINA = "# Jina Body\n\n" + ("rich content " * 60)

    @pytest.mark.asyncio
    async def test_short_local_triggers_jina_and_loses(self, monkeypatch):
        """本地过短触发仲裁,Jina 结果更充实则采用"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        stub = self._stub_strategies(monkeypatch, self.SHORT_LOCAL, self.LONG_JINA)
        page = SimpleNamespace(html_content="<html></html>")

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetcher_mod._extract_with_airead("<html></html>", "http://arb-x")

        assert stub.calls == 1
        assert "Jina Body" in result

    @pytest.mark.asyncio
    async def test_long_local_skips_arbitration(self, monkeypatch):
        """本地结果充实(高于阈值)时不外发,零额外延迟"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        long_local = "# Local\n\n" + ("plenty of text " * 60)
        stub = self._stub_strategies(monkeypatch, long_local, self.LONG_JINA)
        page = SimpleNamespace(html_content="<html></html>")

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetcher_mod._extract_with_airead("<html></html>", "http://arb-y")

        assert stub.calls == 0
        assert "Local" in result

    @pytest.mark.asyncio
    async def test_jina_failure_keeps_local(self, monkeypatch):
        """Jina 失败(空串)时保留本地结果,行为与无仲裁时一致"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from types import SimpleNamespace

        self._stub_strategies(monkeypatch, self.SHORT_LOCAL, "")
        page = SimpleNamespace(html_content="<html></html>")

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetcher_mod._extract_with_airead("<html></html>", "http://arb-z")

        assert "short" in result

    @pytest.mark.asyncio
    async def test_both_empty_falls_back_to_full_page(self, monkeypatch):
        """本地空 + Jina 空时,保留全文 Markdown 兜底"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from types import SimpleNamespace

        self._stub_strategies(monkeypatch, "", "")
        html = "<html><body><h1>Full Page Fallback</h1></body></html>"
        page = SimpleNamespace(html_content=html)

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        result = await fetcher_mod._extract_with_airead(html, "http://arb-w")

        assert "Full Page Fallback" in result

    @pytest.mark.asyncio
    async def test_disabled_arbiter_never_called(self, monkeypatch):
        """SCRAPLING_DISABLE_JINA_ARBITER 关闭后完全不外发"""
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        stub = self._stub_strategies(monkeypatch, self.SHORT_LOCAL, self.LONG_JINA)
        page = SimpleNamespace(html_content="<html></html>")

        async def fake_browse(*a, **k):
            return page

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        original = config.jina_arbiter_disabled
        config.set_jina_arbiter_disabled(True)
        try:
            result = await fetcher_mod._extract_with_airead("<html></html>", "http://arb-d")
        finally:
            config.set_jina_arbiter_disabled(original)

        assert stub.calls == 0
        assert "short" in result


class TestRemoteStrategySkipsBrowse:
    """站点规则显式指定远程策略(如 jina)时,跳过本地抓取直接外发"""

    @pytest.mark.asyncio
    async def test_remote_strategy_bypasses_browse_url(self, monkeypatch):
        from scrapling_fetch_mcp import _fetcher as fetcher_mod
        from scrapling_fetch_mcp._config import config
        from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

        class StubRemote(ExtractorStrategy):
            remote = True

            def extract(self, html, url):
                assert html is None  # 远程策略没有本地 HTML
                return "# Remote Content\n\ndelivered by jina"

        browse_called = []

        async def fake_browse(*a, **k):
            browse_called.append(1)
            from types import SimpleNamespace
            p = SimpleNamespace(html_content="<html></html>")
            return p

        monkeypatch.setattr(fetcher_mod, "browse_url", fake_browse)
        monkeypatch.setattr(fetcher_mod.URLMatcher, "match", lambda self, url: "jina")
        monkeypatch.setattr(
            fetcher_mod.StrategyFactory, "get_strategy",
            classmethod(lambda cls, name, config_path=None: StubRemote()),
        )
        config.cache.clear_all()

        result = await fetch_page_impl("http://remote-x", "basic", "airead", 5000, 0)

        assert browse_called == []  # 本地抓取被跳过
        assert "Remote Content" in result
