# Daemon 化与浏览器池化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 scrapling-fetch-mcp 拆成瘦 MCP 前端 + 常驻抓取 daemon（unix socket NDJSON），并加入默认关闭的按域名分桶浏览器池。

**Architecture:** 两种传输（stdio/streamable-http）的前端进程只保留 MCP SDK、工具 schema 与 BackendClient；抓取全链路（fetcher/extractor/converter/browser_check/PageCache/并发闸门/浏览器池）在 daemon 进程执行。daemon socket 按（包版本，配置摘要8hex）命名隔离，自动拉起、空闲 600s 自退、死亡自动重生。

**Tech Stack:** Python 3.10+/asyncio、mcp SDK ≥2.3.0、scrapling 0.3.6（pin 不动）、platformdirs（新增）、pytest/pytest-asyncio。

**Spec:** `docs/superpowers/specs/2026-11-01-daemon-and-browser-pool-design.md`（实现前先读，本计划从它论证）

## Global Constraints

- `scrapling>=0.3.6,<0.3.7`、`camoufox>=0.4.11,<0.5` 的 pin 不动（`pyproject.toml` 注释说明了原因；`tests/test_dependency_pin.py` 会守护）。
- mcp SDK 本计划内升级为 `mcp>=2.3.0,<3.0.0`。
- 前端可 import 的 `scrapling_fetch_mcp` 模块仅限：`mcp.py`、`_features.py`、`_tool_factory.py`、`_skills.py`、`_auth.py`、`_client.py`、`_config.py`、`daemon/`（其中 `daemon/config_env.py`、`daemon/protocol.py`、`daemon/lifecycle.py`、`daemon/paths.py` 必须保持轻量，不得触发 trafilatura/markitdown/numpy/onnxruntime/playwright/camoufox/scrapling.fetchers import）。
- Windows 不支持 daemon：`ensure_daemon` 在 `sys.platform == "win32"` 时抛带说明的 RuntimeError。
- 浏览器池默认关闭；所有新配置同时有 CLI flag 与 env（`SCRAPLING_*` 惯例，scraping_dir 例外沿用 `SCRAPING_DIR`）。
- 测试命令一律 `uv run pytest ...`（仓库无 pytest ini 段，Task 12 前不需要 marker）。
- 文档（README/MCP_CONFIG_EXAMPLES.md）中文；commit 用 Angular 规范中文 message，按任务原子提交。
- 运行测试产生的临时 daemon socket/lock 一律放 `tmp_path`，通过 `SCRAPLING_DAEMON_DIR` 注入，不得污染真实用户目录。

## Review Focus

1. **前端 import 边界回归**——未来任何人在 mcp.py/前端模块加顶层重 import 会让瘦前端失效：Task 9 的 subprocess 守卫测试钉死（断言 `trafilatura/markitdown/numpy/onnxruntime/playwright/camoufox/scrapling.fetchers` 不出现在 `sys.modules`）。
2. **daemon 中途被杀**（SIGKILL/OOM）——下一请求必须自动重生而不是永久报错：Task 9 的 kill-后-再请求单测钉死。
3. **相对路径 + 不同 CWD 前端**——同一配置字符串在不同工作目录必须算不同配置：Task 4 的归一化测试钉死（`Path.resolve()` 后进 env 与 hash）。
4. **cancel 后浏览器进程残留**——客户端取消后 5s 内 scrapling 会话未退出必须升级处理，不得无声泄漏：Task 7 的宽限期逻辑单测 + Task 13 的 `-m slow` 真实进程检查（`pgrep -f firefox`）钉死。
5. **uvx 滚动更新双 daemon 共存**——新旧版本前端各自 socket 命名，互不干扰且陈旧 socket 防御路径不误杀：Task 6 的 stale-defense 单测 + Task 13 慢速用例钉死。

---

### Task 1: mcp SDK 升级 2.0.0 → 2.3.0

**Files:**
- Modify: `pyproject.toml`（`"mcp>=2.0.0, <3.0.0"` → `"mcp>=2.3.0, <3.0.0"`）
- Modify: `uv.lock`（uv 自动）
- Test: 全量现有测试回归

**Interfaces:**
- Consumes: 无（独立先行）
- Produces: mcp SDK 2.3.0 环境，后续所有任务在此基线上开发

- [ ] **Step 1: 查 changelog 定适配点**

Run: `uv run python -c "import importlib.metadata" && pip index versions mcp 2>/dev/null || true`
再从 PyPI web（或 `uv run python -c "import httpx; print(httpx.get('https://pypi.org/pypi/mcp/json').json()['info']['version'])"`）确认 2.3.0 可达。重点核对 2.0.0→2.3.0 中与本项目相关的 API 面：`MCPServer` 构造参数（`instructions`/`extensions`）、`mcp.server.auth.settings.AuthSettings`、`StaticTokenVerifier`（TokenVerifier 协议）、`mcp.run(transport=...)` 签名、skills extension（SEP-2640）接口。读 venv 内 `mcp/server/mcpserver/server.py` 与 `mcp/server/auth/*` 的当前签名比对 `src/scrapling_fetch_mcp/mcp.py:40-48,313-326`、`_auth.py`、`_skills.py` 的用法。

- [ ] **Step 2: 改 pin 并同步锁**

Run: `uv lock && uv sync --all-extras`（把 pyproject 中 mcp pin 改为 `>=2.3.0, <3.0.0` 后执行）
Expected: lock 解析成功，mcp 2.3.0 安装

- [ ] **Step 3: 全量回归**

Run: `uv run pytest -x -q`
Expected: 全部 PASS。若有失败：逐个判断是 SDK 行为变化还是测试需适配，修复后重跑（本项目相关的高危点：`test_skills_extension.py`、`test_auth.py`、`test_mcp_registration.py`、`test_integration.py`）

- [ ] **Step 4: 手动 stdio 冒烟**

Run: `uv run scrapling-fetch-mcp` 并向 stdin 写一行 `{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"probe","version":"0"}}}`，读 stdout 首行
Expected: 返回含 `"serverInfo"` 的 initialize 响应（用 `timeout 30` 包裹防挂）

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock src/ tests/
git commit -m "build(deps): 升级 mcp SDK 2.0.0→2.3.0

daemon 化前的基线对齐；<3.0.0 上限保留。适配 SDK 在
extensions/auth/streamable-http 上的 API 变化（如有）。"
```

---

### Task 2: PageCache 条目上限

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`（`PageCache` 类 + `Config` + `init_config_from_env`）
- Test: `tests/test_config.py`（追加）

