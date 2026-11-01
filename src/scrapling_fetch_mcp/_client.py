"""前端 BackendClient：daemon 协议的客户端侧（Task 8）。

进程级单例 :func:`get_client` 持有一条到 daemon 的 unix socket 持久连接，
全部请求按自增 id 在同一连接上多路复用；reader 常驻任务按 id 把
response/error/progress 帧分发回等待者：

- **首帧定局（Task 7 契约）**：同一 id 可能先收到正常响应、再收到迟到的
  E_CANCELLED（或反之）——reader 以 ``future.done()`` 判重，首个终帧
  （ok 响应或 error）生效，其后同 id 帧一律忽略；progress 帧只触发
  ``ctx.report_progress`` 回调，永不完结 future。
- **断线重生**：连接级故障（EOF/传输错误/建连失败）→ 丢弃连接 → 重跑
  ``ensure_daemon`` → 最多重试 :data:`_MAX_RETRIES` 次；仍失败抛
  ``BackendError("DAEMON_UNAVAILABLE", 排查指引)``。应用层 error 帧
  不重试，直接映射 ``BackendError(code, message)``。
- **看门狗**：单请求限时 ``acquire_timeout + fetch_timeout + 60s``（每请求
  一个总窗，call 进入时定死 deadline；连接级故障重试共享剩余预算，重试不
  重置窗口），超时发 cancel 帧后抛 ``BackendError("DAEMON_TIMEOUT", ...)``。
- **取消**：``call`` 的调用方任务被取消时由 :func:`make_adapter` 负责
  发 cancel 帧再 re-raise（取消必须继续传播）。重试每次尝试换新请求 id，
  adapter 经 :class:`ActiveCall` 句柄取「当前生效 id」发 cancel——预分配
  的初始 id 在重试后已不对应任何在途任务。

Import 边界约束：本模块在前端 import 白名单上——仅 stdlib、
``daemon.protocol``/``daemon.lifecycle``/``daemon.config_env``/
``daemon.paths``（均为轻模块）；``_config`` 仿 ``daemon.paths`` 在函数内
延迟 import；mcp 的 ``Context`` 仅 TYPE_CHECKING。禁止牵入
``_fetcher``/``_scrapling`` 等重依赖。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import secrets
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.lifecycle import ensure_daemon
from scrapling_fetch_mcp.daemon.paths import pkg_version
from scrapling_fetch_mcp.daemon.protocol import (
    OP_CANCEL,
    ProtocolError,
    make_request,
    parse_frame,
)

if TYPE_CHECKING:  # 纯类型标注，运行时不牵入
    from mcp.server.mcpserver.context import Context

__all__ = [
    "ActiveCall",
    "BackendClient",
    "BackendError",
    "get_client",
    "make_adapter",
]

logger = logging.getLogger("scrapling_fetch_mcp.client")

# 单帧上限：与 daemon worker 的 start_unix_server(limit=...) 一致（spec 定值）。
# worker 属 daemon 侧模块，前端不得反向 import，按约定硬编码同值。
_STREAM_LIMIT = 64 * 1024 * 1024
# ensure_daemon 的就绪期限（秒）：daemon 冷启动（拉进程+初始化）的宽限。
_ENSURE_TIMEOUT = 60.0
# 看门狗松弛项：单请求总窗 = acquire_timeout + fetch_timeout + 该值（spec 定值）。
_WATCHDOG_SLACK = 60.0
# cancel 帧 / 取消收尾的发送期限：尽力而为，超时即放弃（不拦取消传播）。
_CANCEL_TIMEOUT = 2.0
# progress 回调的收尾期限（秒）：顺序语义（进度先于完成）尽力保，回调卡死
# 不拖结果交付。
_PROGRESS_DRAIN_TIMEOUT = 5.0
# 连接级故障的重试上限（brief：丢弃连接 → 重跑 ensure_daemon → 最多重试 2 次）。
_MAX_RETRIES = 2

# daemon 侧 worker 的并发限流错误码（worker 属 daemon 侧，前端按约定硬编码同值）。
CODE_CONCURRENCY_LIMIT = "CONCURRENCY_LIMIT"
# 本模块自产错误码。
CODE_TIMEOUT = "DAEMON_TIMEOUT"
CODE_UNAVAILABLE = "DAEMON_UNAVAILABLE"

_UNAVAILABLE_GUIDANCE = (
    "无法连接或拉起 daemon: {detail}。排查: "
    "①运行 `scrapling-fetch-mcp daemon status` 查看 daemon 状态; "
    "②按需设 SCRAPLING_DAEMON_DIR 指定 daemon 目录, 并检查目录下 daemon-*.log; "
    "③处理后重试, 前端会自动重新拉起 daemon。"
)


class BackendError(RuntimeError):
    """daemon 调用失败：协议 error 帧、看门狗超时或 daemon 不可用。

    ``.code`` 为机器可读错误码（如 ``DAEMON_TIMEOUT``/``CONCURRENCY_LIMIT``），
    ``.message`` 为人读详情；``str(exc)`` 呈现 ``"code: message"``。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class _ConnectionLost(Exception):
    """连接级故障（EOF/传输错误/未连接）：丢弃连接、重跑 ensure_daemon 后重试。"""


