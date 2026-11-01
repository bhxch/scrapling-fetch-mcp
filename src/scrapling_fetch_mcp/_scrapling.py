import asyncio
import os
import re
import signal
from contextlib import redirect_stdout
from os import devnull
from pathlib import Path
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


_pool: Any = None


def get_pool() -> Any:
    """惰性单例浏览器池：首次使用时按 config 定参构造（不启动任何浏览器）。

    daemon/pool 的模块级 import 是轻依赖（scrapling 在其工厂内惰性导入），
    惰性构造只为让 browser_pool 关闭时零开销。参数在首次构造时定型。
    """
    global _pool
    if _pool is None:
        from scrapling_fetch_mcp.daemon.pool import BrowserPool

        _pool = BrowserPool(
            idle_ttl=config.pool_idle_ttl,
            max_age=config.pool_max_age,
            max_sessions=config.pool_max_sessions,
            max_requests=config.pool_max_requests,
        )
    return _pool


def pool_if_built() -> Any:
    """已构造的浏览器池单例；从未使用过则 None（绝不惰性构造）。

    daemon 侧 status/cleanup 的只读探测入口：避免 status 在 browser_pool
    开启但从未抓取时凭空构造空池（空池 stats 会把"未启用"伪装成"已启用
    无会话"，且定型了当时的 config 参数）。外部不应再直接摸 ``_pool``。
    """
    return _pool


# ---------------------------------------------------------------------------
# 取消时的浏览器进程兜底清理
# ---------------------------------------------------------------------------
# scrapling 经 ``async with AsyncStealthySession`` 管理浏览器生命周期；若请求
# 取消恰好落在 ``__aenter__`` 的浏览器启动窗口内（``launch_persistent_context``
# 已 spawn 浏览器/driver 进程但 context 尚未建完），``__aexit__`` 不会执行，
# 进程孤儿化、一直活到 daemon 进程退出断管才死（集成测试实测 6s 后仍残留 7 个
# camoufox 进程）。scrapling 无法从外部补救，只能 OS 层兜底：daemon 经
# start_new_session 是自身会话首，其拉起的浏览器/driver 必为本进程后代——
# 调用前快照后代 pid，取消时 SIGKILL 其间新出现的浏览器/驱动进程。

# 进程名过滤：只杀 cmdline 命中浏览器/驱动的后代（camoufox 全家、playwright
# 的 node driver），并发场景下波及面收敛到「本 daemon 自己拉的浏览器家族」。
_BROWSER_PROC_PATTERN = re.compile(r"camoufox|firefox|playwright", re.IGNORECASE)
# 首轮击杀后留一拍，让垂死进程在启动期 fork 出的子进程冒头再补一轮
_KILL_RESWEEP_DELAY = 0.5


def _process_tree() -> dict[int, int]:
    """读 /proc 一趟，返回 pid → ppid 映射（条目读不到/已退出则跳过）。

    无 /proc 的平台（macOS）返回空表——调用方按「无后代可清」处理，兜底
    降级为不作为，不影响正常抓取。
    """
    tree: dict[int, int] = {}
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return tree
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            # comm 字段可含空格与括号，从最后一个 ')' 之后切字段
            fields = stat[stat.rindex(")") + 1:].split()
            tree[int(entry.name)] = int(fields[1])  # fields[1] 即 ppid
        except (OSError, ValueError, IndexError):
            continue
    return tree


def _descendants(tree: dict[int, int], root: int) -> set[int]:
    """进程树中 root 的全部后代 pid（BFS；空树返回空集）。"""
    children: dict[int, list[int]] = {}
    for pid, ppid in tree.items():
        children.setdefault(ppid, []).append(pid)
    out: set[int] = set()
    stack = [root]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in out:
                out.add(child)
                stack.append(child)
    return out


def _proc_cmdline(pid: int) -> str:
    """/proc/<pid>/cmdline 的 NUL 分隔参数拼成空格串；读不到返回空串。"""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\x00", b" ").decode("utf-8", "replace")


