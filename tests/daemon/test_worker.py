"""daemon/worker 测试（Task 7）。

真 unix socket + 真事件循环直驱 ``DaemonWorker.serve()``；fetch op 用
monkeypatch 假 wrapper，不起浏览器。覆盖：ping 身份、token 鉴权、fetch
路由与 payload 校验、progress 桥、单连接多路复用、取消传播（正常取消 +
宽限期耗尽 killpg 兜底）、并发限流错误码、坏帧不断连、空闲退出、
shutdown 优雅退出、win32 拒绝。
"""

from __future__ import annotations

import asyncio
import os
import signal
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
from scrapling_fetch_mcp.daemon import worker as worker_mod
from scrapling_fetch_mcp.daemon.protocol import (
    E_CANCELLED,
    E_INTERNAL,
    E_UNKNOWN_OP,
    E_UNAUTHORIZED,
    OP_CANCEL,
    OP_FETCH_PAGE,
    OP_FETCH_PATTERN,
    OP_PING,
    OP_SHUTDOWN,
    OP_STATUS,
    make_request,
    parse_frame,
)

# fetch_page_wrapper 的必填形参（payload 键与 wrapper 形参一一对应）。
PAGE_PAYLOAD = {
    "url": "http://x",
    "mode": "basic",
    "format": "markdown",
    "max_length": 100,
    "start_index": 0,
}
PATTERN_PAYLOAD = {
    "url": "http://x",
    "search_pattern": "foo",
    "mode": "basic",
    "format": "markdown",
    "max_length": 100,
}


class Client:
    """测试用 NDJSON 客户端：open_unix_connection 收发整帧。"""

    def __init__(self, sock: Path):
        self._sock = sock
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    async def __aenter__(self) -> "Client":
        self._reader, self._writer = await asyncio.open_unix_connection(
            str(self._sock), limit=64 * 1024 * 1024
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except OSError:
            pass

    async def send(self, frame: bytes) -> None:
        self._writer.write(frame)
        await self._writer.drain()

    async def recv(self) -> dict:
        return parse_frame(await self._reader.readline())

    async def request(self, op: str, payload: dict, token: str, req_id: int) -> dict:
        await self.send(make_request(op, payload, token, req_id, "0.3.0"))
        return await self.recv()


@asynccontextmanager
async def serve_worker(tmp_path, *, env_hash="ab12cd34", idle_timeout=30.0, **worker_kwargs):
    """在进程内拉起 DaemonWorker 任务，就绪后 yield (sock, worker, task)。"""
    sock = tmp_path / "worker.sock"
    w = worker_mod.DaemonWorker(sock, idle_timeout, config_hash=env_hash, **worker_kwargs)
    task = asyncio.create_task(w.serve())
    # 轮询探活连接直至 serve 完成 bind（探活连接即连即关）
    loop = asyncio.get_running_loop()
    deadline = loop.time() + 5.0
    while True:
        try:
            _reader, writer = await asyncio.open_unix_connection(str(sock))
            break
        except OSError:
            if loop.time() > deadline:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
            await asyncio.sleep(0.02)
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
    try:
        yield SimpleNamespace(sock=sock, worker=w, task=task)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ---------- ping / 鉴权 ----------

@pytest.mark.asyncio
async def test_ping_reports_identity(tmp_path):
    async with serve_worker(tmp_path, env_hash="ab12cd34") as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_PING, {}, h.worker.token, 1)
    assert resp["ok"] is True
    result = resp["result"]
    assert result["status"] == "ready"
    assert result["config_hash"] == "ab12cd34"
    for key in ("pid", "pkg", "uptime_s", "clients"):
        assert key in result


@pytest.mark.asyncio
async def test_wrong_token_rejected(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_PING, {}, "wrong", 1)
    assert resp["ok"] is False
    assert resp["error"]["code"] == E_UNAUTHORIZED


