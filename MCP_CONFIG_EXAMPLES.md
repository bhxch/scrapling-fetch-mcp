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

Combine minimum mode and caching for optimal performance:

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

Or with environment variables:

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