**Interfaces:**
- Consumes: 现有 `PageCache(ttl_seconds)`、`config.set_cache_ttl`
- Produces: `PageCache(ttl_seconds, max_entries=256)`；`Config.cache_max_entries` property + `set_cache_max_entries(int)`；env `SCRAPLING_CACHE_MAX_ENTRIES`（默认 256）

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_config.py`）

```python
def test_page_cache_max_entries_fifo_eviction():
    cache = PageCache(ttl_seconds=300, max_entries=3)
    for i in range(3): cache.set(f"u{i}", "basic", f"c{i}")
    cache.set("u3", "basic", "c3")          # 满:先 clear_expired 再 FIFO 逐出 u0
    assert cache.get("u0", "basic") is None
    assert cache.get("u3", "basic") == "c3"

def test_page_cache_evicts_expired_before_fifo():
    cache = PageCache(ttl_seconds=0, max_entries=2)   # ttl=0 → 立即过期
    cache.set("a", "basic", "1"); cache.set("b", "basic", "2")
    cache.set("c", "basic", "3")            # 全部已过期,应清空而非逐出
    assert cache.get("c", "basic") is None  # 且 c 已入缓存

def test_cache_max_entries_env(monkeypatch):
    monkeypatch.setenv("SCRAPLING_CACHE_MAX_ENTRIES", "16")
    cfg = _fresh_config()                    # 沿用该文件现有的单例重置手法
    init_config_from_env()
    assert cfg.cache_max_entries == 16
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -q -k "max_entries"`
Expected: FAIL（`TypeError: __init__() got an unexpected keyword argument 'max_entries'`）

- [ ] **Step 3: 实现**

`PageCache.__init__(self, ttl_seconds: int = 300, max_entries: int = 256)`；`set()` 末尾：先 `clear_expired()`，若 `len(self._cache) >= self._max_entries` 按插入序（dict 保序）逐出最旧直至容纳新条目。`Config` 加 `_cache_max_entries: int = 256`、property、setter（负数 ValueError）、`init_config_from_env` 里读 env。注意 `set_cache_ttl` 重建 cache 时带上 `max_entries`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_config.py -q`
Expected: PASS（含原有用例）

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat(config): PageCache 加条目上限(默认256,FIFO+过期优先)

daemon 长驻会放大无上限增长隐患,此项独立先行。"
```

---

### Task 3: 池/daemon 新配置项（config + env + CLI）

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`（新 property/setter + `init_config_from_env`）
- Modify: `src/scrapling_fetch_mcp/mcp.py`（`_build_arg_parser` 的 CLI flags + `run_server` 内 CLI 覆盖段）
- Test: `tests/test_config.py`（追加）

**Interfaces:**
- Consumes: 现有 Config 惯例
- Produces（后续任务依赖的精确名）:
  - `config.browser_pool: bool`（默认 False）/ `set_browser_pool(bool)`
  - `config.pool_idle_ttl: float`（默认 300.0）/ `config.pool_max_age: float`（1800.0）/ `config.pool_max_sessions: int`（4）/ `config.pool_max_requests: int`（50），各带 setter（负数 ValueError）
  - `config.daemon_dir: Optional[Path]`（默认 None=platformdirs）/ `set_daemon_dir`；`config.daemon_idle_timeout: float`（600.0）/ setter
  - env：`SCRAPLING_BROWSER_POOL`（true/1/yes）、`SCRAPLING_POOL_IDLE_TTL`、`SCRAPLING_POOL_MAX_AGE`、`SCRAPLING_POOL_MAX_SESSIONS`、`SCRAPLING_POOL_MAX_REQUESTS`、`SCRAPLING_DAEMON_DIR`、`SCRAPLING_DAEMON_IDLE_TIMEOUT`
  - CLI：`--browser-pool`（store_true）、`--pool-idle-ttl`、`--pool-max-age`、`--pool-max-sessions`、`--pool-max-requests`（float/int，默认 None）

- [ ] **Step 1: 写失败测试**（`tests/test_config.py` 追加，手法沿用文件内现有 env 用例）

```python
def test_pool_and_daemon_defaults_and_env(monkeypatch):
    cfg = _fresh_config()
    assert cfg.browser_pool is False
    assert (cfg.pool_idle_ttl, cfg.pool_max_age, cfg.pool_max_sessions, cfg.pool_max_requests) == (300.0, 1800.0, 4, 50)
    assert cfg.daemon_idle_timeout == 600.0 and cfg.daemon_dir is None
    monkeypatch.setenv("SCRAPLING_BROWSER_POOL", "true")
    monkeypatch.setenv("SCRAPLING_POOL_MAX_SESSIONS", "2")
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", "/tmp/xyz")
    monkeypatch.setenv("SCRAPLING_DAEMON_IDLE_TIMEOUT", "60")
    init_config_from_env()
    assert cfg.browser_pool is True and cfg.pool_max_sessions == 2
    assert cfg.daemon_dir == Path("/tmp/xyz") and cfg.daemon_idle_timeout == 60.0

def test_pool_setter_validation():
    cfg = _fresh_config()
    with pytest.raises(ValueError): cfg.set_pool_idle_ttl(-1)
    with pytest.raises(ValueError): cfg.set_pool_max_sessions(0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_config.py -q -k "pool or daemon"`
Expected: FAIL（属性不存在）

- [ ] **Step 3: 实现 Config + env**

按 Produces 清单在 `_config.py` 照现有惯例实现（env 布尔解析沿用 `in ('true','1','yes')` 手法；数值 try/except ValueError 忽略）。

- [ ] **Step 4: CLI flags**

`mcp.py` parser 追加上述 flags（help 文案中文，注明对应 env），`run_server` 的"CLI args override environment"段按现有模式接 `if args.X is not None: config.set_X(args.X)`（`--browser-pool` 用 `if args.browser_pool: config.set_browser_pool(True)`）。

- [ ] **Step 5: 跑全量 + Commit**

Run: `uv run pytest tests/test_config.py tests/test_mcp_registration.py -q` → PASS

```bash
git add src/scrapling_fetch_mcp/_config.py src/scrapling_fetch_mcp/mcp.py tests/test_config.py
git commit -m "feat(config): 浏览器池与 daemon 生命周期配置项

池参数默认 idle 300s/max-age 1800s/max-sessions 4/max-requests 50;
daemon 空闲退出默认 600s。全部带 CLI 与 env 双入口。"
```

