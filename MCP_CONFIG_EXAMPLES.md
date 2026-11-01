# MCP Configuration Examples

## Basic Configuration (Default)

The default configuration uses basic mode with automatic escalation and 5-minute cache:

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

## Minimum Mode Configuration (Recommended for Bot-Protected Sites)

To avoid multiple retry attempts that can trigger rate limits, configure a minimum mode:

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

## Page Caching Configuration

Cache page content to avoid repeated requests when fetching large pages in segments:

### Default Cache (5 minutes)

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

### Extended Cache (10 minutes)

Recommended for large documentation sites:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--cache-ttl", "600"
      ]
    }
  }
}
```

### Disable Caching

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--cache-ttl", "0"
      ]
    }
  }
}
```

## Content Saving Configuration

Configure where saved web content (HTML + images) is stored:

### Default Scraping Directory

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

Default: `.temp/scrapling/`

### Custom Scraping Directory

**Command Line:**
```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--scraping-dir", "/Users/username/.scraping/"
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
        "SCRAPING_DIR": "/Users/username/.scraping/"
      }
    }
  }
}
```

### Per-Request Override

The AI can override the default scraping directory on a per-request basis when saving content:

```
"Save that documentation page to /tmp/docs/"
```

## Complete Configuration Example

Combine minimum mode, caching, and default format for optimal performance:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--min-mode", "stealth",
        "--cache-ttl", "600",
        "--default-format", "airead",
        "--disable-features", "save"
      ]
    }
  }
}
```

Or with environment variables:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_MIN_MODE": "stealth",
        "SCRAPLING_CACHE_TTL": "600",
        "SCRAPLING_DEFAULT_FORMAT": "airead",
        "SCRAPLING_DISABLE_FEATURES": "save"
      }
    }
  }
}
```

## Maximum Protection Configuration

For heavily protected sites, use max-stealth as the minimum:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--min-mode", "max-stealth",
        "--cache-ttl", "900"
      ]
    }
  }
}
```

## Mode Hierarchy

- **basic**: Fast (1-2s), works for most sites
- **stealth**: Moderate (3-8s), handles more protection
- **max-stealth**: Maximum (10+s), for heavily protected sites

When you set `--min-mode stealth`:
- Requests for "basic" → upgraded to "stealth"
- Requests for "stealth" → stays "stealth"
- Requests for "max-stealth" → stays "max-stealth"

This prevents the retry pattern (basic → fail → stealth → fail → max-stealth) that can trigger anti-bot protections.

## Cache Benefits

The page cache helps when:
- Fetching large pages in segments (using `start_index`)
- Searching the same page with multiple patterns
- Retrying requests without re-fetching

Cache is automatically invalidated after the TTL expires.

## Feature Control Configuration

Feature Control allows hiding unused MCP tool parameters to reduce token consumption per request.

### Default Configuration (No Save Parameters)

By default, the `save` feature is disabled, so `save_content` and `scraping_dir` parameters are hidden from tool definitions:

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

### Enable Save Feature

To make the save functionality available to the AI:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--enable-features", "save"]
    }
  }
}
```

### Disable Multiple Features for Token Savings

Hide parameters you don't need to minimize per-request token overhead:

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--disable-features", "save,pagination"]
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
        "SCRAPLING_ENABLE_FEATURES": "save"
      }
    }
  }
}
```

## Default Format Configuration

Set the default output format for all fetch operations:

### Airead as Default (AI-Optimized)

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--default-format", "airead"]
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
        "SCRAPLING_DEFAULT_FORMAT": "airead"
      }
    }
  }
}
```

## URL Rewrite Configuration

### Disable URL Rewriting

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

### Custom Rewrite Rules

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

See [URL Rewrite Configuration](docs/url-rewrite-configuration.md) for details on writing custom rules.

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

抓取是资源密集操作（stealth/max-stealth 会启动浏览器进程）。默认最多 5 个并发——自 0.3.0 起该上限为 **daemon 内全局并发**（所有客户端会话共享一个信号量，不再是每会话各自 5），超出排队等待最多 30 秒，超时则返回错误而非崩溃：

```bash
scrapling-fetch-mcp --transport streamable-http --max-concurrent 3 --acquire-timeout 60
```

### 超时调优

抓取一个页面（尤其 stealth/max-stealth 需启动浏览器）可能耗时 10–60 秒，并发排队还会叠加等待。streamable-http 下需注意各层超时：

**服务端（本工具）：**
- `--acquire-timeout`（默认 30s）：并发满时的排队等待超时。长任务场景建议调大，如 `--acquire-timeout 300`。
- `--fetch-timeout`（默认 60s）：单次抓取本身的超时（含浏览器加载），超时返回错误而非无限挂起，避免占满并发槽。注意：超时取消是强制中断第三方抓取/浏览器协程，**浏览器进程可能短暂残留**（取决于 scrapling/camoufox 的清理行为）。