class _Pending:
    """单个在途请求的等待者：future + 进度回调宿主。"""

    __slots__ = ("ctx", "future", "progress_tasks")

    def __init__(self, future: asyncio.Future, ctx: Any) -> None:
        self.future = future
        self.ctx = ctx
        self.progress_tasks: set[asyncio.Task] = set()


class ActiveCall:
    """一次 ``call`` 的取消句柄：记录当前生效（最近一次尝试）的请求 id。

    连接级故障重试时每次尝试换新 id（防 daemon 存活时孤儿任务与新请求同 id
    互相覆盖/误配）；取消方（adapter）经 ``handle.req_id`` 取当前生效 id 发
    cancel 帧，而非预分配的初始 id——后者在重试后已不对应任何在途任务。
    """

    __slots__ = ("req_id",)

    def __init__(self) -> None:
        self.req_id: int | None = None


def _read_lock_token(sock: Path) -> str:
    """从 daemon socket 同名 ``.lock`` 读鉴权 token（lifecycle 约定的 JSON）。

    缺失/坏 JSON/缺 token 一律按连接级失败抛 ``OSError`` → 走重试路径。
    """
    lock_path = sock.with_suffix(".lock")
    token = None
    try:
        info = json.loads(lock_path.read_text(encoding="utf-8"))
        if isinstance(info, dict):
            token = info.get("token")
    except (OSError, json.JSONDecodeError):
        pass
    if not isinstance(token, str) or not token:
        raise OSError(f"daemon lock 缺少 token: {lock_path}")
    return token


