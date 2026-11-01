# Daemon 化与浏览器池化设计

日期：2026-11-01
状态：待评审

## 1. 背景与动机

当前 MCP 前端是 stdio 子进程，**每个客户端会话重付一次完整 import 成本**（实测约
158 MB RSS / 会话，含 uv 包装进程约 192 MB），其中 markitdown → numpy +
onnxruntime 与 trafilatura/readability/scrapling.parser 是大头；camoufox 已安装
时纯 basic 用户也要背 playwright 全套。重型状态（PageCache、策略缓存、
MarkItDown/ONNX session）随进程消亡，stealth 抓取每次新起 Firefox 进程用完即毁。

参照 tools/ocr 的已验证模式（瘦 MCP 前端 + 每用户一个 daemon + unix socket
NDJSON），把抓取后端常驻化。同时把"浏览器实例池化/复用"从非目标升级为可选特性，
按域名分桶控制 WAF 指纹风险。

## 2. 目标 / 非目标 / 反目标

### 目标

1. MCP 前端瘦身：stdio 与 streamable-http 两种传输都是薄前端，全部抓取逻辑在
   daemon 进程执行（多客户端共享 import 内存、PageCache、并发闸门与浏览器池）。
2. Daemon 生命周期全自动：首个请求触发拉起，空闲自动退出，死亡自动重生，对用户
   透明；无需 systemd/socket activation。
3. 浏览器池（默认关闭）：同域名+同模式复用 Firefox 会话，省每次冷启动（数秒 +
   数百 MB 峰值），通过分桶、空闲回收、失败重建、指纹硬上限控制 WAF 风险。
4. 升级 mcp SDK 2.0.0 → 2.3.0（`mcp>=2.3.0,<3.0.0`），并核对 2.0→2.3 的破坏性
   变更（重点：extensions/skills、auth、streamable-http API 面）。
5. 修复长驻暴露的隐患：PageCache 加条目上限；取消传播（MCP cancel → daemon 真
   取消 asyncio 任务并清理浏览器）。

### 非目标（YAGNI）

- systemd / socket activation 集成（自管 daemon 已覆盖）。
- Windows（unix socket 方案仅限 Linux/macOS；Windows 上 daemon 不可用直接报错）。
- basic 模式的池化（AsyncFetcher 无状态，无收益）。
- 浏览器/会话状态跨 daemon 重启持久化。
- 跨机分布式 daemon；多 UID 加固（token + socket 0600 已够单用户场景）。
- 新增 MCP 工具（status 仅作诊断 op，不暴露为工具）。

### 反目标（出现即失败）

- 配置不一致时静默（前端配置 ≠ daemon 配置必须显式报错）。
- daemon 泄漏：客户端全部退出后 daemon 无限存活。
- 池化把同一指纹长期间歇性地打向大量无关域名（farm 特征）。
- 取消/超时后浏览器进程残留累积（现状已知问题，长驻会放大，必须处理）。

## 3. 现状约束

- `fetch_page_impl` / `fetch_pattern_impl`（`_fetcher.py`）已是纯函数式入口，返回
  纯字符串（`METADATA: {json}\n\n{content}`，`_fetcher.py:388,470`），参数均为
  JSON 可序列化值——`page_action` 未通过 MCP 参数外露，协议边界干净。
- scrapling 0.3.6 锁定（0.3.7+ 引擎模块顶层 import patchright 会崩）、camoufox
  <0.5 锁定，import 全部 lazy——这些 pin 与 lazy 约束原样保留。
- 配置已 env 优先（`_config.py` `init_config_from_env`），CLI 参数与 env 一一对应。
- mcp SDK 侧事实（`_streamable_http_modern.py`）：SSE 流最迟 15s 提交并每 15s 发
  `: ping`；uvicorn 未配请求级超时；客户端断连会取消 handler 任务组。daemon 化
  后 streamable-http 前端不再执行抓取，HTTP 超时层对抓取本身不再构成威胁，仅剩
  客户端自身超时（文档已覆盖）。
