from argparse import ArgumentParser
from logging import getLogger
from traceback import format_exc
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from scrapling_fetch_mcp._config import config, init_config_from_env
from scrapling_fetch_mcp._fetcher import (
    fetch_page_impl,
    fetch_pattern_impl,
)

mcp = FastMCP("scrapling-fetch-mcp")


@mcp.tool()
async def s_fetch_page(
    url: str,
    mode: str = "basic",
    format: str = None,
    max_length: int = 8000,
    start_index: int = 0,
    save_content: bool = False,
    scraping_dir: str = ".temp/scrapling/",
) -> str:
    """Fetches a complete web page with pagination support. Retrieves content from websites with bot-detection avoidance. Content is returned as 'METADATA: {json}\\n\\n[content]' where metadata includes length information and truncation status.

    IMPORTANT:
    - Use format='airead' for AI-optimized content extraction (removes navigation, ads, etc., 30-50% token reduction)
    - Use format='markdown' for standard markdown conversion
    - Use format='html' only when you need raw HTML structure

    The airead format uses intelligent content extraction with URL-based routing to specialized strategies for different website types (search engines, documentation, developer platforms, etc.).

    The server can be configured with a minimum mode via --min-mode CLI argument or SCRAPLING_MIN_MODE environment variable to prevent multiple retry attempts from escalating modes.

    Pages are cached for the configured TTL (--cache-ttl, default 300 seconds) to avoid repeated requests when fetching large pages in segments using start_index parameter.

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.
        format: Output format (airead, markdown, or html). Use airead for AI-optimized extraction, markdown for standard conversion, html only for structure analysis. Defaults to server's default format setting.
        max_length: Maximum number of characters to return.
        start_index: On return output starting at this character index, useful if a previous fetch was truncated and more content is required.
        save_content: If True, save complete page content (HTML/Markdown + images) to local filesystem for offline viewing.
        scraping_dir: Directory path for saved content (relative or absolute). Default: .temp/scrapling/
    """
    try:
        # Use configured default format if not specified
        effective_format = format if format is not None else config.default_format
        scraping_path = Path(scraping_dir)

        result = await fetch_page_impl(
            url,
            mode,
            effective_format,
            max_length,
            start_index,
            save_content=save_content,
            scraping_dir=scraping_path,
        )
        return result
    except Exception as e:
        logger = getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_page: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise


@mcp.tool()
async def s_fetch_pattern(
    url: str,
    search_pattern: str,
    mode: str = "basic",
    format: str = None,
    max_length: int = 8000,
    context_chars: int = 200,
) -> str:
    """Extracts content matching regex patterns from web pages. Retrieves specific content from websites with bot-detection avoidance. Returns matched content as 'METADATA: {json}\\n\\n[content]' where metadata includes match statistics and truncation information. Each matched content chunk is delimited with '॥๛॥' and prefixed with '[Position: start-end]' indicating its byte position in the original document, allowing targeted follow-up requests with s-fetch-page using specific start_index values.

    IMPORTANT: Use format='markdown' (default) for reading or extracting content. Only use format='html' when you specifically need the raw HTML structure.

    The server can be configured with a minimum mode via --min-mode CLI argument or SCRAPLING_MIN_MODE environment variable to prevent multiple retry attempts from escalating modes.

    Pages are cached for the configured TTL (--cache-ttl, default 300 seconds) to avoid repeated requests when searching the same page with different patterns.

    Args:
        url: URL to fetch
        search_pattern: Regular expression pattern to search for in the content
        mode: Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.
        format: Output format (html or markdown). Use markdown for content reading/extraction, html only for structure analysis. Defaults to server's default format setting (airead will be converted to markdown).
        max_length: Maximum number of characters to return.
        context_chars: Number of characters to include before and after each match
    """
    try:
        # Use configured default format if not specified
        effective_format = format if format is not None else config.default_format
        # s_fetch_pattern does not support airead, fallback to markdown
        if effective_format == "airead":
            effective_format = "markdown"

        result = await fetch_pattern_impl(
            url, search_pattern, mode, effective_format, max_length, context_chars
        )
        return result
    except Exception as e:
        logger = getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_pattern: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise


def run_server():
    """Parse CLI arguments and start the MCP server"""
    parser = ArgumentParser(
        description="Scrapling Fetch MCP Server - Fetch web content with bot-detection avoidance"
    )
    parser.add_argument(
        "--min-mode",
        choices=["basic", "stealth", "max-stealth"],
        help="Minimum fetching mode level. All requests will use at least this mode, "
        "preventing multiple retries from basic to higher modes. "
        "Can also be set via SCRAPLING_MIN_MODE environment variable.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=300,
        help="Cache time-to-live in seconds for fetched pages. "
        "When fetching large pages in segments, this prevents repeated requests to the same URL. "
        "Set to 0 to disable caching. Default: 300 (5 minutes). "
        "Can also be set via SCRAPLING_CACHE_TTL environment variable.",
    )
    parser.add_argument(
        "--scraping-dir",
        type=str,
        default=".temp/scrapling/",
        help="Default directory for saving scraped content (HTML + images). "
        "Can be overridden per-request with scraping_dir parameter. "
        "Default: .temp/scrapling/ "
        "Can also be set via SCRAPING_DIR environment variable.",
    )
    parser.add_argument(
        "--markdown-converter",
        choices=["markitdown", "markdownify"],
        default="markitdown",
        help="Markdown converter library to use. Default: markitdown. "
        "Can also be set via SCRAPLING_MARKDOWN_CONVERTER environment variable.",
    )
    parser.add_argument(
        "--rules-config",
        type=str,
        default=None,
        help="Path to YAML file with airead format URL routing rules. "
        "Default: Use built-in rules. "
        "Can also be set via SCRAPLING_RULES_CONFIG environment variable.",
    )
    parser.add_argument(
        "--default-format",
        choices=["airead", "markdown", "html"],
        default="markdown",
        help="Default output format for fetch operations. "
        "s_fetch_page supports: airead, markdown, html. "
        "s_fetch_pattern will use markdown if default is airead. "
        "Default: markdown. "
        "Can also be set via SCRAPLING_DEFAULT_FORMAT environment variable.",
    )
    args = parser.parse_args()


    # Initialize from environment first
    init_config_from_env()

    # CLI args override environment variables
    if args.min_mode:
        config.set_min_mode(args.min_mode)

    if args.cache_ttl is not None:
        config.set_cache_ttl(args.cache_ttl)

    if args.scraping_dir:
        config.set_scraping_dir(args.scraping_dir)

    if args.markdown_converter:
        config.set_markdown_converter(args.markdown_converter)

    if args.rules_config:
        config.set_rules_config_path(args.rules_config)

    if args.default_format:
        config.set_default_format(args.default_format)

    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    logger.info(f"Minimum mode set to: {config.min_mode}")
    logger.info(f"Cache TTL set to: {config.cache_ttl} seconds")
    logger.info(f"Scraping directory set to: {config.scraping_dir}")
    logger.info(f"Markdown converter set to: {config.markdown_converter}")
    logger.info(f"Default format set to: {config.default_format}")

    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
