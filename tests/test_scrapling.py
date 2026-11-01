"""Tests for scrapling wrapper"""
import asyncio
import os
import subprocess
import sys
import time

import pytest
from unittest.mock import AsyncMock, MagicMock

import scrapling_fetch_mcp._scrapling as scrapling_mod


@pytest.mark.asyncio
async def test_browse_url_with_page_action():
    """Test browse_url accepts page_action parameter"""
    from scrapling_fetch_mcp._scrapling import browse_url

    # Mock page_action function
    page_action_called = False

    async def test_page_action(page):
        nonlocal page_action_called
        page_action_called = True

    # This test will verify the parameter is accepted
    # We won't actually call browse_url as it requires real browser
    # Just verify the signature accepts the parameter
    import inspect
    sig = inspect.signature(browse_url)
    params = sig.parameters

    # Check if page_action parameter exists
    assert "page_action" in params


class TestBrowseUrlGuard:
    def setup_method(self):
        scrapling_mod._guard = None

    def teardown_method(self):
        scrapling_mod._guard = None

    @pytest.mark.asyncio
    async def test_guard_in_flight_during_call(self, monkeypatch):
        scrapling_mod.init_guard(max_concurrent=2, acquire_timeout=1.0)
        seen = []

        async def fake_browse(url, mode, page_action=None):
            seen.append(scrapling_mod._guard.in_flight)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)

        result = await scrapling_mod.browse_url("http://x", "basic")
        assert result == "page"
        assert seen == [1]
        assert scrapling_mod._guard.in_flight == 0
        assert scrapling_mod._guard.total_acquired == 1

    @pytest.mark.asyncio
    async def test_no_guard_skips_limiting(self, monkeypatch):
        called = []

        async def fake_browse(url, mode, page_action=None):
            called.append(url)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)
        result = await scrapling_mod.browse_url("http://y", "basic")
        assert result == "page"
        assert scrapling_mod._guard is None
        assert called == ["http://y"]


@pytest.mark.asyncio
async def test_stealth_fetch_uses_configured_timeout(monkeypatch):
    """stealth/max-stealth 应把 fetch_timeout(秒)转成毫秒传给 camoufox"""
    from scrapling_fetch_mcp._config import config

    captured = {}

    async def fake_fetch(url, **kwargs):
        captured.update(kwargs)
        resp = MagicMock()
        resp.status = 200
        resp.body = b"<html></html>"
        resp.html_content = "<html></html>"
        return resp

    monkeypatch.setattr(
        "scrapling.fetchers.StealthyFetcher.async_fetch", fake_fetch)

    original = config.fetch_timeout
    try:
        config.set_fetch_timeout(45)
        await scrapling_mod._do_browse("http://x", "stealth")
        assert captured["timeout"] == 45000
        await scrapling_mod._do_browse("http://x", "max-stealth")
        assert captured["timeout"] == 45000
    finally:
        config.set_fetch_timeout(original)