def _kill_spawned_browsers(before: set[int]) -> int:
    """SIGKILL 快照 ``before`` 之后新出现的、cmdline 命中浏览器的后代进程。

    返回击杀数；进程已死/无权限均跳过（兜底尽力而为）。
    """
    fresh = _descendants(_process_tree(), os.getpid()) - before
    killed = 0
    for pid in fresh:
        if _BROWSER_PROC_PATTERN.search(_proc_cmdline(pid)) is None:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except (ProcessLookupError, PermissionError):
            continue
    return killed


# 在飞浏览器抓取计数（并发波及防护，见 _browser_cancel_guard）。
_INFLIGHT_BROWSER_FETCHES = 0


async def _browser_cancel_guard(coro_factory: Callable[[], Any]) -> Any:
    """包一次浏览器抓取：取消落在浏览器启动窗口时不留孤儿进程。

    ``coro_factory`` 零参返回 awaitable（惰性构造：快照须在浏览器进程出现
    之前完成）。取消路径做两轮 SIGKILL 补扫后原样 re-raise——取消必须继续
    传播。非取消路径（成功/普通异常）不做任何进程清扫：正常关闭由 scrapling
    的 ``__aexit__`` 负责，普通异常下 playwright 自会收割自己拉的进程。

    并发波及防护：清扫按「快照差集 + 进程名匹配」无法区分浏览器归属，daemon
    模式下会误杀兄弟请求正在使用的浏览器。仍有其他在飞浏览器抓取（计数 >0）
    时跳过本轮清扫，由最后一个离开者负责——宁可把待收进程留给 daemon 退出
    （close_all 宽限兜底）或池重建收口，也不打断兄弟请求；被波及请求可重试
    的代价已避免，见 README「已知限制」。
    """
    global _INFLIGHT_BROWSER_FETCHES
    before = _descendants(_process_tree(), os.getpid())
    _INFLIGHT_BROWSER_FETCHES += 1
    try:
        result = await coro_factory()
    except asyncio.CancelledError:
        _INFLIGHT_BROWSER_FETCHES -= 1
        if _INFLIGHT_BROWSER_FETCHES == 0:  # 最后一个离开者才清扫
            _kill_spawned_browsers(before)
            await asyncio.sleep(_KILL_RESWEEP_DELAY)
            _kill_spawned_browsers(before)
        raise
    except BaseException:
        _INFLIGHT_BROWSER_FETCHES -= 1
        raise
    else:
        _INFLIGHT_BROWSER_FETCHES -= 1
        return result


async def _do_browse(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None,
) -> Any:
    """Actual scrapling fetch (extracted from browse_url)."""
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        # 浏览器池（默认关）：开启时 stealth/max-stealth 改走池化会话。
        # 放在本函数内 => 保持在 browse_url 的并发闸门之内（spec §6.2）。
        if mode in ("stealth", "max-stealth") and config.browser_pool:
            return await _browser_cancel_guard(
                lambda: get_pool().fetch(
                    url, mode, int(config.fetch_timeout * 1000), page_action=page_action
                )
            )

        if mode == "basic":
            response = await AsyncFetcher.get(
                url,
                stealthy_headers=True,
                headers={"Accept": _MARKDOWN_ACCEPT},
            )
            _attach_negotiated_markdown(response)
            return response
        elif mode == "stealth":
            return await _browser_cancel_guard(
                lambda: StealthyFetcher.async_fetch(
                    url,
                    headless=True,
                    network_idle=True,
                    # camoufox 默认 30s 导航超时,对故意拖延 load 事件的站点
                    # (如 Brave Search)不够;沿用全局 fetch_timeout(秒)
                    timeout=int(config.fetch_timeout * 1000),
                    page_action=page_action,
                )
            )
        elif mode == "max-stealth":
            return await _browser_cancel_guard(
                lambda: StealthyFetcher.async_fetch(
                    url,
                    headless=True,
                    block_webrtc=True,
                    network_idle=True,
                    disable_resources=False,
                    block_images=False,
                    timeout=int(config.fetch_timeout * 1000),
                    page_action=page_action,
                )
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
