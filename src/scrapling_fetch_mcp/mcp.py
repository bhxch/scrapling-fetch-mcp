import sys
import time
from argparse import ArgumentParser
from logging import getLogger
from pathlib import Path

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer

from scrapling_fetch_mcp._auth import StaticTokenVerifier
from scrapling_fetch_mcp._client import make_adapter
from scrapling_fetch_mcp._config import config, init_config_from_env
from scrapling_fetch_mcp._features import (
    FEATURES,
    TOOL_PARAMS,
    S_FETCH_PAGE_DOCSTRING,
    S_FETCH_PATTERN_DOCSTRING,
)
from scrapling_fetch_mcp._skills import SKILL_URI, build_extension
from scrapling_fetch_mcp._tool_factory import build_tool_function
from scrapling_fetch_mcp.daemon.config_env import resolve_daemon_env
from scrapling_fetch_mcp.daemon.lifecycle import daemon_sockets, read_lock, socket_name, transact
from scrapling_fetch_mcp.daemon.paths import daemon_dir
from scrapling_fetch_mcp.daemon.protocol import OP_SHUTDOWN, OP_STATUS

_skill_extension = build_extension()

SERVER_INSTRUCTIONS = (
    "Fetch pages with s_fetch_page / s_fetch_pattern. Prefer "
    "format='airead'. Load skill " + SKILL_URI + " via the skills "
    "extension for detailed fetching workflows."
)


def _build_mcp(**kwargs) -> MCPServer:
    """Single MCPServer construction point.

    Keeps instructions and the skills extension identical between the
    module-level default instance and the auth rebuild branch in
    run_server(); extra kwargs (token_verifier/auth) are passed through.
    """
    return MCPServer(
        "scrapling-fetch-mcp",
        instructions=SERVER_INSTRUCTIONS,
        extensions=[_skill_extension] if _skill_extension else [],
        **kwargs,
    )


mcp = _build_mcp()


def _register_tool(name, param_configs, base_docstring, impl_func):
    """Build a dynamic tool function and register it with MCPServer."""
    func = build_tool_function(
        tool_name=name,
        param_configs=param_configs,
        enabled_features=config.enabled_features,
        base_docstring=base_docstring,
        impl_func=impl_func,
        config=config,
    )
    mcp.tool()(func)


# ---------------------------------------------------------------- daemon 管理 CLI

# 发出 shutdown 后等待 daemon 退出的期限。worker 对 status/shutdown 一律
# 内联即时应答，5s 无响应即视为已死（与 lifecycle.transact 的默认超时一致）。
_SHUTDOWN_EXIT_WAIT = 5.0


def _fmt(value: object) -> str:
    """表格单元格：None → "-"。"""
    return "-" if value is None else str(value)


def _daemon_status() -> int:
    """清点 daemon 目录下全部 socket，表格输出；恒返回 0。

    每个 socket：读 lock 取 token → 发 status 请求（同一鉴权）；无 lock 或
    5s 无响应即标 DEAD（进程已死的 sock/lock 残留），表尾提示 `shutdown --all`
    清场。
    """
    socks = daemon_sockets()
    if not socks:
        print("无存活 daemon")
        return 0
    print(
        f"{'SOCKET':<44} {'PKG':<8} {'HASH':<8} {'PID':>7} "
        f"{'UPTIME':>9} {'CLIENTS':>7} {'CACHE':>6}  STATUS"
    )
    any_dead = False
    for sock in socks:
        lock = read_lock(sock) or {}
        resp = transact(sock, OP_STATUS, str(lock.get("token") or ""))
        if resp is None:
            any_dead = True
            print(
                f"{sock.name:<44} {_fmt(lock.get('pkg')):<8} {_fmt(lock.get('config_hash')):<8} "
                f"{_fmt(lock.get('pid')):>7} {'-':>9} {'-':>7} {'-':>6}  DEAD"
            )
            continue
        r = resp.get("result") or {}
        print(
            f"{sock.name:<44} {_fmt(r.get('pkg')):<8} {_fmt(r.get('config_hash')):<8} "
            f"{_fmt(r.get('pid')):>7} {_fmt(r.get('uptime_s')):>9} "
            f"{_fmt(r.get('clients')):>7} {_fmt(r.get('cache_entries')):>6}  ready"
        )
    if any_dead:
        print("存在失效 socket（进程已死但 sock/lock 残留），执行 `daemon shutdown --all` 可清理")
    return 0


