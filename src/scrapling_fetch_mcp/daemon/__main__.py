"""``python -m scrapling_fetch_mcp.daemon`` 入口：daemon worker 启动序列。

序列（spec 定序）：win32 拒绝 → ``init_config_from_env()``（daemon-owned env
已由 spawn 注入）→ ``normalize_daemon_values()`` 自算 config_hash 并与
spawn 侧注入的期望 hash（``SCRAPLING_DAEMON_CONFIG_HASH``）防御比对（不一致
仅日志告警不退出——按期望 hash 绑定 socket 保证前端找得到）→
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
import os
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
    _spawn_env, self_hash = resolve_daemon_env()
    expected_hash = os.environ.get("SCRAPLING_DAEMON_CONFIG_HASH", "") or self_hash
    if expected_hash != self_hash:
        # 防御比对：spawn 侧与 daemon 侧对同 env 的解析分叉（理论上不应发生）。
        # 仅告警不退出——按期望 hash 绑定 socket，前端才能连上并继续工作。
        logger.warning(
            "config_hash 防御比对不一致: 期望 %s, 自算 %s (按期望值继续)",
            expected_hash, self_hash,
        )
    sock = daemon_dir() / f"{socket_name(expected_hash)}.sock"

    logger.info("daemon 启动: sock=%s", sock)
    ensure_browserforge_data()
    ensure_camoufox()
    init_guard(config.max_concurrent, config.acquire_timeout)

    daemon = worker_mod.DaemonWorker(
        sock,
        idle_timeout=config.daemon_idle_timeout,
        config_hash=expected_hash,
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
