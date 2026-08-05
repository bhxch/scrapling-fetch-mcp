# Streamable-HTTP 传输与并发控制 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留 stdio 默认的前提下，新增 MCP 标准的 streamable-http 远程传输（可选 bearer 鉴权），并用全局信号量 + 排队超时控制并发抓取，防止浏览器资源耗尽。

**Architecture:** 复用 mcp SDK 2.0.0 内置的 streamable-http 传输与 `TokenVerifier` 鉴权；工具注册与实现零改动，所有变化集中在「启动配置（`mcp.py`）」「并发组件（`_concurrency.py`）」「鉴权校验器（`_auth.py`）」「配置（`_config.py`）」与「抓取接入点（`_scrapling.py`）」。`MCPServer` 顶层默认实例保留（不破坏现有测试），`run_server()` 内按配置用 `global mcp` 重建带鉴权的实例。

**Tech Stack:** Python 3.10+、mcp 2.0.0（含 streamable-http / `TokenVerifier` / `AuthSettings` / uvicorn / starlette）、scrapling、pytest + pytest-asyncio。

**设计依据：** `docs/superpowers/specs/2026-08-05-http-websocket-transport-design.md`

**运行测试（任选其一）：**
```bash
uv run --extra test pytest tests/<file>.py -v          # 推荐（uv 管理 test extras）
pytest tests/<file>.py -v                                # 已激活环境
```

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `src/scrapling_fetch_mcp/_concurrency.py` | `ConcurrencyGuard`（信号量+超时）、`ConcurrencyLimitError` | 新建 |
| `src/scrapling_fetch_mcp/_auth.py` | `StaticTokenVerifier`（实现 `TokenVerifier` 协议） | 新建 |
| `src/scrapling_fetch_mcp/_config.py` | `Config` 新增 7 项配置 + setter + env 加载；`PageCache` 并发注释 | 修改 |
| `src/scrapling_fetch_mcp/_scrapling.py` | `init_guard` + `browse_url` 接入 guard；原逻辑移入 `_do_browse` | 修改 |
| `src/scrapling_fetch_mcp/_fetcher.py` | 两个 wrapper 捕获 `ConcurrencyLimitError`（info 日志 + raise） | 修改 |
| `src/scrapling_fetch_mcp/mcp.py` | 7 个 CLI/env 参数、`global mcp` 按配置重建、`init_guard`、`run()` 分支 | 修改 |
| `tests/test_concurrency.py` | `ConcurrencyGuard` 单元测试 | 新建 |
| `tests/test_auth.py` | `StaticTokenVerifier` 单元测试 | 新建 |
| `tests/test_config.py` | 7 项新配置的加载/默认/优先级 | 扩展 |
| `tests/test_scrapling.py` | `browse_url` 接入 guard 的行为 | 扩展 |
| `tests/test_fetcher.py` | wrapper 传播 `ConcurrencyLimitError` | 扩展 |
| `tests/test_mcp_registration.py` | `MCPServer` 接受 auth 参数的 smoke 测试 | 扩展 |
| `README.md` / `MCP_CONFIG_EXAMPLES.md` | streamable-http 部署示例 | 修改 |

**依赖关系**：Task 4/5 依赖 Task 1；Task 6 依赖 1/2/3。建议按编号顺序执行。

---

## Task 1: ConcurrencyGuard 组件

**Files:**
- Create: `src/scrapling_fetch_mcp/_concurrency.py`
- Test: `tests/test_concurrency.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_concurrency.py`

