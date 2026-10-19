"""HTML → Markdown 转换。

从 _fetcher 抽出为独立模块：除 fetch 管线外，抽取策略
（如 ReadabilityStrategy 把正文 HTML 转 Markdown）也需要同一套
转换逻辑，放回 _fetcher 会造成循环导入。
"""

import logging
import os
import tempfile
from typing import Optional

from bs4 import BeautifulSoup
from markitdown import MarkItDown

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._markdownify import _CustomMarkdownify

logger = logging.getLogger("scrapling_fetch_mcp")


def convert_with_markitdown(html: str) -> str:
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


def convert_with_markdownify(html: str) -> str:
    """Convert HTML to Markdown using markdownify library"""
    soup = BeautifulSoup(html, "lxml")
    for script in soup(["script", "style"]):
        script.extract()
    body_elm = soup.find("body")
    return _CustomMarkdownify().convert_soup(body_elm if body_elm else soup)


def html_to_markdown(html: str, converter: Optional[str] = None) -> str:
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
        return convert_with_markitdown(html)
    elif converter == "markdownify":
        return convert_with_markdownify(html)
    else:
        raise ValueError(f"Unknown converter: {converter}")
