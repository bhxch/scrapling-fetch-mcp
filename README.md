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

# Install browser binaries (REQUIRED - large downloads)
uvx --from scrapling-fetch-mcp scrapling install
```

**Important**: The browser installation downloads hundreds of MB of data and must complete before first use. If the MCP server times out on first use, the browsers may still be installing in the background. Wait a few minutes and try again.

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

- **Page fetching**: Retrieves complete web pages with support for pagination
- **Pattern extraction**: Finds and extracts specific content using regex patterns

The AI decides which tool to use based on your request. You just ask naturally:

```
"Can you fetch the docs at https://example.com/api"
"Find all mentions of 'authentication' on that page"
"Get me the installation instructions from their homepage"
```

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
- Images are intercepted during page load via patchright route handling

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