```python
"""Tests for ConcurrencyGuard."""
import asyncio

import pytest

from scrapling_fetch_mcp._concurrency import ConcurrencyGuard, ConcurrencyLimitError


class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_allows_up_to_max_concurrent(self):
        guard = ConcurrencyGuard(max_concurrent=2, acquire_timeout=1.0)
        seen_in_flight = []

        async def hold():
            async with guard:
                seen_in_flight.append(guard.in_flight)

        await asyncio.gather(hold(), hold())
        assert max(seen_in_flight) <= 2
        assert guard.total_acquired == 2
        assert guard.in_flight == 0

    @pytest.mark.asyncio
    async def test_blocks_beyond_max(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=1.0)
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def hold():
            async with guard:
                started.set()
                await proceed.wait()

        holder = asyncio.create_task(hold())
        await started.wait()

        entered = asyncio.Event()

        async def waiter():
            async with guard:
                entered.set()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert not entered.is_set()
        assert guard.in_flight == 1

        proceed.set()
        await asyncio.gather(holder, waiter_task)
        assert guard.total_acquired == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_concurrency_limit_error(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=0.05)
        proceed = asyncio.Event()

        async def hold():
            async with guard:
                await proceed.wait()

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.01)

        with pytest.raises(ConcurrencyLimitError):
            async with guard:
                pass

        proceed.set()
        await holder

    @pytest.mark.asyncio
    async def test_exception_releases_slot(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=1.0)

        with pytest.raises(RuntimeError):
            async with guard:
                raise RuntimeError("boom")

        assert guard.in_flight == 0
        async with guard:
            assert guard.in_flight == 1
        assert guard.in_flight == 0

    def test_invalid_construction(self):
        with pytest.raises(ValueError):
            ConcurrencyGuard(max_concurrent=0, acquire_timeout=1.0)
        with pytest.raises(ValueError):
            ConcurrencyGuard(max_concurrent=1, acquire_timeout=-1.0)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run --extra test pytest tests/test_concurrency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapling_fetch_mcp._concurrency'`

- [ ] **Step 3: 实现** — 创建 `src/scrapling_fetch_mcp/_concurrency.py`

```python
"""Concurrency control: semaphore-based limiting for browser fetch operations."""

import asyncio
from logging import getLogger

logger = getLogger("scrapling_fetch_mcp")


class ConcurrencyLimitError(Exception):
    """Raised when a fetch cannot acquire a concurrency slot within the timeout."""


class ConcurrencyGuard:
    """Limit how many fetch/browser operations run at once.

    Requests beyond ``max_concurrent`` wait up to ``acquire_timeout`` seconds;
    on timeout they raise :class:`ConcurrencyLimitError`. Designed for a single
    asyncio event loop (the stdio and streamable-http transports both run on
    one). ``in_flight`` / ``total_acquired`` are exposed for observability.
    """

    def __init__(self, max_concurrent: int, acquire_timeout: float):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if acquire_timeout < 0:
            raise ValueError("acquire_timeout must be >= 0")
        self._max = max_concurrent
        self._timeout = acquire_timeout
        self._sem = asyncio.Semaphore(max_concurrent)
        self.in_flight = 0
        self.total_acquired = 0

    async def __aenter__(self) -> "ConcurrencyGuard":
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise ConcurrencyLimitError(
                f"并发已达上限({self._max})，等待 {self._timeout}s 超时"
            )
        self.in_flight += 1
        self.total_acquired += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.in_flight -= 1
        self._sem.release()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run --extra test pytest tests/test_concurrency.py -v`
Expected: PASS（5 passed）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_concurrency.py tests/test_concurrency.py
git commit -m "feat(concurrency): add ConcurrencyGuard for fetch limiting"
```

---

## Task 2: StaticTokenVerifier 组件

**Files:**
- Create: `src/scrapling_fetch_mcp/_auth.py`
- Test: `tests/test_auth.py`

- [ ] **Step 1: 写失败测试** — 创建 `tests/test_auth.py`

```python
"""Tests for StaticTokenVerifier."""
import pytest

from scrapling_fetch_mcp._auth import StaticTokenVerifier


class TestStaticTokenVerifier:
    @pytest.mark.asyncio
    async def test_valid_token_returns_access_token(self):
        verifier = StaticTokenVerifier("s3cret")
        result = await verifier.verify_token("s3cret")
        assert result is not None
        assert result.token == "s3cret"
        assert result.client_id == "static-client"
        assert result.scopes == []

    @pytest.mark.asyncio
    async def test_invalid_token_returns_none(self):
        verifier = StaticTokenVerifier("s3cret")
        assert await verifier.verify_token("wrong") is None

    @pytest.mark.asyncio
    async def test_empty_token_returns_none(self):
        verifier = StaticTokenVerifier("s3cret")
        assert await verifier.verify_token("") is None
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run --extra test pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scrapling_fetch_mcp._auth'`

