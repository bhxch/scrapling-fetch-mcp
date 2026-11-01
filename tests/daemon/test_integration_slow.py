"""慢速端到端集成测试（Task 13，``-m slow`` 显式选择）。

与单元测试的根本区别：这里跑**真链路**——``ensure_daemon`` spawn 真 daemon
子进程（``python -m scrapling_fetch_mcp.daemon``）、真 unix socket、真
scrapling 抓取（example.com 走 basic/curl，取消用例走 stealth/camoufox）。
每个用例冷启动一个 daemon（秒级到十秒级）+ 真实网络/浏览器（分钟级），
故全部标记 ``slow``；``uv run pytest -q`` 经 addopts ``-m 'not slow'`` 默认
不跑本文件。

隔离约定（沿用 tests/daemon/test_lifecycle.py 的惯用法）：

- ``SCRAPLING_DAEMON_DIR`` 钉到 tmp_path + 配置单例重置（前后各一次防泄漏）；
- ``SCRAPLING_DAEMON_IDLE_TIMEOUT=30``：即使收尸失败，daemon 也会快速自灭；
- teardown 统一 SIGTERM 收割目录下全部 daemon（真 daemon 对 SIGTERM 优雅
  退出并清 lock/sock，退出码 0——daemon/__main__.py 契约）；
- 前端连接单例 ``_client._client_instance`` 每用例归零，避免跨用例复用指向
  已删 socket 的连接。

浏览器进程断言一律用「前后快照差集」：CI 机器可能有与本项目无关的
firefox，绝不假设环境里没有现存浏览器进程（Review Focus 4）。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

import scrapling_fetch_mcp._client as client_mod
from scrapling_fetch_mcp._browser_check import resolve_stealth_degradation
from scrapling_fetch_mcp._client import BackendClient, get_client, make_adapter
from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.lifecycle import (
    ensure_daemon,
    is_alive,
    ping,
    read_lock,
    socket_name,
)
from scrapling_fetch_mcp.daemon.paths import pkg_version

# ensure_daemon 就绪期限：真 daemon 冷启动要 import scrapling 全链，比假
# worker 宽得多（client 侧 _ENSURE_TIMEOUT=60 略紧，这里 spawn 路径直接调用
# 的场合放宽）。
_SPAWN_TIMEOUT = 120.0
# 取消后观察浏览器残留的宽限：worker 的 cancel 宽限 5s + 浏览器自行退出余量
# （brief 定值 6s；killpg 核弹路径下浏览器即时死亡，软取消路径多等一拍）。
_BROWSER_GRACE = 6.0
# 等待 camoufox 进程出现的上限（冷启动在慢机器上可达数十秒）。
_BROWSER_LAUNCH_TIMEOUT = 90.0


# ---------- 夹具与工具 ----------

def _reset_daemon_config() -> None:
    """重置配置单例的 daemon 字段后从 env 重新加载（沿用 test_lifecycle 手法）。"""
    from scrapling_fetch_mcp._config import Config, init_config_from_env

    cfg = Config()  # Config.__new__ 返回单例,改它即改全局
    cfg._daemon_dir = None
    cfg._daemon_idle_timeout = 600.0
    init_config_from_env()


def _reap_daemons(d: Path, timeout: float = 10.0) -> None:
    """SIGTERM 收割目录下全部 daemon，防止 30s 空闲窗内跨用例积压进程。"""
    for lock in d.glob("daemon-*.lock"):
        if lock.name.endswith(".spawn.lock"):
            continue  # 仲裁锁 owner 是测试进程自身,误读会 SIGTERM 自杀
        try:
            pid = json.loads(lock.read_text(encoding="utf-8"))["pid"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            # 退出的子进程若未被收尸是僵尸态,kill(pid,0) 仍成功;以 waitpid 为准
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    break
            except ChildProcessError:
                break  # 非本进程子进程:SIGTERM 已发,由其自行退出
            time.sleep(0.05)


@pytest.fixture
def daemon_env(monkeypatch, tmp_path):
    """真 daemon 集成的隔离夹具：目录钉 tmp_path + 快速空闲退出 + 用后收割。

    teardown 顺序承重：先收割 daemon（此刻它们仍是可 waitpid 的本进程子
    进程），再撤 env、重置单例——reset 会执行 init_config_from_env，env 未
    撤会把 tmp 路径重新写进单例泄漏给后续测试。
    """
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))
    monkeypatch.setenv("SCRAPLING_DAEMON_IDLE_TIMEOUT", "30")
    monkeypatch.setattr(client_mod, "_client_instance", None)
    _reset_daemon_config()
    yield tmp_path
    _reap_daemons(tmp_path)
    monkeypatch.delenv("SCRAPLING_DAEMON_DIR", raising=False)
    monkeypatch.delenv("SCRAPLING_DAEMON_IDLE_TIMEOUT", raising=False)
    monkeypatch.setattr(client_mod, "_client_instance", None)
    _reset_daemon_config()


_BROWSER_PATTERNS = ("camoufox", "firefox")


def _browser_pids() -> set[int]:
    """全部 camoufox/firefox 进程 pid（``pgrep -f`` 按 cmdline 匹配）。"""
    pids: set[int] = set()
    for pattern in _BROWSER_PATTERNS:
        proc = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        for token in proc.stdout.split():
            with contextlib.suppress(ValueError):
                pids.add(int(token))
    return pids


def _make_slow_site(delay: float) -> tuple[ThreadingHTTPServer, str]:
    """起本地慢响应站点：每个请求 sleep ``delay`` 再回静态页（每连接独立线程）。

    ``daemon_threads=True``：客户端（浏览器）被取消杀死后回写必失败，还挂在
    sleep 上的连接线程不阻塞测试进程退出。
    """
    class _SlowHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(delay)
            body = (
                b"<html><head><title>slow page</title></head>"
                b"<body><h1>slow page body</h1></body></html>"
            )
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionError):
                pass  # 对端(浏览器)已死:线程收场即可

        def log_message(self, format, *args):  # noqa: A002  签名随基类
            pass  # 静音请求日志

    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowHandler)
    server.daemon_threads = True
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{port}/"


# ---------- 用例 ----------

@pytest.mark.slow
@pytest.mark.asyncio
async def test_end_to_end_basic_fetch_via_daemon(daemon_env):
    """adapter → 真 daemon → example.com 全链路：METADATA + 正文 + lock 留痕。"""
    d = daemon_env
    _spawn_env, config_hash = resolve_daemon_env()
    adapter = make_adapter("fetch_page")
    result = await adapter(
        url="https://example.com", mode="basic", format="markdown",
        max_length=2000, start_index=0,
    )
    assert "METADATA:" in result
    assert "Example Domain" in result  # 正文,非仅 METADATA JSON
    # 真 daemon 留下的 lock：身份吻合、pid 非本进程（真子进程而非进程内假件）
    lock_path = d / f"{socket_name(config_hash)}.lock"
    assert lock_path.exists()
    info = json.loads(lock_path.read_text(encoding="utf-8"))
    assert info["config_hash"] == config_hash
    assert info["pkg"] == pkg_version()
    assert info["pid"] != os.getpid()
    assert is_alive(lock_path.with_suffix(".sock"), pkg_version(), config_hash)
    await get_client().aclose()


@pytest.mark.slow
@pytest.mark.asyncio
async def test_second_frontend_reuses_daemon(daemon_env):
    """两个独立 BackendClient（≈两个前端进程）落到同一 socket、同一 daemon。"""
    d = daemon_env
    _spawn_env, config_hash = resolve_daemon_env()
    expected_sock = d / f"{socket_name(config_hash)}.sock"
    c1, c2 = BackendClient(), BackendClient()
    r1 = await c1.call("ping", {})
    r2 = await c2.call("ping", {})
    assert c1._sock == expected_sock and c2._sock == expected_sock  # noqa: SLF001
    assert isinstance(r1["pid"], int) and r1["pid"] == r2["pid"] != os.getpid()
    assert r1["pkg"] == pkg_version() == r2["pkg"]
    assert r1["config_hash"] == config_hash == r2["config_hash"]
    assert is_alive(expected_sock, pkg_version(), config_hash)
    await asyncio.gather(c1.aclose(), c2.aclose())


@pytest.mark.slow
@pytest.mark.asyncio
async def test_client_cancel_leaves_no_firefox(daemon_env):
    """stealth 抓慢站 + 客户端侧取消 → 宽限后无 camoufox/firefox 残留。"""
    # 浏览器未就绪时优雅跳过（同型判定复用 daemon 侧降级逻辑,本进程自检）
    effective, degradation = resolve_stealth_degradation("stealth")
    if effective != "stealth":
        pytest.skip(f"camoufox browser not installed: {degradation}")

    server, url = _make_slow_site(delay=30.0)
    try:
        before = _browser_pids()
        adapter = make_adapter("fetch_page")
        task = asyncio.create_task(adapter(
            url=url, mode="stealth", format="markdown",
            max_length=2000, start_index=0,
        ))
        # 等 camoufox 真正起来（快照差集）：取消太早 = 浏览器未拉起,测不到泄漏
        launched: set[int] = set()
        deadline = time.monotonic() + _BROWSER_LAUNCH_TIMEOUT
        while time.monotonic() < deadline:
            launched = _browser_pids() - before
            if launched or task.done():
                break
            await asyncio.sleep(0.5)
        if not launched:
            outcome = await asyncio.gather(task, return_exceptions=True)
            raise AssertionError(f"浏览器未在期限内启动, fetch 先行收场: {outcome!r}")
        assert not task.done(), f"取消前 fetch 已意外收场: {task!r}"
        # 客户端侧取消：adapter 发 cancel 帧 → daemon 取消 fetch → 浏览器收尾
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(_BROWSER_GRACE)
        leftovers = _browser_pids() - before
        assert not leftovers, f"客户端取消后仍有 camoufox/firefox 残留: {leftovers}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.slow
def test_uv_rolling_update_coexistence(daemon_env, monkeypatch):
    """不同 config_hash 的两个前端并存：各自 socket、各自 daemon、互不扰动。"""
    d = daemon_env
    # 前端一：MIN_MODE=basic
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "basic")
    _reset_daemon_config()
    env1, h1 = resolve_daemon_env()
    sock1 = ensure_daemon(env1, h1, timeout=_SPAWN_TIMEOUT)
    pid1 = read_lock(sock1)["pid"]
    assert sock1 == d / f"{socket_name(h1)}.sock"
    assert is_alive(sock1, pkg_version(), h1)

    # 前端二：MIN_MODE=stealth —— 配置漂移（uv 滚动升级改默认模式同理）换名隔离
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "stealth")
    _reset_daemon_config()
    env2, h2 = resolve_daemon_env()
    assert h2 != h1
    sock2 = ensure_daemon(env2, h2, timeout=_SPAWN_TIMEOUT)
    pid2 = read_lock(sock2)["pid"]

    assert sock2 == d / f"{socket_name(h2)}.sock" and sock2 != sock1
    assert pid1 != pid2
    # 第二次 spawn 后：第一个 daemon 原封不动（Review Focus 5），两者同时存活
    assert read_lock(sock1)["pid"] == pid1
    assert is_alive(sock1, pkg_version(), h1)
    assert is_alive(sock2, pkg_version(), h2)
    # 各自应答身份自洽：ping 回报的 hash 与 socket 名内嵌 hash 一致
    r1 = ping(sock1, read_lock(sock1)["token"])
    r2 = ping(sock2, read_lock(sock2)["token"])
    assert r1 is not None and r1["result"]["config_hash"] == h1
    assert r2 is not None and r2["result"]["config_hash"] == h2
