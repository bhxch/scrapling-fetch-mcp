# HTTP（Streamable-HTTP）传输与并发控制 设计

- **日期**：2026-08-05
- **状态**：已批准（brainstorming 产出，待实现）
- **关联**：scrapling-fetch-mcp

## 1. 背景与动机

当前 scrapling-fetch-mcp 仅支持 stdio 传输：

```python
# src/scrapling_fetch_mcp/mcp.py:192
mcp.run(transport="stdio")
```

只能由本地 MCP 客户端经子进程标准输入输出通信，无法被远程客户端（claude.ai、其他机器上的 Claude Code 等）访问。

需求：

1. 新增 HTTP 传输模式（采用 MCP 标准的 **streamable-http**），使远程 MCP 客户端可经网络连接；
2. 解决多客户端**并发访问**带来的资源耗尽与安全问题（浏览器实例重，无控制会 OOM / 被目标站封禁）。

> 说明：MCP 协议的标准远程传输是 streamable-http（HTTP + SSE 服务器推送），并非 WebSocket。用户原始诉求中的「websocket」泛指「网络实时双向访问」，在 MCP 兼容前提下由 streamable-http 满足，故不单独引入 WebSocket 传输。

## 2. 目标与非目标

### 目标

- 保留 stdio（默认），新增 streamable-http 传输，由配置选择；
- 远程访问的**鉴权、绑定地址、TLS 策略全部可配置**；
- 并发访问受控：**全局信号量限流 + 排队等待 + 超时**，防止浏览器资源耗尽。

### 非目标（YAGNI，明确不做）

- 浏览器实例池化 / 复用；
- 按模式或按客户端分组限流；
- OAuth provider（静态 token 已覆盖内网/个人场景）；
- 进程内 TLS（由前置反向代理终结）；
- 监控 / 状态查询 endpoint；
- 多进程 worker（uvicorn 多 worker）；
- WebSocket 传输。

## 3. 现状分析

| 维度 | 现状 |
|---|---|
| 入口 | `mcp.py:run_server()`，`MCPServer("scrapling-fetch-mcp")`，硬编码 `mcp.run(transport="stdio")` |
| 工具 | `s_fetch_page`、`s_fetch_pattern`，动态注册（`_tool_factory.py`） |
| 抓取 | `_scrapling.py:browse_url`：每次请求新建 `AsyncFetcher`/`StealthyFetcher`，无连接池，无共享浏览器 |
| 浏览器开销 | `stealth`/`max-stealth` 用 camoufox/playwright，单进程数百 MB |
| 缓存 | `_config.py:PageCache`：普通 dict + TTL，同步 get/set |
| 并发 | 全 `async`，**零控制**（无锁 / 信号量 / 队列） |
| 配置 | 环境变量 + CLI 参数，`Config` 单例，CLI 优先 |
| 测试 | pytest + pytest-asyncio |
| 依赖 | mcp 2.0.0（已含 `streamable_http`、`sse_starlette`、`auth/middleware`、uvicorn） |

**关键发现**：mcp SDK 2.0.0 的 `MCPServer.run()` 原生支持三种传输：

```python
def run(self, transport: Literal["stdio","sse","streamable-http"] = "stdio", *,
        host: str = "127.0.0.1", port: int = 8000,
        streamable_http_path: str = "/mcp", ...): ...
```

并内置 bearer token 鉴权（`TokenVerifier` / `BearerAuthBackend` / `AuthSettings`）与 starlette middleware。HTTP server、SSE 推送、session 管理、uvicorn、鉴权中间件**均无需自研**。

结论：本设计的实质新增工作只有**并发控制层**，其余为「配置接线 + 鉴权校验器」。

## 4. 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 传输场景 | 远程 MCP，兼容 MCP 协议 | 复用 SDK 与现有工具层；streamable-http 是 MCP 标准远程传输 |
| 部署 / 鉴权 / TLS | 全部可配置开关 | 适配本地 / 内网 / 公网，沿用 env + CLI 风格 |
| 并发策略 | 全局信号量 + 排队等待 + 超时 | 简单有效，保护重资源，不丢请求 |
| 实现方案 | A：最小集成 | 最大化复用 SDK，改动聚焦，风险低 |
| 默认 transport | **stdio** | 向后兼容，现有行为完全不变 |

## 5. 设计

### 5.1 整体架构与传输层

**原则**：工具注册与实现**零改动**，所有变化集中在 `run_server()` 启动分支与 `MCPServer` 构造的鉴权参数。

启动分支（替换原 `mcp.run(transport="stdio")`）：

```python
if config.transport == "stdio":
    mcp.run(transport="stdio")
elif config.transport == "streamable-http":
    mcp.run(
        transport="streamable-http",
        host=config.host,                      # 默认 "127.0.0.1"
        port=config.port,                      # 默认 8000
        streamable_http_path=config.mcp_path,  # 默认 "/mcp"
        token_verifier=token_verifier,         # auth_token 非空时为 StaticTokenVerifier，否则 None
        auth=auth_settings,                    # 同上：非空时 AuthSettings，否则 None
    )
```

