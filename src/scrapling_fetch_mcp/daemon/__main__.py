"""``python -m scrapling_fetch_mcp.daemon`` 入口：daemon worker 启动序列。

序列（spec 定序）：win32 拒绝 → ``init_config_from_env()``（daemon-owned env
已由 spawn 注入）→ ``resolve_daemon_env()`` 自算 config_hash（唯一身份来
源，绝不读 spawn/用户环境里的 ``SCRAPLING_DAEMON_CONFIG_HASH``——那是
lifecycle 测试喂给 fake_worker 的专用键，残留会让 socket 身份与前端自算
永久不符、陷入无休止重拉）→
``ensure_browserforge_data()``（阻塞，秒级）→ ``ensure_camoufox()``（内部
后台线程，不阻塞）→ ``init_guard`` → 经 :class:`~scrapling_fetch_mcp.daemon.
worker.DaemonWorker` 写 lock（``secrets.token_hex(16)``）→
``start_unix_server(limit=64MiB)`` → chmod 0600 → serve。

SIGTERM/SIGINT → 优雅退出（关 server、删 lock），退出码 0——lifecycle 的
spawn fixture 收尸与管理 CLI 依赖此行为。

重依赖 import 全部收敛在 ``main()`` 内：win32 检查必须先于它们执行，
且轻量 import 本模块（如 win32 拒绝的单测）不牵入项目配置链。
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

logger = logging.getLogger("scrapling_fetch_mcp.daemon")


def main() -> int:
    if sys.platform == "win32":
        raise RuntimeError("daemon 模式依赖 unix socket, 暂不支持 Windows")

    # 重依赖 import 收敛在 win32 检查之后（见模块 docstring）
    from scrapling_fetch_mcp._browser_check import ensure_browserforge_data, ensure_camoufox
    from scrapling_fetch_mcp._config import config, init_config_from_env
    from scrapling_fetch_mcp._scrapling import init_guard
    from scrapling_fetch_mcp.daemon import worker as worker_mod
    from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
    from scrapling_fetch_mcp.daemon.lifecycle import socket_name
    from scrapling_fetch_mcp.daemon.paths import daemon_dir

    # stdout/stderr 由 lifecycle 重定向到 <name>.log，日志是启动失败的唯一线索
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    init_config_from_env()
    # config_hash 唯一来源：本进程 env 自算。SCRAPLING_DAEMON_CONFIG_HASH 是
    # lifecycle 测试喂给 fake_worker 的专用键（fake worker 无法自算），真
    # worker 绝不消费——用户 env 残留该键时按它绑定 socket 会与前端自算
    # hash 永久不符，身份不符→误判陈旧→无休止重拉循环。
    _spawn_env, self_hash = resolve_daemon_env()
    sock = daemon_dir() / f"{socket_name(self_hash)}.sock"

    logger.info("daemon 启动: sock=%s", sock)
    ensure_browserforge_data()
    ensure_camoufox()
    init_guard(config.max_concurrent, config.acquire_timeout)

    daemon = worker_mod.DaemonWorker(
        sock,
        idle_timeout=config.daemon_idle_timeout,
        config_hash=self_hash,
    )
    asyncio.run(_serve(daemon))
    return 0


async def _serve(daemon) -> None:
    """在运行中的事件循环里装信号处理器后进入 serve。"""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, daemon.request_shutdown)
        except (NotImplementedError, RuntimeError):
            pass  # 非 unix 平台/无权限时忽略；win32 已在入口拒绝
    await daemon.serve()


if __name__ == "__main__":
    raise SystemExit(main())
