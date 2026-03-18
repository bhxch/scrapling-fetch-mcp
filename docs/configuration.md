# Configuration Reference

## Configuration Methods

### 1. Environment Variables

```bash
# airead rules configuration file path
export SCRAPLING_RULES_CONFIG=/path/to/custom_rules.yaml

# Other Scrapling settings
export SCRAPLING_MIN_MODE=stealth
export SCRAPLING_CACHE_TTL=300
export SCRAPLING_MARKDOWN_CONVERTER=markitdown
```

### 2. CLI Parameters

```bash
scrapling-fetch-mcp \
  --rules-config /path/to/custom_rules.yaml \
  --min-mode stealth \
  --cache-ttl 300 \
  --markdown-converter markitdown
```

### 3. Configuration Files

**Default location:** `~/.config/scrapling/rules.yaml` (optional)

## Rules Configuration File

### Basic Structure

```yaml
# Global default strategy
default_strategy: dual

# URL routing rules
url_rules:
  - match:
      type: domain
      pattern: "example.com"
    strategy: trafilatura

  - match:
      type: domain_suffix
      pattern: ".google.com"
    strategy: search_engine

  - match:
      type: regex
      pattern: ".*docs\\.python\\.org.*"
    strategy: documentation

# Custom strategies (advanced)
custom_strategies: []
```

### Complete Example

```yaml
# Global default strategy
# Options: dual, trafilatura, readability, scrapling,
#          search_engine, developer_platform, documentation
default_strategy: dual

# URL routing rules (evaluated in order, first match wins)
url_rules:
  # Search engines
  - match:
      type: domain_suffix
      pattern: ".google.com"
    strategy: search_engine

  - match:
      type: domain_suffix
      pattern: ".bing.com"
    strategy: search_engine

  - match:
      type: domain
      pattern: "duckduckgo.com"
    strategy: search_engine

  # Developer platforms
  - match:
      type: domain
      pattern: "github.com"
    strategy: developer_platform

  - match:
      type: domain_suffix
      pattern: ".stackoverflow.com"
    strategy: developer_platform

  - match:
      type: domain
      pattern: "gitlab.com"
    strategy: developer_platform

  # Documentation
  - match:
      type: regex
      pattern: ".*docs\\.python\\.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*developer\\.mozilla\\.org.*"
    strategy: documentation

  # Custom sites
  - match:
      type: domain
      pattern: "mycompany.com"
    strategy: trafilatura

# Custom strategies
custom_strategies:
  - name: my_custom
    module: /path/to/custom_strategy.py
    class: MyCustomStrategy
```

## Match Types

### domain

**Exact domain match** with `www.` prefix support:

```yaml
- match:
    type: domain
    pattern: "github.com"
  strategy: developer_platform
```

Matches:
- `github.com` ✅
- `www.github.com` ✅
- `docs.github.com` ❌

### domain_suffix

**Smart suffix matching** - matches base domain and all subdomains:

```yaml
- match:
    type: domain_suffix
    pattern: ".google.com"
  strategy: search_engine
```

Matches:
- `google.com` ✅
- `www.google.com` ✅
- `mail.google.com` ✅
- `docs.google.com` ✅

**Note:** Leading `.` is recommended but not required:
- `.google.com` → `google.com` and `*.google.com`
- `google.com` → only `google.com`

### regex

**Full URL regex matching**:

```yaml
- match:
    type: regex
    pattern: ".*docs\\.python\\.org/3/library/.*"
  strategy: documentation
```

Matches:
- `https://docs.python.org/3/library/json.html` ✅
- `https://docs.python.org/3/library/os.html` ✅
- `https://docs.python.org/2/library/` ❌

## Strategy Options

### dual (recommended)
**Best for:** General use, highest accuracy
**Performance:** 2-3 seconds
**Description:** Runs 3 extractors, selects best result

### trafilatura
**Best for:** News, blogs, articles
**Performance:** < 1 second
**Description:** General-purpose extraction

### readability
**Best for:** Complex article layouts
**Performance:** < 1 second
**Description:** Mozilla Reader View algorithm

### scrapling
**Best for:** Simple pages
**Performance:** < 0.5 seconds
**Description:** Built-in Markdown conversion