- [ ] **Step 3: 实现** — 创建 `src/scrapling_fetch_mcp/_auth.py`

> 依据：mcp SDK 的 `TokenVerifier` 协议位于 `mcp.server.auth.provider`，仅需实现 `async def verify_token(self, token: str) -> AccessToken | None`（返回 `None` 即拒绝）。`AccessToken` 必填字段：`token / client_id / scopes`。

```python
"""Static bearer-token verifier for the streamable-http transport.

Implements the mcp SDK :class:`~mcp.server.auth.provider.TokenVerifier`
protocol for the simple case of a single shared secret (no OAuth flow).
When ``SCRAPLING_AUTH_TOKEN`` is configured, clients must send
``Authorization: Bearer <token>`` matching it.
"""

from mcp.server.auth.provider import AccessToken


class StaticTokenVerifier:
    """Verify bearer tokens against a single configured secret.

    Structurally satisfies the SDK ``TokenVerifier`` protocol (duck-typed;
    the protocol is not subclassed so we stay decoupled from runtime checks).
    """

    def __init__(self, expected_token: str):
        self._expected = expected_token

    async def verify_token(self, token: str) -> AccessToken | None:
        if token and token == self._expected:
            return AccessToken(
                token=token,
                client_id="static-client",
                scopes=[],
            )
        return None
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run --extra test pytest tests/test_auth.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_auth.py tests/test_auth.py
git commit -m "feat(auth): add StaticTokenVerifier for streamable-http"
```

---

## Task 3: Config 扩展 7 项配置

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 写失败测试** — 在 `tests/test_config.py` 末尾追加（若该文件已有 `from scrapling_fetch_mcp._config import config`，补充导入 `init_config_from_env`）

```python
import pytest
from scrapling_fetch_mcp._config import config, init_config_from_env


class TestTransportConfig:
    def setup_method(self):
        config._transport = "stdio"
        config._host = "127.0.0.1"
        config._port = 8000
        config._mcp_path = "/mcp"
        config._auth_token = ""
        config._max_concurrent = 5
        config._acquire_timeout = 30.0

    def test_defaults(self):
        assert config.transport == "stdio"
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.mcp_path == "/mcp"
        assert config.auth_token == ""
        assert config.max_concurrent == 5
        assert config.acquire_timeout == 30.0

    def test_set_transport_valid(self):
        config.set_transport("streamable-http")
        assert config.transport == "streamable-http"

    def test_set_transport_invalid(self):
        with pytest.raises(ValueError):
            config.set_transport("ws")

    def test_set_port_bounds(self):
        config.set_port(8080)
        assert config.port == 8080
        with pytest.raises(ValueError):
            config.set_port(0)
        with pytest.raises(ValueError):
            config.set_port(70000)

    def test_set_max_concurrent_invalid(self):
        with pytest.raises(ValueError):
            config.set_max_concurrent(0)

    def test_env_loads_transport_config(self, monkeypatch):
        monkeypatch.setenv("SCRAPLING_TRANSPORT", "streamable-http")
        monkeypatch.setenv("SCRAPLING_HOST", "0.0.0.0")
        monkeypatch.setenv("SCRAPLING_PORT", "9000")
        monkeypatch.setenv("SCRAPLING_MCP_PATH", "/api/mcp")
        monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "TOK")
        monkeypatch.setenv("SCRAPLING_MAX_CONCURRENT", "8")
        monkeypatch.setenv("SCRAPLING_ACQUIRE_TIMEOUT", "12.5")
        init_config_from_env()
        assert config.transport == "streamable-http"
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.mcp_path == "/api/mcp"
        assert config.auth_token == "TOK"
        assert config.max_concurrent == 8
        assert config.acquire_timeout == 12.5
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run --extra test pytest tests/test_config.py::TestTransportConfig -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'transport'`

- [ ] **Step 3: 实现配置项**

**3a.** 在 `src/scrapling_fetch_mcp/_config.py` 的 `Config` 类属性区（`_enable_features_raw` 那一行之后，`def __new__` 之前）追加：

