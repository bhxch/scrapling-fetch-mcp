import asyncio

import logging
from functools import reduce
from json import dumps
from pathlib import Path
from re import compile
from re import error as re_error
from traceback import format_exc
from types import SimpleNamespace
from typing import Optional

from bs4 import BeautifulSoup
from mcp.server.mcpserver.context import Context
from yaml import safe_load as _yaml_safe_load

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._browser_check import resolve_stealth_degradation
from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
from scrapling_fetch_mcp._extractor_strategy import (
    count_effective_characters,
    ExtractorStrategy,
)
from scrapling_fetch_mcp._html_converter import html_to_markdown
from scrapling_fetch_mcp._scrapling import browse_url
from scrapling_fetch_mcp._content_saver import ContentSaver
from scrapling_fetch_mcp._url_matcher import URLMatcher
from scrapling_fetch_mcp._strategy_factory import StrategyFactory
from scrapling_fetch_mcp._markdown_postprocessor import (
    apply_markdown_slimming,
    postprocess_markdown,
)

logger = logging.getLogger("scrapling_fetch_mcp")


# HTML head 里的元数据来源:og/twitter 协议标签与常规 meta,按优先级排列
_META_SOURCES = {
    "title": [
        ("meta", {"property": "og:title"}),
        ("meta", {"name": "twitter:title"}),
        ("title", {}),
    ],
    "description": [
        ("meta", {"property": "og:description"}),
        ("meta", {"name": "description"}),
        ("meta", {"name": "twitter:description"}),
    ],
    "author": [
        ("meta", {"name": "author"}),
        ("meta", {"property": "article:author"}),
    ],
    "date": [
        ("meta", {"property": "article:published_time"}),
        ("meta", {"name": "date"}),
        ("meta", {"itemprop": "datePublished"}),
    ],
}


def _parse_frontmatter(text: str) -> dict:
    """解析 Markdown 开头的 YAML frontmatter(边缘直出内容自带)。"""
    if not text.startswith("---"):
        return {}
    try:
        block = text.split("\n---", 1)[0][3:]
        data = _yaml_safe_load(block)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _extract_page_metadata(
    html: str, negotiated_markdown: Optional[str] = None
) -> dict:
    """从页面提取 title/author/date/description,拿不到的键不出现。

    内容协商命中时页面是边缘 Markdown,优先读它的 frontmatter;
    HTML 场景读 og/twitter 协议标签与常规 meta,取第一个非空来源。
    """
    metadata: dict[str, str] = {}

    if negotiated_markdown:
        front = _parse_frontmatter(negotiated_markdown)
        for key in ("title", "description", "author", "date"):
            value = front.get(key)
            if isinstance(value, str) and value.strip():
                metadata[key] = value.strip()
        if len(metadata) == 4:
            return metadata

    try:
        soup = BeautifulSoup(html, "lxml")
        for key, selectors in _META_SOURCES.items():
            if key in metadata:
                continue
            for tag_name, attrs in selectors:
                elem = soup.find(tag_name, attrs) if attrs else soup.find(tag_name)
                value = elem.get("content") if attrs and elem else (
                    elem.get_text(strip=True) if elem else None
                )
                if value and value.strip():
                    metadata[key] = value.strip()
                    break
    except Exception:
        # 元数据是增益信息,解析失败不影响正文返回
        logger.debug("page metadata extraction failed", exc_info=True)

    return metadata


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


def _should_arbitrate(markdown: str) -> bool:
    """本地抽取结果可疑(空或有效字数低于阈值)时才值得外发 Jina 仲裁。"""
    if config.jina_arbiter_disabled:
        return False
    if not markdown or not markdown.strip():
        return True
    return count_effective_characters(markdown) < config.jina_min_chars


async def _arbitrate_with_jina(url: str) -> str:
    """把 URL 交给 Jina Reader 仲裁;任何失败返回空串退回本地结果。"""
    try:
        strategy = StrategyFactory.get_strategy("jina")
        return await asyncio.to_thread(strategy.extract, None, url)
    except Exception:
        logger.warning("jina 仲裁调用异常,使用本地结果 (%s)", url, exc_info=True)
        return ""