class BackendClient:
    """daemon 协议客户端：持久连接、按 id 多路复用、断线自动重拉。

    生命周期：``__init__`` 不做 IO（``resolve_daemon_env`` 惰性到首连）；
    ``call`` 自动建连/重连；``cancel`` 尽力发取消帧；``aclose`` 关连接，
    之后 ``call`` 会重新拉起 daemon。
    """

    def __init__(self) -> None:
        self._connect_lock = asyncio.Lock()  # 串行化首连/重连,防并发重复拉起 daemon
        self._send_lock = asyncio.Lock()  # 单写者纪律:同一时刻仅一个协程写 socket
        self._pending: dict[int, _Pending] = {}
        # id 起点随机化：daemon 独立于 client 进程存活，client 重启后从 0 起
        # 编号可能与 daemon 残留孤儿任务同 id（同类误配），随机起点使其概率可忽略
        self._id_counter = secrets.randbelow(1 << 30)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task | None = None
        self._spawn_env: dict[str, str] | None = None
        self._config_hash: str | None = None
        self._sock: Path | None = None
        self._token: str = ""
        self._pkg: str = ""

    # ---------- 公共 API ----------

    def next_id(self) -> int:
        """分配下一个请求 id（单调递增、随机起点）。

        由 ``call`` 内部为每次尝试自分配（每次尝试换新 id，防 daemon 侧孤儿
        任务同 id 误配）；取消方经 :class:`ActiveCall` 句柄取当前生效 id，
        **调用方无需预分配 id**。``cancel`` 的控制帧 id 亦复用本计数器。
        """
        self._id_counter += 1
        return self._id_counter

    async def call(self, op: str, payload: dict, ctx: Context | None = None, *,
                   req_id: int | None = None, active: ActiveCall | None = None) -> dict:
        """向 daemon 发起一次调用，返回响应帧的 ``result`` 值。

        - error 帧 → ``BackendError(code, message)``（不重试）。
        - 连接级故障/拉起失败 → 丢连重拉，最多重试 ``_MAX_RETRIES`` 次，
          仍失败抛 ``BackendError("DAEMON_UNAVAILABLE", 排查指引)``。
        - 看门狗超时 → 发 cancel 帧，抛 ``BackendError("DAEMON_TIMEOUT", ...)``。
        - ``req_id``：**首次尝试**的请求 id（可选项，缺省自分配）。
        - ``active``：取消句柄（可选项）。每次重试换新 id——daemon 不因客户
          端断连清理任务表，同 id 重放会覆盖孤儿任务注册、其迟到响应帧还会
          按同 id 误配新请求；句柄的 ``req_id`` 随之更新为当前生效 id，供
          取消方（adapter）命中在途请求。
        """
        last: Exception | None = None
        rid = self.next_id() if req_id is None else req_id  # 首尝试 id
        if active is not None:
            active.req_id = rid
        # 看门狗总窗在 call 进入时定死：连接级故障重试共享剩余预算，重试
        # 不重置窗口——总耗时上限与单次尝试一致，不因重试而翻倍
        deadline = asyncio.get_running_loop().time() + self._watchdog_window()
        for _attempt in range(_MAX_RETRIES + 1):
            try:
                await self._ensure_connected()
                return await self._transact(op, payload, ctx, rid, deadline)
            except (_ConnectionLost, OSError, TimeoutError) as exc:
                # BackendError/CancelledError 不在此列：前者不重试,后者必须传播
                last = exc
                await self._drop_connection()
                # 重试换新 id：daemon 存活时旧尝试可能成为孤儿任务仍挂在其
                # _tasks 表（断连不清表），同 id 重放会覆盖注册且孤儿迟到的
                # 响应帧按同 id 命中新 future——换新 id 双向消除（评审 Important）
                rid = self.next_id()
                if active is not None:
                    active.req_id = rid
        raise BackendError(CODE_UNAVAILABLE, _UNAVAILABLE_GUIDANCE.format(detail=last)) from last

    async def cancel(self, req_id: int) -> None:
        """请求 daemon 取消在途请求（op=cancel）；连接已断则静默放弃。"""
        if self._writer is None or self._writer.is_closing():
            return
        frame = make_request(OP_CANCEL, {"cancel_id": req_id}, self._token, self.next_id(), self._pkg)
        try:
            await self._send_frame(frame)
        except asyncio.CancelledError:
            raise  # cancel 自身被取消（事件循环关闭等）：照常传播
        except Exception:  # noqa: BLE001  控制帧尽力而为,失败不反噬调用方
            logger.debug("cancel 帧发送失败(连接可能已断)", exc_info=True)

    async def aclose(self) -> None:
        """关闭连接；在途请求按连接级失败收场。之后仍可 ``call``（自动重连）。"""
        async with self._connect_lock:
            await self._drop_connection()

    # ---------- 连接管理 ----------

    def _is_alive(self) -> bool:
        """连接可用：writer 未关闭且 reader 任务仍在（daemon 死亡 → reader 见 EOF 退出）。"""
        return (
            self._writer is not None
            and not self._writer.is_closing()
            and self._reader_task is not None
            and not self._reader_task.done()
        )

    async def _ensure_connected(self) -> None:
        if self._is_alive():
            return
        async with self._connect_lock:
            if self._is_alive():  # 双检:等锁期间并发调用方可能已完成重连
                return
            await self._drop_connection()  # 清理半死残骸(幂等)
            if self._spawn_env is None or self._config_hash is None:
                self._spawn_env, self._config_hash = resolve_daemon_env()  # 惰性:首用才解析
            # ensure_daemon 内部 time.sleep 轮询（同步阻塞），放线程池避免拖死事件循环，
            # 使其他在途请求的帧收发不受重拉影响
            sock = await asyncio.to_thread(ensure_daemon, self._spawn_env, self._config_hash,
                                           _ENSURE_TIMEOUT)
            token = await asyncio.to_thread(_read_lock_token, sock)
            reader, writer = await asyncio.open_unix_connection(str(sock), limit=_STREAM_LIMIT)
            self._sock = sock
            self._token = token
            self._pkg = pkg_version()
            self._reader = reader
            self._writer = writer
            self._reader_task = asyncio.create_task(self._read_loop(reader))

    async def _drop_connection(self) -> None:
        """丢弃当前连接（幂等）并令全部在途请求按连接级失败收场。"""
        reader_task, self._reader_task = self._reader_task, None
        self._fail_pending(_ConnectionLost("与 daemon 的连接已断开"))
        writer, self._writer = self._writer, None
        self._reader = None
        if reader_task is not None:
            reader_task.cancel()
            await asyncio.gather(reader_task, return_exceptions=True)
        if writer is not None:
            writer.close()
            try:
                await writer.wait_closed()
            except (ConnectionError, OSError):
                pass

    async def _send_frame(self, frame: bytes) -> None:
        writer = self._writer
        if writer is None:
            raise _ConnectionLost("尚未连接 daemon")
        async with self._send_lock:
            try:
                writer.write(frame)
                await writer.drain()
            except (ConnectionError, OSError) as exc:
                raise _ConnectionLost(f"发送失败: {exc}") from exc

    # ---------- reader：按 id 分发 ----------

    async def _read_loop(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                try:
                    line = await reader.readline()
                except (OSError, ValueError):
                    # OSError=传输错误; ValueError=单帧超 limit(流无法重新分帧)
                    break
                if not line:
                    break  # EOF:daemon 死亡/关闭连接
                try:
                    frame = parse_frame(line)
                except Exception as exc:  # noqa: BLE001  坏帧只忽略,绝不击穿读循环(同 worker)
                    # 兜底承重：深嵌套 JSON 可令 json.loads 抛 RecursionError
                    # （非 ProtocolError 子类），只接 ProtocolError 会把这类
                    # 坏帧升级成连接级故障、误杀整条连接的在途请求
                    logger.debug("daemon 发来坏帧, 忽略: %s", exc)
                    continue
                self._dispatch(frame)
        finally:
            # EOF/传输错误/被取消（连接被丢弃）：全部在途请求按连接级失败收场
            self._fail_pending(_ConnectionLost("与 daemon 的连接已断开"))

    def _dispatch(self, frame: dict) -> None:
        """单帧分发（同步、串行）：首帧定局；progress 只触发回调不完结 future。"""
        req_id = frame.get("id")
        if isinstance(req_id, bool) or not isinstance(req_id, int):
            return
        entry = self._pending.get(req_id)
        if entry is None or entry.future.done():
            # 迟到/重复帧（如正常响应之后的 E_CANCELLED）：首帧已定局,忽略
            return
        if "ok" in frame:
            self._pending.pop(req_id, None)
            if frame["ok"] is True:
                entry.future.set_result(frame.get("result"))
            else:
                err = frame.get("error")
                err = err if isinstance(err, dict) else {}
                entry.future.set_exception(
                    BackendError(str(err.get("code", "internal")), str(err.get("message", "")))
                )
        elif "progress" in frame and entry.ctx is not None:
            prog = frame["progress"]
            prog = prog if isinstance(prog, dict) else {}
            # 独立任务跑回调：ctx 卡住只拖自己的请求,不阻塞整条连接的帧分发
            task = asyncio.create_task(self._report_progress(entry, prog))
            entry.progress_tasks.add(task)
            task.add_done_callback(entry.progress_tasks.discard)

    @staticmethod
    async def _report_progress(entry: _Pending, prog: dict) -> None:
        """鸭子类型桥接 ``ctx.report_progress(progress, total, message)``。"""
        try:
            report = getattr(entry.ctx, "report_progress", None)
            if report is None:
                return
            outcome = report(prog.get("progress"), prog.get("total"), prog.get("message"))
            if inspect.isawaitable(outcome):
                await outcome
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  进度回调失败不影响请求本身
            logger.debug("report_progress 回调失败", exc_info=True)

    def _fail_pending(self, exc: Exception) -> None:
        for entry in self._pending.values():
            if not entry.future.done():
                # 每个 future 独立异常实例：异常被 await 时会挂各等待方的
                # traceback，共享同一实例会让彼此的堆栈互相污染
                entry.future.set_exception(type(exc)(str(exc)))
        self._pending.clear()

    # ---------- 单请求事务 ----------

    def _watchdog_window(self) -> float:
        """单请求看门狗总窗时长：acquire_timeout + fetch_timeout + 松弛项。

        总窗在 ``call`` 进入时一次性换算成 deadline，各次尝试只消费剩余
        预算——重试不重置窗口。
        """
        from scrapling_fetch_mcp._config import config  # 延迟 import:不牵入配置链(同 paths)

        return config.acquire_timeout + config.fetch_timeout + _WATCHDOG_SLACK

    async def _transact(self, op: str, payload: dict, ctx: Any, req_id: int | None,
                        deadline: float) -> dict:
        rid = self.next_id() if req_id is None else req_id
        entry = _Pending(asyncio.get_running_loop().create_future(), ctx)
        self._pending[rid] = entry
        try:
            await self._send_frame(make_request(op, payload, self._token, rid, self._pkg))
            timeout = deadline - asyncio.get_running_loop().time()  # 剩余预算(重试共享)
            try:
                result = await asyncio.wait_for(entry.future, timeout)
            except asyncio.TimeoutError:
                await self._cancel_quietly(rid)
                raise BackendError(
                    CODE_TIMEOUT,
                    f"请求 {max(timeout, 0.0):.0f}s 内未完成(acquire+fetch+60s 看门狗), "
                    "已发 cancel 帧取消",
                ) from None
            # 先等 progress 回调落地再返回结果：保证顺序语义（进度先于完成）；
            # 交付是尽力而为——卡死的回调最多拖满有界窗口,不拖结果
            if entry.progress_tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*list(entry.progress_tasks), return_exceptions=True),
                        _PROGRESS_DRAIN_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.debug("progress 回调 %.0fs 未完成, 放弃等待(结果照常交付)",
                                 _PROGRESS_DRAIN_TIMEOUT)
            return result
        finally:
            self._pending.pop(rid, None)
            # 非 success 路径（error 帧/异常/取消）与有界等待超时后遗弃的
            # progress 回调一并取消回收，不留孤儿任务
            for task in list(entry.progress_tasks):
                task.cancel()
            if entry.progress_tasks:
                await asyncio.gather(*list(entry.progress_tasks), return_exceptions=True)

    async def _cancel_quietly(self, req_id: int) -> None:
        try:
            await asyncio.wait_for(self.cancel(req_id), _CANCEL_TIMEOUT)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001  尽力而为
            logger.debug("看门狗 cancel 帧发送失败", exc_info=True)