@pytest.mark.asyncio
async def test_unknown_op_rejected(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request("teleport", {}, h.worker.token, 1)
    assert resp["ok"] is False
    assert resp["error"]["code"] == E_UNKNOWN_OP


# ---------- fetch 路由 / payload 校验 / progress 桥 ----------

@pytest.mark.asyncio
async def test_fetch_page_routes_to_wrapper_and_returns_result(tmp_path, monkeypatch):
    seen = {}

    async def fake_wrapper(**kw):
        seen.update(kw)
        return "METADATA: {}\n\nbody"

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", fake_wrapper)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2)
    assert resp["ok"] is True
    assert resp["result"]["result"].endswith("body")
    assert seen["url"] == "http://x"
    assert seen["mode"] == "basic" and seen["max_length"] == 100
    assert "ctx" not in seen or seen["ctx"] is not None  # 桥对象已注入


@pytest.mark.asyncio
async def test_fetch_pattern_routes_to_pattern_wrapper(tmp_path, monkeypatch):
    seen = {}

    async def fake_pattern(**kw):
        seen.update(kw)
        return "match: foo"

    monkeypatch.setattr(worker_mod, "fetch_pattern_wrapper", fake_pattern)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_FETCH_PATTERN, dict(PATTERN_PAYLOAD), h.worker.token, 2)
    assert resp["ok"] is True
    assert resp["result"]["result"] == "match: foo"
    assert seen["search_pattern"] == "foo"