async def _extract_with_airead(
    html: str, url: str, strategy: Optional[ExtractorStrategy] = None,
    strategy_name: Optional[str] = None,
) -> str:
    """
    Extract content using airead format

    Args:
        html: Raw HTML content
        url: Page URL (for strategy routing)
        strategy: Pre-matched strategy (fetch_page_impl matches early to
                  support remote strategies; when None, match here)
        strategy_name: Name of the pre-matched strategy

    Returns:
        Extracted and postprocessed Markdown content
    """
    # 1-3. Strategy routing (skipped when the caller already matched)
    if strategy is None:
        rules_config_path = config.rules_config_path
        strategy_name = URLMatcher(rules_config_path).match(url)
        strategy = StrategyFactory.get_strategy(strategy_name, rules_config_path)

    # 远程策略(如站点规则显式指定 jina):无本地 HTML,URL 即输入
    if getattr(strategy, "remote", False):
        markdown = await asyncio.to_thread(strategy.extract, None, url)
        return postprocess_markdown(markdown)

    # 4. Execute extraction
    markdown = strategy.extract(html, url)

    # Jina 按需仲裁:本地结果可疑(空/过短)才把 URL 外发给 Jina 对比,
    # 比有效字数取优;正常页面零外发、零额外延迟
    if _should_arbitrate(markdown):
        jina_markdown = await _arbitrate_with_jina(url)
        if count_effective_characters(jina_markdown) > count_effective_characters(markdown):
            logger.info("airead: Jina 仲裁结果胜出 (%s)", url)
            markdown = jina_markdown

    # 级联兜底:策略抽不出正文(trafilatura 返回 None 等)时,
    # 退回全页 Markdown 转换,保证有内容返回而非空结果
    if not markdown or not markdown.strip():
        logger.info(
            "airead: 策略 '%s' 输出为空,回退全页 Markdown 转换 (%s)", strategy_name, url
        )
        markdown = html_to_markdown(html)

    # Unified postprocessing
    markdown = postprocess_markdown(markdown)

    return markdown