- ocr-mcp（`/share/rw/repo/tools/ocr`）的 lifecycle/worker/protocol 模式经过完整
  测试验证，可整体参照；其教训：版本校验未实现（`"v":1` 是装饰性的）、ping 状态
  恒 ready——本项目必须补上。

## 4. 总体架构

**决定：方案 A——两种传输都做成薄前端，全部走 daemon**（用户拍板）。

```
MCP 客户端 (stdio)      MCP 客户端 (streamable-http)
      │                        │ HTTP
┌─────▼──────┐          ┌──────▼───────┐
│ 薄前端进程  │          │ 薄前端进程    │     ~64 MB（MCP SDK + schema + BackendClient）
└─────┬──────┘          └──────┬───────┘
      │    unix socket + NDJSON (token 鉴权, 按 id 多路复用)
      └──────────┬─────────────┘
           ┌─────▼─────┐
           │  daemon   │  ~155 MB（每个 (包版本, 配置) 一个，空闲退出）
           │ fetcher / extractor / converter / browser_check
           │ PageCache / 并发闸门 / 浏览器池（可选）
           └───────────┘
```

- 前端保留：`mcp.py`（传输适配 + CLI + 工具注册）、`_features.py`、
  `_tool_factory.py`、`_skills.py`、`_auth.py`（streamable-http 鉴权）、
  `_client.py`（新，BackendClient）。
- daemon 侧：`_fetcher.py`、`_scrapling.py`、`_extractor_strategy.py`、
  `_strategy_factory.py`、`_html_converter.py`、`_markdownify.py`、
  `_markdown_postprocessor.py`、`_search_engines.py`、`_config.py`（daemon 配置）、
  `_url_matcher.py`、`_url_rewriter.py`、`_default_rules.py`、
  `_default_rewrite_rules.py`、`_browser_check.py`、`_camoufox_fetch.py`、
  `_concurrency.py`，以及新增 `daemon/`（worker/lifecycle/protocol/pool）。
- 同包内按 import 边界隔离：前端 import 链不得触达上述重型模块（CI 加 import
  边界测试强制，见 §9）。
- 不保留"进程内直跑"回退模式；daemon 拉起失败即报错（含清晰排查指引）。

## 5. Daemon 设计

### 5.1 文件与生命周期（参照 ocr-mcp，~500 行基建）

- 路径：`platformdirs.user_data_dir("scrapling-fetch-mcp")/` 下，以
  `daemon-<包版本>-<配置摘要8hex>` 为名一组文件：`.sock`、`.lock`（pid +
  token）、`.spawn.lock`、`.log`；env `SCRAPLING_DAEMON_DIR` 可覆盖。
  **socket 按（包版本，配置摘要）命名隔离**：同版本同配置的前端共享一个
  daemon，不同版本/配置各自拉起、互不干扰，陈旧 daemon 靠空闲 600s 自退回收。
  （2026-11-01 评审后拍板，替代 kill+重拉模型——避免 uvx 滚动更新后新旧前端
  互相 flapping：各自把对方刚拉起的 daemon 判为不匹配并杀掉，永久翻转。代价：
  版本滚动或配置分叉的过渡期短暂共存 2 个 daemon，约 +155 MB，最长约一个空闲
  超时周期。）
- 启动：`ensure_daemon()` → 前端计算自己的（包版本，配置摘要）得出 socket 名 →
  读 lock → `is_alive()`（pid 存活 + socket ping 2s/5s 超时）→ 通过则复用；否则
  清理陈旧 lock/socket，`spawn.lock` `O_CREAT|O_EXCL` 原子仲裁并发拉起，抢到者
  `Popen([sys.executable, "-m", "scrapling_fetch_mcp.daemon"],
  start_new_session=True, stdout/stderr→daemon.log)` 后轮询 ping（0.2s 间隔，
  60s 上限），未抢到者等待对方就绪。ping 应答回读 daemon 自报的 pkg 版本与
  config_hash，与 socket 名期望不符视为陈旧 socket → 清理重拉（防御路径，
  正常不应发生）。