@pytest.mark.asyncio
async def test_fetch_payload_validation_errors(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            # payload 非 dict 已被 parse_frame 的类型校验在协议层拒绝(bad_frame)
            resp = await c.request(OP_FETCH_PAGE, "not-a-dict", h.worker.token, 8)
            assert resp["ok"] is False
            assert resp["error"]["code"] == "bad_frame"
            bad_cases = [
                {k: v for k, v in PAGE_PAYLOAD.items() if k != "url"},  # 缺必填键
                {**PAGE_PAYLOAD, "bogus_key": 1},  # 未知键
            ]
            for i, payload in enumerate(bad_cases):
                resp = await c.request(OP_FETCH_PAGE, payload, h.worker.token, 10 + i)
                assert resp["ok"] is False, f"case {i} 应被拒绝"
                assert resp["error"]["code"] == E_INTERNAL
                assert resp["error"]["message"]
            # 坏 payload 不伤连接：随后的 ping 正常应答
            resp = await c.request(OP_PING, {}, h.worker.token, 99)
            assert resp["ok"] is True


@pytest.mark.asyncio
async def test_progress_bridge_forwards_frames(tmp_path, monkeypatch):
    async def fake_wrapper(**kw):
        await kw["ctx"].report_progress(0, 100, "抓取中")
        await kw["ctx"].report_progress(50, 100, None)  # message 缺省 → 空串
        return "done"

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", fake_wrapper)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            await c.send(make_request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2, "0.3.0"))
            p1 = await asyncio.wait_for(c.recv(), 5)
            p2 = await asyncio.wait_for(c.recv(), 5)
            final = await asyncio.wait_for(c.recv(), 5)
    assert p1["id"] == 2 and p1["progress"] == {"progress": 0, "total": 100, "message": "抓取中"}
    assert p2["progress"] == {"progress": 50, "total": 100, "message": ""}
    assert final["ok"] is True and final["result"]["result"] == "done"


@pytest.mark.asyncio
async def test_multiplex_two_requests_one_connection(tmp_path, monkeypatch):
    a_started, b_started = asyncio.Event(), asyncio.Event()

    async def fake_wrapper(**kw):
        # 两个请求互相等待对方开跑：若 worker 串行处理 fetch 会死锁（5s 超时兜底）
        if kw["url"] == "a://x":
            a_started.set()
            await asyncio.wait_for(b_started.wait(), 5)
            return "A-done"
        b_started.set()
        await asyncio.wait_for(a_started.wait(), 5)
        return "B-done"

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", fake_wrapper)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            await c.send(make_request(OP_FETCH_PAGE, {**PAGE_PAYLOAD, "url": "a://x"}, h.worker.token, 2, "0.3.0"))
            await c.send(make_request(OP_FETCH_PAGE, {**PAGE_PAYLOAD, "url": "b://x"}, h.worker.token, 3, "0.3.0"))
            r2 = await asyncio.wait_for(c.recv(), 5)
            r3 = await asyncio.wait_for(c.recv(), 5)
    by_id = {r2["id"]: r2, r3["id"]: r3}
    assert set(by_id) == {2, 3}
    assert by_id[2]["result"]["result"] == "A-done"
    assert by_id[3]["result"]["result"] == "B-done"


@pytest.mark.asyncio
async def test_fetch_impl_error_maps_to_internal(tmp_path, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", boom)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2)
    assert resp["ok"] is False
    assert resp["error"]["code"] == E_INTERNAL
    assert "boom" in resp["error"]["message"]


@pytest.mark.asyncio
async def test_concurrency_limit_error_maps_to_limit_code(tmp_path, monkeypatch):
    async def limited(**kw):
        raise ConcurrencyLimitError("并发已达上限(2)，等待 0.5s 超时")

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", limited)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2)
    assert resp["ok"] is False
    assert resp["error"]["code"] == "CONCURRENCY_LIMIT"


# ---------- 取消传播 ----------

@pytest.mark.asyncio
async def test_cancel_propagates_and_reports_cancelled(tmp_path, monkeypatch):
    started = asyncio.Event()

    async def slow_wrapper(**kw):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", slow_wrapper)
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            await c.send(make_request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2, "0.3.0"))
            await asyncio.wait_for(started.wait(), 5)
            await c.send(make_request(OP_CANCEL, {"cancel_id": 2}, h.worker.token, 3, "0.3.0"))
            # E_CANCELLED 必发给原始请求 id，且先于 cancel 响应送达
            cancelled_frame = await asyncio.wait_for(c.recv(), 5)
            cancel_resp = await asyncio.wait_for(c.recv(), 5)
        assert h.worker._tasks == {}
    assert cancelled_frame["id"] == 2
    assert cancelled_frame["ok"] is False
    assert cancelled_frame["error"]["code"] == E_CANCELLED
    assert cancel_resp["id"] == 3
    assert cancel_resp["result"] == {"cancelled": True}


@pytest.mark.asyncio
async def test_cancel_unknown_id_reports_false(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_CANCEL, {"cancel_id": 12345}, h.worker.token, 4)
    assert resp["ok"] is True
    assert resp["result"] == {"cancelled": False}


@pytest.mark.asyncio
async def test_cancel_grace_exhausted_triggers_killpg(tmp_path, monkeypatch):
    """宽限期耗尽 → 核弹兜底：os.killpg(os.getpgid(0), SIGKILL) 被调用。

    单测 monkeypatch killpg，不真杀进程（真进程检查留 Task 13）。
    """
    kill_calls = []
    monkeypatch.setattr(
        worker_mod.os, "killpg",
        lambda pgid, sig: kill_calls.append((pgid, sig)),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def zombie_wrapper(**kw):
        started.set()
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            # 模拟浏览器清理挂死：吞掉取消且长期不让出，直到测试放行
            await release.wait()

    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", zombie_wrapper)
    async with serve_worker(tmp_path, cancel_grace=0.2) as h:
        async with Client(h.sock) as c:
            await c.send(make_request(OP_FETCH_PAGE, dict(PAGE_PAYLOAD), h.worker.token, 2, "0.3.0"))
            await asyncio.wait_for(started.wait(), 5)
            await c.send(make_request(OP_CANCEL, {"cancel_id": 2}, h.worker.token, 3, "0.3.0"))
            # 任务杀不死：无 E_CANCELLED 帧，cancel 响应仍照常返回
            resp = await asyncio.wait_for(c.recv(), 5)
            assert resp["id"] == 3
            assert resp["result"] == {"cancelled": True}
        assert kill_calls == [(os.getpgid(0), signal.SIGKILL)]
        release.set()  # 放行僵尸任务，让 serve 收尾能结束


@pytest.mark.asyncio
async def test_cancel_when_target_dies_cancelled_at_unprotected_await(tmp_path):
    """回归（评审 Important）：target.cancel() 落在任务未受保护的 await 上
    （如响应帧的 _safe_send）时，任务以 cancelled 收场，shield 把
    CancelledError 传给 wait_for——_handle_cancel 必须按"取消成功"收尾：
    给原始请求 id 发 E_CANCELLED 并正常返回 {"cancelled": true}，
    绝不能 re-raise（CancelledError 是 BaseException，会穿透
    _process_line 宽兜底杀死整个连接读循环）。
    """
    w = worker_mod.DaemonWorker(tmp_path / "unit.sock", 30.0, config_hash="ab12cd34")
    started = asyncio.Event()

    async def bare_target():
        # 模拟取消点落在 _run_fetch 未捕获 CancelledError 的 await 上：
        # 无内层捕获，cancel() 必然让任务以 cancelled 态收场
        started.set()
        await asyncio.sleep(30)

    target = asyncio.create_task(bare_target())
    w._tasks[2] = target
    sent: list[bytes] = []

    async def send(frame: bytes) -> None:
        sent.append(frame)

    try:
        await asyncio.wait_for(started.wait(), 5)
        resp = parse_frame(
            await asyncio.wait_for(w._handle_cancel(3, {"cancel_id": 2}, send), 5)
        )
        assert target.cancelled()  # 任务确实以 cancelled 收场（复现前提）
        assert resp["ok"] is True and resp["result"] == {"cancelled": True}
        # 原始请求 id 收到终帧 E_CANCELLED（任务死在未保护 await 上时由此补发）
        assert len(sent) == 1
        terminal = parse_frame(sent[0])
        assert terminal["id"] == 2
        assert terminal["error"]["code"] == E_CANCELLED
    finally:
        if not target.done():
            target.cancel()
        await asyncio.gather(target, return_exceptions=True)


# ---------- 坏帧韧性 ----------

@pytest.mark.asyncio
async def test_bad_frame_does_not_kill_connection(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            await c.send(b"this is not json\n")
            f1 = await asyncio.wait_for(c.recv(), 5)
            # 深嵌套 JSON：json.loads 可能抛 RecursionError（穿透 ProtocolError），
            # 读循环的宽兜底必须接住且不断连
            deep = (
                b'{"v":2,"id":9,"op":"ping","token":"t","payload":'
                + b"[" * 5000 + b"]" * 5000 + b"}\n"
            )
            await c.send(deep)
            f2 = await asyncio.wait_for(c.recv(), 5)
            f3 = await c.request(OP_PING, {}, h.worker.token, 10)
    assert f1["ok"] is False
    assert f2["ok"] is False
    assert f3["ok"] is True  # 连接与 worker 均存活


# ---------- status ----------

@pytest.mark.asyncio
async def test_status_reports_snapshot(tmp_path):
    async with serve_worker(tmp_path, env_hash="ab12cd34") as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_STATUS, {}, h.worker.token, 1)
    assert resp["ok"] is True
    r = resp["result"]
    assert r["config_hash"] == "ab12cd34"
    for key in ("pid", "pkg", "uptime_s", "clients", "cache_entries",
                "stealth_ready", "degradation"):
        assert key in r
    assert r["pool"] is None  # browser_pool 默认关:不暴露池统计


@pytest.mark.asyncio
async def test_status_pool_stats_when_browser_pool_enabled(tmp_path, monkeypatch):
    """browser_pool 开启时 status 的 pool 字段接真实 stats()"""
    from scrapling_fetch_mcp import _scrapling
    from scrapling_fetch_mcp._config import config

    fake_stats = {"sessions": 2, "hits": 5, "misses": 3, "buckets": ["example.com"]}

    class FakePool:
        def stats(self):
            return fake_stats

    monkeypatch.setattr(_scrapling, "get_pool", lambda: FakePool())
    original = config.browser_pool
    config.set_browser_pool(True)
    try:
        async with serve_worker(tmp_path) as h:
            async with Client(h.sock) as c:
                resp = await c.request(OP_STATUS, {}, h.worker.token, 1)
    finally:
        config.set_browser_pool(original)
    assert resp["ok"] is True
    assert resp["result"]["pool"] == fake_stats


# ---------- 空闲退出 / shutdown ----------

@pytest.mark.asyncio
async def test_idle_timeout_exits(tmp_path):
    async with serve_worker(tmp_path, idle_timeout=0.2) as h:
        async with Client(h.sock):
            pass  # 建连即断：引用计数归零后启动空闲倒计时
        await asyncio.wait_for(h.task, 0.5)  # 断连后 0.5s 内 serve() 返回
    assert not h.sock.exists()
    assert not h.sock.with_suffix(".lock").exists()


@pytest.mark.asyncio
async def test_new_connection_cancels_idle_wait(tmp_path):
    async with serve_worker(tmp_path, idle_timeout=0.3) as h:
        # 第一次连接断开后，在空闲超时窗内重连：worker 不得退出
        async with Client(h.sock):
            pass
        await asyncio.sleep(0.15)  # 空闲等待已开始但未超时
        async with Client(h.sock) as c:
            resp = await asyncio.wait_for(
                c.request(OP_PING, {}, h.worker.token, 1), 5
            )
            assert resp["ok"] is True
        assert not h.task.done()  # 空闲等待被打断，worker 仍在服务
        await asyncio.wait_for(h.task, 2.0)  # 随后按新倒计时正常空闲退出
    assert not h.sock.exists()


@pytest.mark.asyncio
async def test_shutdown_op_stops_worker(tmp_path):
    async with serve_worker(tmp_path) as h:
        async with Client(h.sock) as c:
            resp = await c.request(OP_SHUTDOWN, {}, h.worker.token, 7)
            assert resp["ok"] is True
            await asyncio.wait_for(h.task, 2.0)  # 响应后 serve() 优雅返回
    assert not h.sock.exists()
    assert not h.sock.with_suffix(".lock").exists()


@pytest.mark.asyncio
async def test_cleanup_closes_pool_when_constructed(tmp_path, monkeypatch):
    """spec §6.2:daemon 退出销毁全部池化会话;池未构造(默认关)则零触碰"""
    from scrapling_fetch_mcp import _scrapling

    class FakePool:
        def __init__(self):
            self.closed = 0

        async def close_all(self):
            self.closed += 1

    # 池未构造:cleanup 不触碰
    monkeypatch.setattr(_scrapling, "_pool", None)
    w = worker_mod.DaemonWorker(tmp_path / "w.sock", 30.0, config_hash="ab")
    await w._cleanup()
    # 池已构造:cleanup 经 close_all 收口
    fake = FakePool()
    monkeypatch.setattr(_scrapling, "_pool", fake)
    w = worker_mod.DaemonWorker(tmp_path / "w2.sock", 30.0, config_hash="ab")
    await w._cleanup()
    assert fake.closed == 1


@pytest.mark.asyncio
async def test_cleanup_pool_close_hang_falls_back_to_kill(tmp_path, monkeypatch):
    """I2 回归：close_all 挂死 → 限时转 _kill_spawned_browsers，lock/sock 照常清理。

    无时限的 await pool.close_all() 会被 Firefox close 挂死拖成 daemon 永不
    退出（lock/sock 残留）。宽限耗尽后 SIGKILL 浏览器后代再继续退出路径。
    """
    from scrapling_fetch_mcp import _scrapling

    class HangPool:
        async def close_all(self):
            await asyncio.Event().wait()  # 永不完成（模拟 Firefox close 挂死）

    killed: list[set] = []

    def fake_kill(before):
        killed.append(before)
        return 0

    monkeypatch.setattr(_scrapling, "_kill_spawned_browsers", fake_kill)
    monkeypatch.setattr(_scrapling, "_pool", HangPool())
    monkeypatch.setattr(worker_mod, "_CLOSE_ALL_GRACE", 0.1)
    sock = tmp_path / "w3.sock"
    sock.write_bytes(b"")
    sock.with_suffix(".lock").write_text("{}")
    w = worker_mod.DaemonWorker(sock, 30.0, config_hash="ab")
    # 若无超时保护,本 wait_for 会超时炸出（测试即失败）
    await asyncio.wait_for(w._cleanup(), 5.0)
    assert killed == [set()]  # 退出路径击杀现存全部浏览器后代
    assert not sock.exists()
    assert not sock.with_suffix(".lock").exists()


# ---------- __main__ 入口 ----------

def test_main_rejects_windows(monkeypatch):
    from scrapling_fetch_mcp.daemon import __main__ as daemon_main

    monkeypatch.setattr(daemon_main.sys, "platform", "win32")
    with pytest.raises(RuntimeError):
        daemon_main.main()


def test_main_binds_self_computed_hash_ignoring_env_key(monkeypatch, tmp_path):
    """M3 回归：真 worker 不读 SCRAPLING_DAEMON_CONFIG_HASH（fake_worker 专用键）。

    daemon/__main__ 曾读该键做绑定 hash：用户 env 残留时按残留值绑定 socket，
    与前端自算 hash 永久不符 → is_alive 身份不符 → 清理重拉无休止循环。
    身份唯一来源必须是本进程 env 自算（config_env.normalize_daemon_values）。
    """
    from scrapling_fetch_mcp._config import Config
    from scrapling_fetch_mcp.daemon import __main__ as daemon_main
    from scrapling_fetch_mcp.daemon.config_env import (
        DAEMON_OWNED_ENV_KEYS,
        resolve_daemon_env,
    )
    from scrapling_fetch_mcp.daemon.lifecycle import socket_name

    # env 整备：daemon-owned 键清零（hash 确定）+ 注入残留专用键 + 目录钉 tmp
    saved_env = {k: os.environ.get(k) for k in DAEMON_OWNED_ENV_KEYS}
    for k in DAEMON_OWNED_ENV_KEYS:
        os.environ.pop(k, None)
    monkeypatch.setenv("SCRAPLING_DAEMON_CONFIG_HASH", "deadbeef")
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))
    Config()._daemon_dir = None  # 未初始化态：身份全靠 main 内的 init+自算

    captured: dict = {}

    class FakeDaemon:
        def __init__(self, sock, idle_timeout, *, config_hash=None,
                     cancel_grace=worker_mod.CANCEL_GRACE):
            captured["sock"] = Path(sock)
            captured["config_hash"] = config_hash

        async def serve(self):
            return None

    async def fake_serve(daemon):
        await daemon.serve()

    monkeypatch.setattr(worker_mod, "DaemonWorker", FakeDaemon)
    monkeypatch.setattr(daemon_main, "_serve", fake_serve)  # 避开信号处理器注册
    monkeypatch.setattr(daemon_main.logging, "basicConfig", lambda **kw: None)
    monkeypatch.setattr(
        "scrapling_fetch_mcp._browser_check.ensure_browserforge_data", lambda: None
    )
    monkeypatch.setattr("scrapling_fetch_mcp._browser_check.ensure_camoufox", lambda: None)
    monkeypatch.setattr(
        "scrapling_fetch_mcp._scrapling.init_guard", lambda *a, **kw: None
    )
    try:
        assert daemon_main.main() == 0
    finally:
        for k, v in saved_env.items():  # monkeypatch 管不到上面的直接 pop
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        cfg = Config()
        cfg._daemon_dir = None  # 清掉 main 内 init 写进单例的 tmp 路径
        cfg._daemon_idle_timeout = 600.0

    _spawn_env, self_hash = resolve_daemon_env()
    assert captured["config_hash"] == self_hash
    assert self_hash != "deadbeef"  # 残留专用键未被消费
    assert captured["sock"].name == f"{socket_name(self_hash)}.sock"