```python
    # --- Transport / server / concurrency ---
    _transport: str = "stdio"
    _host: str = "127.0.0.1"
    _port: int = 8000
    _mcp_path: str = "/mcp"
    _auth_token: str = ""
    _max_concurrent: int = 5
    _acquire_timeout: float = 30.0
```

**3b.** 在 `Config` 类内（建议放在 `set_disable_url_rewrite` 之后、`enabled_features` property 之前）追加 property/setter：

```python
    @property
    def transport(self) -> str:
        return self._transport

    def set_transport(self, transport: str) -> None:
        if transport not in ("stdio", "streamable-http"):
            raise ValueError(
                f"Invalid transport '{transport}'. Must be one of: ['stdio', 'streamable-http']"
            )
        self._transport = transport

    @property
    def host(self) -> str:
        return self._host

    def set_host(self, host: str) -> None:
        self._host = host

    @property
    def port(self) -> int:
        return self._port

    def set_port(self, port: int) -> None:
        if not (1 <= port <= 65535):
            raise ValueError("port must be between 1 and 65535")
        self._port = port

    @property
    def mcp_path(self) -> str:
        return self._mcp_path

    def set_mcp_path(self, path: str) -> None:
        self._mcp_path = path

    @property
    def auth_token(self) -> str:
        return self._auth_token

    def set_auth_token(self, token: str) -> None:
        self._auth_token = token

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    def set_max_concurrent(self, value: int) -> None:
        if value < 1:
            raise ValueError("max_concurrent must be >= 1")
        self._max_concurrent = value

    @property
    def acquire_timeout(self) -> float:
        return self._acquire_timeout

    def set_acquire_timeout(self, value: float) -> None:
        if value < 0:
            raise ValueError("acquire_timeout must be >= 0")
        self._acquire_timeout = value
```

**3c.** 在 `init_config_from_env()` 函数末尾（`config._enable_features_raw = [...]` 之后）追加 env 加载：

```python
    # --- Transport / server / concurrency config ---
    env_transport = getenv("SCRAPLING_TRANSPORT", "").lower()
    if env_transport:
        try:
            config.set_transport(env_transport)
        except ValueError:
            pass  # Invalid value, use default

    env_host = getenv("SCRAPLING_HOST", "")
    if env_host:
        config.set_host(env_host)

    env_port = getenv("SCRAPLING_PORT", "")
    if env_port:
        try:
            config.set_port(int(env_port))
        except ValueError:
            pass

    env_mcp_path = getenv("SCRAPLING_MCP_PATH", "")
    if env_mcp_path:
        config.set_mcp_path(env_mcp_path)

    env_auth_token = getenv("SCRAPLING_AUTH_TOKEN", "")
    if env_auth_token:
        config.set_auth_token(env_auth_token)

    env_max_concurrent = getenv("SCRAPLING_MAX_CONCURRENT", "")
    if env_max_concurrent:
        try:
            config.set_max_concurrent(int(env_max_concurrent))
        except ValueError:
            pass

    env_acquire_timeout = getenv("SCRAPLING_ACQUIRE_TIMEOUT", "")
    if env_acquire_timeout:
        try:
            config.set_acquire_timeout(float(env_acquire_timeout))
        except ValueError:
            pass
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run --extra test pytest tests/test_config.py -v`
Expected: PASS（新测试通过，且不破坏既有测试）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat(config): add transport/auth/concurrency config options"
```

---

## Task 4: _scrapling.py 接入 ConcurrencyGuard

**Files:**
- Modify: `src/scrapling_fetch_mcp/_scrapling.py`
- Test: `tests/test_scrapling.py`

> 把原 `browse_url` 的抓取逻辑移入 `_do_browse`；`browse_url` 变为薄封装，若 guard 已初始化则用 `async with _guard` 包裹。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_scrapling.py` 追加（必要时补充 import）