---

### Task 4: daemon 配置解析与摘要（`daemon/config_env.py`）

**Files:**
- Create: `src/scrapling_fetch_mcp/daemon/__init__.py`（空）
- Create: `src/scrapling_fetch_mcp/daemon/config_env.py`
- Test: `tests/daemon/test_config_env.py`（新建，`tests/daemon/__init__.py` 空文件）

**Interfaces:**
- Consumes: Task 3 的 env 键名
- Produces（后续任务依赖）:
  - `DAEMON_OWNED_ENV_KEYS: tuple[str, ...]`——daemon-owned env 键全集（见下）
  - `resolve_daemon_env(cli: dict[str, object] | None = None) -> tuple[dict[str, str], str]`——返回 `(spawn_env, config_hash8)`：daemon-owned 键的归一化 env dict（相对路径已转绝对），及 sha256 前 8 hex
  - `normalize_daemon_values() -> dict[str, str | int | float | bool]`——canonical 值 dict（config_hash 的输入）
  - 常量 `PROTOCOL_VERSION: int = 2`（放本模块，protocol.py 引用）

`DAEMON_OWNED_ENV_KEYS` 精确清单：`SCRAPLING_MIN_MODE, SCRAPLING_CACHE_TTL, SCRAPLING_CACHE_MAX_ENTRIES, SCRAPING_DIR, SCRAPLING_MARKDOWN_CONVERTER, SCRAPLING_RULES_CONFIG, SCRAPLING_DEFAULT_FORMAT, SCRAPLING_URL_REWRITE_CONFIG, SCRAPLING_DISABLE_URL_REWRITE, JINA_API_KEY, SCRAPLING_DISABLE_JINA_ARBITER, SCRAPLING_JINA_MIN_CHARS, SCRAPLING_MAX_CONCURRENT, SCRAPLING_ACQUIRE_TIMEOUT, SCRAPLING_FETCH_TIMEOUT, SCRAPLING_BROWSER_POOL, SCRAPLING_POOL_IDLE_TTL, SCRAPLING_POOL_MAX_AGE, SCRAPLING_POOL_MAX_SESSIONS, SCRAPLING_POOL_MAX_REQUESTS`。明确不含：`SCRAPLING_TRANSPORT/HOST/PORT/MCP_PATH/AUTH_TOKEN`（传输归前端）、`SCRAPLING_DISABLE_FEATURES/ENABLE_FEATURES`（仅 schema）、`SCRAPLING_DAEMON_DIR/IDLE_TIMEOUT`（生命周期归前端）。

归一化规则：路径键（`SCRAPING_DIR, SCRAPLING_RULES_CONFIG, SCRAPLING_URL_REWRITE_CONFIG`）→ `str(Path(v).expanduser().resolve())`（不存在也 resolve，Path.resolve 非 strict）；数值 → 解析成 int/float 后进 canonical dict；布尔 → Python bool；解析失败的键按未设置处理（与 `init_config_from_env` 的容错一致）。`config_hash = sha256(json.dumps(normalize_daemon_values(), sort_keys=True, ensure_ascii=True).encode()).hexdigest()[:8]`。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_config_env.py`

```python
def test_hash_stable_and_paths_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRAPING_DIR", ".temp/scrapling/")
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "stealth")
    env, h1 = resolve_daemon_env()
    assert env["SCRAPING_DIR"] == str((tmp_path / ".temp/scrapling").resolve())
    assert len(h1) == 8 and int(h1, 16) >= 0
    _, h2 = resolve_daemon_env()          # 同输入同 hash
    assert h1 == h2

def test_same_string_different_cwd_differs(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRAPING_DIR", ".temp/scrapling/")
    monkeypatch.chdir(tmp_path); _, h_a = resolve_daemon_env()
    monkeypatch.chdir(tmp_path / ".."); _, h_b = resolve_daemon_env()
    assert h_a != h_b                     # 反目标"静默不一致"的钉子

def test_transport_keys_excluded(monkeypatch):
    monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "secret"); monkeypatch.setenv("SCRAPLING_PORT", "9999")
    e1, h1 = resolve_daemon_env()
    monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "other"); monkeypatch.setenv("SCRAPLING_PORT", "1234")
    _, h2 = resolve_daemon_env()
    assert h1 == h2 and "SCRAPLING_AUTH_TOKEN" not in e1

def test_defaults_when_env_empty(monkeypatch):
    for k in DAEMON_OWNED_ENV_KEYS: monkeypatch.delenv(k, raising=False)
    env, h = resolve_daemon_env()
    assert env.get("SCRAPLING_MIN_MODE") is None      # 未设置不进 env,由 daemon 侧默认值兜底
    assert len(h) == 8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/daemon/test_config_env.py -q`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现**

纯 stdlib（hashlib/json/pathlib/os），不 import 任何重模块（本文件在 import 边界白名单上）。`cli` 参数本任务可忽略（Task 10 接线时前端已把 CLI 覆盖写回 os.environ 或直接传入 dict 覆盖，签名预留）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/daemon/test_config_env.py -q` → PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/daemon/ tests/daemon/
git commit -m "feat(daemon): daemon-owned 配置解析与摘要

相对路径归一化为绝对路径再进 env 与 hash;传输/features/生命周期
键不入摘要。socket 命名隔离的配置摘要来源。"
```

---

### Task 5: NDJSON 协议（`daemon/protocol.py`）

**Files:**
- Create: `src/scrapling_fetch_mcp/daemon/protocol.py`
- Test: `tests/daemon/test_protocol.py`

**Interfaces:**
- Consumes: `daemon/config_env.PROTOCOL_VERSION`
- Produces:
  - `make_request(op: str, payload: dict, token: str, req_id: int, pkg: str) -> bytes`（含尾部 `\n`）
  - `make_response(req_id: int, result: object) -> bytes`、`make_error(req_id: int, code: str, message: str) -> bytes`
  - `make_progress(req_id: int, progress: float, total: float, message: str) -> bytes`
  - `parse_frame(line: bytes) -> dict`——JSON 解码 + 信封校验（`v` 必须等于 `PROTOCOL_VERSION`，否则 `ProtocolError`；请求必须有 `id/op/token`）
  - `ProtocolError(ValueError)`；错误码常量 `E_UNAUTHORIZED/E_UNKNOWN_OP/E_CANCELLED/E_INTERNAL`
  - op 名常量 `OP_FETCH_PAGE = "fetch_page"`、`OP_FETCH_PATTERN = "fetch_pattern"`、`OP_CANCEL = "cancel"`、`OP_PING = "ping"`、`OP_STATUS = "status"`、`OP_SHUTDOWN = "shutdown"`

信封：请求 `{"v":2,"id":int,"op":str,"token":str,"pkg":str,"payload":{}}`；响应 `{"v":2,"id":int,"ok":true,"result":...}`；错误 `{"v":2,"id":int,"ok":false,"error":{"code":str,"message":str}}`；progress 中间帧 `{"v":2,"id":int,"progress":{"progress":float,"total":float,"message":str}}`。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_protocol.py`

