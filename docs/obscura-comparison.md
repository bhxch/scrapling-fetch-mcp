# 对比实验：scrapling-fetch-mcp vs Obscura 网页抓取能力评估

- 日期：2026-11-05
- 目的：对比本项目（Scrapling 0.3.6 + camoufox + daemon）与 [Obscura](https://github.com/h4ckf0r0day/obscura)（纯 Rust headless 引擎 v0.2.6）的网页抓取能力，评估将本项目抓取底层切换为 Obscura 的可行性。
- 环境：Fedora Linux x86_64；出口走 fake-ip 透明代理；Obscura 用官方 release 二进制（`x86_64-linux-stealth` 变体，含渲染 + stealth 传输）；本项目走 daemon 生产链路（`make_adapter("fetch_page")`，含缓存/Jina 仲裁等全部管线）。

## 1. 对比对象画像

| 维度 | scrapling-fetch-mcp（本项目） | Obscura v0.2.6 |
|---|---|---|
| 抓取引擎 | curl_cffi（basic，impersonate 最新 Chrome）+ camoufox（stealth，真 Firefox 反指纹） | 自研 Rust 引擎：V8 + 自研 DOM/渲染（taffy）+ 自研 HTTP 栈（stealth 变体用 wreq/BoringSSL） |
| JS 执行 | 真 Firefox（camoufox） | 真 V8，但 DOM/Web API 为自研模拟 |
| 反指纹 | camoufox（浏览器指纹级）+ browserforge | 进程级指纹随机化 + Chrome TLS/UA 模拟（stealth 需专用二进制 feature） |
| 进程模型 | 常驻 daemon（unix socket，空闲 600s 退出）+ 浏览器会话池（可选） | 单次进程（fetch）/多 worker 进程（scrape/serve） |
| 输出 | airead（正文提取+策略路由+Jina 仲裁）/ markdown / html | text / markdown（全 DOM 转换）/ html / links / original |
| 交付形态 | Python MCP server | Rust CLI + CDP server（兼容 Puppeteer/Playwright）+ MCP server |

## 2. 实验方法

站点矩阵 8 个，每站点重复 1-3 轮取中位：

| 类别 | 站点 | 判据 |
|---|---|---|
| 静态 | example.com、wikipedia | 关键词命中 + 最小长度 |
| JS 渲染 | news.ycombinator、quotes.toscrape/js、react.dev | JS 注入内容命中（quotes/js 无 JS 执行必失败） |
| 商业反爬 | g2.com（DataDome）、scrapingcourse-cf（Cloudflare 挑战页） | 未出现挑战页标记且正文命中 |
| 指纹 | tls.peet.ws/api/all | JA3/JA4/HTTP2 指纹自报 |

模式：本项目 basic / stealth / max-stealth（强制 `SCRAPLING_MIN_MODE=basic` 以获得真 basic——注意代码默认 min_mode=stealth，会把 basic 静默提升，`_config.py:85`）；Obscura default / stealth（`--allow-private-network` 绕过 SSRF 防护对 fake-ip DNS 的误伤）。

指标：正确性（关键词/挑战页标记/长度）、wall time、进程树 RSS 峰值、TLS/JA4 指纹、并发总耗时。

局限：机器上另有会话在并发抓取（已通过 daemon token 隔离 RSS 口径，但 CPU/网络争抢无法完全消除）；DataDome/CF 实测结果受出口 IP 信誉影响，换环境结论可能不同。

## 3. 核心结果

### 3.1 正确性（网页能否正确加载）——最重要指标

每格：成功率 · 中位耗时 · 中位内容长度 · 中位 RSS

| 站点 | ours/basic | ours/stealth | ours/max-stealth | obscura/default | obscura/stealth |
|---|---|---|---|---|---|
| example.com | 3/3 · 1.7s · 958 · 225MB | 3/3 · 4.6s · 917 · 1238MB | 3/3 · 4.5s · 917 · 1246MB | 3/3 · 1.1s · 960 · 39MB | 3/3 · 1.3s · 960 · 41MB |
| wikipedia | 3/3 · 1.2s · 27111 · 254MB | 3/3 · 6.7s · 27123 · 1318MB | 3/3 · 6.9s · 27123 · 1341MB | 3/3 · 5.7s · 58400 · 130MB | 3/3 · 5.4s · 58400 · 128MB |
| news.ycombinator | 3/3 · 0.9s · 4028 · 258MB | 3/3 · 4.8s · 4247 · 1324MB | 3/3 · 4.9s · 4245 · 1329MB | 3/3 · 1.6s · 10251 · 46MB | 3/3 · 2.0s · 10252 · 48MB |
| quotes.toscrape/js | 3/3† · 2.1s · 1064 · 261MB | 3/3 · 6.3s · 1526 · 1310MB | 3/3 · 6.3s · 1526 · 1303MB | 3/3 · 3.7s · 1751 · 48MB | 3/3 · 4.1s · 1751 · 50MB |
| react.dev（SPA） | 3/3‡ · 0.8s · 1736 · 282MB | 3/3 · 6.0s · 6929 · 1394MB | 3/3 · 6.0s · 6929 · 1401MB | 3/3 · 4.6s · 16024 · 148MB | 3/3 · 4.2s · 16024 · 141MB |
| g2.com（DataDome） | 0/2 · 16.5s | 1/2 · 18.7s | 1/2 · 20.0s | 0/2 · 2.0s | 0/2 · 3.4s |
| scrapingcourse-cf（CF 挑战） | 0/2（挑战页） | 0/2（挑战页） | 0/2（挑战页） | 0/2（挑战页） | 0/2（挑战页） |
| tls.peet.ws（JSON） | 1/1 · 0.7s | 1/1 · 3.9s | 1/1 · 16.6s | 1/1 · 0.7s | 1/1 · 0.7s |

总成功率：ours basic 80%、stealth/max-stealth 各 85%；obscura default/stealth 各 90%。

† basic 对 quotes/js 的命中来自 airead 管线的 Jina Reader 仲裁兜底（服务端渲染），非本地能力。
‡ basic 对 react.dev 只拿到 SSR 壳（1.7KB），airead 提取后的正文远少于 Obscura 全渲染的 16KB。

要点：

- **常规站点两边都能正确加载**，含 JS 渲染站：Obscura 自研引擎对 react.dev 这类重 SPA 渲染成功（16KB 内容），V8+DOM 模拟在本次矩阵内未暴露兼容性问题。
- **JS 渲染深度**：Obscura 拿到的渲染内容最全（wikipedia 58KB 全文、react.dev 16KB）；本项目 stealth 6.9KB（airead 只取正文属口径差异）；basic 只有 SSR 壳。
- **商业反爬双方都无解**：DataDome（g2.com）两边基本全挡（本项目 stealth/max-stealth 各偶发通过 1 次，属间歇放行）；Cloudflare 挑战页连 camoufox max-stealth 也停留在 "Performing security verification"。反爬成败更取决于 IP 信誉而非客户端指纹。

### 3.2 反爬能力（TLS/HTTP2 指纹实测，tls.peet.ws）

| 实现 | UA 自报 | HTTP | JA4 | 解读 |
|---|---|---|---|---|
| ours basic | Mac Chrome | h2 | `t13d1516h2_8daaf6152771_d8a2da3f94cd` | curl_cffi impersonate 最新 Chrome，强 |
| ours stealth/max | Firefox/156 | h2 | `t13d1517h2_8daaf6152771_3cbfd9057e0d` | 真 Firefox 全栈一致，最强一致性 |
| obscura default | 自有 UA（无版本号） | **HTTP/1.1** | `t13d1011h1_61a7ad8aa9b6_3fcd1a44f3e3` | 自研栈特征（无 h2、10 cipher/11 扩展），**极易被指纹识别** |
| obscura stealth | Windows Chrome | h2 | `t13d1516h2_8daaf6152771_d8a2da3f94cd` | BoringSSL 模拟 Chrome，与 curl_cffi 同段，强 |

- Obscura 的 stealth 传输层模拟有效，但**必须使用专用 `-stealth` 构建并显式开启**；default 模式指纹弱。
- 本项目 basic 就自带 Chrome TLS 模拟（scrapling 静态引擎底层为 curl_cffi `impersonate=DEFAULT_CHROME`，见 `.venv/.../scrapling/engines/static.py:48`），这一层并不落后。
- 行为层反爬（DataDome/CF 挑战）双方实测均不能稳定通过。
- Obscura SSRF 防护在 fake-ip 代理环境会误拦所有域名（解析到 198.18.0.0/15 即拒），必须 `--allow-private-network`；对部署在代理/企业网络环境的兼容性是个坑。

### 3.3 抓取效率

| 口径 | ours | obscura |
|---|---|---|
| 静态/轻 JS 单次（热） | **0.7-2.1s**（basic，daemon 热路径） | 1.1-2.0s（含进程冷启动） |
| JS/SPA 单次 | 4.2-10.1s（stealth，每请求冷启动 camoufox） | **3.7-4.6s** |
| 服务冷启动+首抓 | 3.5s（basic）/ 5.9s（stealth） | ~1s（无服务概念，进程即起） |
| 5 站并发总耗时 | basic **~2.9s**；stealth 17.3s（并发 5 个 camoufox 冷启动） | **4.1s**（--concurrency 5，多 worker 进程） |
| 页面缓存 | 有（TTL 300s，命中 ~0.05s） | 无 |

- 本项目 **basic 路径不弱**：daemon 热路径下比 Obscura 更快（无进程启动开销 + 缓存）。
- **stealth 是本项目瓶颈**：每请求冷启动 camoufox（4-7s、~1.2GB 峰值）。生产环境可开 `--browser-pool` 复用会话消除，但本次按默认配置测。
- Obscura 引擎层确实快且并发友好（多 worker 进程，5 并发 4.1s）。

### 3.4 运行时消耗

| 口径 | ours | obscura |
|---|---|---|
| 静态抓取进程峰值 | 210-310MB（daemon 常驻含依赖加载） | **17-48MB** |
| JS 渲染进程峰值 | 1.2-1.6GB（daemon + camoufox 树） | **130-160MB** |
| 空闲驻留 | daemon 常驻 ~282MB，空闲 600s 后退出 | 0（进程退出即释放） |
| 磁盘 | camoufox 浏览器 ~1.2GB | 单二进制 ~84MB |

README 宣称的"30MB 内存/85ms 加载"在真实站点上不会出现（那是极简页面的理想值），但**数量级优势属实**：JS 渲染场景内存约为本项目的 1/10。

### 3.5 输出质量（给 AI 读的正文）

wikipedia 样例对比：

- 本项目 airead：干净的正文 markdown（`# Web scraping` 标题 + 正文段落），27KB 无导航噪音。
- Obscura `--dump markdown`：全 DOM 转换，58KB 中前置大段主导航/侧栏/表格残留，正文淹没其中；文档明示不内置 Readability（"Obscura does not bundle Readability"，`docs/Extract-data.md:97`）。

本项目 airead 管线（策略路由 + Jina 仲裁 + markdown 瘦身 + 分页 + 元数据）是 Obscura 当前完全不具备的增值层。

## 4. 切换可行性评估

### 4.1 若切换，保留什么、重写什么

本项目架构分层清晰，底层替换点在 `_scrapling.py:_do_browse`（`src/scrapling_fetch_mcp/_scrapling.py:211`）：

- **可直接保留**（与底层无关）：MCP 工具层、daemon/pool 生命周期、缓存、分页、`s_fetch_pattern` 正则搜索、markdown 后处理、URL 重写。
- **必须自建/适配**：
  - airead 正文提取：Obscura 无 readability，需把它 dump 的 html 接回 trafilatura/readability 管线（即现有 `_extractor_strategy.py` 输入源换成 Obscura html）——可行但等于绕开 Obscura 的 markdown；
  - stealth 语义映射：Obscura 的 `--stealth` 是传输层模拟，与 camoufox 的浏览器级反指纹不等价，JS 指纹检测（creepjs 类）下风险更高；
  - `page_action`/save_content（截图/资源保存）：Obscura 有 screenshot/PDF 但无逐资源保存对等能力；
  - 集成通道三选一：CLI 子进程（每请求冷启动，无 cookie/会话复用，池化语义难做）、`obscura serve` CDP + playwright-python（引入双浏览器栈）、obscura-mcp（工具语义不符）。三条路都比现状复杂。

### 4.2 收益与代价

收益：

1. JS 渲染场景内存降一个数量级（1.4GB → 150MB）、并发吞吐高（5 并发 4.1s vs stealth 17.3s）；
2. 部署面小：84MB 二进制替代 1.2GB camoufox（若同时放弃 camoufox）。

代价/风险：

1. **反爬上限不升反降的隐患**：失去真浏览器级反指纹（camoufox），Obscura 的自研 DOM/Web API 在深度 JS 指纹检测下是未知数（本次矩阵未测出差异，但 sannysoft 类检测矩阵已改版无法对比）；
2. **正文提取与工具语义要重做**，airead 质量短期回退；
3. **商业反爬双双无解**，切换在"最重要的网页能否正确加载"维度收益≈0（本次矩阵 Obscura 90% vs 本项目 stealth 85%，差距来自 basic 拿 SSR 壳时的口径，而非真实能力差）；
4. Obscura 成熟度：0.2.x、自研引擎长尾兼容风险（react.dev 级 OK，长尾站点未知）、SSRF 防护对代理环境不友好、benchmark 数字（85ms/30MB）为理想值营销口径；
5. 本项目 basic 路径（curl_cffi）已经覆盖了 Obscura default 的场景且指纹更强、更快。

### 4.3 结论

**不建议整体切换底层为 Obscura**：

- 常规抓取本项目 basic 已更快且指纹更强；
- stealth 场景 Obscura 无反爬增益（商业反爬两边都过不去），反指纹上限反而存疑；
- 正文提取/工具语义/会话池化全部要重做，改动面大而收益集中在内存与并发——这类需求可以先用已实现的 `--browser-pool`（消除 camoufox 冷启动）缓解。

**可保留的观察项**：

1. 若未来目标是"大规模、轻资源、无真浏览器"的渲染抓取（边缘部署、多租户），Obscura 的引擎定位契合，可做为一个**可选引擎适配器**（`_do_browse` 增加一个 engine 分支）接入试点，airead 管线原样复用其 html dump；
2. 跟踪 Obscura 的 Readability 类能力与 MCP 生态成熟度，再复评；
3. 若部署环境受 1.2GB 浏览器限制，短期替代方案是仅用 basic 模式（curl_cffi）+ 明确放弃 JS 站，无需引入 Obscura。

## 5. 附录：复现

- 站点矩阵与判据：`.temp/bench/sites.py`
- 双方 runner：`.temp/bench/bench_ours.py`（daemon 生产链路，token 隔离 RSS 采样）、`.temp/bench/bench_obscura.py`（CLI + /usr/bin/time -v）
- 专项：`.temp/bench/bench_tlsfp.py`（TLS 指纹）、`.temp/bench/bench_concurrency.py`（并发）
- 原始数据：`.temp/bench/results/{ours,obscura}.jsonl`（104 条记录）
- 汇总：`.temp/bench/analyze.py`
- Obscura 二进制与源码：`/var/tmp/obscura-compare/`（release v0.2.6 stealth 变体）

注意：本项目代码默认 `min_mode="stealth"`（`_config.py:85`），直接复现 basic 数据须设 `SCRAPLING_MIN_MODE=basic`。
