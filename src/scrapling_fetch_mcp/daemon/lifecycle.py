"""daemon 生命周期：按 (版本, 配置摘要) 命名隔离的自动拉起/复用/仲裁。

前端拿到 ``(spawn_env, config_hash8)``（Task 4）后，经 :func:`ensure_daemon`
保证同配置的 daemon 恰好一个、且身份吻合：

1. 拼 socket 名 ``daemon-<pkgver>-<hash>``（:func:`socket_name`，升级或改
   配置即换名隔离，互不打扰）。
2. ``<name>.lock`` 存在且 :func:`is_alive`（lock pid 存活 + ping 应答自报
   的 pkg/hash 与期望一致）→ 直接复用。
3. 否则 :func:`_cleanup_stale` 清理同名陈旧 sock/lock，``<name>.spawn.lock``
   以 ``O_CREAT|O_EXCL`` 仲裁并发 spawn：抢到者 ``Popen`` 拉起
   ``python -m <_DAEMON_MODULE>``（``start_new_session=True`` 使 daemon
   成为自身进程组长——Task 7 的强杀兜底依赖此点；stdout/stderr 重定向到
   ``<name>.log``），未抢到者只轮询等待。
4. 双方都按 0.2s 间隔轮询 ping+is_alive 直至就绪或超时。

不做打断式 kill 替换：应答身份不符只视为陈旧 socket，清理后按需重拉
（旧 daemon 随其空闲退出自然消亡）。

Import 边界约束：仅 stdlib + ``daemon.paths``/``daemon.protocol``（均为
前端白名单轻模块）。lock 文件 JSON ``{"pid","token","pkg","config_hash",
"sock"}`` 由 daemon 进程自己写（Task 7；本任务的假 worker 同构实现）。
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from scrapling_fetch_mcp.daemon.paths import daemon_dir, pkg_version
from scrapling_fetch_mcp.daemon.protocol import (
    OP_PING,
    ProtocolError,
    make_request,
    parse_frame,
)

__all__ = [
    "daemon_sockets",
    "ensure_daemon",
    "is_alive",
    "ping",
    "socket_name",
]

# spawn 的目标模块。模块级常量便于测试注入假 worker（monkeypatch 本名字）。
_DAEMON_MODULE = "scrapling_fetch_mcp.daemon"

_SPIN_INTERVAL = 0.2  # 就绪轮询间隔
_CONNECT_TIMEOUT = 2.0  # is_alive 的 ping connect 超时
_RESPONSE_TIMEOUT = 5.0  # is_alive 的 ping 响应超时


# ---------- 命名 ----------

def socket_name(config_hash: str) -> str:
    """socket 基名（不含后缀，调用方自行加 ``.sock``/``.lock``/``.log``）。"""
    return f"daemon-{pkg_version()}-{config_hash}"


def daemon_sockets() -> list[Path]:
    """daemon 目录下全部 ``daemon-*.sock``（管理 CLI 清点用），按名排序。"""
    return sorted(daemon_dir().glob("daemon-*.sock"))


# ---------- ping ----------

def _transact(sock: Path, payload: bytes, connect_timeout: float, response_timeout: float) -> dict | None:
    """连接、发一帧、收一帧响应；任何失败（连接/超时/非成功帧/坏帧）返回 None。"""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(connect_timeout)
            s.connect(str(sock))
            s.settimeout(response_timeout)
            s.sendall(payload)
            buf = bytearray()
            while b"\n" not in buf:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf.extend(chunk)
    except OSError:
        return None
    if b"\n" not in buf:
        return None
    try:
        frame = parse_frame(bytes(buf).split(b"\n", 1)[0])
    except ProtocolError:
        return None
    if frame.get("ok") is not True:
        return None
    return frame


def ping(sock: Path, token: str, timeout: float = 5.0) -> dict | None:
    """向 daemon socket 发 ping 并返回响应帧；失败返回 None（管理 CLI/测试用）。"""
    return _transact(sock, make_request(OP_PING, {}, token, 0, pkg_version()), timeout, timeout)


# ---------- 存活判定 ----------

def _read_lock(sock: Path) -> dict | None:
    """读 sock 同名 ``.lock``；缺失/坏 JSON/非 object 一律 None。"""
    try:
        info = json.loads(sock.with_suffix(".lock").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return info if isinstance(info, dict) else None


def _pid_alive(pid: object) -> bool:
    """``kill(pid, 0)`` 探活：非正整数/不存在为假，无权限视为活着。"""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_alive(sock: Path, expect_pkg: str, expect_hash: str) -> bool:
    """sock 是否指向一个身份吻合的活 daemon。

    判据（任一不满足即 False）：lock 可读且 pid 存活；ping 在 connect 2s /
    响应 5s 内成功；应答 result 自报的 ``pkg``/``config_hash`` 与期望一致
    （不符说明 socket 是旧版本/旧配置的陈旧残留）。
    """
    info = _read_lock(sock)
    if info is None or not _pid_alive(info.get("pid")):
        return False
    resp = _transact(sock, make_request(OP_PING, {}, str(info.get("token") or ""), 0, pkg_version()),
                     _CONNECT_TIMEOUT, _RESPONSE_TIMEOUT)
    if resp is None:
        return False
    result = resp.get("result")
    if not isinstance(result, dict):
        return False
    return result.get("pkg") == expect_pkg and result.get("config_hash") == expect_hash


# ---------- 拉起与仲裁 ----------

def _cleanup_stale(d: Path, name: str) -> None:
    """清理同名陈旧 sock/lock（仅在判定 is_alive 为假后调用）。

    绝不碰 ``<name>.spawn.lock``——那是并发 spawn 仲裁锁，删它会破坏互斥；
    仲裁锁由抢锁方在 finally 中保证释放。
    """
    for suffix in (".sock", ".lock"):
        try:
            (d / f"{name}{suffix}").unlink()
        except OSError:
            pass  # 不存在/正被并发清理等;清理尽力而为,后续 bind 失败有日志可查


def _wait_ready(sock: Path, expect_pkg: str, config_hash: str, deadline: float,
                proc: subprocess.Popen | None) -> Path:
    """轮询 ping+is_alive 直至就绪；抢到的 spawn 进程先行退出则快速失败。"""
    while True:
        if is_alive(sock, expect_pkg, config_hash):
            return sock
        if proc is not None and proc.poll() is not None:
            raise TimeoutError(
                f"daemon 进程启动即退出 (exit={proc.returncode}), 日志: {sock.with_suffix('.log')}"
            )
        if time.monotonic() >= deadline:
            raise TimeoutError(f"daemon 未在期限内就绪: {sock}")
        time.sleep(_SPIN_INTERVAL)


def ensure_daemon(spawn_env: dict[str, str], config_hash: str, timeout: float = 60.0) -> Path:
    """确保同 (版本, 配置摘要) 的 daemon 恰好一个且就绪，返回其 socket 路径。

    ``spawn_env`` 为 Task 4 ``resolve_daemon_env`` 产出的 daemon-owned env，
    与 ``os.environ`` 合并后注入子进程。并发调用以 ``<name>.spawn.lock`` 的
    ``O_CREAT|O_EXCL`` 仲裁：仅抢到者 spawn，其余轮询等待同一结果。
    """
    if sys.platform == "win32":
        raise RuntimeError("daemon 模式依赖 unix socket, 暂不支持 Windows")

    d = daemon_dir()
    name = socket_name(config_hash)
    sock = d / f"{name}.sock"
    expect_pkg = pkg_version()
    deadline = time.monotonic() + timeout

    if is_alive(sock, expect_pkg, config_hash):
        return sock

    _cleanup_stale(d, name)

    spawn_lock = d / f"{name}.spawn.lock"
    winner = False
    try:
        fd = os.open(spawn_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, json.dumps({"pid": os.getpid()}).encode())
        finally:
            os.close(fd)
        winner = True
    except FileExistsError:
        winner = False

    proc: subprocess.Popen | None = None
    if winner:
        # append:同 (版本,hash) 的多次拉起日志累计留痕,便于事后排查
        with open(d / f"{name}.log", "ab") as log:
            proc = subprocess.Popen(
                [sys.executable, "-m", _DAEMON_MODULE],
                env={**os.environ, **spawn_env},
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                cwd="/",
            )
    try:
        return _wait_ready(sock, expect_pkg, config_hash, deadline, proc)
    finally:
        if winner:
            try:
                spawn_lock.unlink()
            except FileNotFoundError:
                pass