```python
def test_request_roundtrip():
    line = make_request(OP_PING, {}, "tok", 7, "0.3.0")
    assert line.endswith(b"\n") and b"\n" not in line[:-1]   # 单行
    frame = parse_frame(line)
    assert frame["v"] == 2 and frame["op"] == "ping" and frame["token"] == "tok" and frame["id"] == 7

def test_parse_rejects_wrong_version():
    with pytest.raises(ProtocolError): parse_frame(b'{"v":1,"id":1,"op":"ping","token":"t"}')

def test_progress_and_error_frames():
    assert parse_frame(make_progress(3, 1, 2, "x"))["progress"]["total"] == 2
    err = parse_frame(make_error(3, E_CANCELLED, "bye"))
    assert err["ok"] is False and err["error"]["code"] == "cancelled"

def test_payload_with_newlines_stays_single_line():
    line = make_request(OP_FETCH_PAGE, {"url": "http://x", "mode": "basic", "content": "a\nb"}, "t", 1, "0.3.0")
    assert line.count(b"\n") == 1
```

- [ ] **Step 2/3/4:** 确认失败 → 实现（纯 stdlib json；`json.dumps(..., ensure_ascii=True)` 保证单行）→ 确认通过（`uv run pytest tests/daemon/test_protocol.py -q`）

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/daemon/protocol.py tests/daemon/test_protocol.py
git commit -m "feat(daemon): NDJSON 协议信封与帧编解码

请求/响应/错误/progress 四类帧,协议版本 v=2 校验。"
```

---

### Task 6: 生命周期（`daemon/paths.py` + `daemon/lifecycle.py`）

**Files:**
- Modify: `pyproject.toml`（dependencies 加 `"platformdirs>=4.0"`）
- Create: `src/scrapling_fetch_mcp/daemon/paths.py`
- Create: `src/scrapling_fetch_mcp/daemon/lifecycle.py`
- Test: `tests/daemon/test_lifecycle.py`

**Interfaces:**
- Consumes: Task 4 的 `resolve_daemon_env`；Task 5 的 `make_request/parse_frame/OP_PING`
- Produces:
  - `paths.pkg_version() -> str`（`importlib.metadata.version("scrapling-fetch-mcp")`）
  - `paths.daemon_dir() -> Path`（`config.daemon_dir` 或 `platformdirs.user_data_dir("scrapling-fetch-mcp")`，mkdir parents）
  - `lifecycle.socket_name(config_hash: str) -> str`——`f"daemon-{pkg_version()}-{config_hash}"`
  - `lifecycle.ensure_daemon(spawn_env: dict[str, str], config_hash: str, timeout: float = 60.0) -> Path`——返回已就绪 daemon 的 socket 路径
  - `lifecycle.is_alive(sock: Path, expect_pkg: str, expect_hash: str) -> bool`——lock pid 存活 + ping（connect 2s/响应 5s），应答自报 pkg/hash 与期望不符返回 False
  - `lifecycle.daemon_sockets() -> list[Path]`——目录下全部 `daemon-*.sock`（管理 CLI 用）
  - `lifecycle.ping(sock: Path, token: str, timeout: float = 5.0) -> dict | None`——发 ping 收响应（管理 CLI/测试用）

`ensure_daemon` 流程（对齐 ocr-mcp `lifecycle.py:107-151`）：win32 直接 RuntimeError；拼 socket 名 → lock 存在且 `is_alive` → 返回；否则 `_cleanup_stale`（删同前缀 sock/lock），`spawn.lock` `O_CREAT|O_EXCL` 仲裁：抢到者 `subprocess.Popen([sys.executable, "-m", "scrapling_fetch_mcp.daemon"], env={**os.environ, **spawn_env}, start_new_session=True, stdin=DEVNULL, stdout=stderr→daemon-<...>.log, cwd="/")` 后轮询 ping+is_alive（0.2s 间隔，timeout 上限 60s）；未抢到者同样轮询等待。lock 文件内容 JSON：`{"pid","token","pkg","config_hash","sock"}`。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_lifecycle.py`（全部用 `monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))` + 沿用 `tests/test_config.py` 的 config 重置手法）

```python
def test_socket_name_embeds_version_and_hash():
    name = socket_name("ab12cd34")
    assert name.startswith("daemon-") and name.endswith("-ab12cd34") and ".sock" not in name

def test_is_alive_false_on_missing_lock(tmp_path):
    assert is_alive(tmp_path / "nope.sock", "0.3.0", "ab12cd34") is False

def test_ensure_daemon_spawns_and_reuses(spawn_fake_daemon):   # fixture:见下
    env, h = {"SCRAPLING_DAEMON_IDLE_TIMEOUT": "60"}, "ab12cd34"
    sock1 = ensure_daemon(env, h, timeout=30)
    assert sock1.exists()
    pid1 = json.loads((sock1.with_suffix(".lock")).read_text())["pid"]
    sock2 = ensure_daemon(env, h, timeout=30)                  # 第二次复用,不新起
    assert json.loads(sock2.with_suffix(".lock").read_text())["pid"] == pid1

def test_stale_socket_with_wrong_hash_is_respawned(spawn_fake_daemon):
    # 手工伪造 lock+sock(自报 hash 与期望不符) → ensure_daemon 必须清理重拉
    ...
    sock = ensure_daemon(env, "ffffff11", timeout=30)
    assert json.loads(sock.with_suffix(".lock").read_text())["config_hash"] == "ffffff11"
```

fixture `spawn_fake_daemon`：monkeypatch `lifecycle._DAEMON_MODULE` 启动命令为一个假 worker（`python -m tests.daemon.fake_worker`，见 Task 7 的假实现；本任务先写 `tests/daemon/fake_worker.py` 骨架：读 env `SCRAPLING_DAEMON_DIR`，在期望 socket 名上 serve ping 即可）。