```python
import pytest
import scrapling_fetch_mcp._scrapling as scrapling_mod


class TestBrowseUrlGuard:
    def setup_method(self):
        scrapling_mod._guard = None

    def teardown_method(self):
        scrapling_mod._guard = None

    @pytest.mark.asyncio
    async def test_guard_in_flight_during_call(self, monkeypatch):
        scrapling_mod.init_guard(max_concurrent=2, acquire_timeout=1.0)
        seen = []

        async def fake_browse(url, mode, page_action=None):
            seen.append(scrapling_mod._guard.in_flight)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)

        result = await scrapling_mod.browse_url("http://x", "basic")
        assert result == "page"
        assert seen == [1]
        assert scrapling_mod._guard.in_flight == 0
        assert scrapling_mod._guard.total_acquired == 1

    @pytest.mark.asyncio
    async def test_no_guard_skips_limiting(self, monkeypatch):
        called = []

        async def fake_browse(url, mode, page_action=None):
            called.append(url)
            return "page"

        monkeypatch.setattr(scrapling_mod, "_do_browse", fake_browse)
        result = await scrapling_mod.browse_url("http://y", "basic")
        assert result == "page"
        assert scrapling_mod._guard is None
        assert called == ["http://y"]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run --extra test pytest tests/test_scrapling.py::TestBrowseUrlGuard -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'init_guard'`（或 `_do_browse`）

- [ ] **Step 3: 实现** — 用以下完整内容替换 `src/scrapling_fetch_mcp/_scrapling.py`

```python
from contextlib import redirect_stdout
from os import devnull
from typing import Any, Callable, Optional

from scrapling_fetch_mcp._concurrency import ConcurrencyGuard

_guard: Optional[ConcurrencyGuard] = None


def init_guard(max_concurrent: int, acquire_timeout: float) -> None:
    """Initialize the global concurrency guard. Call once at server startup."""
    global _guard
    _guard = ConcurrencyGuard(max_concurrent, acquire_timeout)


async def _do_browse(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None,
) -> Any:
    """Actual scrapling fetch (extracted from browse_url)."""
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        if mode == "basic":
            return await AsyncFetcher.get(url, stealthy_headers=True)
        elif mode == "stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                page_action=page_action,
            )
        elif mode == "max-stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                block_webrtc=True,
                network_idle=True,
                disable_resources=False,
                block_images=False,
                page_action=page_action,
            )
        else:
            raise ValueError(f"Unknown mode: {mode}")


async def browse_url(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None
) -> Any:
    """
    Browse URL using scrapling fetcher, gated by the global concurrency guard
    when initialized (see :func:`init_guard`).

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, max-stealth)
        page_action: Optional async callable that receives the Playwright ``page``
                     object (scrapling's native ``page_action`` contract) for
                     automation such as image capture. Only stealth/max-stealth
                     modes pass it through; basic mode ignores it.
    """
    if _guard is None:
        return await _do_browse(url, mode, page_action)
    async with _guard:
        return await _do_browse(url, mode, page_action)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run --extra test pytest tests/test_scrapling.py -v`
Expected: PASS（新测试通过，且不破坏既有 `test_scrapling.py`）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_scrapling.py tests/test_scrapling.py
git commit -m "feat(scrapling): gate browse_url with concurrency guard"
```

---

## Task 5: _fetcher.py wrapper 捕获 ConcurrencyLimitError

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`（`fetch_page_wrapper` 与 `fetch_pattern_wrapper`）
- Test: `tests/test_fetcher.py`

> 让并发超时被记为 INFO（属预期限流，而非 ERROR），并继续向上抛出由 MCP SDK 转为 tool error。

- [ ] **Step 1: 写失败测试** — 在 `tests/test_fetcher.py` 追加

```python
import pytest
import scrapling_fetch_mcp._fetcher as fetcher_mod
from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
from scrapling_fetch_mcp._fetcher import fetch_page_wrapper, fetch_pattern_wrapper


class TestWrapperConcurrencyError:
    def setup_method(self):
        config.set_disable_url_rewrite(True)

    @pytest.mark.asyncio
    async def test_page_wrapper_propagates_concurrency_error(self, monkeypatch):
        async def boom(*a, **k):
            raise ConcurrencyLimitError("busy")

        monkeypatch.setattr(fetcher_mod, "browse_url", boom)
        with pytest.raises(ConcurrencyLimitError):
            await fetch_page_wrapper("http://x", "basic", "markdown", 1000, 0)

    @pytest.mark.asyncio
    async def test_pattern_wrapper_propagates_concurrency_error(self, monkeypatch):
        async def boom(*a, **k):
            raise ConcurrencyLimitError("busy")

        monkeypatch.setattr(fetcher_mod, "browse_url", boom)
        with pytest.raises(ConcurrencyLimitError):
            await fetch_pattern_wrapper("http://x", "pattern", "basic", "markdown", 1000)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run --extra test pytest tests/test_fetcher.py::TestWrapperConcurrencyError -v`
