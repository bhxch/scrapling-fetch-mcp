"""daemon 管理 CLI 测试（Task 10）。

进程内 DaemonWorker（Task 7 ``serve_worker`` fixture 同款探活）+
``SCRAPLING_DAEMON_DIR=tmp_path``；CLI 走阻塞 socket（lifecycle.transact），
不能堵事件循环，故经 ``asyncio.to_thread`` 在工作线程里调用。覆盖：
status 表格（存活/DEAD 残留/空目录）、默认 shutdown 只杀当前版本+hash、
``--socket`` 定点、``--all`` 清场、``run_server`` 的 daemon argv 分流。
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from scrapling_fetch_mcp import mcp as mcp_mod
from scrapling_fetch_mcp.daemon import worker as worker_mod
from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.lifecycle import ping, socket_name


def _reset_daemon_config() -> None:
    """重置配置单例的 daemon 字段后从 env 重新加载（沿 test_lifecycle 手法）。"""
    from scrapling_fetch_mcp._config import Config, init_config_from_env

    cfg = Config()  # Config.__new__ 返回单例,改它即改全局
    cfg._daemon_dir = None
    cfg._daemon_idle_timeout = 600.0
    init_config_from_env()


@pytest.fixture
def daemon_env(monkeypatch, tmp_path):
    """daemon 目录钉到 tmp_path：setenv + 单例重置（前后各一次防泄漏）。"""
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))
    _reset_daemon_config()
    yield tmp_path
    monkeypatch.delenv("SCRAPLING_DAEMON_DIR", raising=False)
    _reset_daemon_config()


def current_hash() -> str:
    """测试进程当前的 config_hash——CLI 默认 shutdown 的目标身份。"""
    return resolve_daemon_env()[1]


def _write_lock(sock, *, pid, token="tok", config_hash="deadbeef", pkg="0.2.0") -> None:
    """写同构 lock 文件（daemon 进程自写 {"pid","token","pkg","config_hash","sock"}）。"""
    sock.with_suffix(".lock").write_text(
        json.dumps(
            {
                "pid": pid,
                "token": token,
                "pkg": pkg,
                "config_hash": config_hash,
                "sock": str(sock),
            }
        ),
        encoding="utf-8",
    )


@asynccontextmanager
async def serve_named_worker(d, config_hash, *, idle_timeout=30.0):
    """在 d 下按 socket_name 公式起一个进程内 DaemonWorker。

    与 test_worker.serve_worker 同款：探活连接即连即关，就绪后 yield
    (sock, worker, task)；退出时兜底 cancel。
    """
    sock = d / f"{socket_name(config_hash)}.sock"
    w = worker_mod.DaemonWorker(sock, idle_timeout, config_hash=config_hash)
    task = asyncio.create_task(w.serve())
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


@asynccontextmanager
async def serve_stuck_ok_daemon(sock):
    """假 daemon：对任何请求回成功帧，但 sock 永不消失、绝不退出。

    shutdown 请求也回 ok:true → `_shutdown_socket` 走"已接受但等 sock 消失
    超时"的失败路径（配合把 `_SHUTDOWN_EXIT_WAIT` 调小）。
    """

    async def handle(reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                frame = json.loads(line)
                writer.write(
                    json.dumps(
                        {"v": 2, "id": frame.get("id"), "ok": True, "result": {}}
                    ).encode() + b"\n"
                )
                await writer.drain()
        except (ConnectionError, json.JSONDecodeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    server = await asyncio.start_unix_server(handle, str(sock))
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()


@asynccontextmanager
async def serve_unauthorized_daemon(sock, *, token="real-token"):
    """假 daemon：token 不匹配的请求回 E_UNAUTHORIZED 错误帧（存活但拒绝）。"""

    async def handle(reader, writer):
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                frame = json.loads(line)
                resp: dict = {"v": 2, "id": frame.get("id")}
                if frame.get("token") != token:
                    resp.update(
                        {
                            "ok": False,
                            "error": {"code": "unauthorized", "message": "token 不匹配"},
                        }
                    )
                else:
                    resp.update({"ok": True, "result": {}})
                writer.write(json.dumps(resp).encode() + b"\n")
                await writer.drain()
        except (ConnectionError, json.JSONDecodeError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass

    server = await asyncio.start_unix_server(handle, str(sock))
    try:
        yield server
    finally:
        server.close()
        await server.wait_closed()


# ---------- status ----------

@pytest.mark.asyncio
async def test_status_lists_running_daemon(daemon_env, capsys):
    h = current_hash()
    async with serve_named_worker(daemon_env, h):
        rc = await asyncio.to_thread(mcp_mod._daemon_main, ["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert f"{socket_name(h)}.sock" in out  # 表格含 sock 名
    assert "ready" in out  # 存活标记
    for column in ("PID", "UPTIME", "CLIENTS", "CACHE"):  # 表头齐全
        assert column in out


def test_status_empty_dir_says_none(daemon_env, capsys):
    assert mcp_mod._daemon_main(["status"]) == 0
    assert "无存活 daemon" in capsys.readouterr().out


def test_status_marks_dead_socket_and_hints_all(daemon_env, capsys):
    """连接失败（假 sock 文件）→ DEAD 标记 + `shutdown --all` 清理提示。"""
    sock = daemon_env / "daemon-0.2.0-deadbeef.sock"
    sock.write_text("not a socket")
    _write_lock(sock, pid=999999999, config_hash="deadbeef")
    rc = mcp_mod._daemon_main(["status"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DEAD" in out
    assert "shutdown --all" in out


# ---------- shutdown ----------

@pytest.mark.asyncio
async def test_shutdown_default_stops_current_daemon(daemon_env):
    """默认目标=当前 pkg_version+config_hash：shutdown 后 serve() 返回、lock 消失。"""
    h = current_hash()
    async with serve_named_worker(daemon_env, h) as hnd:
        rc = await asyncio.to_thread(mcp_mod._daemon_main, ["shutdown"])
        assert rc == 0
        await asyncio.wait_for(hnd.task, 2.0)  # worker serve() 优雅返回
    assert not hnd.sock.exists()
    assert not hnd.sock.with_suffix(".lock").exists()


def test_shutdown_empty_dir_exits_1(daemon_env, capsys):
    assert mcp_mod._daemon_main(["shutdown"]) == 1
    assert "未找到" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_shutdown_socket_flag_targets_single_daemon(daemon_env):
    h = current_hash()
    other = "beefcafe"
    async with serve_named_worker(daemon_env, h) as keep, \
            serve_named_worker(daemon_env, other) as kill:
        rc = await asyncio.to_thread(
            mcp_mod._daemon_main, ["shutdown", "--socket", socket_name(other)]
        )
        assert rc == 0
        await asyncio.wait_for(kill.task, 2.0)  # 只杀指定 socket
        assert not kill.sock.exists()
        # 另一个 daemon 不受影响,仍可 ping 通（token 取自其 lock）
        lock = json.loads(keep.sock.with_suffix(".lock").read_text(encoding="utf-8"))
        assert await asyncio.to_thread(ping, keep.sock, lock["token"]) is not None


@pytest.mark.asyncio
async def test_shutdown_all_cleans_residue_and_stops_alive(daemon_env):
    """--all 清场：活 daemon 停止、死残留 sock/lock 一并清理。"""
    residue = daemon_env / "daemon-0.2.0-deadbeef.sock"
    residue.write_text("not a socket")
    h = current_hash()
    async with serve_named_worker(daemon_env, h) as hnd:
        rc = await asyncio.to_thread(mcp_mod._daemon_main, ["shutdown", "--all"])
        assert rc == 0
        await asyncio.wait_for(hnd.task, 2.0)
    assert not hnd.sock.exists()
    assert not residue.exists()


@pytest.mark.asyncio
async def test_shutdown_all_processes_every_socket_stuck_first(daemon_env, monkeypatch, capsys):
    """--all 不短路：首个 daemon 卡死走强杀升级后，其余 socket 仍被逐个处理。

    假 daemon（0.0.0 版本名排序在前）应答 shutdown 成功帧但 sock 永不消失
    → 等待超时升级强杀；排在后面的真 worker 必须仍被正常停止。
    """
    monkeypatch.setattr(mcp_mod, "_SHUTDOWN_EXIT_WAIT", 0.3)
    monkeypatch.setattr(mcp_mod, "_ESCALATION_TERM_WAIT", 0.3)
    stuck = daemon_env / "daemon-0.0.0-aaaa0000.sock"
    _write_lock(stuck, pid=999999999, token="tok", config_hash="aaaa0000")
    h = current_hash()
    async with serve_stuck_ok_daemon(stuck):
        async with serve_named_worker(daemon_env, h) as hnd:
            rc = await asyncio.to_thread(mcp_mod._daemon_main, ["shutdown", "--all"])
            assert rc == 0  # 强杀升级完成清场,不算失败
            await asyncio.wait_for(hnd.task, 2.0)  # 后面的真 daemon 仍被处理
    out = capsys.readouterr()
    assert "升级强杀" in out.out  # 升级过程有输出说明
    assert not stuck.exists() and not stuck.with_suffix(".lock").exists()  # 残留已清
    assert not hnd.sock.exists()


@pytest.mark.asyncio
async def test_shutdown_timeout_escalates_sigterm_then_sigkill(daemon_env, monkeypatch, capsys):
    """等待超时升级序列：SIGTERM → 宽限等待 → 仍活 SIGKILL，pid 取自 lock。"""
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(mcp_mod, "_SHUTDOWN_EXIT_WAIT", 0.2)
    monkeypatch.setattr(mcp_mod, "_ESCALATION_TERM_WAIT", 0.3)
    stuck = daemon_env / "daemon-0.0.0-bbbb0000.sock"
    _write_lock(stuck, pid=424242, token="tok", config_hash="bbbb0000")
    async with serve_stuck_ok_daemon(stuck):
        rc = await asyncio.to_thread(mcp_mod._shutdown_socket, stuck)
    assert rc is True  # 强杀后清场,视为处理成功
    assert killed == [(424242, signal.SIGTERM), (424242, signal.SIGKILL)]  # 顺序+pid 来自 lock
    assert not stuck.exists()
    assert not stuck.with_suffix(".lock").exists()
    assert "升级强杀" in capsys.readouterr().out


@pytest.mark.asyncio
async def test_shutdown_error_frame_keeps_sock_and_lock(daemon_env, monkeypatch, capsys):
    """ok:false 错误帧 = 存活 daemon 明确拒绝：不动 sock/lock，明确报错并计入失败。

    token 竞态场景：CLI 按旧 lock token 发 shutdown，daemon 已换新 token
    回 E_UNAUTHORIZED——此刻 sock/lock 是活 daemon 的身份文件，绝不能删，
    也不可升级强杀；`--all` 聚合下该失败仍使 exit 1，其余 daemon 照常处理。
    """
    killed: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "kill", lambda pid, sig: killed.append((pid, sig)))
    refuser = daemon_env / "daemon-0.0.0-cccc0000.sock"
    _write_lock(refuser, pid=424242, token="stale-token", config_hash="cccc0000")
    h = current_hash()
    async with serve_unauthorized_daemon(refuser, token="real-token"):
        async with serve_named_worker(daemon_env, h) as hnd:
            rc = await asyncio.to_thread(mcp_mod._daemon_main, ["shutdown", "--all"])
            assert rc == 1  # 拒绝计入失败
            await asyncio.wait_for(hnd.task, 2.0)  # 其余 daemon 照常处理
    out = capsys.readouterr()
    assert "unauthorized" in out.err  # 明确报错
    assert refuser.exists() and refuser.with_suffix(".lock").exists()  # 身份文件未删
    assert killed == []  # 存活 daemon 不升级强杀
    assert not hnd.sock.exists()


# ---------- run_server argv 分流 ----------

def test_run_server_dispatches_daemon_argv(daemon_env, monkeypatch, capsys):
    """`daemon` 占位在 MCP 参数解析前拦截；退出码即进程退出码。"""
    monkeypatch.setattr(sys, "argv", ["scrapling-fetch-mcp", "daemon", "status"])
    with pytest.raises(SystemExit) as ei:
        mcp_mod.run_server()
    assert ei.value.code == 0
    assert "无存活 daemon" in capsys.readouterr().out


def test_run_server_daemon_dispatch_honors_daemon_dir_env(monkeypatch, tmp_path, capsys):
    """I1 回归：argv 分流早于主路径初始化，分支内必须先 init_config_from_env。

    不补这一行则 daemon_dir() 读未初始化单例（_daemon_dir=None）→ platformdirs
    默认目录，SCRAPLING_DAEMON_DIR 被无视，status/shutdown 看错目录。
    """
    from scrapling_fetch_mcp._config import Config

    Config()._daemon_dir = None  # 模拟未初始化单例,后续全靠分流内的 init 生效
    sock = tmp_path / "daemon-9.9.9-deadbeef.sock"
    sock.write_text("not a socket")  # 假 sock → status 表内 DEAD 行仍可见
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["scrapling-fetch-mcp", "daemon", "status"])
    try:
        with pytest.raises(SystemExit) as ei:
            mcp_mod.run_server()
        out = capsys.readouterr().out
    finally:
        monkeypatch.delenv("SCRAPLING_DAEMON_DIR", raising=False)
        _reset_daemon_config()  # 清掉分流内 init 写进单例的 tmp 路径,防泄漏
    assert ei.value.code == 0
    assert "daemon-9.9.9-deadbeef.sock" in out  # 看到的是 env 指定目录, 非 platformdirs 默认