**TLS 策略**：生产 HTTPS 由前置反向代理（nginx / caddy）终结 TLS，进程内不做 TLS，避免证书管理复杂度。文档给出反代示例。进程内 TLS（`--ssl-certfile`）列为未来扩展，暂不实现。

**复用关系**：HTTP server、SSE 推送、session 管理、uvicorn、鉴权中间件——全部来自 mcp SDK，不重写。

### 5.2 并发控制层（核心）

**问题**：streamable-http 下多客户端可并发调用；`stealth`/`max-stealth` 每次新建浏览器进程，N 并发 = N 浏览器进程，易 OOM / 被封。

**并发模型**：uvicorn 单进程单 event loop，并发是**协程级**（多个 tool call 同时 in-flight），故用 `asyncio.Semaphore`，不用 threading 原语。

**新组件**：`_concurrency.py`

```python
class ConcurrencyLimitError(Exception):
    """并发已达上限且等待超时。"""


class ConcurrencyGuard:
    """全局并发限流器：信号量 + 排队等待 + 超时。"""

    def __init__(self, max_concurrent: int, acquire_timeout: float):
        self._sem = asyncio.Semaphore(max_concurrent)
        self._timeout = acquire_timeout
        self._max = max_concurrent
        self.in_flight = 0        # 当前占用（指标）
        self.total_acquired = 0   # 累计获取（指标）

    async def __aenter__(self):
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise ConcurrencyLimitError(
                f"并发已达上限({self._max})，等待 {self._timeout}s 超时"
            )
        self.in_flight += 1
        self.total_acquired += 1
        return self

    async def __aexit__(self, *exc):
        self.in_flight -= 1
        self._sem.release()   # 异常路径也释放
```

**接入点**：包在 `_scrapling.py:browse_url` 外层（唯一接触浏览器处）。

```python
_guard: ConcurrencyGuard | None = None

def init_guard(max_concurrent: int, acquire_timeout: float) -> None:
    global _guard
    _guard = ConcurrencyGuard(max_concurrent, acquire_timeout)

async def browse_url(url, mode, page_action=None):
    if _guard is None:
        return await _do_browse(url, mode, page_action)
    async with _guard:                       # 占槽 → 抓取 → 释放（含异常）
        return await _do_browse(url, mode, page_action)
```

**关键决策**：

1. **全局单一信号量**：所有模式、所有客户端共享一个上限。简单、防目标站频控。
2. **basic 模式也纳入限流**：虽为纯 HTTP 较轻，但统一限流防频控、行为一致；basic 很快不会久占槽。
3. **接入 `browse_url` 而非 `fetch_page_impl`**：粒度最细，槽利用率最高；每次浏览器调用独立计槽。
4. **stdio 下也启用 guard**：MCP 客户端可在单连接上并发发多个 tool call，不限流同样会打爆资源；guard 成本极低，故**无论 transport 都 `init_guard`**。
5. **超时 → `ConcurrencyLimitError`**：工具层捕获，转成 MCP error result 返回客户端，**不崩溃进程**。
6. **指标**：`in_flight` / `total_acquired`，启动日志打印配置；状态查询接口暂不做（YAGNI）。

### 5.3 配置项

`_config.py` 的 `Config` 单例扩展，沿用「env + CLI 双通道、CLI 优先」：

| 配置项 | env | CLI | 默认 | 说明 |
|---|---|---|---|---|
| transport | `SCRAPLING_TRANSPORT` | `--transport` | `stdio` | `stdio` / `streamable-http` |
| host | `SCRAPLING_HOST` | `--host` | `127.0.0.1` | 绑定地址 |
| port | `SCRAPLING_PORT` | `--port` | `8000` | 端口 |
| mcp_path | `SCRAPLING_MCP_PATH` | `--mcp-path` | `/mcp` | streamable-http 路径 |
| auth_token | `SCRAPLING_AUTH_TOKEN` | `--auth-token` | （空） | bearer token；空 = 无鉴权 |
| max_concurrent | `SCRAPLING_MAX_CONCURRENT` | `--max-concurrent` | `5` | 并发上限 |
| acquire_timeout | `SCRAPLING_ACQUIRE_TIMEOUT` | `--acquire-timeout` | `30` | 等待超时（秒） |

### 5.4 鉴权

`_auth.py` 实现 `StaticTokenVerifier`，满足 mcp SDK 的 `TokenVerifier` 协议：校验请求的 `Authorization: Bearer <token>` 是否等于配置的 `auth_token`。

- **启用条件**：`transport != "stdio"` 且 `auth_token` 非空；
- **安全警示**：当 `transport == "streamable-http"` 且 `auth_token` 为空 且 `host != "127.0.0.1"` 时，启动期输出 warning 日志，提示无鉴权暴露在非本地；
- **鉴权失败**：由 SDK 的 `BearerAuthBackend` / `RequireAuthMiddleware` 自动返回 401，无需额外处理。

> `TokenVerifier` 的精确方法签名以 mcp 2.0.0 SDK 实际接口为准，实现时对齐。

