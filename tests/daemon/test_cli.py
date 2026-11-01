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
    sock.with_suffix(".lock").write_text(
        json.dumps(
            {
                "pid": 999999999,
                "token": "tok",
                "pkg": "0.2.0",
                "config_hash": "deadbeef",
                "sock": str(sock),
            }
        ),
        encoding="utf-8",
    )
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


# ---------- run_server argv 分流 ----------

def test_run_server_dispatches_daemon_argv(daemon_env, monkeypatch, capsys):
    """`daemon` 占位在 MCP 参数解析前拦截；退出码即进程退出码。"""
    monkeypatch.setattr(sys, "argv", ["scrapling-fetch-mcp", "daemon", "status"])
    with pytest.raises(SystemExit) as ei:
        mcp_mod.run_server()
    assert ei.value.code == 0
    assert "无存活 daemon" in capsys.readouterr().out