class TestMarkdownContentNegotiation:
    """basic 模式的 Accept: text/markdown 协商探测"""

    def _make_response(self, content_type=None, body=b"# Hello"):
        # SimpleNamespace 而非 MagicMock:未附加的属性 getattr 必须拿到 None
        from types import SimpleNamespace
        resp = SimpleNamespace()
        resp.body = body
        headers = {}
        if content_type is not None:
            headers["Content-Type"] = content_type
        resp.headers = headers
        resp.html_content = "<html><body>wrapped</body></html>"
        return resp

    @pytest.mark.asyncio
    async def test_basic_request_sends_markdown_accept_header(self, monkeypatch):
        """basic 模式请求应带内容协商 Accept 头"""
        captured = {}

        async def fake_get(url, **kwargs):
            captured.update(kwargs)
            return self._make_response()

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        await scrapling_mod._do_browse("http://x", "basic")

        accept = captured["headers"]["Accept"]
        assert "text/markdown" in accept
        assert "text/html" in accept  # 未命中时可回退

    @pytest.mark.asyncio
    async def test_markdown_response_body_attached(self, monkeypatch):
        """响应为 text/markdown 时,原始 body 应挂到 markdown_content"""
        async def fake_get(url, **kwargs):
            return self._make_response(content_type="text/markdown; charset=utf-8",
                                       body=b"# Real Markdown\n\ntext")

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) == "# Real Markdown\n\ntext"

    @pytest.mark.asyncio
    async def test_html_response_not_attached(self, monkeypatch):
        """普通 HTML 响应不应附加 markdown_content"""
        async def fake_get(url, **kwargs):
            return self._make_response(content_type="text/html; charset=utf-8")

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) is None

    @pytest.mark.asyncio
    async def test_missing_content_type_header_tolerated(self, monkeypatch):
        """响应无 Content-Type 时不应抛错"""
        async def fake_get(url, **kwargs):
            return self._make_response()

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        resp = await scrapling_mod._do_browse("http://x", "basic")

        assert getattr(resp, "markdown_content", None) is None


class FakePool:
    """池替身：记录 fetch 入参，可断言路由是否经池。"""

    def __init__(self):
        self.calls = []

    async def fetch(self, url, mode, timeout_ms, page_action=None):
        self.calls.append((url, mode, timeout_ms, page_action))
        return "pooled-page"


class TestBrowserPoolRouting:
    """config.browser_pool 开关：stealth/max-stealth 走池，basic 与关闭时走原路径"""

    def setup_method(self):
        scrapling_mod._pool = None

    def teardown_method(self):
        scrapling_mod._pool = None

    @pytest.mark.asyncio
    async def test_enabled_stealth_routes_through_pool(self, monkeypatch):
        from scrapling_fetch_mcp._config import config

        fake_pool = FakePool()
        monkeypatch.setattr(scrapling_mod, "get_pool", lambda: fake_pool)
        called = []
        timeout_ms = int(config.fetch_timeout * 1000)

        async def fail_fetch(url, **kwargs):
            called.append(url)  # 池开启时不应直连 StealthyFetcher
            return "direct-page"

        monkeypatch.setattr(
            "scrapling.fetchers.StealthyFetcher.async_fetch", fail_fetch)

        original = config.browser_pool
        config.set_browser_pool(True)
        try:
            result = await scrapling_mod._do_browse("http://x", "stealth", None)
        finally:
            config.set_browser_pool(original)
        assert result == "pooled-page"
        assert called == []  # 未走原路径
        assert fake_pool.calls == [("http://x", "stealth", timeout_ms, None)]

    @pytest.mark.asyncio
    async def test_enabled_max_stealth_routes_through_pool(self, monkeypatch):
        from scrapling_fetch_mcp._config import config

        fake_pool = FakePool()
        monkeypatch.setattr(scrapling_mod, "get_pool", lambda: fake_pool)
        timeout_ms = int(config.fetch_timeout * 1000)
        original = config.browser_pool
        config.set_browser_pool(True)
        try:
            await scrapling_mod._do_browse("http://x", "max-stealth", None)
        finally:
            config.set_browser_pool(original)
        assert fake_pool.calls == [("http://x", "max-stealth", timeout_ms, None)]

    @pytest.mark.asyncio
    async def test_enabled_basic_ignores_pool(self, monkeypatch):
        """basic 模式永不经池:浏览器池开启时也保持原行为"""
        from scrapling_fetch_mcp._config import config
        from types import SimpleNamespace

        fake_pool = FakePool()
        monkeypatch.setattr(scrapling_mod, "get_pool", lambda: fake_pool)

        async def fake_get(url, **kwargs):
            return SimpleNamespace(body=b"<html></html>", html_content="<html></html>",
                                   headers={"Content-Type": "text/html"})

        monkeypatch.setattr("scrapling.fetchers.AsyncFetcher.get", fake_get)
        original = config.browser_pool
        config.set_browser_pool(True)
        try:
            resp = await scrapling_mod._do_browse("http://x", "basic")
        finally:
            config.set_browser_pool(original)
        assert fake_pool.calls == []
        assert getattr(resp, "markdown_content", None) is None

    @pytest.mark.asyncio
    async def test_disabled_keeps_original_path(self, monkeypatch):
        """池关闭(默认):stealth 走原 StealthyFetcher 路径,不触达 get_pool"""
        from scrapling_fetch_mcp._config import config

        def fail_get_pool():
            raise AssertionError("browser_pool=False 时不应构造/使用池")

        monkeypatch.setattr(scrapling_mod, "get_pool", fail_get_pool)
        captured = {}

        async def fake_fetch(url, **kwargs):
            captured.update(kwargs)
            return "direct-page"

        monkeypatch.setattr(
            "scrapling.fetchers.StealthyFetcher.async_fetch", fake_fetch)

        assert config.browser_pool is False  # 默认关闭
        result = await scrapling_mod._do_browse("http://x", "stealth")
        assert result == "direct-page"
        assert "timeout" in captured


