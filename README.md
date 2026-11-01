# scrapling-fetch-mcp

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![PyPI version](https://img.shields.io/pypi/v/scrapling-fetch-mcp.svg)](https://pypi.org/project/scrapling-fetch-mcp/)

An MCP server that helps AI assistants access text content from websites that implement bot detection, bridging the gap between what you can see in your browser and what the AI can access.

## Intended Use

This tool is optimized for low-volume retrieval of documentation and reference materials (text/HTML only) from websites that implement bot detection. It has not been designed or tested for general-purpose site scraping or data harvesting.

> **Note**: This project was developed in collaboration with Claude Sonnets 3.7 and 4.5, using [LLM Context](https://github.com/cyberchitta/llm-context.py).

## Installation

### Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager

### Install

```bash
# Install scrapling-fetch-mcp
uv tool install scrapling-fetch-mcp
```

**Important**: the stealth browser (~1.2 GB) downloads **in the background** the first time the daemon spins up (triggered by the first tool request — the MCP server itself is ready immediately and `basic` mode works right away). The download resumes from where it stopped (HTTP Range) and retries automatically whenever the connection stalls; until it finishes, `stealth`/`max-stealth` requests fall back to basic (see below). Pre-install to skip that window entirely.

### Stealth Mode Requirements

`stealth` and `max-stealth` modes drive a modified Firefox ([camoufox](https://github.com/daijro/camoufox)) with browserforge fingerprint data. Both are **downloaded in the background when the daemon first spins up** (i.e. on the first tool request — the MCP server starts listening immediately); until the browser is ready, stealth requests automatically degrade to `basic` and the tool result's `METADATA` carries a `degradation` note saying so. Pre-install to avoid the degraded window:

```bash
# camoufox Firefox (~1.2 GB, no resume on interrupted downloads)
# from the daijro/camoufox GitHub releases
uvx --from scrapling-fetch-mcp camoufox fetch
```

browserforge fingerprint data (~0.6 MB) is also auto-fetched when the daemon first spins up — from GitHub by default, falling back to the npm registry (`registry.npmjs.org`, then `registry.npmmirror.com`) when GitHub is unreachable.

camoufox runs **headless** and does not need a desktop or Xvfb on a normal Linux server. If stealth launches fail with missing shared libraries, install the Firefox runtime OS packages once — this installs system packages via apt, not browsers (run as root): `uvx --from scrapling-fetch-mcp playwright install-deps firefox`. (`basic` mode needs none of the above at all — it uses curl-cffi with no browser.)

## Setup with Claude Desktop

Add this configuration to your Claude Desktop MCP settings:

**MacOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"]
    }
  }
}
```

After updating the config, restart Claude Desktop.

## What It Does

This MCP server provides two tools that Claude can use automatically when you ask it to fetch web content:

- **`s_fetch_page`**: Retrieves complete web pages with pagination support
- **`s_fetch_pattern`**: Finds and extracts specific content using regex patterns

The AI decides which tool to use based on your request. You just ask naturally:

```
"Can you fetch the docs at https://example.com/api"
"Find all mentions of 'authentication' on that page"
"Get me the installation instructions from their homepage"
```

## 架构：后台 daemon 与浏览器池

自 0.3.0 起，MCP 前端是薄壳：工具调用经 unix socket（NDJSON + token 鉴权，按请求 id 多路复用）转发给按需自动拉起的后台 daemon 进程——抓取逻辑、页面缓存、并发闸门与可选浏览器池全部在 daemon 内执行，多个客户端会话共享同一份内存与缓存，前端进程保持轻量、随客户端即起即灭。

### 生命周期（全自动，无需 systemd / socket activation）

| 阶段 | 行为 |
|------|------|
| 自动拉起 | 首个工具请求触发：前端确保同 (包版本，配置摘要) 的 daemon 恰好一个并等待就绪（并发拉起经 spawn.lock 仲裁，不会重复起进程） |
| 空闲自退 | 全部客户端断开后空闲 600s（`SCRAPLING_DAEMON_IDLE_TIMEOUT` 可调）自动退出；退出前销毁池化浏览器、清理 socket/lock |
| streamable-http 不触发空闲自退 | 该传输下前端进程长存即持久连接长存，daemon 始终有客户端，「空闲 600s 自退」不会触发——daemon 寿命 = 前端进程寿命；stdio 场景不受影响，仍按空闲超时自退 |
| 死亡重生 | daemon 意外死亡时前端检测到断连，自动重拉后重试请求 |
| 版本/配置隔离 | socket 名为 `daemon-<包版本>-<配置摘要8hex>`：升级或改抓取配置即换名，各自拉起、互不干扰 |
| 过渡期共存 | 版本滚动（如 uvx 自动更新）期间新旧 daemon 短暂共存 2 个（约 +155 MB），旧 daemon 在一个空闲超时周期内自退消亡 |

### 管理 CLI

```bash
scrapling-fetch-mcp daemon status              # 表格列出全部 daemon（版本/配置/pid/uptime/客户端数/缓存）
scrapling-fetch-mcp daemon shutdown            # 优雅停止当前版本+配置的 daemon
scrapling-fetch-mcp daemon shutdown --all      # 停止全部 daemon 并清理残留（含其他版本/配置）
scrapling-fetch-mcp daemon shutdown --socket daemon-0.3.0-abcd1234   # 定点停止指定 socket
```

退出码语义：默认 `shutdown` 与 `--socket` 定点在目标不存在时退出 1；`shutdown --all` 在无匹配 daemon 时返回 0（无事可做）。
> **Windows 暂不支持**：daemon 依赖 unix socket，仅限 Linux/macOS；Windows 上会直接报错。

### 并发语义变化

`--max-concurrent`（默认 5）自 0.3.0 起为 **daemon 内全局并发**：所有客户端会话共享同一个信号量（此前是每个客户端会话各自 5）。超限请求排队等待 `--acquire-timeout` 秒后返回 `CONCURRENCY_LIMIT` 类错误，前端提示稍后重试。

### 浏览器池（可选，默认关闭）

`--browser-pool`（env `SCRAPLING_BROWSER_POOL`）开启后，stealth/max-stealth 请求按 **(eTLD+1 注册域名, mode)** 分桶复用 Firefox 会话，省去每次冷启动（数秒 + 数百 MB 峰值）。跨域名不共享身份；任一重建触发即销毁重建：空闲 >300s、累计年龄 >1800s（指纹新鲜度硬上限）、请求数达 50（每会话恰服务 50 次）、抓取异常、疑似挑战页。池上限 4 个活跃会话（`SCRAPLING_POOL_MAX_SESSIONS`，LRU 逐出）。daemon 空闲退出或版本重拉时全部池化会话销毁，不留持久状态。

### 已知限制：多客户端并发下的取消波及

多个客户端会话共享同一 daemon。stealth/max-stealth 抓取配有「取消兜底清扫」：请求被取消且恰好落在浏览器启动窗口时，daemon 会 SIGKILL 其间新出现的浏览器/驱动进程，防止孤儿进程泄漏。该清扫按进程名匹配（camoufox/firefox/playwright），无法区分浏览器归属于哪个请求——若此刻同一 daemon 内还有**其他在飞的浏览器抓取**，清扫会跳过（并发计数防护）；但如果被取消的请求是最后一个在飞者，而兄弟请求的浏览器恰在其后启动，仍存在波及窗口：兄弟请求可能因浏览器被杀而报错。此为 scrapling 上层无法根除的边界（进程层面无归属信息），**受影响的兄弟请求直接重试即可**——前端会自动重拉浏览器/daemon。单客户端顺序使用不受任何影响。

## Parameters Reference

### `s_fetch_page` — Fetch Complete Pages

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | *(required)* | The URL to fetch |
| `mode` | `str` | `"basic"` | Fetching mode: `basic`, `stealth`, `max-stealth`. Effective mode is `max(requested, server_min_mode)` |
| `format` | `str` | `"markdown"` | Output format: `airead` (AI-optimized), `markdown`, `html`. Defaults to server `--default-format` setting |
| `max_length` | `int` | `8000` | Maximum number of characters to return |
| `start_index` | `int` | `0` | Start returning content from this character position (for paginating large pages) |
| `save_content` | `bool` | `false` | Save complete page (HTML/Markdown + images) to local filesystem |
| `scraping_dir` | `str` | `".temp/scrapling/"` | Directory path for saved content |

### `s_fetch_pattern` — Extract by Regex

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `url` | `str` | *(required)* | The URL to fetch |
| `search_pattern` | `str` | *(required)* | Regular expression to search for in the page content |
| `mode` | `str` | `"basic"` | Fetching mode: `basic`, `stealth`, `max-stealth` |
| `format` | `str` | `"markdown"` | Output format: `markdown`, `html`. Note: `airead` is automatically converted to `markdown` for this tool |
| `max_length` | `int` | `8000` | Maximum number of characters to return |
| `context_chars` | `int` | `200` | Number of characters to include before and after each regex match |

### Server Configuration (CLI Arguments & Environment Variables)

These settings are configured when starting the MCP server, either via CLI arguments or environment variables. CLI args take priority over environment variables.

| CLI Argument | Environment Variable | Type | Default | Description |
|--------------|---------------------|------|---------|-------------|
| `--min-mode` | `SCRAPLING_MIN_MODE` | `str` | `"stealth"` | Minimum fetching mode. All requests use at least this level, preventing redundant retries |
| `--cache-ttl` | `SCRAPLING_CACHE_TTL` | `int` | `300` | Page cache TTL in seconds. Set to `0` to disable |
| `--scraping-dir` | `SCRAPLING_DIR` | `str` | `".temp/scrapling/"` | Default directory for saved content |
| `--markdown-converter` | `SCRAPLING_MARKDOWN_CONVERTER` | `str` | `"markitdown"` | Markdown converter: `markitdown` or `markdownify` |
| `--rules-config` | `SCRAPLING_RULES_CONFIG` | `str` | — | Path to custom airead URL routing rules YAML file |
| `--default-format` | `SCRAPLING_DEFAULT_FORMAT` | `str` | `"markdown"` | Default output format: `airead`, `markdown`, or `html` |
| `--disable-url-rewrite` | `SCRAPLING_DISABLE_URL_REWRITE` | `bool` | `false` | Disable automatic URL rewriting |
| `--url-rewrite-config` | `SCRAPLING_URL_REWRITE_CONFIG` | `str` | — | Path to custom URL rewrite rules YAML file |
| `--disable-features` | `SCRAPLING_DISABLE_FEATURES` | `str` | `""` | Comma-separated features to disable |
| `--enable-features` | `SCRAPLING_ENABLE_FEATURES` | `str` | `""` | Comma-separated features to enable |
| `--transport` | `SCRAPLING_TRANSPORT` | `str` | `"stdio"` | Transport: `stdio` (default, local) or `streamable-http` (remote access) |
| `--host` | `SCRAPLING_HOST` | `str` | `"127.0.0.1"` | Bind host for streamable-http |
| `--port` | `SCRAPLING_PORT` | `int` | `8000` | Bind port for streamable-http |
| `--mcp-path` | `SCRAPLING_MCP_PATH` | `str` | `"/mcp"` | URL path for streamable-http |
| `--auth-token` | `SCRAPLING_AUTH_TOKEN` | `str` | `""` | Bearer token for streamable-http auth. Empty = no auth |
| `--max-concurrent` | `SCRAPLING_MAX_CONCURRENT` | `int` | `5` | Max concurrent fetches — **global across all client sessions** (daemon-wide semaphore since 0.3.0) |
| `--acquire-timeout` | `SCRAPLING_ACQUIRE_TIMEOUT` | `float` | `30` | Seconds to wait for a concurrency slot before failing |
| `--fetch-timeout` | `SCRAPLING_FETCH_TIMEOUT` | `float` | `60` | Seconds before a single fetch is aborted (includes browser loading) |
| `--browser-pool` | `SCRAPLING_BROWSER_POOL` | `bool` | `false` | Enable the browser session pool for stealth modes (per-(domain, mode) reuse) |
| `--pool-idle-ttl` | `SCRAPLING_POOL_IDLE_TTL` | `float` | `300` | Seconds an idle pooled browser session survives before recycle |
| `--pool-max-age` | `SCRAPLING_POOL_MAX_AGE` | `float` | `1800` | Max lifetime of a pooled session regardless of activity (fingerprint freshness cap) |
| `--pool-max-sessions` | `SCRAPLING_POOL_MAX_SESSIONS` | `int` | `4` | Max pooled browser sessions (LRU eviction) |
| `--pool-max-requests` | `SCRAPLING_POOL_MAX_REQUESTS` | `int` | `50` | Requests a pooled session serves before recycle |
| — | `SCRAPLING_CACHE_MAX_ENTRIES` | `int` | `256` | Page cache max entries (expired-first, then FIFO eviction) |
| `--daemon-dir` | `SCRAPLING_DAEMON_DIR` | `str` | platformdirs user data dir | Daemon runtime directory (sockets/locks/logs) |
| `--daemon-idle-timeout` | `SCRAPLING_DAEMON_IDLE_TIMEOUT` | `float` | `600` | Seconds of no clients before the daemon exits |

### Streamable-HTTP (Remote Access)

By default the server runs over stdio (local subprocess). To allow remote MCP clients to connect over HTTP, use `--transport streamable-http`:

```bash
# Local (no auth)
scrapling-fetch-mcp --transport streamable-http --port 8000

# LAN with bearer auth
scrapling-fetch-mcp --transport streamable-http --host 0.0.0.0 --port 8000 --auth-token SECRET
```

Clients connect to `http://<host>:<port>/mcp` and must send `Authorization: Bearer SECRET` when an auth token is configured. Concurrency is bounded by `--max-concurrent` (default 5) — since 0.3.0 this limit is **global across all connected clients** (enforced inside the daemon); requests beyond the limit queue for up to `--acquire-timeout` seconds, then return an error instead of crashing. For public HTTPS, terminate TLS at a reverse proxy (Caddy/Nginx). See [`MCP_CONFIG_EXAMPLES.md`](MCP_CONFIG_EXAMPLES.md) for full deployment examples.

## Feature Control

MCP tool parameters consume tokens in every request. Feature Control allows hiding unused parameters to reduce token consumption.

### Available Features

| Feature | Default | Controls |
|---------|---------|----------|
| `stealth` | enabled | `mode` parameter |
| `format` | enabled | `format` parameter |
| `pagination` | enabled | `start_index` parameter |
| `save` | disabled | `save_content`, `scraping_dir` parameters |

### Usage Examples (CLI)

```bash
# Enable save feature (default is disabled)
scrapling-fetch-mcp --enable-features save

# Disable multiple features for maximum token savings
scrapling-fetch-mcp --disable-features save,pagination
```

### Environment Variables

- `SCRAPLING_DISABLE_FEATURES` — comma-separated features to disable
- `SCRAPLING_ENABLE_FEATURES` — comma-separated features to enable

> **Note**: `--enable-features` takes priority over `--disable-features`, which takes priority over recommended defaults.

## Output Format: airead

The `airead` format provides AI-optimized content extraction, automatically removing navigation bars, ads, sidebars, and other non-essential elements. This reduces token usage by 30-50% while preserving >90% of core content.

airead uses **intelligent URL-based routing** to select the best extraction strategy for each website type:

| Strategy | Best For | Description |
|----------|----------|-------------|
| `dual` | General use | Runs 3 extractors (trafilatura + readability + scrapling), selects best result |
| `search_engine` | Google, Bing, DuckDuckGo, Startpage, Brave, SearxNG | Per-engine adapters with deterministic selectors |
| `developer_platform` | GitHub, GitLab, StackOverflow | Preserves code blocks, tables, and API docs |
| `documentation` | MDN, ReadTheDocs, etc. | Optimized for technical documentation |
| `trafilatura` | News, blogs, articles | Fast general-purpose extraction |
| `readability` | Complex article layouts | Firefox Reader View algorithm |
| `scrapling` | Simple pages | Built-in Markdown conversion |

> **Note**: airead is only supported by `s_fetch_page`. When used with `s_fetch_pattern`, it automatically falls back to `markdown`.

See [airead Format Guide](docs/airead-format-guide.md) for details on custom strategies and URL routing rules.

## Protection Modes

The tools support three levels of bot detection bypass:

- **basic**: Fast (1-2s), works for most sites
- **stealth**: Moderate (3-8s), handles more protection
- **max-stealth**: Maximum (10+s), for heavily protected sites

By default, Claude automatically starts with `basic` mode and escalates if needed. However, this can result in multiple requests to the same site, potentially triggering rate limits.

## Minimum Mode Configuration

To prevent multiple retry attempts and reduce the risk of being blocked, you can configure a minimum fetching mode. This ensures all requests use at least the specified mode level, avoiding unnecessary retries.

### Using Command Line Arguments

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--min-mode", "stealth"]
    }
  }
}
```

### Using Environment Variables

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_MIN_MODE": "stealth"
      }
    }
  }
}
```