- 退出：连接引用计数归零后空闲 600s（`SCRAPLING_DAEMON_IDLE_TIMEOUT`）自杀；退出
  前关闭所有池化浏览器、删 lock。
- 鉴权：daemon 启动生成 `secrets.token_hex(16)` 写入 lock；每请求校验；socket
  chmod 0600。
- 就绪定义：socket 可 ping 即 ready（与 OCR 一致）。stealth 浏览器下载照旧在
  daemon 内后台进行，未就绪时按现有 METADATA 降级语义返回。

### 5.2 协议（NDJSON over unix socket）

信封：请求 `{"v":2, "pkg":"<前端包版本>", "id", "op", "token", "payload"}`；响应
`{"v":2, "id", "ok", "result"|"error"}`；中间帧（daemon→前端，工具执行中）：
`{"v":2, "id", "progress":{...}}`。

- op 集合：`fetch_page`、`fetch_pattern`（payload=工具参数 dict，result=字符串）、
  `cancel`（payload={cancel_id}）、`ping`（就绪探测）、`status`（诊断：stealth
  就绪/降级原因、池状态、缓存条目/命中、pid、uptime、版本）、`shutdown`。
- **版本握手（吸取 OCR 教训）**：协议信封带 `v`（协议版本）；daemon 在 ping/
  握手应答中自报 pkg 版本与 config_hash。因 socket 命名已按（版本，配置）隔离，
  正常路径不会出现不匹配；若自报值与 socket 名期望不符，前端按陈旧 socket 处理
  （清理 + 重拉），不做打断在途请求的主动 kill 替换。
- **按 id 多路复用**：同一前端连接可并发携带多个请求（id 关联响应与 progress
  帧）；`cancel` 按 id 取消 daemon 侧 asyncio 任务。daemon 侧并发仍由现有
  `ConcurrencyGuard`（默认 5）控制——语义从"每会话 5"变为"全局 5"，属预期变化，
  写入文档。
- **取消传播**：MCP 客户端 cancel 通知 → 前端发 `cancel` → daemon 取消对应
  asyncio 任务；daemon 内部 `fetch_timeout` 兜底照旧。取消路径必须显式关闭
  scrapling 会话/等待浏览器退出（对 cancel 加宽限期 ~5s，超时强杀进程组），解决
  现状"浏览器进程可能短暂残留"。
- **配置归属与摘要**：daemon-owned 配置（`_config.py` 中除
  transport/host/port/auth/mcp-path 外全部影响抓取行为的键：min-mode、cache-ttl、
  max-concurrent、fetch/acquire timeout、jina_*、rules/rewrite 文件路径、
  browser-pool 及池参数、scraping_dir 等；features 仅影响前端 schema，不入摘要）
  由拉起者以 env 形式传给子进程（现有 `SCRAPLING_*` env 直接继承，CLI 参数在
  前端解析后转写成 env）。**配置摘要** = 归一化后的 daemon-owned 配置做
  canonical JSON + sha256 取前 8 hex。**相对路径（scraping_dir、rules/rewrite
  配置文件）在前端先解析为绝对路径**（相对 MCP 客户端工作目录，保持既有语义）
  再进 env 与摘要，避免"同字符串、不同 CWD"被判一致（反目标：静默不一致）。
  不同摘要即不同 daemon（§5.1），不存在 CONFIG_MISMATCH 报错路径。

### 5.3 前端 BackendClient

- 每前端进程一条持久连接；首连 `ensure_daemon` 用 asyncio.Lock 防重复拉起；请求
  按 id 复用；连接断开/超时 → 丢弃连接重跑 `ensure_daemon`（最多 2 次），仍失败
  → MCP is_error 结果 `ERROR: DAEMON_UNAVAILABLE: ...`（沿用 OCR 兜底语义）。