def _shutdown_socket(sock: Path) -> bool:
    """停掉单个 socket 指向的 daemon；返回是否处理成功。

    正常路径：lock 取 token → shutdown 请求 → 轮询等待 sock 消失（worker
    退出时统一清理 lock 与 sock）。无 lock/5s 无响应：活 daemon 不可能超时，
    按死残留直接清理 sock/lock（`--all` 清场的兜底语义）。
    """
    lock = read_lock(sock)
    resp = None if lock is None else transact(sock, OP_SHUTDOWN, str(lock.get("token") or ""))
    if resp is None:
        for path in (sock, sock.with_suffix(".lock")):
            try:
                path.unlink()
            except OSError:
                pass  # 已被并发清理等;清理尽力而为
        print(f"{sock.name}: 无响应, 已清理残留 sock/lock")
        return True
    deadline = time.monotonic() + _SHUTDOWN_EXIT_WAIT
    while sock.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    if sock.exists():
        print(f"{sock.name}: 已接受退出请求但超时未退出", file=sys.stderr)
        return False
    return True


def _daemon_shutdown(args) -> int:
    """shutdown 分支：--all 清场 / --socket 定点 / 默认仅当前版本+配置。"""
    if args.all:
        socks = daemon_sockets()
        if not socks:
            print("无存活 daemon")
            return 0
        return 0 if all(_shutdown_socket(sock) for sock in socks) else 1
    if args.socket:
        name = args.socket.removesuffix(".sock")
        sock = daemon_dir() / f"{name}.sock"
    else:
        _spawn_env, config_hash = resolve_daemon_env()
        sock = daemon_dir() / f"{socket_name(config_hash)}.sock"
    if not sock.exists():
        print(f"未找到目标 daemon: {sock.name}")
        return 1
    return 0 if _shutdown_socket(sock) else 1


def _daemon_main(argv: list[str]) -> int:
    """``daemon status|shutdown`` 子命令入口；返回进程退出码。

    独立 ArgumentParser，不与 MCP 参数共享命名空间。status 恒退出 0；
    shutdown 找不到目标退出 1。
    """
    parser = ArgumentParser(
        prog="scrapling-fetch-mcp daemon",
        description="管理后台抓取 daemon（status 查看 / shutdown 停止）",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="表格列出全部 daemon（版本/配置/pid/缓存）")
    sp = sub.add_parser("shutdown", help="停止 daemon（默认仅当前版本+配置）")
    group = sp.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true",
                       help="停止全部 daemon 并清理残留（含其他版本/配置）")
    group.add_argument("--socket", metavar="SOCK",
                       help="只处理指定 socket 名（可带 .sock 后缀）")
    args = parser.parse_args(argv)
    if args.command == "status":
        return _daemon_status()
    return _daemon_shutdown(args)


