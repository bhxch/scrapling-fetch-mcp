"""daemon 生命周期：按 (版本, 配置摘要) 命名隔离的自动拉起/复用/仲裁。

前端拿到 ``(spawn_env, config_hash8)``（Task 4）后，经 :func:`ensure_daemon`
保证同配置的 daemon 恰好一个、且身份吻合：

1. 拼 socket 名 ``daemon-<pkgver>-<hash>``（:func:`socket_name`，升级或改
   配置即换名隔离，互不打扰）。
2. ``<name>.lock`` 存在且 :func:`is_alive`（lock pid 存活 + ping 应答自报
   的 pkg/hash 与期望一致）→ 直接复用。
3. ``<name>.spawn.lock`` 以 ``O_CREAT|O_EXCL`` **先仲裁**：仅持锁者有权
   spawn 与清理，其余调用方沦为输家只轮询。输家发现 owner 已死（前端持锁
   途中被杀、或启动途中抛错）→ unlink 后重试抢锁一次，自动重拉能力自愈，
   不被陈旧仲裁锁永久卡死。
4. 持锁者**复查** :func:`is_alive`（快速判负与抢到锁之间，先到者可能已
   完成 spawn）→ 活着直接释放锁复用；否则 :func:`_cleanup_stale` 清理同名
   陈旧 sock/lock 后 ``Popen`` 拉起 ``python -m <_DAEMON_MODULE>``
   （``start_new_session=True`` 使 daemon 成为自身进程组长——Task 7 的
   强杀兜底依赖此点；stdout/stderr 重定向到 ``<name>.log``）。
5. 双方按 0.2s 间隔轮询 ping+is_alive 直至就绪或超时；持锁跨度由 finally
   保证释放。

不做打断式 kill 替换：应答身份不符只视为陈旧 socket，清理后按需重拉
（旧 daemon 随其空闲退出自然消亡）。

Import 边界约束：仅 stdlib + ``daemon.paths``/``daemon.protocol``（均为
前端白名单轻模块）。lock 文件 JSON ``{"pid","token","pkg","config_hash",
"sock"}`` 由 daemon 进程自己写（Task 7；本任务的假 worker 同构实现）。
"""

from __future__ import annotations

import json
import logging
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
    "read_lock",
    "socket_name",
    "transact",
]

logger = logging.getLogger("scrapling_fetch_mcp.daemon.lifecycle")

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


# ---------- ping / 管理面请求 ----------

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


def transact(sock: Path, op: str, token: str, *, payload: dict | None = None,
             timeout: float = 5.0) -> dict | None:
    """向 daemon 发一帧指定 op 的请求并等响应（管理 CLI 的 status/shutdown 用）。

    token 取自目标 daemon 自己的 lock 文件，与普通请求同一鉴权；连接失败/
    超时/非成功帧一律返回 None（活 daemon 对 ping/status/shutdown 均内联
    即时应答，5s 无响应即可判定已死）。
    """
    return _transact(sock, make_request(op, payload or {}, token, 0, pkg_version()),
                     timeout, timeout)


def ping(sock: Path, token: str, timeout: float = 5.0) -> dict | None:
    """向 daemon socket 发 ping 并返回响应帧；失败返回 None（管理 CLI/测试用）。"""
    return transact(sock, OP_PING, token, timeout=timeout)


# ---------- 存活判定 ----------