Expected: FAIL（`browse_url` mock 未抛出该错误前，wrapper 行为未定；或导入/逻辑错误）

- [ ] **Step 3: 实现**

**3a.** 在 `src/scrapling_fetch_mcp/_fetcher.py` 顶部 import 区追加：

```python
from scrapling_fetch_mcp._concurrency import ConcurrencyLimitError
```

**3b.** 修改 `fetch_page_wrapper`（当前 `except Exception as e:` 之前）插入一个专门的 `except`。替换该函数末尾的 try/except 为：

```python
    try:
        effective_format = format if format is not None else config.default_format
        scraping_path = Path(scraping_dir)
        result = await fetch_page_impl(
            url, mode, effective_format, max_length, start_index,
            save_content=save_content, scraping_dir=scraping_path,
        )
        return result
    except ConcurrencyLimitError as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.info("s_fetch_page 并发限流: %s", str(e))
        raise
    except Exception as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_page: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise
```

**3c.** 对 `fetch_pattern_wrapper` 做同样改造，其 try/except 改为：

```python
    try:
        effective_format = format if format is not None else config.default_format
        if effective_format == "airead":
            effective_format = "markdown"
        result = await fetch_pattern_impl(
            url, search_pattern, mode, effective_format, max_length, context_chars
        )
        return result
    except ConcurrencyLimitError as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.info("s_fetch_pattern 并发限流: %s", str(e))
        raise
    except Exception as e:
        logger = logging.getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_pattern: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run --extra test pytest tests/test_fetcher.py -v`
Expected: PASS（新测试通过，既有不破坏）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): log concurrency limit as info in wrappers"
```

---

## Task 6: mcp.py 启动改造（传输分支 + 鉴权 + init_guard）

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`
- Test: `tests/test_mcp_registration.py`

> 关键约束：`MCPServer` 在模块顶层 `mcp.py:21` 构造，但 `auth`/`token_verifier` 是构造期参数、配置在 `run_server()` 才解析。策略：保留顶层默认实例（测试依赖它），在 `run_server()` 顶部声明 `global mcp`，仅当启用鉴权时重建实例；`_register_tool` 签名不变。

- [ ] **Step 1: 写 smoke 测试** — 在 `tests/test_mcp_registration.py` 末尾追加

```python
class TestServerAuthConstruction:
    def test_mcp_server_accepts_token_verifier_and_auth(self):
        """MCPServer must construct cleanly with a static token verifier."""
        from mcp.server.mcpserver import MCPServer
        from mcp.server.auth.settings import AuthSettings

        from scrapling_fetch_mcp._auth import StaticTokenVerifier

        server = MCPServer(
            "scrapling-fetch-mcp-test",
            token_verifier=StaticTokenVerifier("secret"),
            auth=AuthSettings(
                issuer_url="http://127.0.0.1:8000/",
                resource_server_url="http://127.0.0.1:8000/",
            ),
        )
        assert server is not None
```

- [ ] **Step 2: 运行测试验证失败/基线**

Run: `uv run --extra test pytest tests/test_mcp_registration.py::TestServerAuthConstruction -v`
Expected: 即便在改造前也可能 PASS（mcp 已支持），作为基线。若改造引入回归会被后续步骤捕获。继续。

- [ ] **Step 3: 实现 mcp.py 改造**

**3a.** 调整顶部 import（在现有 `from mcp.server.mcpserver import MCPServer` 附近）：

```python
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
```

并新增：

```python
from scrapling_fetch_mcp._auth import StaticTokenVerifier
from scrapling_fetch_mcp._scrapling import init_guard
```

**3b.** 在 `run_server()` 的 `parser = ArgumentParser(...)` 之后、`args = parser.parse_args()` 之前，追加 7 个 CLI 参数（接在 `--enable-features` 之后）：

