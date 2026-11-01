"""daemon worker：op 路由、token 鉴权、按 id 多路复用、取消传播与空闲退出。

单 unix socket、单事件循环服务全部前端连接。承重设计：

- **ping 延迟是承重约束**：lifecycle 的 is_alive 用 2s connect / 5s 响应判活，
  忙碌的 worker 若拖延 ping 会被误判陈旧而遭重拉。因此每个 fetch 请求都
  作为独立 asyncio 任务分派（多路复用），cancel 亦以任务分发（其 5s 宽限
  等待绝不阻塞读循环）；ping/status/shutdown 由读循环内联即时应答——
  fetch 逻辑绝不内联进读循环。响应一律按请求 id 关联，到达顺序对前端无
  影响（按 id 定界）。
- **坏帧韧性**：读循环对单帧的解析与分派整体兜底 ``Exception``（深嵌套
  JSON 可令 ``json.loads`` 抛 ``RecursionError`` 穿透 ``ProtocolError``），
  坏帧以错误帧应答，绝不击穿连接或 worker。
- **取消传播（Review Focus）**：``cancel`` 对目标任务 ``cancel()`` 后
  ``wait_for(shield(task), 宽限期)``；宽限耗尽（浏览器清理挂死、任务杀不
  死）则 ``os.killpg`` 强杀整个进程组（daemon 经 ``start_new_session`` 是
  自身进程组长，scrapling 拉起的浏览器同组——daemon 与残留浏览器同归于尽，
  前端检测死亡后自动重拉）。此为最后手段，任何软性收尾都无法保证时才走。
  cancel op 自身的取消语义：仅当 cancel 任务自己被取消（读循环终止/收尾）
  时向外传播；目标任务以 cancelled 收场则补发 E_CANCELLED 后照常收尾。

Import 边界约束：本模块仅 daemon 侧使用，允许模块级引入重依赖
（``_fetcher``/``_scrapling`` 等）；前端白名单模块
（protocol/config_env/paths/lifecycle）不得反向 import 本模块。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import secrets
import signal
import time
from pathlib import Path

from scrapling_fetch_mcp import _scrapling
from scrapling_fetch_mcp._browser_check import resolve_stealth_degradation
from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
from scrapling_fetch_mcp._fetcher import fetch_page_wrapper, fetch_pattern_wrapper
from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.paths import pkg_version
from scrapling_fetch_mcp.daemon.protocol import (
    E_BAD_FRAME,
    E_CANCELLED,
    E_INTERNAL,
    E_UNAUTHORIZED,
    E_UNKNOWN_OP,
    OP_CANCEL,
    OP_FETCH_PAGE,
    OP_FETCH_PATTERN,
    OP_PING,
    OP_SHUTDOWN,
    OP_STATUS,
    ProtocolError,
    make_error,
    make_progress,
    make_response,
    parse_frame,
)

__all__ = [
    "CANCEL_GRACE",
    "CONCURRENCY_LIMIT_CODE",
    "STREAM_LIMIT",
    "DaemonWorker",
    "ProgressBridge",
]

logger = logging.getLogger("scrapling_fetch_mcp.daemon.worker")

# 单帧上限：与 start_unix_server(limit=...) 一致（spec 定值）。
STREAM_LIMIT = 64 * 1024 * 1024
# 有连接时 serve 循环的轮询间隔：shutdown/断连最迟此时被察觉（远小于空闲超时量级）。
_ACTIVE_POLL = 0.05
# cancel 后等待目标任务退出的宽限期；耗尽即 killpg 核弹兜底（spec 定值 5s）。
CANCEL_GRACE = 5.0
# 退出时等待 in-flight fetch 任务收尾的期限；挂死任务交给进程退出兜底。
_EXIT_TASK_GRACE = 2.0
# 退出时等待 pool.close_all 的宽限；Firefox close 挂死时转 OS 层击杀兜底，
# daemon 必须能退出（spec 反目标：daemon 泄漏、lock/sock 永不清理）。
_CLOSE_ALL_GRACE = 5.0
# 并发限流错误码（前端映射回限流文案）。
CONCURRENCY_LIMIT_CODE = "CONCURRENCY_LIMIT"


def _wrapper_params(fn) -> tuple[frozenset[str], frozenset[str]]:
    """从 wrapper 签名提取 (必填键, 可选键)；``ctx`` 由 worker 注入不算 payload 键。"""
    required: set[str] = set()
    optional: set[str] = set()
    for name, param in inspect.signature(fn).parameters.items():
        if name == "ctx":
            continue
        (optional if param.default is not inspect.Parameter.empty else required).add(name)
    return frozenset(required), frozenset(optional)


# payload 键 ↔ wrapper 形参一一对应的校验依据（模块导入期自 REAL wrapper 算出，
# 不受测试 monkeypatch 影响）。
_PAYLOAD_SPEC: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    OP_FETCH_PAGE: _wrapper_params(fetch_page_wrapper),
    OP_FETCH_PATTERN: _wrapper_params(fetch_pattern_wrapper),
}


def _validate_payload(op: str, payload: object) -> dict[str, object]:
    """payload 键与 wrapper 形参 1:1 校验；违规抛 ValueError（映射 E_INTERNAL）。"""
    if not isinstance(payload, dict):
        raise ValueError(f"payload 必须是 JSON object, 得到 {type(payload).__name__}")
    required, optional = _PAYLOAD_SPEC[op]
    unknown = sorted(payload.keys() - required - optional)
    if unknown:
        raise ValueError(f"payload 含未知键: {unknown}, 合法键: {sorted(required | optional)}")
    missing = sorted(required - payload.keys())
    if missing:
        raise ValueError(f"payload 缺少必填键: {missing}")
    return payload


async def _safe_send(send, frame: bytes) -> None:
    """尽力发送：对端断开等传输错误只记日志，不反噬调用方（fetch 任务/取消路径）。"""
    try:
        await send(frame)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001  传输层一切失败都按对端消失处理
        logger.debug("帧发送失败(对端可能已断开)", exc_info=True)


class ProgressBridge:
    """fetch wrapper 的 ``ctx`` 鸭子类型：``report_progress`` → 协议 progress 帧。

    ``_fetcher._maybe_report_progress`` 对 ``ctx=None`` 已容错，桥对象只需补
    这一个方法；``message`` 为 None 时以空串落帧（协议帧 message 必填）。
    """

    def __init__(self, req_id: int, send) -> None:
        self._req_id = req_id
        self._send = send

    async def report_progress(self, progress: float, total: float,
                              message: str | None = None) -> None:
        await self._send(
            make_progress(self._req_id, progress, total, "" if message is None else message)
        )


class DaemonWorker:
    """单 socket 的 daemon worker；``serve()`` 阻塞至空闲超时或 shutdown。

    直接以 ``(sock, idle_timeout)`` 构造即可驱动（单测不经过 ``__main__``）；
    ``config_hash`` 缺省按 daemon-owned env 自算，``token`` 缺省随机生成并经
    lock 文件与 ``.token`` 属性披露。
    """

    def __init__(self, sock: Path, idle_timeout: float, *,
                 config_hash: str | None = None,
                 cancel_grace: float = CANCEL_GRACE) -> None:
        self._sock = Path(sock)
        self._idle_timeout = idle_timeout
        self._config_hash = config_hash if config_hash is not None else resolve_daemon_env()[1]
        self._cancel_grace = cancel_grace
        self._token = secrets.token_hex(16)
        self._lock_path = self._sock.with_suffix(".lock")
        self._started = time.monotonic()
        self._tasks: dict[int, asyncio.Task] = {}
        # 在飞的 cancel op 任务（连接级任务集另持有引用；cleanup 时统一收口）
        self._cancel_tasks: set[asyncio.Task] = set()
        self._clients = 0
        self._stopping = False
        self._server: asyncio.AbstractServer | None = None
        self._idle_event = asyncio.Event()

    @property
    def token(self) -> str:
        """本实例的鉴权 token（与写进 lock 文件的一致）。"""
        return self._token

    @property
    def config_hash(self) -> str:
        return self._config_hash

    # ---------- 主循环 ----------

    async def serve(self) -> None:
        """写 lock → 起 server → chmod 0600 → 服务至空闲超时/shutdown。

        退出路径统一经 ``_cleanup``：关 server、取消 in-flight 任务（限时）、
        删 lock 与 sock。
        """
        self._sock.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._sock.unlink()  # 防御:陈旧 socket 文件会让 bind 失败(生产路径已由 spawn 仲裁清理)
        except FileNotFoundError:
            pass
        self._write_lock()
        try:
            self._server = await asyncio.start_unix_server(
                self._handle_connection, path=str(self._sock), limit=STREAM_LIMIT
            )
            os.chmod(self._sock, 0o600)  # socket 承载本机用户会话,仅 owner 可连
            while not self._stopping:
                if self._clients > 0:
                    await asyncio.sleep(_ACTIVE_POLL)
                    continue
                # clear-before-wait：等待期间新连接 set 事件即可打断空闲等待
                self._idle_event.clear()
                try:
                    await asyncio.wait_for(self._idle_event.wait(), timeout=self._idle_timeout)
                except asyncio.TimeoutError:
                    if self._clients > 0:
                        # 竞态收口：连接的 set 落在 clients 检查之后、clear 之前
                        # （事件被误清）时，超时醒来发现其实有活连接——重新计时
                        continue
                    logger.info("空闲 %ss 无连接, daemon 退出", self._idle_timeout)
                    break
        finally:
            await self._cleanup()

    def request_shutdown(self) -> None:
        """请求优雅退出（shutdown op 与 SIGTERM/SIGINT 处理器共用）。"""
        self._stopping = True
        self._idle_event.set()  # 打断可能正在进行的空闲等待

    def _write_lock(self) -> None:
        """lock JSON ``{"pid","token","pkg","config_hash","sock"}``（lifecycle 同构）。"""
        self._lock_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "token": self._token,
                    "pkg": pkg_version(),
                    "config_hash": self._config_hash,
                    "sock": str(self._sock),
                }
            ),
            encoding="utf-8",
        )

    async def _cleanup(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self._tasks:
            for task in self._tasks.values():
                task.cancel()
            # 限时收尾：正常取消毫秒级返回；杀不死的应用层僵尸由进程退出兜底
            await asyncio.wait(list(self._tasks.values()), timeout=_EXIT_TASK_GRACE)
        if self._cancel_tasks:
            for task in list(self._cancel_tasks):
                task.cancel()  # 未决 cancel op 的宽限等待一并打断
            await asyncio.wait(list(self._cancel_tasks), timeout=_EXIT_TASK_GRACE)
        # 浏览器池收口（spec §6.2：daemon 退出不留池化浏览器）。放在任务
        # 收尾之后——无在飞 fetch 时 close_all 才安全。仅当池已惰性构造过
        # 才关（默认关时 _pool 为 None，零开销）。限时宽限：Firefox close
        # 挂死会让无时限的 await 永不返回，daemon 泄漏、lock/sock 永不删；
        # 超时转 _kill_spawned_browsers SIGKILL 全部浏览器后代后照常清理。
        pool = getattr(_scrapling, "_pool", None)
        if pool is not None:
            try:
                await asyncio.wait_for(pool.close_all(), _CLOSE_ALL_GRACE)
            except asyncio.TimeoutError:
                logger.warning(
                    "浏览器池收口超过 %.1fs 未完成, 转杀残留浏览器进程后退出",
                    _CLOSE_ALL_GRACE,
                )
                # 快照传空集=击杀现存的全部浏览器后代（daemon 是自身进程组长,
                # 后代必为它自己拉起的浏览器/驱动; 测试进程内 monkeypatch 之）
                _scrapling._kill_spawned_browsers(set())
            except Exception:  # noqa: BLE001  退出路径关闭失败不阻断清锁删 sock
                logger.warning("浏览器池收口失败", exc_info=True)
        for path in (self._lock_path, self._sock):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    # ---------- 连接处理 ----------

    async def _handle_connection(self, reader: asyncio.StreamReader,
                                 writer: asyncio.StreamWriter) -> None:
        """单连接读循环：NDJSON 逐帧处理；引用计数支撑空闲退出。"""
        self._clients += 1
        self._idle_event.set()  # 与 clear-before-wait 配套：打断进行中的空闲等待
        ops: set[asyncio.Task] = set()  # 本连接分发出的 cancel op 任务

        async def send(frame: bytes) -> None:
            writer.write(frame)
            await writer.drain()

        try:
            while not self._stopping:
                try:
                    line = await reader.readuntil(b"\n")
                except asyncio.IncompleteReadError:
                    break  # 对端关闭（残缺半行按断连处理）
                except asyncio.LimitOverrunError:
                    # 单帧超 64MiB：流已无法可靠重新分帧，只能断开本连接
                    # （上限内的坏帧走 _process_line 的错误应答，连接存活）
                    logger.warning("单帧超过 %d 字节上限, 断开连接", STREAM_LIMIT)
                    break
                response = await self._process_line(line, send, ops)
                if response is not None:
                    await send(response)
        except (ConnectionError, OSError):
            pass  # 对端断开属连接生命周期的正常终点
        finally:
            # 读循环终止 → 本连接未决的 cancel op 一并取消（外层取消传播到
            # 任务；其 E_CANCELLED/cancel 响应再无通道，_safe_send 兜底吞掉）
            for task in ops:
                task.cancel()
            self._clients -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _process_line(self, line: bytes, send, ops: set) -> bytes | None:
        """解析并分派一帧；任何异常都折成错误帧，绝不让坏帧击穿读循环。

        宽兜底 ``Exception`` 是承重的：深嵌套 JSON 可令 ``json.loads`` 抛
        ``RecursionError``（不是 ``ProtocolError`` 子类），不接住会杀死连接。
        ``ops`` 收集分发出的 cancel op 任务（读循环取消时反向取消它们）。
        """
        try:
            frame = parse_frame(line)
            return await self._dispatch(frame, send, ops)
        except ProtocolError as exc:
            return make_error(0, E_BAD_FRAME, str(exc))
        except Exception as exc:  # noqa: BLE001  见 docstring：兜底即本函数的存在理由
            logger.warning("帧处理异常, 按 internal 错误应答: %r", exc)
            return make_error(0, E_INTERNAL, f"帧处理失败: {exc}")

    async def _dispatch(self, frame: dict, send, ops: set) -> bytes | None:
        """op 路由。fetch/cancel 返回 None（响应由独立任务按 id 多路复用发出）。"""
        req_id = frame.get("id", 0)
        token = frame.get("token")
        if not isinstance(token, str) or token != self._token:
            return make_error(req_id, E_UNAUTHORIZED, "token 不匹配, 拒绝服务")
        op = frame.get("op")
        payload = frame.get("payload")
        if op == OP_PING:
            return make_response(req_id, self._ping_result())
        if op == OP_STATUS:
            return make_response(req_id, self._status_result())
        if op == OP_CANCEL:
            # 独立任务分发：5s 宽限等待绝不阻塞读循环（同连接的 ping/status
            # 必须即时应答）。响应由任务完成后经 _safe_send 发出。
            task = asyncio.create_task(self._run_cancel(req_id, payload, send))
            ops.add(task)
            self._cancel_tasks.add(task)
            task.add_done_callback(self._cancel_tasks.discard)
            return None
        if op == OP_SHUTDOWN:
            self.request_shutdown()
            return make_response(req_id, {"status": "stopping"})
        if op in (OP_FETCH_PAGE, OP_FETCH_PATTERN):
            # 独立任务分派：fetch 再慢也不阻塞读循环（ping 延迟承重，见模块 docstring）
            task = asyncio.create_task(self._run_fetch(req_id, op, payload, send))
            self._tasks[req_id] = task
            return None
        return make_error(req_id, E_UNKNOWN_OP, f"未知 op: {op!r}")

    # ---------- op 实现 ----------

    def _identity(self) -> dict:
        return {
            "pid": os.getpid(),
            "pkg": pkg_version(),
            "config_hash": self._config_hash,
            "uptime_s": round(time.monotonic() - self._started, 3),
            "clients": self._clients,
        }

    def _ping_result(self) -> dict:
        return {"status": "ready", **self._identity()}

    def _status_result(self) -> dict:
        _effective_mode, degradation = resolve_stealth_degradation("stealth")
        # 浏览器池统计：默认关（None）；开启时惰性构造空池 harmless——
        # 只有 fetch 才拉浏览器，stats 报零值即"池已启用尚无会话"
        pool_stats = _scrapling.get_pool().stats() if config.browser_pool else None
        return {
            **self._identity(),
            # PageCache 未暴露公开 size；暂以内部 _cache 计数披露
            "cache_entries": len(config.cache._cache),  # noqa: SLF001
            "stealth_ready": _effective_mode == "stealth",
            "degradation": degradation,
            "pool": pool_stats,
        }

    async def _run_cancel(self, req_id: int, payload: object, send) -> None:
        """cancel op 任务体：响应由本任务经 _safe_send 发出（读循环不等待）。

        取消语义（承接原内联实现）：仅当 cancel 任务自身被取消（读循环终止、
        worker 收尾）才向外传播——此时响应通道已关闭，不再伪造应答。
        """
        try:
            response = await self._handle_cancel(req_id, payload, send)
        except asyncio.CancelledError:
            raise
        await _safe_send(send, response)

    async def _handle_cancel(self, req_id: int, payload: object, send) -> bytes:
        cancel_id = payload.get("cancel_id") if isinstance(payload, dict) else None
        if isinstance(cancel_id, bool) or not isinstance(cancel_id, int):
            return make_error(req_id, E_INTERNAL, "cancel payload 需要整数 cancel_id")
        target = self._tasks.get(cancel_id)
        if target is None or target.done():
            return make_response(req_id, {"cancelled": False})
        target.cancel()
        try:
            # shield：宽限期内任务自行收尾（E_CANCELLED 由任务自己发给原始 id），
            # 超时只取消本等待者，目标任务继续挂着——然后走下面的核弹兜底
            await asyncio.wait_for(asyncio.shield(target), self._cancel_grace)
        except asyncio.TimeoutError:
            # —— 核弹兜底（最后手段）——
            # 宽限期耗尽说明浏览器子进程清理挂死、任务无法取消。daemon 经
            # start_new_session 成为其进程组长，scrapling 拉起的浏览器同属该
            # 进程组；SIGKILL 整组让 daemon 与残留浏览器同归于尽，前端检测到
            # daemon 死亡会按需自动重拉。软性手段（继续等/只杀浏览器）都无法
            # 保证收尾，故直接强杀。生产路径 killpg 即进程死亡，其后的代码不可达；
            # 单测 monkeypatch os.killpg 后才会走到返回。
            logger.error(
                "cancel %s: %.1fs 宽限期耗尽且任务无法取消, killpg 强杀进程组"
                "（daemon 与残留浏览器同尽, 前端自动重拉）",
                cancel_id, self._cancel_grace,
            )
            os.killpg(os.getpgid(0), signal.SIGKILL)
        except asyncio.CancelledError:
            if target.cancelled():
                # 目标任务以 cancelled 收场=取消已生效，但取消点落在任务未受
                # 保护的 await 上（如响应帧的 _safe_send），E_CANCELLED 可能未
                # 及发出——这里补发（重复发亦无害：客户端对已完成 id 的迟到
                # 终帧忽略）。绝不能 re-raise：CancelledError 是 BaseException，
                # 会穿透 _process_line 的宽兜底与连接读循环，杀死整个连接
                # （cancel 调用方收到 EOF 而非响应，同连接其他 in-flight 请求
                # 的响应通道一并丢失）。
                await _safe_send(send, make_error(cancel_id, E_CANCELLED, "请求已被取消"))
            else:
                raise  # cancel op 自身被取消（事件循环关闭等），不吞
        except Exception:  # noqa: BLE001  目标任务以异常收场=取消已生效
            pass
        return make_response(req_id, {"cancelled": True})

    async def _run_fetch(self, req_id: int, op: str, payload: object, send) -> None:
        """fetch 任务体：校验 payload → 闸门 → wrapper → 按结果发帧。"""
        try:
            try:
                kwargs = _validate_payload(op, payload)
            except ValueError as exc:
                await _safe_send(send, make_error(req_id, E_INTERNAL, str(exc)))
                return
            bridge = ProgressBridge(req_id, send)
            wrapper = fetch_page_wrapper if op == OP_FETCH_PAGE else fetch_pattern_wrapper
            try:
                guard = _scrapling._guard  # 运行期取模块属性:init_guard 在 __main__ 里晚于 import
                if guard is None:
                    # 闸门未初始化（单测直驱 DaemonWorker）：不设限直接跑
                    result = await wrapper(ctx=bridge, **kwargs)
                else:
                    async with guard:
                        result = await wrapper(ctx=bridge, **kwargs)
            except ConcurrencyLimitError as exc:
                await _safe_send(send, make_error(req_id, CONCURRENCY_LIMIT_CODE, str(exc)))
                return
            except asyncio.CancelledError:
                # 正常取消路径：给原始请求 id 回 E_CANCELLED。刻意不重新抛出、
                # 让任务以正常完成收场——cancel 方的 shield 等待因此及时返回，
                # 不会误入宽限期/核弹兜底。
                await _safe_send(send, make_error(req_id, E_CANCELLED, "请求已被取消"))
                return
            except Exception as exc:  # noqa: BLE001  wrapper 已记详细日志,这里只落协议帧
                logger.exception("fetch 失败 id=%s op=%s", req_id, op)
                await _safe_send(send, make_error(req_id, E_INTERNAL, str(exc)))
                return
            await _safe_send(send, make_response(req_id, {"result": result}))
        finally:
            self._tasks.pop(req_id, None)