# ---------- 模块级单例与 adapter ----------

_client_instance: BackendClient | None = None


def get_client() -> BackendClient:
    """进程级单例（全进程共享一条 daemon 连接；测试可重置 ``_client_instance``）。"""
    global _client_instance
    if _client_instance is None:
        _client_instance = BackendClient()
    return _client_instance


def _normalize_scraping_dir(op: str, params: dict[str, Any]) -> None:
    """把 ``scraping_dir`` 归一化为绝对路径（spec 已拍板：相对路径前端归一化）。

    daemon 以 ``cwd="/"`` spawn，payload 里的相对路径——含缺省时 wrapper
    的 ``".temp/scrapling/"`` 默认——会落到 ``/.temp``（非 root 必 EACCES）。
    前端 cwd 即用户 cwd：缺省/空值注入 ``config.scraping_dir`` 的绝对值，
    显式传入值就地 ``expanduser().resolve()``，与 0.2.x 前端直跑语义一致。
    仅 fetch_page 的 wrapper 接受该形参（注入他 op 会触发 payload 键校验
    拒绝）；``_config`` 函数内延迟 import（同 ``_watchdog_window``）。
    """
    if op != "fetch_page":
        return
    from scrapling_fetch_mcp._config import config

    raw = params.get("scraping_dir")
    if raw:
        params["scraping_dir"] = str(Path(raw).expanduser().resolve())
    else:
        params["scraping_dir"] = str(config.scraping_dir.expanduser().resolve())