- [ ] **Step 2/3/4:** 确认失败 → 实现（注意：spawn 的模块名做模块级常量 `_DAEMON_MODULE = "scrapling_fetch_mcp.daemon"` 便于测试注入；daemon 进程以 `start_new_session=True` 成为自己的进程组长——Task 7 的强杀兜底依赖此点）→ 确认通过

- [ ] **Step 5: 全量 + Commit**

Run: `uv run pytest tests/daemon/ -q` → PASS

```bash
git add pyproject.toml uv.lock src/scrapling_fetch_mcp/daemon/ tests/daemon/
git commit -m "feat(daemon): 生命周期——按(版本,配置摘要)socket 命名隔离

ensure_daemon 自动拉起/复用/spawn 仲裁/陈旧防御;ping 自报 pkg 与
config_hash 不符视为陈旧 socket 清理重拉,不做打断式 kill 替换。"
```

---

### Task 7: daemon worker（`daemon/worker.py` + `daemon/__main__.py`）

**Files:**
- Create: `src/scrapling_fetch_mcp/daemon/worker.py`
- Create: `src/scrapling_fetch_mcp/daemon/__main__.py`
- Modify: `tests/daemon/fake_worker.py`（Task 6 骨架充实为可复用假 worker）
- Test: `tests/daemon/test_worker.py`

**Interfaces:**
- Consumes: Task 4 `resolve_daemon_env/normalize_daemon_values`、Task 5 全部、Task 6 `paths/lifecycle`（写 lock）、`_fetcher.fetch_page_wrapper/fetch_pattern_wrapper`（daemon 侧，签名见 `_fetcher.py:473-518`）、`_browser_check.ensure_browserforge_data/ensure_camoufox`、`_scrapling.init_guard`、`_config.init_config_from_env`
- Produces:
  - `python -m scrapling_fetch_mcp.daemon` 可直接启动
  - `DaemonWorker(sock: Path, idle_timeout: float).serve() -> None`（阻塞；单测直接驱动）
  - 支持 op：`ping`→`{"status":"ready","pid","pkg","config_hash","uptime_s","clients"}`；`fetch_page`/`fetch_pattern`→`{"result": str}`（payload 键与 wrapper 形参一一对应）；`cancel`→`{"cancelled": true|false}`；`status`→`{"pid","pkg","config_hash","uptime_s","clients","cache_entries","stealth_ready","degradation","pool":{...}|null}`；`shutdown`→优雅退出
  - token 鉴权：请求 token ≠ daemon token → `E_UNAUTHORIZED`
  - 并发：单连接多请求按 id 多路复用；全局并发由 `init_guard` 闸门控制

worker 启动序列（`__main__.py`）：`init_config_from_env()`（daemon-owned env 已由 spawn 注入）→ `normalize_daemon_values()` 自算 config_hash（与 socket 名防御比对，仅日志告警不退出）→ `ensure_browserforge_data()`（阻塞，秒级）→ `ensure_camoufox()`（内部已是后台线程不阻塞）→ `init_guard(config.max_concurrent, config.acquire_timeout)` → 写 lock（`secrets.token_hex(16)`）→ `asyncio.start_unix_server(sock, limit=64*1024*1024)` → chmod 0600 → serve。

关键机制：
- **任务注册表** `self._tasks: dict[int, asyncio.Task]`：fetch op 进入即注册，finally 移除。
- **progress 桥**：给 wrapper 传 `ctx=ProgressBridge(send_frame)`——duck type，提供 `async def report_progress(self, progress, total, message=None)`（内部 `send_frame(make_progress(req_id,...))`）。`_maybe_report_progress` 对 `ctx=None` 已容错，桥对象只补这一个方法即可。
- **cancel 传播（Review Focus 4）**：收到 `cancel{id}` → `task.cancel()` → `asyncio.wait_for(asyncio.shield(task), 5)`；仍活着（宽限期耗尽）→ 记日志后 `os.killpg(os.getpgid(0), signal.SIGKILL)`（核弹兜底：daemon 与其拉起的浏览器同进程组——Task 6 `start_new_session` 保证——daemon 死掉后前端自动重生；此为最后手段，注释说明）。任务正常被取消 → 响应 `E_CANCELLED`。对不存在/已完成的 id → `{"cancelled": false}`。
- **空闲退出**：连接引用计数（`stream_writer` 计数）归零后 `asyncio.wait_for(idle_event, timeout=idle_timeout)`；退出前 close server、销毁引用（池/缓存随进程消亡）、删 lock。
- fetch impl 异常 → `make_error(id, E_INTERNAL, str(e))`；`ConcurrencyLimitError` → `make_error(id, "CONCURRENCY_LIMIT", str(e))`（前端映射回限流文案）。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_worker.py`（真 unix socket + 真事件循环；fetch op 用 monkeypatch 假 wrapper，不起浏览器）

```python
async def test_ping_reports_identity(tmp_path, ...):
    async with serve_worker(tmp_path, env_hash="ab12cd34") as (sock, token):   # fixture 拉起 DaemonWorker 任务
        resp = await ping(sock, token)
        assert resp["status"] == "ready" and resp["config_hash"] == "ab12cd34"

async def test_wrong_token_rejected(...):
    resp = await raw_request(sock, make_request(OP_PING, {}, "wrong", 1, "0.3.0"))
    assert resp["error"]["code"] == E_UNAUTHORIZED

async def test_fetch_page_routes_to_wrapper_and_returns_result(monkeypatch, ...):
    seen = {}
    async def fake_wrapper(**kw): seen.update(kw); return "METADATA: {}\n\nbody"
    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", fake_wrapper)
    resp = await raw_request(sock, make_request(OP_FETCH_PAGE, {"url": "http://x", "mode": "basic", "max_length": 100}, token, 2, "0.3.0"))
    assert resp["result"]["result"].endswith("body") and seen["url"] == "http://x"

async def test_multiplex_two_requests_one_connection(...):     # 两个慢请求交错,各自 id 收到各自响应
    ...

async def test_cancel_propagates_and_reports_cancelled(monkeypatch, ...):
    started = asyncio.Event()
    async def slow_wrapper(**kw): started.set(); await asyncio.sleep(30)
    monkeypatch.setattr(worker_mod, "fetch_page_wrapper", slow_wrapper)
    # 发 fetch(不读响应) → 等 started → 发 cancel → 收 E_CANCELLED 响应,worker _tasks 清空

async def test_idle_timeout_exits(...):                        # idle_timeout=0.2,断连后 0.5s 内进程内 serve() 返回且 lock 删除