def read_lock(sock: Path) -> dict | None:
    """读 sock 同名 ``.lock``；缺失/坏 JSON/非 object 一律 None（管理 CLI 用）。"""
    try:
        info = json.loads(sock.with_suffix(".lock").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return info if isinstance(info, dict) else None


def _parse_stat(stat_text: str) -> str | None:
    """从 ``/proc/<pid>/stat`` 内容取状态字段；畸形内容返回 None。

    comm 字段（第二字段）可含空格与括号，从最后一个 ``)`` 之后切字段：
    其后首个字段即状态（``R``/``S``/``Z``/...，内核 proc(5) 约定）。
    """
    head = stat_text.rfind(")")
    if head < 0:
        return None
    fields = stat_text[head + 1:].split()
    return fields[0] if fields else None


def _proc_state(pid: int) -> str | None:
    """读 ``/proc/<pid>/stat`` 取进程状态字段；/proc 不可达返回 None。"""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_stat(stat)


def _pid_alive(pid: object) -> bool:
    """``kill(pid, 0)`` 探活：非正整数/不存在/僵尸(Z)为假，无权限视为活着。

    僵尸进程已死但未被收尸，``kill(pid, 0)`` 仍成功——lock 文件指向这种
    pid 时必须判死，否则陈旧 daemon 的 lock 会把重拉卡在"复用假活进程"。
    Linux 下追加 ``/proc/<pid>/stat`` 状态检查；/proc 不可达（macOS 等）
    保持纯 ``os.kill`` 判定。
    """
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
    if _proc_state(pid) == "Z":
        return False
    return True


def is_alive(sock: Path, expect_pkg: str, expect_hash: str) -> bool:
    """sock 是否指向一个身份吻合的活 daemon。

    判据（任一不满足即 False）：lock 可读且 pid 存活；ping 在 connect 2s /
    响应 5s 内成功；应答 result 自报的 ``pkg``/``config_hash`` 与期望一致
    （不符说明 socket 是旧版本/旧配置的陈旧残留）。
    """
    info = read_lock(sock)
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

def _spawn_lock_owner_dead(spawn_lock: Path) -> bool:
    """仲裁锁 owner pid 已死则 True；内容缺失/不可解析按存活处理。

    宁可轮询不可误夺：owner 刚 open 未 write pid 的微窗口若被误判死亡，
    抢夺会造成双 spawn——比输家多等一轮超时严重得多。
    """
    try:
        info = json.loads(spawn_lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(info, dict):
        return False
    pid = info.get("pid")
    return isinstance(pid, int) and not isinstance(pid, bool) and not _pid_alive(pid)


def _acquire_spawn_lock(spawn_lock: Path) -> bool:
    """``O_CREAT|O_EXCL`` 抢仲裁锁；owner 已死的陈旧锁 unlink 后重试一次。

    多个输家同时抢夺同一把死锁时，unlink 与重试的竞争由 O_EXCL 天然仲裁：
    至多一方成功持有，其余 FileExists 后即按输家处理（不再二次抢夺）。
    """
    for attempt in (0, 1):
        try:
            fd = os.open(spawn_lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if attempt == 0 and _spawn_lock_owner_dead(spawn_lock):
                # unlink 前立即重读复核 owner 仍死：首次检查与 unlink 之间，
                # 另一输家可能已夺走死锁并写入自己的活 pid——此刻重读判活，
                # 放弃抢夺沦为轮询输家（避免误删他方新锁造成双 spawn）。
                # 复核与 unlink 之间仍残留固有微窗口（他方恰在此瞬间重建新锁
                # 会被误删），O_EXCL 仲裁只能收窄到这一步；窗口极小且其后果
                # （双"胜者"）由后续 is_alive 复查与幂等清理兜底。
                if not _spawn_lock_owner_dead(spawn_lock):
                    return False
                try:
                    spawn_lock.unlink()
                except OSError:
                    return False  # 并发方已在处理,沦为轮询输家
                continue
            return False
        try:
            os.write(fd, json.dumps({"pid": os.getpid()}).encode())
        finally:
            os.close(fd)
        return True
    return False


def _launch(d: Path, name: str, spawn_env: dict[str, str]) -> subprocess.Popen:
    """拉起 daemon 子进程；stdout/stderr 追加到 ``<name>.log``。

    调用方必须处于持有仲裁锁的 try/finally 保护内——open/Popen 抛错（如
    ENOSPC）时锁仍被释放，自动重拉能力不会随单次异常永久丧失。
    """
    # append：同 (版本,hash) 的多次拉起日志累计留痕，便于事后排查
    with open(d / f"{name}.log", "ab") as log:
        return subprocess.Popen(
            [sys.executable, "-m", _DAEMON_MODULE],
            env={**os.environ, **spawn_env},
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            cwd="/",
        )


def _cleanup_stale(d: Path, name: str) -> None:
    """清理同名陈旧 sock/lock（仅持仲裁锁的胜者、且复查 is_alive 判负后调用）。

    绝不碰 ``<name>.spawn.lock``——那是并发 spawn 仲裁锁，删它会破坏互斥；
    仲裁锁由抢锁方在 finally 中保证释放。输家无权调用本函数：其 is_alive
    判负与清理之间可能恰有他者的 daemon 就绪，无差别 unlink 会误杀活跃
    socket。
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
    ``O_CREAT|O_EXCL`` 先仲裁：仅持锁者可 spawn 与清理；持锁后先复查
    is_alive（期间先到者可能已就绪，命中即释放锁复用），输家在 owner 已死
    时可抢夺一次。持锁跨度由 finally 保证释放。
    """
    if sys.platform == "win32":
        raise RuntimeError("daemon 模式依赖 unix socket, 暂不支持 Windows")

    d = daemon_dir()
    name = socket_name(config_hash)
    sock = d / f"{name}.sock"
    spawn_lock = d / f"{name}.spawn.lock"
    expect_pkg = pkg_version()
    deadline = time.monotonic() + timeout

    if is_alive(sock, expect_pkg, config_hash):
        return sock

    winner = _acquire_spawn_lock(spawn_lock)
    proc: subprocess.Popen | None = None
    try:
        if winner:
            # 复查：快速判负与抢到锁之间，先到者可能已完成 spawn（其 daemon
            # 不受本锁约束）——命中即复用，绝不二次 spawn
            if is_alive(sock, expect_pkg, config_hash):
                return sock
            _cleanup_stale(d, name)
            proc = _launch(d, name, spawn_env)
        return _wait_ready(sock, expect_pkg, config_hash, deadline, proc)
    finally:
        if winner:
            try:
                spawn_lock.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                # 释放失败（权限/并发竞态等）记日志后继续：finally 抛新异常
                # 会掩盖 try 内原始异常，且自动重拉能力不应随单次失败丧失
                logger.debug("spawn.lock 释放失败: %s", spawn_lock, exc_info=True)