```python
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
```

**3c.** 在 `run_server()` 函数体最开头加 `global mcp`（使其后可重新绑定）：

```python
def run_server():
    """Parse CLI arguments and start the MCP server"""
    global mcp
    parser = ArgumentParser(
```

**3d.** 在 CLI 覆盖区（`if args.url_rewrite_config:` 之后、feature 解析之前）追加：

```python
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
```

**3e.** 在配置日志区（`logger.info(f"Features disabled: ...")` 之后）追加：

```python
    logger.info(f"Transport: {config.transport}")
    if config.transport == "streamable-http":
        logger.info(f"Bind: {config.host}:{config.port}{config.mcp_path}")
        logger.info(f"Auth: {'enabled' if config.auth_token else 'disabled'}")
    logger.info(f"Concurrency: max={config.max_concurrent}, timeout={config.acquire_timeout}s")
```

**3f.** 将 `run_server()` 末尾的两个 `_register_tool(...)` 调用 + `mcp.run(transport="stdio")`（原 `mcp.py:178-192`）**整体替换**为下面这块。顺序至关重要：`init_guard` → 必要时重建带鉴权的 `mcp` 实例 → 注册工具（绑到当前全局实例）→ 按传输启动。

```python
    # Initialize concurrency guard (both stdio and http run on one event loop;
    # MCP clients may issue concurrent tool calls even over stdio).
    init_guard(config.max_concurrent, config.acquire_timeout)

    # When auth is enabled, (re)build the MCPServer with a token verifier.
    # MUST happen before registering tools so they bind to the authed instance.
    if config.transport == "streamable-http" and config.auth_token:
        mcp = MCPServer(
            "scrapling-fetch-mcp",
            token_verifier=StaticTokenVerifier(config.auth_token),
            auth=AuthSettings(
                # mcp SDK 2.0.0 中 issuer_url 与 resource_server_url 均为必填；
                # 静态 token 场景无独立 OAuth 服务器，二者同值（server 自身标识）。
                issuer_url=f"http://{config.host}:{config.port}/",
                resource_server_url=f"http://{config.host}:{config.port}/",
            ),
        )

    # Build and register tools dynamically (registers onto the current global mcp)
    _register_tool(
        "s_fetch_page",
        TOOL_PARAMS["s_fetch_page"],
        S_FETCH_PAGE_DOCSTRING,
        fetch_page_wrapper,
    )
    _register_tool(
        "s_fetch_pattern",
        TOOL_PARAMS["s_fetch_pattern"],
        S_FETCH_PATTERN_DOCSTRING,
        fetch_pattern_wrapper,
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
```

> 说明：原文件 `mcp.py:178-192` 的两个 `_register_tool(...)` 与末行 `mcp.run(...)` 全部被上方代码块取代（注册调用已包含在内，不要保留旧的一份）。`global mcp`（Step 3c）使第 4 行的 `mcp = MCPServer(...)` 重新绑定模块全局变量，故随后的 `_register_tool`（内部引用全局 `mcp`）会把工具注册到鉴权实例上。

- [ ] **Step 4: 运行全部测试验证通过**

Run: `uv run --extra test pytest -v`
Expected: PASS（全绿，含既有测试）

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/mcp.py tests/test_mcp_registration.py
git commit -m "feat(server): add streamable-http transport with optional auth"
```

---

## Task 7: PageCache 并发特性注释

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`（`PageCache` 类 docstring）

- [ ] **Step 1: 实现** — 把 `PageCache` 的 docstring（`_config.py:20`）替换为：

```python
class PageCache:
    """Simple in-memory cache with TTL for page content.

    Concurrency note: ``get`` / ``set`` / ``clear_*`` are synchronous and
    contain no ``await``, so under a single asyncio event loop they execute
    atomically — no data corruption. A cache stampede (duplicate fetch) is
    possible when two callers miss the same key across an ``await
    browse_url``; this is acceptable for this workload. Do not call these
    methods from multiple OS threads.
    """
```

- [ ] **Step 2: 提交**

```bash
git add src/scrapling_fetch_mcp/_config.py
git commit -m "docs(cache): document PageCache concurrency characteristics"
```