async def test_shutdown_op_stops_worker(...):                  # shutdown → serve() 返回,lock 删除
```

- [ ] **Step 2/3/4:** 确认失败 → 实现 → 确认通过（`uv run pytest tests/daemon/test_worker.py -q`；cancel-强杀分支单测用假 `os.killpg` monkeypatch 验证调用即可，真进程检查留 Task 13）

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/daemon/worker.py src/scrapling_fetch_mcp/daemon/__main__.py tests/daemon/
git commit -m "feat(daemon): DaemonWorker——op 路由/鉴权/多路复用/取消传播

fetch 按 id 多路复用,progress 桥接协议帧;cancel 宽限 5s 后
killpg 兜底(浏览器残留的核弹保险,daemon 死后前端自动重生);
引用计数空闲退出。"
```

---

### Task 8: 前端 BackendClient（`_client.py`）

**Files:**
- Create: `src/scrapling_fetch_mcp/_client.py`
- Test: `tests/test_client.py`

**Interfaces:**
- Consumes: Task 5 protocol、Task 6 lifecycle、Task 4 `resolve_daemon_env`
- Produces:
  - `class BackendClient`: `__init__(self) -> None`（内部惰性 `resolve_daemon_env()`）；`async def call(self, op: str, payload: dict, ctx: Context | None = None) -> dict`——ensure 连接 → 发请求 → progress 帧 → `ctx.report_progress(progress, total, message)` → 返回 `result`；`error` 响应抛 `BackendError(code, message)`；`async def cancel(self, req_id: int) -> None`；`async def aclose(self) -> None`
  - `class BackendError(RuntimeError)`: `.code` 属性
  - 模块级单例 `get_client() -> BackendClient`
  - `make_adapter(op: str) -> Callable`——生成 `(ctx, **params) -> str` 形态的异步工具函数：`req_id = client.next_id(); try: resp = await client.call(op, params, ctx) except CancelledError: await client.cancel(req_id); raise`；`BackendError` 的 CONCURRENCY_LIMIT 映射为 `RuntimeError("并发已达上限(全局),请稍后重试: ...")`，其余映射 `RuntimeError(f"ERROR: {code}: {message}")`（MCP 框架把工具异常转 is_error 结果）
  - 请求看门狗：`timeout = config.acquire_timeout + config.fetch_timeout + 60`，超时发 cancel 后抛 `BackendError("DAEMON_TIMEOUT", ...)`
  - 断线重试：连接级异常/EOF → 丢弃连接 → 重跑 `ensure_daemon` → 最多重试 2 次；仍失败抛 `BackendError("DAEMON_UNAVAILABLE", 排查指引字符串, 含 `scrapling-fetch-mcp daemon status` 与 `SCRAPLING_DAEMON_DIR`)`

reader 任务常驻：`id → Future` 表分发 response/progress；`_connect_lock` 防并发首连重复拉起 daemon。

- [ ] **Step 1: 写失败测试** `tests/test_client.py`（BackendClient 的 `ensure_daemon`/socket 路径 monkeypatch 到 tmp_path，配合 Task 7 的 `serve_worker` fixture 或直接 fake socket server）

```python
async def test_call_roundtrip_and_progress(monkeypatch, ...):
    # fake daemon: 收 fetch 请求 → 发 progress 帧 → 发响应
    seen_progress = []
    class Ctx: 
        async def report_progress(self, p, t, m=None): seen_progress.append((p, t, m))
    resp = await client.call("fetch_page", {"url": "u"}, Ctx())
    assert seen_progress == [(50, 100, "x")] and resp["result"] == "..."

async def test_retry_after_daemon_kill(...):
    sock = await ensure_started(); c = get_client()
    await c.call("ping", {}, None)
    kill_daemon(sock)                                  # SIGKILL
    assert (await c.call("ping", {}, None))["status"] == "ready"   # Review Focus 2

async def test_unavailable_maps_to_daemon_unavailable(monkeypatch, ...):
    # ensure_daemon 指向空目录且 spawn 命令 monkeypatch 为必然失败
    with pytest.raises(BackendError, match="DAEMON_UNAVAILABLE"): await c.call("ping", {}, None)

async def test_cancel_on_client_cancellation(...):
    # fake daemon 慢响应 → 任务取消 → fake daemon 收到 cancel 帧 → CancelledError 传播
```

- [ ] **Step 2/3/4:** 确认失败 → 实现 → 确认通过

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_client.py tests/test_client.py
git commit -m "feat(client): 前端 BackendClient——多路复用/进度桥/断线重生

持久连接按 id 复用;progress→ctx.report_progress;客户端取消→
cancel 帧;daemon 死亡自动重拉,不可用时报 DAEMON_UNAVAILABLE 附排查指引。"
```

---

### Task 9: 前端接线（mcp.py 瘦身）+ import 边界守卫

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`（import 面、`_register_tool` 的 impl、`run_server` 启动序列）
- Modify: `src/scrapling_fetch_mcp/_tool_factory.py`（如它顶层 import `_fetcher` 类型——改为 `TYPE_CHECKING` 或去依赖；以实际 grep 为准）
- Test: `tests/test_import_boundary.py`（新建）、`tests/test_mcp_registration.py`（适配）

**Interfaces:**
- Consumes: Task 8 `get_client/make_adapter`、Task 4 `resolve_daemon_env`
- Produces: `uv run scrapling-fetch-mcp` 行为不变（工具 schema/文档串不变），抓取改走 daemon；`run_server()` 不再调用 `ensure_browserforge_data/ensure_camoufox`

改造点（全部有据可查）：
1. `mcp.py:8-11,22` 删除对 `_browser_check/_fetcher` 的顶层 import；`mcp.py:24` 的 `build_extension()` 保留（轻）。
2. `_register_tool(..., impl_func=make_adapter("fetch_page"))` / `make_adapter("fetch_pattern")`；`_tool_factory` 若有 `from scrapling_fetch_mcp._fetcher import ...` 顶层行，挪进 `TYPE_CHECKING` 或删除。
3. `run_server()`：`init_config_from_env()` + CLI 覆盖后，调一次 `resolve_daemon_env()` 热身（校验配置合法），其余不变；`_auth.py` 分支不动。
4. daemon 拉起/浏览器准备全部发生在 worker（Task 7），前端不再 import `_browser_check`。

- [ ] **Step 1: 写失败测试** `tests/test_import_boundary.py`