- progress 帧 → `ctx.report_progress` 映射；客户端 cancel → 发 `cancel` 帧。

### 5.4 daemon 管理 CLI

入口 `scrapling-fetch-mcp daemon status|shutdown`：`status` 扫描用户 daemon 目录
下全部 socket，汇总列出存活 daemon（socket 名、pkg 版本、config_hash、uptime、
客户端数、池与缓存概要，读 lock + ping）；`shutdown` 按 `--all` 或 `--socket
<名>` 优雅退出，默认仅当前版本+配置的 daemon。token 鉴权同普通请求，无 daemon
时安静退出（status 输出空表）。

## 6. 浏览器池设计（默认关闭）

### 6.1 形态

- 开关：`--browser-pool` / `SCRAPLING_BROWSER_POOL`（默认 off，用户拍板沿用本人
  此前建议：可选特性）。
- 实现基于 scrapling `AsyncStealthySession` 自管生命周期（现有便捷 API
  `async_fetch` 是一次性 session，`fetchers/firefox.py:191`），每次 `fetch(url)`
  复用同一 Firefox 进程与 context。

### 6.2 分桶与回收（核心：控制"指纹新鲜度"风险）

- 桶键：`(eTLD+1 域名, mode)`（mode ∈ stealth/max-stealth，启动参数不同必须分
  桶；域名用 tldextract——trafilatura 已带入的依赖）。同域名连续抓多页时复用收
  益最大、风险增量最小；跨域名不共享身份，天然避免 farm 特征。
- 回收/重建触发（任一满足即销毁重建）：
  1. 空闲 > 300s（`SCRAPLING_POOL_IDLE_TTL`）；
  2. 累计年龄 > 1800s（`SCRAPLING_POOL_MAX_AGE`，指纹硬上限，即"新鲜度"约束）；
  3. 抓取异常/超时；
  4. 疑似挑战页（响应 METADATA 中现有可疑信号 + 标题/内容 Cloudflare interstitial
     启发式）——疑被标记的身份不可复用；
  5. 请求数 > 50（`SCRAPLING_POOL_MAX_REQUESTS`，防状态累积）。
- 并发：同桶内 `asyncio.Lock` 串行（一个 Firefox context 上的多 tab 并发会放大
  资源与关联风险，不做）；不同桶并行，池总量仍受全局 `ConcurrencyGuard` 约束。
- 池上限：最多 4 个活跃 Firefox（`SCRAPLING_POOL_MAX_SESSIONS`），LRU 逐出；池
  命中/未命中计数进 `status` op。
- daemon 空闲退出/版本重拉时全部池化会话销毁，不留持久状态。

## 7. 前置修复

1. **PageCache 条目上限**：`_config.py` PageCache 增加上限（默认 256 条，env
   `SCRAPLING_CACHE_MAX_ENTRIES`），超限先淘汰已过期、仍满则 FIFO 逐出；每次插入
   顺带 `clear_expired`。daemon 长驻会放大无上限增长的隐患，此项独立可测，先行
   落地。
2. **mcp SDK 升级**：`mcp>=2.3.0,<3.0.0`；核对 2.0.0→2.3.0 changelog（重点
   extensions（SEP-2640 skills）、auth、streamable-http 签名）；回归现有测试与
   手动 stdio/http 冒烟。此步独立可先行，不依赖 daemon。
3. **超时文档修正**：`MCP_CONFIG_EXAMPLES.md` 超时章节补记调查结论（SDK 每 15s
   SSE 心跳独立于工具 progress，浏览器加载阶段无需工具侧心跳；nginx 默认
   `proxy_read_timeout` 在心跳可透传（buffering off）时即够用，调大属双保险）。

## 8. 版本与发布