### Mode Hierarchy

The modes follow a hierarchy where each level includes all previous capabilities:

```
basic < stealth < max-stealth
```

When you set `--min-mode stealth`, all requests will use at least `stealth` mode, even if the AI requests `basic`. This prevents the pattern of trying `basic` → failing → retrying with `stealth`, which can trigger anti-bot protections.

## Page Caching

To avoid repeated requests when fetching large pages in segments, the server caches page content for a configurable time period. This is especially useful when:

- Fetching large documentation pages that need multiple requests with different `start_index` values
- Searching the same page with multiple regex patterns
- Retrying failed requests without re-fetching the entire page

### Cache Configuration

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--min-mode", "stealth",
        "--cache-ttl", "600"
      ]
    }
  }
}
```

Or using environment variables:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_MIN_MODE": "stealth",
        "SCRAPLING_CACHE_TTL": "600"
      }
    }
  }
}
```

**Cache settings:**
- Default TTL: 300 seconds (5 minutes)
- Set to 0 to disable caching
- Cache is URL + mode specific (same URL with different modes are cached separately)

## Markdown Converter Configuration

Choose which library to use for HTML to Markdown conversion:

- **markitdown** (default): Microsoft's MarkItDown library - optimized for document conversion
- **markdownify**: Custom markdownify-based converter - existing implementation