```python
HEAVY = ("trafilatura", "markitdown", "numpy", "onnxruntime", "playwright",
         "camoufox", "scrapling.fetchers", "scrapling_fetch_mcp._fetcher",
         "scrapling_fetch_mcp._scrapling", "scrapling_fetch_mcp._extractor_strategy")

def test_frontend_import_stays_thin():
    code = ("import sys; import scrapling_fetch_mcp.mcp; "
            "bad=[m for m in %r for k in sys.modules if k == m or k.startswith(m + '.')]; "
            "raise SystemExit('heavy: ' + ','.join(bad) if bad else 0)") % (HEAVY,)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT)
    assert r.returncode == 0, r.stdout + r.stderr
```

（REPO_ROOT 取 `Path(__file__).resolve().parents[1]`；`uv run` 保证包已安装）

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_import_boundary.py -q`
Expected: FAIL（现状 `mcp.py` 顶层 import `_fetcher` → trafilatura/numpy 全在）

- [ ] **Step 3: 实施改造**（上面 4 点）

- [ ] **Step 4: 回归 + 冒烟**

Run: `uv run pytest tests/test_mcp_registration.py tests/test_import_boundary.py tests/test_tool_factory.py -q` → PASS
Run: `timeout 30 uv run python -c "import json,subprocess;p=subprocess.Popen(['uv','run','scrapling-fetch-mcp'],stdin=subprocess.PIPE,stdout=subprocess.PIPE);p.stdin.write(b'{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"initialize\",\"params\":{\"protocolVersion\":\"2025-06-18\",\"capabilities\":{},\"clientInfo\":{\"name\":\"t\",\"version\":\"0\"}}}\n');print(p.stdout.readline())"` → 含 serverInfo

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/mcp.py src/scrapling_fetch_mcp/_tool_factory.py tests/
git commit -m "feat(mcp): 前端瘦身——工具改走 daemon,import 边界守卫

stdio/streamable-http 前端只保留 SDK+schema+BackendClient;
重 import 全部移入 daemon 进程。CI 守卫测试防回归。"
```

---

### Task 10: daemon 管理 CLI（`daemon status|shutdown`）

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`（argv 预处理：`daemon` 子命令分流，不进 MCP 路径）
- Modify: `src/scrapling_fetch_mcp/daemon/lifecycle.py`（如需补 `read_lock(sock) -> dict | None`）
- Test: `tests/daemon/test_cli.py`

**Interfaces:**
- Consumes: Task 6 `daemon_sockets/ping/read_lock`、Task 5 `make_request/OP_STATUS/OP_SHUTDOWN`
- Produces: `uv run scrapling-fetch-mcp daemon status`（表格：sock 名、pkg、hash、pid、uptime、clients、cache_entries；无 daemon 时输出"无存活 daemon"退出 0）；`uv run scrapling-fetch-mcp daemon shutdown [--all | --socket <名>]`（默认仅当前版本+hash 的 daemon）；退出码：status 恒 0，shutdown 找不到目标 1

实现：`run_server()` 入口先判 `sys.argv[1:2] == ["daemon"]` → `argv.pop(1)` 后按 `--status/--shutdown/--all/--socket` 用 `ArgumentParser` 解析并执行，`sys.exit(rc)`；MCP 路径零改动。status 对每个 socket：lock JSON + ping（5s 超时，失败标记 DEAD 并提示可 `shutdown --all` 清理）。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_cli.py`：起一个 fake worker（Task 7 fixture）→ `main(["daemon","status"])` 输出含其 sock 名与 "ready"（capsys）；`daemon shutdown` 后 worker serve 返回、lock 消失；对空目录 `daemon shutdown` 退出码 1。

- [ ] **Step 2/3/4:** 失败 → 实现 → 通过（`uv run pytest tests/daemon/test_cli.py -q`）

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/mcp.py src/scrapling_fetch_mcp/daemon/ tests/daemon/
git commit -m "feat(cli): daemon status/shutdown 管理子命令

status 汇总全部存活 daemon(版本/配置/pid/池/缓存);shutdown
默认仅当前版本+配置,--all 清场。"
```

---

### Task 11: 浏览器池（`daemon/pool.py`）+ `_scrapling.py` 接线

**Files:**
- Create: `src/scrapling_fetch_mcp/daemon/pool.py`
- Modify: `src/scrapling_fetch_mcp/_scrapling.py`（`_do_browse` 的 stealth/max-stealth 分支）
- Test: `tests/daemon/test_pool.py`、`tests/test_scrapling.py`（追加）

**Interfaces:**
- Consumes: `scrapling.engines._browsers._camoufox.AsyncStealthySession`（`.fetch(url, timeout=, page_action=)`，构造参数对齐 `_scrapling.py:63-83` 两分支的 kwargs；`__aenter__/__aexit__/close` 见 scrapling `_camoufox.py:509-524`）；Task 3 的 config 属性
- Produces:
  - `class BrowserPool`: `__init__(self, idle_ttl: float, max_age: float, max_sessions: int, max_requests: int)`；`async def fetch(self, url: str, mode: str, timeout_ms: int, page_action: Callable | None = None) -> Any`（返回 scrapling Response）；`async def close_all() -> None`；`def stats() -> dict`（`{"sessions": n, "hits": h, "misses": m, "buckets": [域名...]}`）
  - `daemon/worker.py` 的 `status` op 里 `pool` 字段接 `stats()`（Task 7 预留 null 处）
  - `_scrapling.py`：`config.browser_pool` 为真且 mode ∈ {stealth, max-stealth} 时改走 `get_pool().fetch(...)`（`get_pool()` 模块级惰性单例，参数取 config；basic 分支与关闭时行为完全不变）

桶语义（spec §6.2 全部落实）：桶键 `(tldextract(url).registered_domain or urllib.parse.urlsplit(url).netloc, mode)`；桶内 `asyncio.Lock` 串行；命中判定——桶存在且未触发任一重建条件（空闲>idle_ttl、年龄>max_age、请求数>max_requests）则复用（hits+1），否则销毁重建（misses+1）；`fetch` 抛异常 → 销毁该桶会话再 re-raise；挑战页检测：复用 `_fetcher` 管线现有的可疑信号判断函数（以 grep `_extractor_strategy.py`/`_fetcher.py` 的 jina 仲裁可疑判定为准，抽成可复用谓词 `looks_suspicious(response) -> bool`，若已在别处实现则引用之）→ 疑似即销毁桶；池总量 `max_sessions` LRU 逐出（逐出即 close）。

- [ ] **Step 1: 写失败测试** `tests/daemon/test_pool.py`（FakeSession 替身：记录构造参数、fetch 计数、可注入异常；monkeypatch `pool._new_session` 工厂）

```python
async def test_same_domain_reuses_session(...):
    await pool.fetch("http://a.example.com/1", "stealth", 1000); await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert fake.built == 1 and pool.stats()["hits"] == 1