### search_engine
**Best for:** Search results (Google, Bing, DuckDuckGo)
**Description:** Extracts result listings, removes ads

### developer_platform
**Best for:** GitHub, GitLab, StackOverflow
**Description:** Preserves code blocks, tables, API docs

### documentation
**Best for:** Technical documentation sites
**Description:** Optimized for API docs, code examples

## Custom Strategies

### Basic Custom Strategy

```yaml
custom_strategies:
  - name: my_custom
    module: /absolute/path/to/strategy.py
    class: MyCustomStrategy
```

### Multiple Custom Strategies

```yaml
custom_strategies:
  - name: hacker_news
    module: ./strategies/hackernews.py
    class: HackerNewsStrategy

  - name: reddit
    module: ./strategies/reddit.py
    class: RedditStrategy

  - name: wikipedia
    module: ./strategies/wikipedia.py
    class: WikipediaStrategy
```

### Using Custom Strategies

```yaml
url_rules:
  - match:
      type: domain
      pattern: "news.ycombinator.com"
    strategy: hacker_news

  - match:
      type: domain_suffix
      pattern: ".reddit.com"
    strategy: reddit

  - match:
      type: domain
      pattern: "wikipedia.org"
    strategy: wikipedia
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SCRAPLING_RULES_CONFIG` | Path to custom rules YAML | Built-in rules |
| `SCRAPLING_MIN_MODE` | Minimum fetch mode | `stealth` |
| `SCRAPLING_CACHE_TTL` | Cache TTL (seconds) | `300` |
| `SCRAPLING_MARKDOWN_CONVERTER` | Markdown converter | `markitdown` |

## Configuration Priority

1. **CLI parameters** (highest)
2. **Environment variables**
3. **Built-in defaults** (lowest)

Example:

```bash
# Built-in default: dual
export SCRAPLING_DEFAULT_STRATEGY=trafilatura  # Override: trafilatura
scrapling-fetch-mcp --default-strategy readability  # Final: readability
```

## Validation

### Validate Configuration File

```bash
# Check YAML syntax
python3 -c "import yaml; yaml.safe_load(open('custom_rules.yaml'))"

# Test URL matching
python3 << 'EOF'
from scrapling_fetch_mcp._url_matcher import URLMatcher
from pathlib import Path

matcher = URLMatcher(Path('custom_rules.yaml'))
print(matcher.match("https://example.com"))
EOF
```

### Debug Configuration Loading

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from scrapling_fetch_mcp._url_matcher import URLMatcher

matcher = URLMatcher()
# Logs will show:
# - Config file path
# - Rules loaded
# - Match attempts
```

## Best Practices

### 1. Version Control Your Rules

```bash
git add custom_rules.yaml
git commit -m "Update airead routing rules"
```

### 2. Use Relative Paths for Team Projects

```yaml
custom_strategies:
  - name: team_strategy
    module: ./strategies/team.py  # Relative to project root
    class: TeamStrategy
```

### 3. Test Before Deployment

```bash
# Dry run with custom rules
export SCRAPLING_RULES_CONFIG=./test_rules.yaml
pytest tests/test_airead_*.py -v
```

### 4. Document Your Rules

```yaml
# custom_rules.yaml
# Version: 1.0
# Last updated: 2026-03-18
# Author: Team Name

# Rules for internal documentation sites
url_rules:
  # Internal API docs
  - match:
      type: domain_suffix
      pattern: ".docs.internal.company.com"
    strategy: documentation

  # Internal blog
  - match:
      type: domain
      pattern: "blog.company.com"
    strategy: trafilatura
```

## Troubleshooting

### Issue: Custom rules not loaded
**Check:**
```bash
echo $SCRAPLING_RULES_CONFIG  # Should show path
ls -la $SCRAPLING_RULES_CONFIG  # File should exist
```

### Issue: YAML parse error
**Validate:**
```bash
python3 -c "import yaml; yaml.safe_load(open('custom_rules.yaml'))"
```

### Issue: Strategy not found
**Check:**
- Module path is absolute or correctly relative
- Python file has no syntax errors
- Class name matches exactly
- Strategy class inherits from `ExtractorStrategy`