### Using Command Line Arguments

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--markdown-converter", "markitdown"]
    }
  }
}
```

### Using Environment Variables

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_MARKDOWN_CONVERTER": "markitdown"
      }
    }
  }
}
```

**Default**: `markitdown`

## Content Saving Feature

Save complete web pages (HTML/Markdown + images) to your local filesystem for offline viewing.

### Basic Usage

```python
# The AI can save pages with images for offline viewing
# Just mention you want to save or keep the content locally
"Can you fetch and save the article at https://example.com/guide"
"Save that documentation page so I can view it offline"
```

### Directory Structure

Saved content is organized as:

```
.temp/scrapling/
├── example.com_20260316_143025/
│   ├── page.html          # Modified HTML with local image paths
│   ├── metadata.json      # Page metadata (URL, fetch time, mode)
│   ├── images/            # Downloaded images (deduplicated)
│   │   ├── logo.jpg
│   │   └── banner.png
│   └── image_mapping.json # Original URL -> local path mapping
```

### Features

- **Offline viewing**: All images are downloaded and referenced locally
- **Image deduplication**: Identical images (same hash) stored only once
- **URL preservation**: Original image URLs saved in `data-original-src` attributes and `image_mapping.json`
- **Markdown support**: Save as Markdown with local image references

### Requirements