def run_server():
    """Parse CLI arguments and start the MCP server"""
    # `daemon` 管理子命令分流：在 MCP 参数解析前拦截，处理完即退出，MCP 路径零改动
    if sys.argv[1:2] == ["daemon"]:
        sys.argv.pop(1)
        sys.exit(_daemon_main(sys.argv[1:]))
    global mcp
    parser = ArgumentParser(
        description="Scrapling Fetch MCP Server - Fetch web content with bot-detection avoidance"
    )
    parser.add_argument(
        "--min-mode",
        choices=["basic", "stealth", "max-stealth"],
        help="Minimum fetching mode level. All requests will use at least this mode, "
        "preventing multiple retries from basic to higher modes. "
        "Can also be set via SCRAPLING_MIN_MODE environment variable.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=300,
        help="Cache time-to-live in seconds for fetched pages. "
        "When fetching large pages in segments, this prevents repeated requests to the same URL. "
        "Set to 0 to disable caching. Default: 300 (5 minutes). "
        "Can also be set via SCRAPLING_CACHE_TTL environment variable.",
    )
    parser.add_argument(
        "--scraping-dir",
        type=str,
        default=".temp/scrapling/",
        help="Default directory for saving scraped content (HTML + images). "
        "Can be overridden per-request with scraping_dir parameter. "
        "Default: .temp/scrapling/ "
        "Can also be set via SCRAPLING_DIR environment variable.",
    )
    parser.add_argument(
        "--markdown-converter",
        choices=["markitdown", "markdownify"],
        default="markitdown",
        help="Markdown converter library to use. Default: markitdown. "
        "Can also be set via SCRAPLING_MARKDOWN_CONVERTER environment variable.",
    )
    parser.add_argument(
        "--rules-config",
        type=str,
        default=None,
        help="Path to YAML file with airead format URL routing rules. "
        "Default: Use built-in rules. "
        "Can also be set via SCRAPLING_RULES_CONFIG environment variable.",
    )
    parser.add_argument(
        "--default-format",
        choices=["airead", "markdown", "html"],
        default="markdown",
        help="Default output format for fetch operations. "
        "s_fetch_page supports: airead, markdown, html. "
        "s_fetch_pattern will use markdown if default is airead. "
        "Default: markdown. "
        "Can also be set via SCRAPLING_DEFAULT_FORMAT environment variable.",
    )
    parser.add_argument(
        "--disable-url-rewrite",
        action="store_true",
        help="Disable automatic URL rewriting. Default: enabled.",
    )
    parser.add_argument(
        "--url-rewrite-config",
        type=str,
        default=None,
        help="Path to YAML file with custom URL rewrite rules.",
    )
    parser.add_argument(
        "--disable-features",
        type=str,
        default="",
        help="Comma-separated list of features to disable. "
        "Available features: stealth, format, pagination, save. "
        "Can also be set via SCRAPLING_DISABLE_FEATURES environment variable.",
    )
    parser.add_argument(
        "--enable-features",
        type=str,
        default="",
        help="Comma-separated list of features to enable. "
        "Available features: stealth, format, pagination, save. "
        "Can also be set via SCRAPLING_ENABLE_FEATURES environment variable.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default=None,
        help="Transport protocol. Default: stdio. "
        "Can also be set via SCRAPLING_TRANSPORT environment variable.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Bind host for streamable-http. Default: 127.0.0.1. "
        "Can also be set via SCRAPLING_HOST environment variable.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for streamable-http. Default: 8000. "
        "Can also be set via SCRAPLING_PORT environment variable.",
    )
    parser.add_argument(
        "--mcp-path",
        type=str,
        default=None,
        help="URL path for streamable-http. Default: /mcp. "
        "Can also be set via SCRAPLING_MCP_PATH environment variable.",
    )
    parser.add_argument(
        "--auth-token",
        type=str,
        default=None,
        help="Bearer token for streamable-http auth. Empty = no auth. "
        "Can also be set via SCRAPLING_AUTH_TOKEN environment variable.",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=None,
        help="Max concurrent fetches (semaphore). Default: 5. "
        "Can also be set via SCRAPLING_MAX_CONCURRENT environment variable.",
    )
    parser.add_argument(
        "--acquire-timeout",
        type=float,
        default=None,
        help="Seconds to wait for a concurrency slot before failing. Default: 30. "
        "Can also be set via SCRAPLING_ACQUIRE_TIMEOUT environment variable.",
    )
    parser.add_argument(
        "--fetch-timeout",
        type=float,
        default=None,
        help="Seconds before a single fetch is aborted. Default: 60. "
        "Can also be set via SCRAPLING_FETCH_TIMEOUT environment variable.",
    )
    parser.add_argument(
        "--browser-pool",
        action="store_true",
        help="启用浏览器会话池，跨请求复用会话以降低启动开销。默认关闭。"
        "也可通过 SCRAPLING_BROWSER_POOL 环境变量（true/1/yes）设置。",
    )
    parser.add_argument(
        "--pool-idle-ttl",
        type=float,
        default=None,
        help="池中浏览器会话空闲多久后回收（秒）。默认: 300。"
        "也可通过 SCRAPLING_POOL_IDLE_TTL 环境变量设置。",
    )
    parser.add_argument(
        "--pool-max-age",
        type=float,
        default=None,
        help="池中浏览器会话最长存活时间（秒），到期强制回收。默认: 1800。"
        "也可通过 SCRAPLING_POOL_MAX_AGE 环境变量设置。",
    )
    parser.add_argument(
        "--pool-max-sessions",
        type=int,
        default=None,
        help="浏览器会话池容量上限。默认: 4。"
        "也可通过 SCRAPLING_POOL_MAX_SESSIONS 环境变量设置。",
    )
    parser.add_argument(
        "--pool-max-requests",
        type=int,
        default=None,
        help="池中单个浏览器会话服务多少次请求后回收。默认: 50。"
        "也可通过 SCRAPLING_POOL_MAX_REQUESTS 环境变量设置。",
    )
    args = parser.parse_args()


    # Initialize from environment first
    init_config_from_env()

    # CLI args override environment variables
    if args.min_mode:
        config.set_min_mode(args.min_mode)

    if args.cache_ttl is not None:
        config.set_cache_ttl(args.cache_ttl)

    if args.scraping_dir:
        config.set_scraping_dir(args.scraping_dir)

    if args.markdown_converter:
        config.set_markdown_converter(args.markdown_converter)

    if args.rules_config:
        config.set_rules_config_path(args.rules_config)

    if args.default_format:
        config.set_default_format(args.default_format)

    if args.disable_url_rewrite:
        config.set_disable_url_rewrite(True)

    if args.url_rewrite_config:
        config.set_url_rewrite_config_path(args.url_rewrite_config)

    if args.transport is not None:
        config.set_transport(args.transport)
    if args.host is not None:
        config.set_host(args.host)
    if args.port is not None:
        config.set_port(args.port)
    if args.mcp_path is not None:
        config.set_mcp_path(args.mcp_path)
    if args.auth_token is not None:
        config.set_auth_token(args.auth_token)
    if args.max_concurrent is not None:
        config.set_max_concurrent(args.max_concurrent)
    if args.acquire_timeout is not None:
        config.set_acquire_timeout(args.acquire_timeout)
    if args.fetch_timeout is not None:
        config.set_fetch_timeout(args.fetch_timeout)

    if args.browser_pool:
        config.set_browser_pool(True)
    if args.pool_idle_ttl is not None:
        config.set_pool_idle_ttl(args.pool_idle_ttl)
    if args.pool_max_age is not None:
        config.set_pool_max_age(args.pool_max_age)
    if args.pool_max_sessions is not None:
        config.set_pool_max_sessions(args.pool_max_sessions)
    if args.pool_max_requests is not None:
        config.set_pool_max_requests(args.pool_max_requests)

    # Resolve features (merge env raw values + CLI args, call once)
    disable_cli_list = [f.strip() for f in args.disable_features.split(",") if f.strip()]
    enable_cli_list = [f.strip() for f in args.enable_features.split(",") if f.strip()]
    disable_list = config._disable_features_raw + disable_cli_list
    enable_list = config._enable_features_raw + enable_cli_list
    config.resolve_features(disable_list, enable_list)

    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    logger.info(f"Minimum mode set to: {config.min_mode}")
    logger.info(f"Cache TTL set to: {config.cache_ttl} seconds")
    logger.info(f"Scraping directory set to: {config.scraping_dir}")
    logger.info(f"Markdown converter set to: {config.markdown_converter}")
    logger.info(f"Default format set to: {config.default_format}")
    logger.info(f"URL rewrite: {'disabled' if config.disable_url_rewrite else 'enabled'}")

    # Log feature status
    all_features = set(FEATURES.keys())
    logger.info(f"Features enabled: {sorted(config.enabled_features)}")
    logger.info(f"Features disabled: {sorted(all_features - config.enabled_features)}")

    logger.info(f"Transport: {config.transport}")
    if config.transport == "streamable-http":
        logger.info(f"Bind: {config.host}:{config.port}{config.mcp_path}")
        logger.info(f"Auth: {'enabled' if config.auth_token else 'disabled'}")
    logger.info(f"Concurrency: max={config.max_concurrent}, timeout={config.acquire_timeout}s")

    # daemon-owned 配置热身：归一化 + 摘要在启动时先算一遍（无 IO、不拉起
    # daemon），尽早暴露配置问题。daemon 拉起与浏览器准备全部移入 daemon
    # 侧 worker（__main__.py），前端不再 import _browser_check。
    resolve_daemon_env()

    # When auth is enabled, (re)build the MCPServer with a token verifier.
    # MUST happen before registering tools so they bind to the authed instance.
    if config.transport == "streamable-http" and config.auth_token:
        mcp = _build_mcp(
            token_verifier=StaticTokenVerifier(config.auth_token),
            auth=AuthSettings(
                issuer_url=f"http://{config.host}:{config.port}/",
                resource_server_url=f"http://{config.host}:{config.port}/",
                # 静态共享密钥 verifier 自身即校验 token,无 resource 绑定
                # 概念;显式 False 消除 SDK 2.2+ 的 MCPDeprecationWarning,
                # 并锁定与 2.x 相同的行为(3.0 将默认 True)。
                validate_token_resource=False,
            ),
        )

    # Build and register tools dynamically (registers onto the current global mcp).
    # 抓取改走 daemon：impl 为 BackendClient adapter（进度桥接/取消/错误映射
    # 均在 make_adapter 内部），前端不再 import _fetcher 重链。
    _register_tool(
        "s_fetch_page",
        TOOL_PARAMS["s_fetch_page"],
        S_FETCH_PAGE_DOCSTRING,
        make_adapter("fetch_page"),
    )
    _register_tool(
        "s_fetch_pattern",
        TOOL_PARAMS["s_fetch_pattern"],
        S_FETCH_PATTERN_DOCSTRING,
        make_adapter("fetch_pattern"),
    )

    # Start the server with the selected transport
    if config.transport == "streamable-http":
        if not config.auth_token and config.host not in ("127.0.0.1", "localhost"):
            logger.warning(
                "streamable-http 无鉴权且绑定非本地地址 (%s)，存在未授权访问风险",
                config.host,
            )
        mcp.run(
            transport="streamable-http",
            host=config.host,
            port=config.port,
            streamable_http_path=config.mcp_path,
        )
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    run_server()
