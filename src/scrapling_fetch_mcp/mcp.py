from argparse import ArgumentParser
from logging import getLogger

from mcp.server.fastmcp import FastMCP

from scrapling_fetch_mcp._config import config, init_config_from_env
from scrapling_fetch_mcp._features import (
    FEATURES,
    TOOL_PARAMS,
    S_FETCH_PAGE_DOCSTRING,
    S_FETCH_PATTERN_DOCSTRING,
)
from scrapling_fetch_mcp._tool_factory import build_tool_function
from scrapling_fetch_mcp._fetcher import fetch_page_wrapper, fetch_pattern_wrapper

mcp = FastMCP("scrapling-fetch-mcp")


def _register_tool(name, param_configs, base_docstring, impl_func):
    """Build a dynamic tool function and register it with FastMCP."""
    func = build_tool_function(
        tool_name=name,
        param_configs=param_configs,
        enabled_features=config.enabled_features,
        base_docstring=base_docstring,
        impl_func=impl_func,
    )
    mcp.tool()(func)


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
        "Can also be set via SCRAPLING_DIR environment variable.",
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
    parser.add_argument(
        "--disable-url-rewrite",
        action="store_true",
        help="Disable automatic URL rewriting. Default: enabled.",
    )
    parser.add_argument(
        "--url-rewrite-config",
        type=str,
        default=None,
        help="Path to YAML file with custom URL rewrite rules.",
    )
    parser.add_argument(
        "--disable-features",
        type=str,
        default="",
        help="Comma-separated list of features to disable. "
        "Available features: stealth, format, pagination, save. "
        "Can also be set via SCRAPLING_DISABLE_FEATURES environment variable.",
    )
    parser.add_argument(
        "--enable-features",
        type=str,
        default="",
        help="Comma-separated list of features to enable. "
        "Available features: stealth, format, pagination, save. "
        "Can also be set via SCRAPLING_ENABLE_FEATURES environment variable.",
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

    if args.disable_url_rewrite:
        config.set_disable_url_rewrite(True)

    if args.url_rewrite_config:
        config.set_url_rewrite_config_path(args.url_rewrite_config)

    # Resolve features (merge env raw values + CLI args, call once)
    disable_cli_list = [f.strip() for f in args.disable_features.split(",") if f.strip()]
    enable_cli_list = [f.strip() for f in args.enable_features.split(",") if f.strip()]
    disable_list = config._disable_features_raw + disable_cli_list
    enable_list = config._enable_features_raw + enable_cli_list
    config.resolve_features(disable_list, enable_list)

    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    logger.info(f"Minimum mode set to: {config.min_mode}")
    logger.info(f"Cache TTL set to: {config.cache_ttl} seconds")
    logger.info(f"Scraping directory set to: {config.scraping_dir}")
    logger.info(f"Markdown converter set to: {config.markdown_converter}")
    logger.info(f"Default format set to: {config.default_format}")
    logger.info(f"URL rewrite: {'disabled' if config.disable_url_rewrite else 'enabled'}")

    # Log feature status
    all_features = set(FEATURES.keys())
    logger.info(f"Features enabled: {sorted(config.enabled_features)}")
    logger.info(f"Features disabled: {sorted(all_features - config.enabled_features)}")

    # Build and register tools dynamically
    _register_tool(
        "s_fetch_page",
        TOOL_PARAMS["s_fetch_page"],
        S_FETCH_PAGE_DOCSTRING,
        fetch_page_wrapper,
    )
    _register_tool(
        "s_fetch_pattern",
        TOOL_PARAMS["s_fetch_pattern"],
        S_FETCH_PATTERN_DOCSTRING,
        fetch_pattern_wrapper,
    )

    mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