- 包版本 0.2.0 → **0.3.0**（minor：新特性 + 行为变化）。
- README / MCP_CONFIG_EXAMPLES.md 新增：daemon 架构说明（一句话 + 生命周期表 +
  按（版本，配置）隔离的拓扑说明与过渡期双 daemon 共存说明）、管理 CLI
  （`daemon status|shutdown`）、新 env/CLI（`SCRAPLING_DAEMON_DIR`、
  `SCRAPLING_DAEMON_IDLE_TIMEOUT`、`--browser-pool` 及池参数）、并发语义变化
  （全局 5）、Windows 不支持说明。

## 9. 测试策略

- 单元：协议编解码与 progress/cancel 帧；lifecycle（复用/spawn 仲裁/陈旧清理/就绪
  轮询超时/（版本，配置）socket 命名隔离/ping 自报与期望不符的陈旧防御）；token
  拒绝；取消传播（含宽限期强杀路径，用假进程验证）；配置摘要（相对路径归一化、
  daemon-owned 键集）；PageCache 上限/过期/逐出；池逻辑（桶键、五个重建触发、
  LRU、串行锁）用 fake session 全覆盖，不起真浏览器；CLI status/shutdown。
- import 边界守卫（CI）：前端入口 `import scrapling_fetch_mcp.mcp` 后断言
  `sys.modules` 不含 `_fetcher/_scrapling/_extractor_strategy/markitdown/
  trafilatura/numpy/onnxruntime/playwright/camoufox`——防止未来回归把重 import
  拉回前端。
- 集成：spawn 真 daemon 走 unix socket 全链路（basic 模式 example.com 真实抓取，
  带 token、cancel、版本握手用例）；池化端到端标记 `-m slow`（同 ocr-mcp 的
  真实模型端到端先例），每日常规 CI 跑 basic、金丝雀工作流跑 stealth。
- 现有测试迁移：`_fetcher`/`_extractor_strategy` 等测试改从 daemon 侧 import，
  断言逻辑不变。

## 10. 留给 builder 的决定

- `daemon/` 包内部文件切分与命名（protocol/lifecycle/worker/pool 建议对齐 ocr-mcp
  但不强制）。
- `cancel` 宽限期内 scrapling 会话关闭的具体等待方式（context.close() vs 进程组
  kill 的组合）。
- 池化挑战页启发式的具体判定字段（在 METADATA 现有可疑信号上扩展，允许 builder
  按测试站点调整阈值）。
- mcp 2.0→2.3 changelog 中与本项目 API 面相关的具体适配点。

## 附：已拍板决定（非 builder 可改）

| 决定 | 内容 | 来源 |
|---|---|---|
| 架构 | 双传输均薄前端，全部走 daemon（方案 A） | 用户 2026-11-01 |
| 池化默认 | 默认关闭，`--browser-pool` 开启；分桶/回收/重建形态 | 用户认可"按建议设计" |
| mcp SDK | 升级至 2.3.0（`mcp>=2.3.0,<3.0.0`） | 用户 2026-11-01 |
| daemon 拓扑 | socket 按（包版本，配置摘要）命名隔离；不做 kill+重拉、无 CONFIG_MISMATCH 报错；陈旧 daemon 靠空闲自退 | 用户 2026-11-01（评审后拍板） |
| 相对路径 | 前端归一化为绝对路径（相对 MCP 客户端 CWD）再进 env/摘要/payload | 本人（评审后） |
| daemon 管理 CLI | `daemon status\|shutdown` 最小子命令 | 本人（评审后） |
| 配置摘要编码 | daemon-owned 键 canonical JSON + sha256 前 8 hex | 本人（评审后） |
| 包版本 | 0.3.0 minor | 本人按惯例定 |
| 池参数默认值 | idle 300s / max-age 1800s / max-sessions 4 / max-requests 50 | 本人 |
| daemon 空闲退出 | 600s | 本人（对齐 OCR） |
| 不保留直跑模式 | daemon 拉起失败即报错 | 本人（方案 A 的一致推论） |