---

## Task 8: 文档更新

**Files:**
- Modify: `MCP_CONFIG_EXAMPLES.md`
- Modify: `README.md`

- [ ] **Step 1: 更新 `MCP_CONFIG_EXAMPLES.md`** — 追加一节：

```markdown
## Streamable-HTTP（远程访问）

默认仍为 stdio（本地子进程）。要启用远程 HTTP 传输，设置 `--transport streamable-http`。

### 本地（无鉴权）

```bash
scrapling-fetch-mcp --transport streamable-http --port 8000
```

客户端连接：`http://127.0.0.1:8000/mcp`

### 内网 + Bearer 鉴权

```bash
scrapling-fetch-mcp \
  --transport streamable-http \
  --host 0.0.0.0 \
  --port 8000 \
  --auth-token YOUR_SECRET
```

客户端需在请求头携带：`Authorization: Bearer YOUR_SECRET`。

### 并发控制

抓取是资源密集操作（stealth/max-stealth 会启动浏览器）。默认最多 5 个并发，超出排队等待最多 30 秒：

```bash
scrapling-fetch-mcp --transport streamable-http --max-concurrent 3 --acquire-timeout 60
```

### 公网 HTTPS（由反向代理终结 TLS）

进程内不做 TLS，建议前置 Caddy/Nginx。Caddy 示例：

```caddyfile
mcp.example.com {
  reverse_proxy localhost:8000
}
```

### 可用配置项

| 配置 | env | CLI | 默认 |
|---|---|---|---|
| 传输 | `SCRAPLING_TRANSPORT` | `--transport` | `stdio` |
| 绑定地址 | `SCRAPLING_HOST` | `--host` | `127.0.0.1` |
| 端口 | `SCRAPLING_PORT` | `--port` | `8000` |
| 路径 | `SCRAPLING_MCP_PATH` | `--mcp-path` | `/mcp` |
| 鉴权 token | `SCRAPLING_AUTH_TOKEN` | `--auth-token` | （空） |
| 最大并发 | `SCRAPLING_MAX_CONCURRENT` | `--max-concurrent` | `5` |
| 等待超时(秒) | `SCRAPLING_ACQUIRE_TIMEOUT` | `--acquire-timeout` | `30` |
```

- [ ] **Step 2: 更新 `README.md`** — 在「配置/运行」相关章节追加一行指引：

```markdown
> 远程访问（streamable-http）与并发控制详见 [`MCP_CONFIG_EXAMPLES.md`](MCP_CONFIG_EXAMPLES.md#streamable-http远程访问)。
```

- [ ] **Step 3: 提交**

```bash
git add MCP_CONFIG_EXAMPLES.md README.md
git commit -m "docs: add streamable-http deployment examples"
```

---

## 集成验证（手动，可选但推荐）

- [ ] 起 stdio 模式确认行为不变：`scrapling-fetch-mcp`（默认）
- [ ] 起 http 模式：`scrapling-fetch-mcp --transport streamable-http --port 8000`，用 MCP 客户端或 httpx 连 `http://127.0.0.1:8000/mcp`，调用 `s_fetch_page` 成功
- [ ] 带鉴权：加 `--auth-token SECRET`，无 token 请求被拒（401），带正确 token 成功
- [ ] 并发压测：`--max-concurrent 2`，同时发 >2 个 stealth 请求，验证排队与超时返回错误、`in_flight` 不超 2

---

## 验收标准（对照 spec）

1. 默认 `stdio` 行为不变（现有测试全绿）✅ Task 6 分支默认 stdio
2. `--transport streamable-http` 可连且能调两个工具 ✅ Task 6
3. `auth_token` 正确/错误鉴权 ✅ Task 2 + Task 6
4. 并发超上限排队、超时返回错误、`in_flight` 不超上限 ✅ Task 1 + Task 4
5. 异常/超时不崩溃进程 ✅ Task 5（raise 交 MCP 层）
6. 7 项配置 env/CLI 生效、CLI 优先 ✅ Task 3 + Task 6
7. http + 无 token + 非 localhost 启动 warning ✅ Task 6 Step 3f
