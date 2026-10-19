from contextlib import redirect_stdout
from os import devnull
from typing import Any, Callable, Optional

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._concurrency import ConcurrencyGuard

_guard: Optional[ConcurrencyGuard] = None

# 内容协商优先 text/markdown(Cloudflare "Markdown for Agents" 等,
# 站长在边缘侧返回现成 Markdown);不支持的站点按标准 HTTP 语义
# 自然回退 text/html,探测零额外请求。
_MARKDOWN_ACCEPT = "text/markdown, text/html;q=0.9, */*;q=0.8"


def _attach_negotiated_markdown(response: Any) -> None:
    """basic 响应返回 text/markdown 时,把保真正文挂到响应对象上。

    scrapling 的 Response 无 slots,允许动态附加属性;fetch 管线用
    getattr(page, "markdown_content", None) 读取。body 是原始响应体,
    html_content 会把 Markdown 文本包进 <html><body> 而失真,不能用。
    """
    try:
        headers = getattr(response, "headers", None) or {}
        content_type = ""
        for key, value in headers.items():
            if str(key).lower() == "content-type":
                content_type = str(value).lower()
                break
        if "text/markdown" not in content_type:
            return
        body = getattr(response, "body", None)
        if body:
            response.markdown_content = body if isinstance(body, str) else body.decode("utf-8", "replace")
    except Exception:
        # 探测失败不影响原抓取结果,按普通 HTML 走后续管线
        pass


def init_guard(max_concurrent: int, acquire_timeout: float) -> None:
    """Initialize the global concurrency guard. Call once at server startup."""
    global _guard
    _guard = ConcurrencyGuard(max_concurrent, acquire_timeout)


async def _do_browse(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None,
) -> Any:
    """Actual scrapling fetch (extracted from browse_url)."""
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        if mode == "basic":
            response = await AsyncFetcher.get(
                url,
                stealthy_headers=True,
                headers={"Accept": _MARKDOWN_ACCEPT},
            )
            _attach_negotiated_markdown(response)
            return response
        elif mode == "stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                # camoufox 默认 30s 导航超时,对故意拖延 load 事件的站点
                # (如 Brave Search)不够;沿用全局 fetch_timeout(秒)
                timeout=int(config.fetch_timeout * 1000),
                page_action=page_action,
            )
        elif mode == "max-stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                block_webrtc=True,
                network_idle=True,
                disable_resources=False,
                block_images=False,
                timeout=int(config.fetch_timeout * 1000),
                page_action=page_action,
            )
        else:
            raise ValueError(f"Unknown mode: {mode}")


async def browse_url(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None
) -> Any:
    """
    Browse URL using scrapling fetcher, gated by the global concurrency guard
    when initialized (see :func:`init_guard`).

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, max-stealth)
        page_action: Optional async callable that receives the Playwright ``page``
                     object (scrapling's native ``page_action`` contract) for
                     automation such as image capture. Only stealth/max-stealth
                     modes pass it through; basic mode ignores it.
    """
    if _guard is None:
        return await _do_browse(url, mode, page_action)
    async with _guard:
        return await _do_browse(url, mode, page_action)