class TestGetPoolSingleton:
    """get_pool 惰性单例:参数取自 config,二次调用同一实例;pool_if_built
    只读探测绝不构造"""

    def setup_method(self):
        scrapling_mod._pool = None

    def teardown_method(self):
        scrapling_mod._pool = None

    def test_lazy_singleton_reads_config(self):
        from scrapling_fetch_mcp._config import config
        from scrapling_fetch_mcp.daemon.pool import BrowserPool

        pool = scrapling_mod.get_pool()
        try:
            assert isinstance(pool, BrowserPool)
            assert scrapling_mod.get_pool() is pool  # 同一实例
            stats = pool.stats()
            assert stats["sessions"] == 0 and stats["hits"] == 0
        finally:
            scrapling_mod._pool = None

    def test_pool_if_built_never_constructs(self):
        """未构造返回 None;已构造原样返回,全程不触发惰性构造。"""
        assert scrapling_mod.pool_if_built() is None
        sentinel = object()
        scrapling_mod._pool = sentinel
        assert scrapling_mod.pool_if_built() is sentinel


class TestBrowserCancelGuard:
    """取消兜底清扫：快照后新增的浏览器/驱动后代被 SIGKILL（孤儿泄漏防线）"""

    def test_process_tree_and_descendants(self):
        tree = scrapling_mod._process_tree()
        assert os.getpid() in tree
        # 构造真实子进程:pid 互为父子关系可被 BFS 找到
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            fresh = scrapling_mod._descendants(scrapling_mod._process_tree(), os.getpid())
            assert child.pid in fresh
        finally:
            child.kill()
            child.wait()

    def test_kill_spawned_browsers_kills_only_matching_descendants(self):
        # 模拟浏览器后代:cmdline 含 camoufox 字样的常驻子进程
        browser_like = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "camoufox-sim"]
        )
        # 不命中的后代:cmdline 无浏览器字样,绝不被误杀
        bystander = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            time.sleep(0.3)  # 等两个子进程真正起来(出现在 /proc)
            killed = scrapling_mod._kill_spawned_browsers(before=set())
            assert killed >= 1
            assert _pid_gone(browser_like.pid), "浏览器样后代未被击杀"
            assert not _pid_gone(bystander.pid), "非浏览器后代被误杀"
        finally:
            bystander.kill()
            bystander.wait()

    def test_kill_spawned_browsers_spares_preexisting(self):
        # before 快照已有的浏览器样后代不在清扫范围(并发请求的浏览器不受影响)
        preexisting = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)", "camoufox-sim"]
        )
        try:
            time.sleep(0.3)
            killed = scrapling_mod._kill_spawned_browsers(before={preexisting.pid})
            assert killed == 0
            assert not _pid_gone(preexisting.pid), "快照内进程被误杀"
        finally:
            preexisting.kill()
            preexisting.wait()

    @pytest.mark.asyncio
    async def test_guard_reraises_and_sweeps(self):
        # 取消路径:清扫后 CancelledError 原样传播(取消必须继续传播)
        async def boom():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await scrapling_mod._browser_cancel_guard(boom)

    @pytest.mark.asyncio
    async def test_guard_passthrough_on_success(self):
        async def ok():
            return "page"

        assert await scrapling_mod._browser_cancel_guard(ok) == "page"

    @pytest.mark.asyncio
    async def test_guard_skips_sweep_while_siblings_inflight(self, monkeypatch):
        """I3 回归：兄弟浏览器请求在飞时跳过清扫（并发波及防护）。

        清扫按进程名匹配无法区分浏览器归属，daemon 模式下会误杀兄弟请求
        正在使用的浏览器。计数 >0 时跳过，取消照常传播。
        """
        killed: list[set] = []
        monkeypatch.setattr(
            scrapling_mod, "_kill_spawned_browsers",
            lambda before: killed.append(before) or 0,
        )
        monkeypatch.setattr(scrapling_mod, "_KILL_RESWEEP_DELAY", 0)

        sibling_started = asyncio.Event()
        sibling_release = asyncio.Event()

        async def sibling() -> str:
            async def body():
                sibling_started.set()
                await sibling_release.wait()  # 模拟仍在飞的抓取
                return "sib"
            return await scrapling_mod._browser_cancel_guard(body)

        async def victim() -> str:
            async def body():
                await sibling_started.wait()
                raise asyncio.CancelledError
            try:
                await scrapling_mod._browser_cancel_guard(body)
            except asyncio.CancelledError:
                return "cancelled-propagated"  # 取消必须继续传播

        sib_task = asyncio.create_task(sibling())
        try:
            assert await asyncio.wait_for(victim(), 5) == "cancelled-propagated"
            assert killed == []  # 兄弟在飞:本轮清扫被跳过
            sibling_release.set()
            assert await asyncio.wait_for(sib_task, 5) == "sib"  # 兄弟不受波及
            assert killed == []  # 兄弟正常完成,正常路径本就不清扫
        finally:
            sibling_release.set()
        assert scrapling_mod._INFLIGHT_BROWSER_FETCHES == 0  # 计数精确归零

    @pytest.mark.asyncio
    async def test_guard_sweeps_when_last_leaver_cancelled(self, monkeypatch):
        """无兄弟在飞（或自己是最后离开者）时清扫照旧，计数归零。"""
        killed: list[set] = []
        monkeypatch.setattr(
            scrapling_mod, "_kill_spawned_browsers",
            lambda before: killed.append(before) or 0,
        )
        monkeypatch.setattr(scrapling_mod, "_KILL_RESWEEP_DELAY", 0)

        async def boom():
            raise asyncio.CancelledError

        with pytest.raises(asyncio.CancelledError):
            await scrapling_mod._browser_cancel_guard(boom)
        assert len(killed) == 2  # 首轮 + resweep
        assert scrapling_mod._INFLIGHT_BROWSER_FETCHES == 0

    @pytest.mark.asyncio
    async def test_guard_counter_reset_on_non_cancel_exception(self, monkeypatch):
        """普通异常路径不清扫但计数必须归零（BaseException 分支）。"""
        monkeypatch.setattr(
            scrapling_mod, "_kill_spawned_browsers",
            lambda before: pytest.fail("普通异常路径不得清扫"),
        )

        async def fail():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await scrapling_mod._browser_cancel_guard(fail)
        assert scrapling_mod._INFLIGHT_BROWSER_FETCHES == 0


def _pid_gone(pid: int, timeout: float = 2.0) -> bool:
    """SIGKILL 后进程已收尸（轮询等待,内核终止与 wait 可见间有微秒级竞态）"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if os.waitpid(pid, os.WNOHANG)[0] == pid:
                return True
        except ChildProcessError:
            return True  # 非本进程子进程:信号已发
        time.sleep(0.05)
    return False