- Use `mode="max-stealth"` or `mode="stealth"` (basic mode may not load images)
- Images are captured by listening to browser response events during page load (requires the stealth setup; see [Stealth Mode Requirements](#stealth-mode-requirements))

### Scraping Directory Configuration

Configure where saved content is stored:

**Command Line:**
```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--scraping-dir", "/custom/scraping/path/"
      ]
    }
  }
}
```

**Environment Variable:**
```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_DIR": "/custom/scraping/path/"
      }
    }
  }
}
```

**Default**: `.temp/scrapling/`

## Tips for Best Results

- Just ask naturally - Claude handles the technical details
- For large pages, Claude can page through content automatically
- For specific searches, mention what you're looking for and Claude will use pattern matching
- The metadata returned helps Claude decide whether to page or search

## URL Rewriting

The server automatically rewrites certain URLs to lighter, more accessible versions:

- **GitHub**: `blob` URLs → `raw.githubusercontent.com` (direct file content)
- **DuckDuckGo**: Search pages → HTML version (no JavaScript)
- **Reddit**: `www.reddit.com` → `old.reddit.com` (lighter version)
- **StackOverflow**: Question pages → StackPrinter format (printer-friendly)

This improves both stealth success rates and fetch speed.

### Disable URL Rewriting

If you need to access the original URLs:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--disable-url-rewrite"]
    }
  }
}
```

Or via environment variable:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_DISABLE_URL_REWRITE": "true"
      }
    }
  }
}
```

### Custom Rewrite Rules

Add your own rewrite rules via configuration file:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--url-rewrite-config", "/path/to/rewrite-rules.yaml"
      ]
    }
  }
}
```

See [URL Rewrite Configuration](docs/url-rewrite-configuration.md) for details.

## Limitations

- Designed for text content only (documentation, articles, references)
- Not for high-volume scraping or data harvesting
- May not work with sites requiring authentication
- Performance varies by site complexity and protection level

Built with [Scrapling](https://github.com/D4Vinci/Scrapling) for web scraping with bot detection bypass.

## License

Apache 2.0
