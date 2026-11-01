"""前端 BackendClient 测试（Task 8）。

真 unix socket + 进程内假 daemon（asyncio server 直收协议帧，不 spawn 真
worker，也不 import daemon.worker）；``ensure_daemon`` monkeypatch 到假
socket 路径。覆盖：roundtrip+progress 桥、daemon 死亡自动重拉、
DAEMON_UNAVAILABLE 映射、客户端取消→cancel 帧+CancelledError 传播、
重复终帧容忍（Task 7 契约：首帧定局）、看门狗超时、adapter 错误映射、
模块级单例。
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from scrapling_fetch_mcp import _client as client_mod
from scrapling_fetch_mcp._client import (
    BackendClient,
    BackendError,
    get_client,
    make_adapter,
)
from scrapling_fetch_mcp.daemon.protocol import (
    E_CANCELLED,
    make_error,
    make_progress,
    make_response,
    parse_frame,
)


# ---------- 假 daemon ----------

class FakeDaemon:
    """进程内假 daemon：真 unix socket，每帧请求 spawn 独立任务交 handler。

    与真 worker 同构的多路复用（handler 慢不阻塞后续帧处理，cancel 测试
    依赖此点）；``kill`` 模拟 SIGKILL：停 accept + 掐断全部在途连接，
    客户端侧表现为 EOF。
    """

    def __init__(self, sock: Path, handler) -> None:
        self.sock = sock
        self.handler = handler  # async handler(frame: dict, send)
        self.token = "fake-" + os.urandom(8).hex()
        self.received: list[dict] = []
        self._server: asyncio.AbstractServer | None = None
        self._tasks: set[asyncio.Task] = set()
        self._writers: set[asyncio.StreamWriter] = set()

    async def start(self) -> None:
        self.sock.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.sock.unlink()
        except FileNotFoundError:
            pass
        self._server = await asyncio.start_unix_server(self._on_connect, path=str(self.sock))
        # lock JSON 与真 worker 同构（client 据此取 token）
        self.sock.with_suffix(".lock").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "token": self.token,
                    "pkg": "0.0.0",
                    "config_hash": "deadbeef",
                    "sock": str(self.sock),
                }
            ),
            encoding="utf-8",
        )

    async def _on_connect(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        async def send(frame: bytes) -> None:
            writer.write(frame)
            await writer.drain()

        task = asyncio.current_task()
        assert task is not None
        self._tasks.add(task)
        self._writers.add(writer)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    frame = parse_frame(line)
                except client_mod.ProtocolError:
                    continue
                self.received.append(frame)
                # 每帧独立任务分派（与真 worker 同构的多路复用）：handler 慢
                # 不阻塞后续帧处理——cancel 测试依赖 cancel 帧能插队处理
                handler_task = asyncio.create_task(self._run_handler(frame, send))
                self._tasks.add(handler_task)
                handler_task.add_done_callback(self._tasks.discard)
        except (ConnectionError, OSError):
            pass
        finally:
            self._tasks.discard(task)
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _run_handler(self, frame: dict, send) -> None:
        try:
            await self.handler(frame, send)
        except (ConnectionError, OSError):
            pass  # 连接被 kill/对端断开时在途 handler 的写失败属正常终点

    def abort_connections(self) -> None:
        """掐断当前全部连接但不停止服务（模拟 daemon 存活时的连接级故障）。"""
        for w in list(self._writers):
            w.transport.abort()

    async def kill(self) -> None:
        """模拟 daemon 被杀：停 accept、取消全部连接任务（客户端看到 EOF）。

        先取消连接任务再 ``wait_closed``：Python 3.12 起该调用会等全部
        连接处理结束，客户端仍持着持久连接，顺序颠倒会互相等待死锁。
        """
        server, self._server = self._server, None
        if server is not None:
            server.close()
        for task in list(self._tasks):
            task.cancel()
        if server is not None:
            await server.wait_closed()
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        self._tasks.clear()


async def wait_connection_dead(c: BackendClient, timeout: float = 3.0) -> None:
    """轮询直至客户端感知连接死亡（reader 任务结束）。"""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not (c._writer is not None and c._reader_task is not None and c._reader_task.done()):
        if loop.time() > deadline:
            raise AssertionError("客户端未在期限内感知 daemon 死亡")
        await asyncio.sleep(0.01)


async def ready_handler(frame: dict, send) -> None:
    await send(make_response(frame["id"], {"status": "ready"}))


# ---------- fixtures ----------

@pytest.fixture(autouse=True)
def _reset_singleton():
    """模块级单例不跨测试泄漏（事件循环绑定对象随测试更替）。"""
    client_mod._client_instance = None
    yield
    client_mod._client_instance = None


@pytest.fixture
def patch_ensure(monkeypatch):
    """把 _client.ensure_daemon 换成返回指定 socket 路径的假实现。

    传入路径或可调用对象（每次调用求值，供 kill-重拉测试切换新旧 daemon）；
    返回调用记录列表供断言。
    """

    def _patch(sock_source):
        calls: list[tuple] = []

        def fake_ensure(spawn_env, config_hash, timeout=60.0):
            calls.append((spawn_env, config_hash, timeout))
            return sock_source() if callable(sock_source) else sock_source

        monkeypatch.setattr(client_mod, "ensure_daemon", fake_ensure)
        return calls

    return _patch


# ---------- 1. roundtrip + progress ----------

@pytest.mark.asyncio
async def test_call_roundtrip_and_progress(tmp_path, patch_ensure):
    progress_sent = asyncio.Event()

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            await send(make_progress(frame["id"], 50, 100, "x"))
            progress_sent.set()
            await send(make_response(frame["id"], {"result": "MARKDOWN-BODY"}))
        else:
            await send(make_response(frame["id"], {"status": "ready"}))

    d = FakeDaemon(tmp_path / "d1.sock", handler)
    await d.start()
    calls = patch_ensure(d.sock)
    c = BackendClient()
    try:
        seen_progress = []

        class Ctx:
            async def report_progress(self, p, t, m=None):
                seen_progress.append((p, t, m))

        resp = await asyncio.wait_for(c.call("fetch_page", {"url": "u"}, Ctx()), 5)
        assert resp["result"] == "MARKDOWN-BODY"
        assert seen_progress == [(50, 100, "x")]
        assert len(calls) == 1  # 首连恰好一次 ensure_daemon
    finally:
        await c.aclose()
        await d.kill()


@pytest.mark.asyncio
async def test_call_without_ctx_skips_progress_bridge(tmp_path, patch_ensure):
    """ctx=None 时 progress 帧被安全忽略，响应照常返回。"""

    async def handler(frame: dict, send) -> None:
        await send(make_progress(frame["id"], 1, 2, "y"))
        await send(make_response(frame["id"], {"result": "OK"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    c = BackendClient()
    try:
        resp = await asyncio.wait_for(c.call("fetch_page", {"url": "u"}, None), 5)
        assert resp["result"] == "OK"
    finally:
        await c.aclose()
        await d.kill()


@pytest.mark.asyncio
async def test_hung_progress_callback_does_not_block_result(tmp_path, patch_ensure, monkeypatch):
    """progress 回调卡死：结果仍有界及时返回（progress 交付是尽力而为）。"""
    monkeypatch.setattr(client_mod, "_PROGRESS_DRAIN_TIMEOUT", 0.2)

    class HungCtx:
        async def report_progress(self, p, t, m=None):
            await asyncio.sleep(30)  # 卡死：永不主动完成

    async def handler(frame: dict, send) -> None:
        await send(make_progress(frame["id"], 1, 2, "x"))
        await send(make_response(frame["id"], {"result": "OK"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    c = BackendClient()
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        resp = await asyncio.wait_for(c.call("fetch_page", {"url": "u"}, HungCtx()), 5)
        elapsed = loop.time() - start
        assert resp["result"] == "OK"
        # 旧实现会 gather 到回调的 30s 睡眠结束；有界化后拖满收尾窗口即交付
        assert elapsed < 3.0
    finally:
        await c.aclose()
        await d.kill()


# ---------- 2. daemon 死亡自动重拉 ----------

@pytest.mark.asyncio
async def test_retry_after_daemon_kill(tmp_path, patch_ensure):
    d1 = FakeDaemon(tmp_path / "d1.sock", ready_handler)
    d2 = FakeDaemon(tmp_path / "d2.sock", ready_handler)
    await d1.start()
    await d2.start()
    socks = iter([d1.sock, d2.sock])
    calls = patch_ensure(lambda: next(socks))
    c = BackendClient()
    try:
        resp1 = await asyncio.wait_for(c.call("ping", {}, None), 5)
        assert resp1["status"] == "ready"
        assert len(calls) == 1
        await d1.kill()  # 模拟 SIGKILL
        await wait_connection_dead(c)
        # 下一次调用自动重跑 ensure_daemon → 拉起新 daemon → 成功
        resp2 = await asyncio.wait_for(c.call("ping", {}, None), 5)
        assert resp2["status"] == "ready"
        assert len(calls) == 2
    finally:
        await c.aclose()
        await d2.kill()


@pytest.mark.asyncio
async def test_adapter_retry_after_connection_loss_uses_new_id(tmp_path, patch_ensure):
    """评审 Important 回归钉：daemon 存活但连接级故障 → 重试必须换新请求 id。

    daemon 不因客户端断连清理 _tasks：同 id 重放会让新任务覆盖孤儿注册，
    且孤儿迟到的响应帧按同 id 命中新 future（旧结果误配新请求）。换新 id
    双向消除。测试同时验证孤儿 id 的迟到帧被安全忽略、连接仍然可用。
    """
    killed = {"done": False}
    first_id: list[int] = []

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            if not killed["done"]:
                killed["done"] = True
                first_id.append(frame["id"])
                d.abort_connections()  # 不回帧直接掐断:客户端按连接级故障重试
                return
            # 孤儿任务迟到帧在第二请求响应**之前**同步发出：时序由发送顺序
            # 保证（不靠 sleep），迟到帧先到且必须被忽略（首帧定局/无 pending）
            if first_id and first_id[0] != frame["id"]:
                await send(make_response(first_id[0], {"result": "ORPHAN-LATE"}))
            await send(make_response(frame["id"], {"result": "SECOND"}))
        else:
            await send(make_response(frame["id"], {"status": "ready"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)  # daemon 存活:两次尝试指向同一 daemon
    adapter = make_adapter("fetch_page")
    try:
        result = await asyncio.wait_for(adapter(None, url="u"), 5)
        assert result == "SECOND"  # 孤儿迟到帧未误配（仍是第二次尝试的结果）
        fetches = [f for f in d.received if f["op"] == "fetch_page"]
        assert len(fetches) == 2
        assert fetches[1]["id"] != fetches[0]["id"]  # 重试换新 id（本回归的承重断言）
        # 连接仍可用
        assert (await asyncio.wait_for(get_client().call("ping", {}, None), 5))["status"] == "ready"
    finally:
        await get_client().aclose()
        await d.kill()


# ---------- 3. DAEMON_UNAVAILABLE ----------

@pytest.mark.asyncio
async def test_unavailable_maps_to_daemon_unavailable(monkeypatch):
    def boom(spawn_env, config_hash, timeout=60.0):
        raise TimeoutError("daemon 未在期限内就绪")

    monkeypatch.setattr(client_mod, "ensure_daemon", boom)
    # 隔离真实 env 解析:不触 daemon 目录解析链的文件系统副作用(mkdir)
    monkeypatch.setattr(client_mod, "resolve_daemon_env", lambda cli=None: ({}, "deadbeef"))
    c = BackendClient()
    with pytest.raises(BackendError) as excinfo:
        await asyncio.wait_for(c.call("ping", {}, None), 10)
    assert excinfo.value.code == "DAEMON_UNAVAILABLE"
    msg = str(excinfo.value)
    assert "scrapling-fetch-mcp daemon status" in msg
    assert "SCRAPLING_DAEMON_DIR" in msg


# ---------- 4. 客户端取消 → cancel 帧 ----------

@pytest.mark.asyncio
async def test_adapter_cancel_frame_on_cancellation(tmp_path, patch_ensure):
    fetch_started = asyncio.Event()
    cancel_seen = asyncio.Event()

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            fetch_started.set()
            await asyncio.sleep(30)  # 永不主动完成，等客户端取消
        elif frame["op"] == "cancel":
            cancel_seen.set()
            await send(make_error(frame["payload"]["cancel_id"], E_CANCELLED, "请求已被取消"))
            await send(make_response(frame["id"], {"cancelled": True}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    adapter = make_adapter("fetch_page")
    task = asyncio.create_task(adapter(None, url="u"))
    try:
        await asyncio.wait_for(fetch_started.wait(), 5)
        await asyncio.sleep(0.05)  # 让请求帧送达 fake daemon
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        await asyncio.wait_for(cancel_seen.wait(), 5)
        # cancel 帧必须命中原请求 id（adapter 预分配 id 传给 call）
        fetch_frame = next(f for f in d.received if f["op"] == "fetch_page")
        cancel_frame = next(f for f in d.received if f["op"] == "cancel")
        assert cancel_frame["payload"]["cancel_id"] == fetch_frame["id"]
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await get_client().aclose()
        await d.kill()


# ---------- 5. 重复终帧容忍（Task 7 契约） ----------

@pytest.mark.asyncio
async def test_duplicate_terminal_first_wins(tmp_path, patch_ensure):
    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            if frame["payload"]["url"] == "ok-first://x":
                # 正常响应在前，迟到的 E_CANCELLED 在后：首个终帧定局
                await send(make_response(frame["id"], {"result": "FIRST-OK"}))
                await send(make_error(frame["id"], E_CANCELLED, "迟到的取消"))
            else:
                # 错误在前，迟到的成功在后：首个终帧定局
                await send(make_error(frame["id"], E_CANCELLED, "已被取消"))
                await send(make_response(frame["id"], {"result": "LATE-OK"}))
        else:
            await send(make_response(frame["id"], {"status": "ready"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    c = BackendClient()
    try:
        resp = await asyncio.wait_for(c.call("fetch_page", {"url": "ok-first://x"}, None), 5)
        assert resp["result"] == "FIRST-OK"
        with pytest.raises(BackendError) as excinfo:
            await asyncio.wait_for(c.call("fetch_page", {"url": "err-first://x"}, None), 5)
        assert excinfo.value.code == E_CANCELLED
    finally:
        await c.aclose()
        await d.kill()


# ---------- 6. 看门狗超时 ----------

@pytest.mark.asyncio
async def test_watchdog_timeout_sends_cancel(tmp_path, patch_ensure, monkeypatch):
    from scrapling_fetch_mcp._config import config

    cancel_seen = asyncio.Event()
    fetch_started = asyncio.Event()

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            fetch_started.set()
            await asyncio.sleep(30)  # daemon 挂死：永不应答
        elif frame["op"] == "cancel":
            cancel_seen.set()
            await send(make_response(frame["id"], {"cancelled": True}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    monkeypatch.setattr(config, "_acquire_timeout", 0.0)  # monkeypatch 自动还原,不直改单例
    monkeypatch.setattr(config, "_fetch_timeout", 0.0)
    monkeypatch.setattr(client_mod, "_WATCHDOG_SLACK", 0.1)
    c = BackendClient()
    try:
        with pytest.raises(BackendError) as excinfo:
            await asyncio.wait_for(c.call("fetch_page", {"url": "u"}, None), 10)
        assert excinfo.value.code == "DAEMON_TIMEOUT"
        await asyncio.wait_for(cancel_seen.wait(), 5)  # 超时后发了 cancel 帧
        fetch_frame = next(f for f in d.received if f["op"] == "fetch_page")
        cancel_frame = next(f for f in d.received if f["op"] == "cancel")
        assert cancel_frame["payload"]["cancel_id"] == fetch_frame["id"]
    finally:
        await c.aclose()
        await d.kill()


@pytest.mark.asyncio
async def test_watchdog_deadline_shared_across_retries(tmp_path, patch_ensure, monkeypatch):
    """看门狗按每请求总窗计：重试共享预算，不因连接级故障重试而重置窗口。

    总窗 0.6s：首尝试慢速失败消耗 0.3s，二尝试挂死后看门狗应在进入后约
    0.6s 触发——旧实现每次尝试各给 0.6s，会拖到 0.9s 之外。
    """
    from scrapling_fetch_mcp._config import config

    attempts = {"n": 0}
    cancel_seen = asyncio.Event()

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            attempts["n"] += 1
            if attempts["n"] == 1:
                await asyncio.sleep(0.3)  # 首尝试:慢速失败,消耗总窗预算
                d.abort_connections()
                return
            await asyncio.sleep(30)  # 二尝试挂死:等看门狗触发
        elif frame["op"] == "cancel":
            cancel_seen.set()
            await send(make_response(frame["id"], {"cancelled": True}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    old_acquire, old_fetch = config.acquire_timeout, config.fetch_timeout
    config.set_acquire_timeout(0.0)
    config.set_fetch_timeout(0.0)
    monkeypatch.setattr(client_mod, "_WATCHDOG_SLACK", 0.6)  # 总窗 0.6s
    c = BackendClient()
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        with pytest.raises(BackendError) as excinfo:
            await c.call("fetch_page", {"url": "u"}, None)
        elapsed = loop.time() - start
        assert excinfo.value.code == "DAEMON_TIMEOUT"
        assert elapsed < 0.75  # 总窗语义(旧的重置窗口语义会 >= 0.9)
        assert attempts["n"] >= 2  # 确实发生过重试
        await asyncio.wait_for(cancel_seen.wait(), 5)  # 超时后发了 cancel 帧
    finally:
        config.set_acquire_timeout(old_acquire)
        config.set_fetch_timeout(old_fetch)
        await c.aclose()
        await d.kill()


@pytest.mark.asyncio
async def test_watchdog_window_allows_fast_retries_to_succeed(tmp_path, patch_ensure, monkeypatch):
    """总窗内两次快速连接失败后第三次成功：剩余预算照常交付结果。"""
    from scrapling_fetch_mcp._config import config

    attempts = {"n": 0}

    async def handler(frame: dict, send) -> None:
        if frame["op"] == "fetch_page":
            attempts["n"] += 1
            if attempts["n"] <= 2:
                d.abort_connections()  # 快速连接级失败,几乎不耗预算
                return
            await send(make_response(frame["id"], {"result": "THIRD-OK"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    old_acquire, old_fetch = config.acquire_timeout, config.fetch_timeout
    config.set_acquire_timeout(0.0)
    config.set_fetch_timeout(0.0)
    monkeypatch.setattr(client_mod, "_WATCHDOG_SLACK", 1.0)  # 总窗 1.0s
    c = BackendClient()
    try:
        loop = asyncio.get_running_loop()
        start = loop.time()
        resp = await asyncio.wait_for(c.call("fetch_page", {"url": "u"}, None), 5)
        assert resp["result"] == "THIRD-OK"
        assert attempts["n"] == 3  # 三次尝试全部发生在同一总窗内
        assert loop.time() - start < 1.0
    finally:
        config.set_acquire_timeout(old_acquire)
        config.set_fetch_timeout(old_fetch)
        await c.aclose()
        await d.kill()


# ---------- 7. adapter 错误映射 ----------

@pytest.mark.asyncio
async def test_adapter_error_mapping(tmp_path, patch_ensure):
    async def handler(frame: dict, send) -> None:
        if frame["payload"]["url"] == "limit://x":
            await send(make_error(frame["id"], "CONCURRENCY_LIMIT", "并发已达上限(2)，等待超时"))
        else:
            await send(make_error(frame["id"], "internal", "boom"))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    adapter = make_adapter("fetch_page")
    try:
        with pytest.raises(RuntimeError, match="并发已达上限\\(全局\\),请稍后重试"):
            await asyncio.wait_for(adapter(None, url="limit://x"), 5)
        with pytest.raises(RuntimeError, match="ERROR: internal: boom"):
            await asyncio.wait_for(adapter(None, url="other://x"), 5)
    finally:
        await get_client().aclose()
        await d.kill()


# ---------- 8. 模块级单例 ----------

def test_get_client_singleton():
    assert get_client() is get_client()
    assert isinstance(get_client(), BackendClient)


@pytest.mark.asyncio
async def test_make_adapter_binds_client_lazily(tmp_path, patch_ensure):
    """adapter 在调用时刻才解析单例：工厂先建、单例后重置,仍走重置后的新实例。

    工厂时刻绑定会 被 _reset_singleton 这类测试隔离/热重载甩开——旧实例
    永不建连,连接全部落在当前生效的进程级单例上。
    """

    async def handler(frame: dict, send) -> None:
        await send(make_response(frame["id"], {"result": "LAZY-OK"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    adapter = make_adapter("fetch_page")  # 先建工厂
    stale = get_client()
    client_mod._client_instance = None    # 后重置单例
    try:
        result = await asyncio.wait_for(adapter(None, url="u"), 5)
        assert result == "LAZY-OK"
        fresh = get_client()
        assert fresh is not stale         # 适配器用的是重置后的新单例
        assert stale._writer is None and stale._reader_task is None  # 旧实例从未建连
    finally:
        await get_client().aclose()
        await d.kill()


# ---------- 9. scraping_dir 前端归一化（C2 回归） ----------

@pytest.mark.asyncio
async def test_adapter_injects_absolute_scraping_dir_when_absent(
    tmp_path, patch_ensure, monkeypatch
):
    """C2 回归：payload 缺省时注入 config.scraping_dir 的绝对值。

    daemon 以 cwd="/" spawn：缺省时 wrapper 的 ".temp/scrapling/" 相对默认
    会落到 /.temp（非 root 必 EACCES）。前端 cwd 即用户 cwd，归一化在此层
    完成后 daemon 收到的就是可用绝对路径。
    """
    monkeypatch.chdir(tmp_path)

    async def handler(frame: dict, send) -> None:
        await send(make_response(frame["id"], {"result": "ok"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    adapter = make_adapter("fetch_page")
    pattern_adapter = make_adapter("fetch_pattern")
    try:
        await asyncio.wait_for(
            adapter(None, url="u", mode="basic", format="markdown",
                    max_length=100, start_index=0), 5)
        await asyncio.wait_for(
            pattern_adapter(None, url="u", search_pattern="x", mode="basic",
                            format="markdown", max_length=100), 5)
        page = next(f for f in d.received if f["op"] == "fetch_page")
        pattern = next(f for f in d.received if f["op"] == "fetch_pattern")
        sd = page["payload"]["scraping_dir"]
        assert Path(sd).is_absolute()
        assert not sd.startswith("/.temp")
        assert sd == str((tmp_path / ".temp/scrapling").resolve())  # config 缺省值
        # 他 op 的 wrapper 不接受该形参：不注入，否则 daemon payload 键校验拒绝
        assert "scraping_dir" not in pattern["payload"]
    finally:
        await get_client().aclose()
        await d.kill()


@pytest.mark.asyncio
async def test_adapter_resolves_relative_scraping_dir(tmp_path, patch_ensure, monkeypatch):
    """C2 回归：显式传入的相对 scraping_dir 就地 resolve 为绝对。"""
    monkeypatch.chdir(tmp_path)

    async def handler(frame: dict, send) -> None:
        await send(make_response(frame["id"], {"result": "ok"}))

    d = FakeDaemon(tmp_path / "d.sock", handler)
    await d.start()
    patch_ensure(d.sock)
    adapter = make_adapter("fetch_page")
    try:
        await asyncio.wait_for(
            adapter(None, url="u", mode="basic", format="markdown",
                    max_length=100, start_index=0, scraping_dir="out/x"), 5)
        page = next(f for f in d.received if f["op"] == "fetch_page")
        assert page["payload"]["scraping_dir"] == str((tmp_path / "out/x").resolve())
    finally:
        await get_client().aclose()
        await d.kill()