def make_adapter(op: str) -> Callable[..., Awaitable[str]]:
    """生成 MCP 工具形态的异步函数 ``(ctx=None, **params) -> str``。

    - 客户端取消 → 经 :class:`ActiveCall` 句柄取当前生效 id、短超时尽力发
      cancel 帧 → re-raise（取消必须传播）。
    - ``BackendError`` 的 ``CONCURRENCY_LIMIT`` →
      ``RuntimeError("并发已达上限(全局),请稍后重试: ...")``；
    - 其余 → ``RuntimeError(f"ERROR: {code}: {message}")``（MCP 框架把工具
      异常转 is_error 结果）。
    """

    async def adapter(ctx: Context | None = None, **params: Any) -> str:
        # 单例惰性解析到调用时刻：工厂时刻绑定会被单例重置（测试隔离/热
        # 重载）甩开,adapter 永远拿当前生效的进程级实例
        client = get_client()
        # 取消句柄：call 内部重试会换新 id，cancel 必须命中当前生效的请求 id
        # （预分配 id 在重试后已不对应任何在途任务）
        active = ActiveCall()
        _normalize_scraping_dir(op, params)
        try:
            resp = await client.call(op, params, ctx, active=active)
        except asyncio.CancelledError:
            if active.req_id is not None:
                try:
                    await asyncio.wait_for(client.cancel(active.req_id), _CANCEL_TIMEOUT)
                except Exception:  # noqa: BLE001  收尾尽力而为,绝不拦取消传播
                    logger.debug("取消收尾: cancel 帧未送达", exc_info=True)
            raise
        except BackendError as exc:
            if exc.code == CODE_CONCURRENCY_LIMIT:
                raise RuntimeError(f"并发已达上限(全局),请稍后重试: {exc.message}") from exc
            raise RuntimeError(f"ERROR: {exc.code}: {exc.message}") from exc
        return resp["result"]

    return adapter
