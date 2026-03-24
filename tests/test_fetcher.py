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