def _create_metadata(
    total_length: int,
    retrieved_length: int,
    is_truncated: bool,
    start_index: Optional[int] = None,
    match_count: Optional[int] = None,
    page_metadata: Optional[dict] = None,
    degradation: Optional[str] = None,
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
    if page_metadata:
        metadata.update(page_metadata)
    if degradation:
        metadata["degradation"] = degradation
    return dumps(metadata)


async def _maybe_report_progress(
    ctx: Optional[Context],
    progress: float,
    total: float = 100,
    message: Optional[str] = None,
) -> None:
    """Report progress via the MCP Context when one is available.

    The SDK auto-injects a Context into tool calls; we forward it down to
    the impl so progress notifications can be emitted at key stages, acting
    as liveness heartbeats during long fetches (especially valuable for
    streamable-http SSE transport to avoid idle disconnects).

    Guarded so callers without a Context (direct library use, unit tests)
    are unaffected.
    """
    if ctx is not None:
        try:
            await ctx.report_progress(progress, total, message)
        except Exception:
            # Progress is best-effort: a failing SSE session (e.g. client
            # disconnect) must not abort the in-flight fetch.
            logger.debug("progress report failed", exc_info=True)


async def fetch_page_impl(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: Optional[Path] = None,
    no_links: bool = False,
    no_images: bool = False,
    refresh: bool = False,
    ctx: Optional[Context] = None,
) -> str:
    # URL 重写（在最开始执行，确保缓存基于重写后的 URL）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")

    effective_mode = config.get_effective_mode(mode)
    # stealth 浏览器未就绪(后台下载中/下载失败)时降级 basic;必须在缓存
    # 查询前定型,让降级结果落在 basic 的缓存键下,并在 METADATA 里说明
    effective_mode, degradation = resolve_stealth_degradation(effective_mode)

    # airead 需要提前做策略路由:远程策略(URL 即输入)可跳过本地抓取
    airead_strategy = None
    airead_strategy_name = None
    if format == "airead":
        rules_config_path = config.rules_config_path
        airead_strategy_name = URLMatcher(rules_config_path).match(url)
        airead_strategy = StrategyFactory.get_strategy(
            airead_strategy_name, rules_config_path
        )
    remote_airead = getattr(airead_strategy, "remote", False)

    # Setup content saver if needed
    content_saver = None
    page_action = None
    if save_content and scraping_dir:
        if remote_airead:
            logger.warning("远程策略无本地页面可保存,忽略 save_content (%s)", url)
        else:
            content_saver = ContentSaver(scraping_dir, url, format)
            page_action = content_saver.create_page_action()

    # Check cache first; refresh=True 跳过缓存强制重抓(调试站点规则/内容刚更新)
    cached_page = None if refresh else config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    elif remote_airead:
        # 远程策略:URL 直接交给策略(不经本地浏览器),结果包成页面对象
        # 进缓存,复用下方协商直通管线(不仲裁、无本地全文兜底)
        await _maybe_report_progress(ctx, 0, 100, "远程抽取中")
        remote_markdown = await asyncio.to_thread(airead_strategy.extract, None, url)
        page = SimpleNamespace(html_content="", markdown_content=remote_markdown)
        config.cache.set(url, effective_mode, page)
    else:
        # About to perform the slow network/browse step — emit a heartbeat
        # so transports (e.g. streamable-http SSE) know we are alive.
        await _maybe_report_progress(ctx, 0, 100, "抓取中")
        # Fetch and cache the page
        try:
            page = await asyncio.wait_for(
                browse_url(url, effective_mode, page_action=page_action),
                timeout=config.fetch_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"抓取超时（{config.fetch_timeout}s）") from None
        config.cache.set(url, effective_mode, page)

    # Browse complete — moving to content conversion.
    await _maybe_report_progress(ctx, 80, 100, "转换中")

    is_markdown = format == "markdown"

    # Get HTML content
    html_content = page.html_content

    # Save content if requested
    if content_saver:
        html_content = await content_saver.save_content(html_content)

    # 内容协商命中:目标站点(basic 模式)在边缘直接返回了现成 Markdown
    # (如 Cloudflare "Markdown for Agents"),markdown/airead 直通,跳过本地抽取
    negotiated_markdown = getattr(page, "markdown_content", None)
    if not isinstance(negotiated_markdown, str) or not negotiated_markdown:
        negotiated_markdown = None

    # Extract content based on format
    if format == "airead":
        if negotiated_markdown:
            full_content = postprocess_markdown(negotiated_markdown)
        else:
            full_content = await _extract_with_airead(
                html_content, url,
                strategy=airead_strategy, strategy_name=airead_strategy_name,
            )
    elif is_markdown:
        full_content = (
            negotiated_markdown if negotiated_markdown else html_to_markdown(html_content)
        )
    else:  # html
        full_content = html_content

    # 内容瘦身:链接/图片标记对文本模型纯烧 token;html 结构分析不受影响
    if format != "html":
        full_content = apply_markdown_slimming(full_content, no_links, no_images)

    total_length = len(full_content)
    truncated_content = full_content[start_index : start_index + max_length]
    is_truncated = total_length > (start_index + max_length)

    metadata_json = _create_metadata(
        total_length, len(truncated_content), is_truncated, start_index,
        page_metadata=_extract_page_metadata(html_content, negotiated_markdown),
        degradation=degradation,
    )
    await _maybe_report_progress(ctx, 100, 100, "完成")
    return f"METADATA: {metadata_json}\n\n{truncated_content}"


async def fetch_pattern_impl(
    url: str,
    search_pattern: str,
    mode: str,
    format: str,
    max_length: int,
    context_chars: int,
    no_links: bool = False,
    no_images: bool = False,
    refresh: bool = False,
    ctx: Optional[Context] = None,
) -> str:
    # URL 重写（在最开始执行，确保缓存基于重写后的 URL）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")

    effective_mode = config.get_effective_mode(mode)
    # 与 fetch_page_impl 相同的降级规则,见 resolve_stealth_degradation
    effective_mode, degradation = resolve_stealth_degradation(effective_mode)

    # Check cache first; refresh=True 跳过缓存强制重抓
    cached_page = None if refresh else config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    else:
        # About to perform the slow network/browse step — emit a heartbeat.
        await _maybe_report_progress(ctx, 0, 100, "抓取中")
        # Fetch and cache the page
        try:
            page = await asyncio.wait_for(
                browse_url(url, effective_mode),
                timeout=config.fetch_timeout,
            )
        except asyncio.TimeoutError:
            raise TimeoutError(f"抓取超时（{config.fetch_timeout}s）") from None
        config.cache.set(url, effective_mode, page)

    # Browse complete — moving to search/conversion.
    await _maybe_report_progress(ctx, 80, 100, "转换中")

    is_markdown = format == "markdown"
    # 内容协商命中时(basic 模式边缘直出 Markdown)直接使用,跳过本地转换
    negotiated_markdown = getattr(page, "markdown_content", None)
    if not isinstance(negotiated_markdown, str) or not negotiated_markdown:
        negotiated_markdown = None
    if is_markdown and negotiated_markdown:
        full_content = negotiated_markdown
    elif is_markdown:
        full_content = html_to_markdown(page.html_content)
    else:
        full_content = page.html_content

    if format != "html":
        full_content = apply_markdown_slimming(full_content, no_links, no_images)

    original_length = len(full_content)
    matched_content, match_count = _search_content(
        full_content, search_pattern, context_chars
    )

    if not matched_content:
        metadata_json = _create_metadata(
            original_length, 0, False, None, 0, degradation=degradation
        )
        await _maybe_report_progress(ctx, 100, 100, "完成")
        return f"METADATA: {metadata_json}\n\n"

    truncated_content = matched_content[:max_length]
    is_truncated = len(matched_content) > max_length

    metadata_json = _create_metadata(
        original_length, len(truncated_content), is_truncated, None, match_count,
        page_metadata=_extract_page_metadata(page.html_content, negotiated_markdown),
        degradation=degradation,
    )
    await _maybe_report_progress(ctx, 100, 100, "完成")
    return f"METADATA: {metadata_json}\n\n{truncated_content}"


async def fetch_page_wrapper(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: str = ".temp/scrapling/",
    no_links: bool = False,
    no_images: bool = False,
    refresh: bool = False,
    ctx: Optional[Context] = None,
) -> str:
    """Wrapper: format resolution, Path conversion, error handling."""
    try:
        effective_format = format if format is not None else config.default_format
        scraping_path = Path(scraping_dir)
        result = await fetch_page_impl(
            url, mode, effective_format, max_length, start_index,
            save_content=save_content, scraping_dir=scraping_path,
            no_links=no_links, no_images=no_images, refresh=refresh, ctx=ctx,
        )
        return result
    except ConcurrencyLimitError as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.info("s_fetch_page 并发限流: %s", str(e))
        raise
    except Exception as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_page: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise


async def fetch_pattern_wrapper(
    url: str,
    search_pattern: str,
    mode: str,
    format: str,
    max_length: int,
    context_chars: int = 200,
    no_links: bool = False,
    no_images: bool = False,
    refresh: bool = False,
    ctx: Optional[Context] = None,
) -> str:
    """Wrapper: format resolution, airead fallback, error handling."""
    try:
        effective_format = format if format is not None else config.default_format
        if effective_format == "airead":
            effective_format = "markdown"
        result = await fetch_pattern_impl(
            url, search_pattern, mode, effective_format, max_length, context_chars,
            no_links=no_links, no_images=no_images, refresh=refresh, ctx=ctx,
        )
        return result
    except ConcurrencyLimitError as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.info("s_fetch_pattern 并发限流: %s", str(e))
        raise
    except Exception as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_pattern: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise
