"""假 daemon worker（Task 6 骨架，供 test_lifecycle 的 spawn 流程使用）。

``python -m tests.daemon.fake_worker``（经 lifecycle._DAEMON_MODULE 注入，
Task 7 充实为可复用假实现）。模拟 Task 7 真 worker 的最小行为子集：

- 读 ``SCRAPLING_DAEMON_DIR``（必需）；期望 hash 优先取 spawn 侧注入的
  ``SCRAPLING_DAEMON_CONFIG_HASH``，缺省按 ``resolve_daemon_env`` 自算
  （与真 worker 启动序列一致）；``SCRAPLING_DAEMON_IDLE_TIMEOUT`` 接受
  不实现（本骨架无空闲退出，仅为 env 面与真 worker 对齐）。
- 用与 lifecycle 相同的 ``socket_name`` 公式命名 socket（直接 import 同一
  实现，杜绝两处公式漂移）。
- bind 后写 lock JSON ``{"pid","token","pkg","config_hash","sock"}``，
  与 Task 7 真 worker 写的 lock 同构——is_alive 据此取 token 发 ping。
- 只路由 ``ping``，应答 result 自报
  ``{"status","pid","pkg","config_hash","uptime_s","clients"}``。
- SIGTERM/SIGINT：关 server、删 sock+lock，退出码 0（fixture 据此收尸）。
- ``SCRAPLING_FAKE_WORKER_FAIL=1``：模拟启动即崩（验证 ensure_daemon 的
  提前退出检测与日志落盘），退出码 3。
- 往 ``<name>.journal`` 追加本进程 pid：并发 spawn 仲裁测试据此断言
  只拉起过一个实例（测试专用工件，真 worker 无此文件）。

Task 7 已落地真 worker（``scrapling_fetch_mcp.daemon.worker``，由
``tests/daemon/test_worker.py`` 直驱测试）。本假实现不再扩展 op 面：它只
服务 spawn 仲裁/生命周期测试，保持零重依赖（不起浏览器、不 import
worker），与真 worker 的 lock/ping 契约同构即可。
"""

from __future__ import annotations

import json
import os
import secrets
import signal
import socket
import sys
import time
from pathlib import Path

from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.lifecycle import socket_name
from scrapling_fetch_mcp.daemon.paths import pkg_version
from scrapling_fetch_mcp.daemon.protocol import (
    E_INTERNAL,
    E_UNKNOWN_OP,
    OP_PING,
    ProtocolError,
    make_error,
    make_response,
    parse_frame,
)

_ACCEPT_TIMEOUT = 0.2  # accept 轮询间隔:信号处理器置位 stopping 后最迟此时退出
_STARTED = time.monotonic()


def resolve_config_hash() -> str:
    """期望 config_hash：spawn 侧注入优先，缺省按 daemon-owned env 自算。"""
    injected = os.environ.get("SCRAPLING_DAEMON_CONFIG_HASH", "")
    if injected:
        return injected
    return resolve_daemon_env()[1]


def ping_result(config_hash: str) -> dict:
    """ping 应答 result（键集与 Task 7 真 worker 的 ping 应答一致）。"""
    return {
        "status": "ready",
        "pid": os.getpid(),
        "pkg": pkg_version(),
        "config_hash": config_hash,
        "uptime_s": round(time.monotonic() - _STARTED, 3),
        "clients": 0,
    }


def handle_frame(line: bytes, config_hash: str) -> bytes:
    """单帧请求 → 单帧响应字节（本骨架只认 ping；Task 7 在此扩 op 表）。"""
    frame = parse_frame(line)
    req_id = frame.get("id", 0)
    if frame.get("op") != OP_PING:
        return make_error(req_id, E_UNKNOWN_OP, f"fake_worker 只支持 ping, 得到 {frame.get('op')!r}")
    return make_response(req_id, ping_result(config_hash))


def write_lock(sock_path: Path, config_hash: str) -> str:
    """写 lock JSON（键集与真 worker 相同），返回 token。"""
    token = secrets.token_hex(16)
    lock = {
        "pid": os.getpid(),
        "token": token,
        "pkg": pkg_version(),
        "config_hash": config_hash,
        "sock": str(sock_path),
    }
    sock_path.with_suffix(".lock").write_text(json.dumps(lock), encoding="utf-8")
    return token


def _serve_connection(conn: socket.socket, config_hash: str) -> None:
    """单连接读循环：NDJSON 逐帧应答，直至对端关闭或超时。"""
    with conn:
        conn.settimeout(5.0)
        buf = b""
        while True:
            try:
                chunk = conn.recv(65536)
            except (socket.timeout, OSError):
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    resp = handle_frame(line, config_hash)
                except ProtocolError as exc:
                    resp = make_error(0, "bad_frame", str(exc))
                except Exception as exc:  # 兜底：不让单连接异常击穿服务
                    resp = make_error(0, E_INTERNAL, str(exc))
                conn.sendall(resp)


def serve(sock_path: Path, config_hash: str) -> int:
    """阻塞服务：bind → 写 lock → accept 循环；SIGTERM/SIGINT 清理后退出 0。"""
    sock_path.parent.mkdir(parents=True, exist_ok=True)
    for path in (sock_path, sock_path.with_suffix(".lock")):
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    stopping = False

    def _stop(signum, frame):  # noqa: ARG001  (信号处理器签名)
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(8)
    server.settimeout(_ACCEPT_TIMEOUT)
    write_lock(sock_path, config_hash)
    # 实例计数：并发 spawn 仲裁测试据此断言只有抢到 spawn.lock 的一方拉起进程
    with open(sock_path.with_suffix(".journal"), "a", encoding="utf-8") as fh:
        fh.write(f"{os.getpid()}\n")
    try:
        while not stopping:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                continue  # 瞬时错误（如 ECONNABORTED）；server 未被关闭,不会风暴
            _serve_connection(conn, config_hash)
    finally:
        server.close()
        for path in (sock_path, sock_path.with_suffix(".lock")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    return 0


def main() -> int:
    if os.environ.get("SCRAPLING_FAKE_WORKER_FAIL") == "1":
        print("fake_worker: 模拟启动失败", file=sys.stderr)
        return 3
    daemon_root = os.environ.get("SCRAPLING_DAEMON_DIR", "")
    if not daemon_root:
        print("fake_worker 需要 SCRAPLING_DAEMON_DIR", file=sys.stderr)
        return 2
    config_hash = resolve_config_hash()
    sock_path = Path(daemon_root) / f"{socket_name(config_hash)}.sock"
    return serve(sock_path, config_hash)


if __name__ == "__main__":
    raise SystemExit(main())