async def test_different_domain_or_mode_new_bucket(...):      # b 域名 / max-stealth 各建新桶
async def test_rebuild_on_idle_ttl_and_max_age_and_max_requests(...):  # 注入时钟(monkeypatch time.monotonic)
async def test_rebuild_on_fetch_error_and_on_suspicious_response(...):
async def test_lru_evicts_beyond_max_sessions(...):           # max_sessions=2,第 3 桶淘汰最旧
async def test_close_all_closes_everything(...):
async def test_bucket_lock_serializes_same_domain(...):       # 并发两个 fetch,同桶串行(FakeSession 记录重叠)
```

`tests/test_scrapling.py` 追加：`config.browser_pool=True` 时 `_do_browse("u","stealth")` 走 pool（monkeypatch `_scrapling.get_pool`），False 时走原路径（现有用例回归）。

- [ ] **Step 2/3/4:** 失败 → 实现 → 通过（`uv run pytest tests/daemon/test_pool.py tests/test_scrapling.py -q`）

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/daemon/pool.py src/scrapling_fetch_mcp/_scrapling.py src/scrapling_fetch_mcp/daemon/worker.py tests/
git commit -m "feat(pool): 浏览器池——按(域名,模式)分桶,五触发重建

同域名复用 Firefox 会话省冷启动;空闲/年龄/请求数/异常/疑似挑战
均销毁重建,LRU 限池深,默认关闭(--browser-pool 开启)。"
```

---

### Task 12: 文档更新 + 版本 0.3.0

**Files:**
- Modify: `pyproject.toml`（`version = "0.2.0"` → `"0.3.0"`）
- Modify: `README.md`、`MCP_CONFIG_EXAMPLES.md`

**Interfaces:**
- Consumes: 全部前序任务产出的事实
- Produces: 与实现一致的文档；版本 0.3.0

- [ ] **Step 1: README 更新**（中文）：架构段加 daemon 一句话 + 生命周期表（自动拉起/空闲 600s 自退/死亡重生/按版本+配置隔离、过渡期可能短暂双 daemon ~155MB）；`daemon status|shutdown` 用法；新 CLI/env 清单（Task 3 全部 + `SCRAPLING_DAEMON_DIR`/`SCRAPLING_DAEMON_IDLE_TIMEOUT`/`SCRAPLING_CACHE_MAX_ENTRIES`）；并发语义变化（max-concurrent 从每会话变全局）；Windows 不支持说明。
- [ ] **Step 2: MCP_CONFIG_EXAMPLES.md 更新**：新配置进"可用配置项"表；超时章节补调查结论（SDK 每 15s SSE 心跳独立于工具 progress，浏览器加载阶段无需工具侧心跳；nginx `proxy_read_timeout` 在 `proxy_buffering off` 下默认值即可存活，调大属双保险；替换原"浏览器加载阶段内部无法插入心跳"表述）；DAEMON_UNAVAILABLE/daemon 排查指引。
- [ ] **Step 3: 验证**

Run: `uv run pytest -q`（全量）→ PASS；`rg -n "0\\.2\\.0" pyproject.toml README.md` 确认版本已换
- [ ] **Step 4: Commit**

```bash
git add pyproject.toml README.md MCP_CONFIG_EXAMPLES.md uv.lock
git commit -m "chore(release): 0.3.0——daemon 架构与浏览器池文档

生命周期/管理 CLI/新配置项入册;超时章节按 SDK 心跳机制调查
结论修正(15s SSE ping 独立于工具 progress)。"
```

---

### Task 13: 慢速集成测试（`-m slow`）+ CI marker

**Files:**
- Create: `tests/daemon/test_integration_slow.py`
- Modify: `pyproject.toml`（`[tool.pytest.ini_options] markers = ["slow: 需要真实 daemon/浏览器的端到端用例"]`）
- Modify: `.github/workflows/canary.yml`（如存在慢速位；无则仅本地）

**Interfaces:**
- Consumes: 全链路（真 daemon spawn、真 basic 抓取）
- Produces: `uv run pytest -m slow` 可选跑的真集成

- [ ] **Step 1: 写测试**（全部 `@pytest.mark.slow`，`SCRAPLING_DAEMON_DIR` 注入 tmp_path，`SCRAPLING_DAEMON_IDLE_TIMEOUT=30`）

```python
async def test_end_to_end_basic_fetch_via_daemon(tmp_path):        # s_fetch_page 工具函数级:adapter→daemon→example.com
    # 断言结果含 METADATA 与正文,daemon lock 存在

async def test_second_frontend_reuses_daemon(tmp_path):            # 两个 BackendClient 实例 → 同一 socket 同一 pid
async def test_client_cancel_leaves_no_firefox(tmp_path):          # stealth 抓取慢站(自建本地 slow http server),客户端侧取消
    # await asyncio.sleep(6) 后 subprocess pgrep -f "firefox" 不含 camoufox 残留(Review Focus 4)
async def test_uv_rolling_update_coexistence(tmp_path):            # 伪造不同 hash 的第二个前端 → 各自 socket 并存,互不干扰(Review Focus 5)
```

- [ ] **Step 2: 跑确认行为**（允许先 FAIL 后修实现，集成暴露的问题回修对应模块并小提交）

Run: `uv run pytest tests/daemon/test_integration_slow.py -m slow -q`
Expected: PASS（浏览器用例耗时分钟级属预期）

- [ ] **Step 3: marker 注册 + 全量**

pyproject 加 markers 段；`uv run pytest -q`（不含 slow）→ PASS

- [ ] **Step 4: Commit**

```bash
git add tests/daemon/test_integration_slow.py pyproject.toml .github/
git commit -m "test(daemon): -m slow 端到端集成——真实抓取/取消无残留/双版本共存"
```

---

## 收尾

- 全量：`uv run pytest -q` + `uv run pytest -m slow -q`（一次性）。
- `git log --oneline` 核对提交序列原子性。
- 向用户汇报：性能对比数字（前端 RSS 64 MB vs 192 MB/会话）、池默认关闭的提醒、双 daemon 共存说明。