### 5.5 缓存安全

`_config.py:PageCache` 当前为同步 get/set。在单 event loop 下，若方法体内不含 `await`，则执行是原子的、天然安全。实现时**审计所有调用点**：

- 若全部在同步段（无跨 `await` 竞态）→ 保持现状，无需加锁；
- 若存在跨 `await` 竞态 → 加 `asyncio.Lock` 保护。

不过度设计。

### 5.6 错误处理

- `ConcurrencyLimitError`（并发超时）→ 工具层 catch → MCP error result，不抛崩；
- 浏览器抓取异常 → 维持现有错误传播，不额外包装；
- 启动期校验：`transport` 非法 / `port` 越界 / 配置冲突 → 清晰报错并退出。

## 6. 文件改动清单

| 文件 | 改动 |
|---|---|
| `src/scrapling_fetch_mcp/_concurrency.py`（新） | `ConcurrencyGuard`、`ConcurrencyLimitError` |
| `src/scrapling_fetch_mcp/_auth.py`（新） | `StaticTokenVerifier` |
| `src/scrapling_fetch_mcp/mcp.py` | 新增 transport/host/port/mcp_path/auth_token/max_concurrent/acquire_timeout 的 CLI + env；`run()` 分支；`init_guard` 调用；构造 `token_verifier` / `auth` |
| `src/scrapling_fetch_mcp/_config.py` | `Config` 新增 7 项配置 + setter；`init_config_from_env` 扩展；`PageCache` 审计 |
| `src/scrapling_fetch_mcp/_scrapling.py` | `browse_url` 接入 guard；新增 `init_guard` |
| `pyproject.toml` | mcp 已含传输依赖；如 `uvicorn`/`starlette` 未显式声明则补（已被 mcp 间接依赖） |
| `tests/test_concurrency.py`（新） | `ConcurrencyGuard` 单元测试 |
| `tests/test_auth.py`（新） | `StaticTokenVerifier` 测试 |
| `tests/test_config.py`（扩展） | 7 项新配置的加载、默认值、优先级 |
| `tests/test_mcp_registration.py`（扩展） | transport 分支、鉴权启用条件 |
| `README.md` / `MCP_CONFIG_EXAMPLES.md` | streamable-http 配置示例、反代 TLS 说明 |

## 7. 测试策略

延续 pytest + pytest-asyncio：

- **`test_concurrency.py`（新）**：并发 N 个协程验证 `in_flight` 不超 `max`；acquire 超时抛 `ConcurrencyLimitError`；异常路径正确释放槽位；指标计数正确。
- **`test_auth.py`（新）**：`StaticTokenVerifier` 正确 / 错误 token 的校验结果。
- **`test_config.py`（扩展）**：7 项新配置的 env / CLI 加载、默认值、CLI 优先 env。
- **`test_mcp_registration.py`（扩展）**：transport 分支选择、鉴权启用条件（stdio 不鉴权、http+token 鉴权、http 无 token 警示）。
- **集成测试（手动 / 可选）**：起 streamable-http 实例，httpx 连 `/mcp` 调用两个工具；并发压测验证限流（超上限排队、超时返回错误）。
- **回归**：现有测试全绿。

## 8. 验收标准

1. 默认 `stdio` 行为与现状完全一致（现有测试全绿，无行为变更）；
2. `--transport streamable-http` 启动后，MCP / httpx 客户端可连 `http://host:port/mcp` 调用两个工具；
3. 配 `auth_token` 时：错误 token → 401，正确 token → 可用；
4. 并发压测：超过 `max_concurrent` 的请求排队，超 `acquire_timeout` 返回错误，`in_flight` 永不超上限；
5. 浏览器异常 / 并发超时**不导致进程崩溃**；
6. 7 项新配置 env / CLI 均生效，CLI 优先于 env；
7. `transport=http` + 无 token + 非 localhost 启动时输出 warning。

## 9. 部署示例

**stdio（默认，不变）**：

```json
{
  "mcpServers": {
    "scrapling-fetch": { "command": "uvx", "args": ["scrapling-fetch-mcp"] }
  }
}
```

**streamable-http（本地）**：

```bash
scrapling-fetch-mcp --transport streamable-http --port 8000
```

**streamable-http（内网 + 鉴权）**：

```bash
scrapling-fetch-mcp --transport streamable-http --host 0.0.0.0 --port 8000 --auth-token SECRET
```

**公网 TLS（caddy 反代终结）**：

```caddyfile
mcp.example.com {
  reverse_proxy localhost:8000
}
```

## 10. 未来扩展（暂不实现）

- 浏览器实例池化 / 复用（提升吞吐，需 scrapling 支持实例注入）；
- 按模式分组信号量（basic 与 stealth 分开上限）；
- 按客户端 / session 限流；
- OAuth authorization server provider；
- 进程内 TLS（`--ssl-certfile` / `--ssl-keyfile` 透传 uvicorn）；
- 监控 / 状态查询 endpoint（暴露 `in_flight` 等指标）。
