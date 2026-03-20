import logging
import os
import tempfile
from functools import reduce
from json import dumps
from re import compile
from re import error as re_error
from typing import Optional
from pathlib import Path

from bs4 import BeautifulSoup
from markitdown import MarkItDown

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._markdownify import _CustomMarkdownify
from scrapling_fetch_mcp._scrapling import browse_url
from scrapling_fetch_mcp._content_saver import ContentSaver
from scrapling_fetch_mcp._url_matcher import URLMatcher
from scrapling_fetch_mcp._strategy_factory import StrategyFactory
from scrapling_fetch_mcp._markdown_postprocessor import postprocess_markdown

logger = logging.getLogger("scrapling_fetch_mcp")


def _convert_with_markitdown(html: str) -> str:
    """Convert HTML to Markdown using markitdown library

    Note: MarkItDown requires a file path (not HTML string), so we create
    a temporary file for conversion and clean it up afterward to avoid resource leaks.
    """
    # Create temporary file with HTML content
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write(html)
        temp_file = f.name

    try:
        converter = MarkItDown()
        result = converter.convert(temp_file)
        return result.text_content
    finally:
        # Clean up temporary file
        os.unlink(temp_file)


def _convert_with_markdownify(html: str) -> str:
    """Convert HTML to Markdown using markdownify library"""
    soup = BeautifulSoup(html, "lxml")
    for script in soup(["script", "style"]):
        script.extract()
    body_elm = soup.find("body")
    return _CustomMarkdownify().convert_soup(body_elm if body_elm else soup)


def _html_to_markdown(html: str, converter: Optional[str] = None) -> str:
    """
    Convert HTML to Markdown using configured converter.

    Args:
        html: HTML content to convert
        converter: Converter to use ('markitdown' or 'markdownify').
                   If None, uses configured default.

    Returns:
        Markdown formatted string
    """
    if converter is None:
        converter = config.markdown_converter

    if converter == "markitdown":
        return _convert_with_markitdown(html)
    elif converter == "markdownify":
        return _convert_with_markdownify(html)
    else:
        raise ValueError(f"Unknown converter: {converter}")


def _search_content(
    content: str, pattern: str, context_chars: int = 200
) -> tuple[str, int]:
    try:
        matches = list(compile(pattern).finditer(content))
        if not matches:
            return "", 0
        chunks = [
            (
                max(0, match.start() - context_chars),
                min(len(content), match.end() + context_chars),
            )
            for match in matches
        ]
        merged_chunks = reduce(
            lambda acc, chunk: (
                [*acc[:-1], (acc[-1][0], max(acc[-1][1], chunk[1]))]
                if acc and chunk[0] <= acc[-1][1]
                else [*acc, chunk]
            ),
            chunks,
            [],
        )
        result_sections = [
            f"॥๛॥\n[Position: {start}-{end}]\n{content[start:end]}"
            for start, end in merged_chunks
        ]
        return "\n".join(result_sections), len(matches)
    except re_error as e:
        return f"ERROR: Invalid regex pattern: {str(e)}", 0


def _extract_with_airead(html: str, url: str) -> str:
    """
    Extract content using airead format

    Args:
        html: Raw HTML content
        url: Page URL (for strategy routing)

    Returns:
        Extracted and postprocessed Markdown content
    """
    # 1. Get configuration file path
    rules_config_path = config.rules_config_path

    # 2. URL matching
    matcher = URLMatcher(rules_config_path)
    strategy_name = matcher.match(url)

    # 3. Get strategy instance
    strategy = StrategyFactory.get_strategy(strategy_name, rules_config_path)

    # 4. Execute extraction
    markdown = strategy.extract(html, url)

    # 5. Unified postprocessing
    markdown = postprocess_markdown(markdown)

    return markdown


def _create_metadata(
    total_length: int,
    retrieved_length: int,
    is_truncated: bool,
    start_index: Optional[int] = None,
    match_count: Optional[int] = None,
) -> str:
    metadata = {
        "total_length": total_length,
        "retrieved_length": retrieved_length,
        "is_truncated": is_truncated,
        "percent_retrieved": round((retrieved_length / total_length) * 100, 2)
        if total_length > 0
        else 100,
    }
    if start_index is not None:
        metadata["start_index"] = start_index
    if match_count is not None:
        metadata["match_count"] = match_count
    return dumps(metadata)


async def fetch_page_impl(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: Optional[Path] = None,
) -> str:
    # URL 重写（在最开始执行，确保缓存基于重写后的 URL）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")

    effective_mode = config.get_effective_mode(mode)

    # Setup content saver if needed
    content_saver = None
    page_action = None
    if save_content and scraping_dir:
        content_saver = ContentSaver(scraping_dir, url, format)
        page_action = content_saver.create_page_action()

    # Check cache first
    cached_page = config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    else:
        # Fetch and cache the page
        page = await browse_url(url, effective_mode, page_action=page_action)
        config.cache.set(url, effective_mode, page)

    is_markdown = format == "markdown"

    # Get HTML content
    html_content = page.html_content

    # Save content if requested
    if content_saver:
        html_content = await content_saver.save_content(html_content)

    # Extract content based on format
    if format == "airead":
        full_content = _extract_with_airead(html_content, url)
    elif is_markdown:
        full_content = _html_to_markdown(html_content)
    else:  # html
        full_content = html_content

    total_length = len(full_content)
    truncated_content = full_content[start_index : start_index + max_length]
    is_truncated = total_length > (start_index + max_length)

    metadata_json = _create_metadata(
        total_length, len(truncated_content), is_truncated, start_index
    )
    return f"METADATA: {metadata_json}\n\n{truncated_content}"


async def fetch_pattern_impl(
    url: str,
    search_pattern: str,
    mode: str,
    format: str,
    max_length: int,
    context_chars: int,
) -> str:
    # URL 重写（在最开始执行，确保缓存基于重写后的 URL）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")

    effective_mode = config.get_effective_mode(mode)

    # Check cache first
    cached_page = config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    else:
        # Fetch and cache the page
        page = await browse_url(url, effective_mode)
        config.cache.set(url, effective_mode, page)

    is_markdown = format == "markdown"
    full_content = (
        _html_to_markdown(page.html_content) if is_markdown else page.html_content
    )

    original_length = len(full_content)
    matched_content, match_count = _search_content(
        full_content, search_pattern, context_chars
    )

    if not matched_content:
        metadata_json = _create_metadata(original_length, 0, False, None, 0)
        return f"METADATA: {metadata_json}\n\n"

    truncated_content = matched_content[:max_length]
    is_truncated = len(matched_content) > max_length

    metadata_json = _create_metadata(
        original_length, len(truncated_content), is_truncated, None, match_count
    )
    return f"METADATA: {metadata_json}\n\n{truncated_content}"