**反向代理（最常见的超时来源）：**
- nginx 默认 `proxy_read_timeout 60s`：服务端 SSE 流每 15s 发一条 `: ping` 心跳（见下），在 `proxy_buffering off`（心跳可即时透传）下默认值即可存活；调大属双保险（防心跳被中间层缓冲吞掉）：
  ```nginx
  location /mcp {
      proxy_pass http://127.0.0.1:8000;
      proxy_read_timeout 300s;
      proxy_send_timeout 300s;
      proxy_buffering off;   # 让 SSE 流与 15s 心跳即时透传
  }
  ```
- Caddy 默认无读超时，长连接友好，无需额外配置。

**MCP 客户端：**
- 客户端（如 Claude Code）的 HTTP 请求超时也需大于最长抓取耗时，按客户端文档调大。

**进度心跳（SSE 保活，2026-11 调查结论）：** streamable-http 下 SSE 流最迟 15s 提交，且 SDK 每 15s 发一条 `: ping` 心跳——**独立于工具 progress 上报**，浏览器加载阶段同样有心跳，无需工具侧补发。因此只要心跳可即时透传（如 nginx `proxy_buffering off`），代理默认读超时即可存活；客户端超时仍需大于最长抓取耗时，调大代理读超时属双保险。

### 公网 HTTPS（由反向代理终结 TLS）

进程内不做 TLS，建议前置 Caddy/Nginx 终结 TLS。Caddy 示例：

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
| 最大并发（全局） | `SCRAPLING_MAX_CONCURRENT` | `--max-concurrent` | `5` |
| 等待超时(秒) | `SCRAPLING_ACQUIRE_TIMEOUT` | `--acquire-timeout` | `30` |
| 抓取超时(秒) | `SCRAPLING_FETCH_TIMEOUT` | `--fetch-timeout` | `60` |
| 缓存条目上限 | `SCRAPLING_CACHE_MAX_ENTRIES` | — | `256` |
| 浏览器池 | `SCRAPLING_BROWSER_POOL` | `--browser-pool` | 关 |
| 池空闲回收(秒) | `SCRAPLING_POOL_IDLE_TTL` | `--pool-idle-ttl` | `300` |
| 池最长寿命(秒) | `SCRAPLING_POOL_MAX_AGE` | `--pool-max-age` | `1800` |
| 池容量上限 | `SCRAPLING_POOL_MAX_SESSIONS` | `--pool-max-sessions` | `4` |
| 池单会话请求预算 | `SCRAPLING_POOL_MAX_REQUESTS` | `--pool-max-requests` | `50` |
| daemon 目录 | `SCRAPLING_DAEMON_DIR` | — | platformdirs 用户数据目录 |
| daemon 空闲退出(秒) | `SCRAPLING_DAEMON_IDLE_TIMEOUT` | — | `600` |

> **配置与 daemon 的关系**：抓取行为相关的配置（除传输/鉴权/features 与 daemon 生命周期两项外）归 daemon 所有，其归一化值的摘要参与 socket 命名（`daemon-<包版本>-<摘要8hex>`）——改配置即换名，各自拉起独立 daemon，互不干扰，不存在配置静默不一致。`SCRAPLING_DAEMON_DIR` / `SCRAPLING_DAEMON_IDLE_TIMEOUT` 仅影响生命周期，不入摘要。

## daemon（后台抓取进程）故障排查

自 0.3.0 起，抓取在一个按需自动拉起的后台 daemon 进程内执行：首个请求触发拉起；全部客户端断开后空闲 600s 自动退出；死亡后前端自动重拉。socket 按（包版本，配置摘要）命名隔离，版本滚动期间新旧 daemon 可能短暂共存 2 个（约 +155 MB）。**Windows 暂不支持**（依赖 unix socket），会直接报错。

工具返回 `ERROR: DAEMON_UNAVAILABLE: ...` 表示前端无法连接或拉起 daemon，按序排查：

1. **查看 daemon 状态**：
   ```bash
   scrapling-fetch-mcp daemon status
   ```
   表格列出全部 daemon（socket 名/版本/配置摘要/pid/uptime/客户端数/缓存条目）。`DEAD` 行表示进程已死但 sock/lock 残留，执行 `scrapling-fetch-mcp daemon shutdown --all` 清场后重试。
2. **检查 daemon 日志**：daemon 目录默认在 platformdirs 用户数据目录（可用 `SCRAPLING_DAEMON_DIR` 覆盖指定）；目录下 `daemon-*.log` 是启动失败的唯一线索（daemon 的 stdout/stderr 重定向于此）。
3. **重试**：处理后直接重试即可——前端检测到 daemon 死亡会自动重拉，无需手动清理（残留可用 `shutdown --all` 清）。

相关停止命令：`daemon shutdown`（默认仅当前版本+配置）、`--all`（全部）、`--socket <名>`（定点）。
