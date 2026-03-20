# URL Rewrite Configuration

## Overview

The URL rewrite feature automatically transforms certain URLs to lighter, more accessible versions before fetching. This improves both stealth success rates and fetch speed.

## Built-in Rules

The following rules are enabled by default:

| Website | Original URL | Rewritten URL | Benefit |
|---------|--------------|---------------|---------|
| GitHub | `github.com/user/repo/blob/branch/file` | `raw.githubusercontent.com/user/repo/branch/file` | Direct file content, no HTML rendering |
| DuckDuckGo | `duckduckgo.com/?q=query` | `duckduckgo.com/html/?q=query` | HTML version, no JavaScript |
| Reddit | `www.reddit.com/r/...` | `old.reddit.com/r/...` | Lighter version, less JavaScript |
| StackOverflow | `stackoverflow.com/questions/12345/title` | `stackprinter.com/export?question=12345&...` | Printer-friendly format |

## Disabling URL Rewrite

### Globally (CLI Argument)

```bash
scrapling-fetch-mcp --disable-url-rewrite
```

### Globally (Environment Variable)

```bash
export SCRAPLING_DISABLE_URL_REWRITE=true
scrapling-fetch-mcp
```

### In Claude Desktop Config

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

## Custom Rules

Create a YAML file with your custom rewrite rules:

### Basic Structure

```yaml
url_rewrite_rules:
  - match:
      type: domain | domain_suffix | regex
      pattern: "pattern string"
    rewrite:
      type: regex_replace | path_prefix | domain_replace | none
      # type-specific parameters
```

### Match Types

#### domain
Exact domain match (with www prefix support):

```yaml
- match:
    type: domain
    pattern: example.com
  # Matches: example.com, www.example.com
```

#### domain_suffix
Domain suffix match (supports wildcards):

```yaml
- match:
    type: domain_suffix
    pattern: .example.com
  # Matches: example.com, sub.example.com, anything.example.com
```

#### regex
Regular expression match:

```yaml
- match:
    type: regex
    pattern: 'example\.com/page/\d+'
  # Matches: example.com/page/123, example.com/page/456
```

### Rewrite Types

#### regex_replace
Replace using regular expression:

```yaml
- rewrite:
    type: regex_replace
    pattern: 'example\.com/page/(\d+)'
    replacement: 'lite.example.com/view/\1'
```

#### domain_replace
Replace domain name:

```yaml
- rewrite:
    type: domain_replace
    old: www.example.com
    new: lite.example.com
```

#### path_prefix
Add prefix to path:

```yaml
- rewrite:
    type: path_prefix
    prefix: /lite
  # example.com/page → example.com/lite/page
```

#### none
Disable rewriting (useful for overriding built-in rules):

```yaml
- rewrite:
    type: none
```

### Example Configuration

```yaml
url_rewrite_rules:
  # Override built-in GitHub rule
  - match:
      type: domain_suffix
      pattern: github.com
    rewrite:
      type: regex_replace
      pattern: 'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)'
      replacement: 'raw.githubusercontent.com/\1/\2/\3/\4'
  
  # Add GitLab support
  - match:
      type: domain_suffix
      pattern: gitlab.com
    rewrite:
      type: regex_replace
      pattern: 'gitlab\.com/([^/]+)/([^/]+)/-/blob/([^/]+)/(.*)'
      replacement: 'gitlab.com/\1/\2/-/raw/\3/\4'
  
  # Disable Reddit rewriting (use modern version)
  - match:
      type: domain
      pattern: www.reddit.com
    rewrite:
      type: none
```

### Using Custom Rules

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--url-rewrite-config", "/path/to/custom-rewrite-rules.yaml"
      ]
    }
  }
}
```

Or via environment variable:

```bash
export SCRAPLING_URL_REWRITE_CONFIG=/path/to/custom-rewrite-rules.yaml
scrapling-fetch-mcp
```

## Priority

Rules are applied in this order:

1. Custom rules (from top to bottom in config file)
2. Built-in rules (GitHub, DuckDuckGo, Reddit, StackOverflow)
3. No match (URL remains unchanged)

The first matching rule wins.

## Limitations

- Query parameters and fragments are preserved by most rewrite types
- Maximum 3 rewrite iterations (prevents infinite loops)
- Only HTTP and HTTPS URLs are supported
- Invalid URLs are returned unchanged

## Debugging

To see which URLs are being rewritten, check the DEBUG logs:

```python
import logging
logging.getLogger("scrapling_fetch_mcp").setLevel(logging.DEBUG)
```

This will show messages like:
```
URL rewritten: https://github.com/user/repo/blob/main/file.md → https://raw.githubusercontent.com/user/repo/main/file.md
```

## FAQ

### When should I disable URL rewriting?

- When you need the full HTML interface (e.g., GitHub's web UI)
- When the lightweight version is missing features you need
- When debugging fetch issues

### Can I override built-in rules?

Yes! Custom rules take priority over built-in rules. Create a rule with the same match pattern and set `type: none` to disable it.

### Do rewrite rules affect caching?

Yes. The cache is based on the rewritten URL, not the original. This prevents duplicate fetches of the same content accessed via different URL forms.

### What if a rewrite rule breaks?

If a custom rule causes errors, the rewriter falls back to the original URL. Check the logs for error messages.