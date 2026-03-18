# airead Format Usage Guide

## What is airead?

airead is an AI-optimized content extraction format that reduces token usage by 30-50% while preserving >90% of core content. It intelligently removes navigation, ads, sidebars, and other non-essential elements.

## Basic Usage

```python
# MCP Tool
await s_fetch_page(
    url="https://github.com/user/repo",
    format="airead"  # AI-optimized extraction
)

# CLI
scrapling-fetch-mcp fetch --format airead "https://example.com"
```

## Built-in Strategies

### 1. dual (default)
**Triple comparison strategy** - Runs trafilatura, readability, and scrapling extractors, then selects the best result based on effective character count.
- Best for: General-purpose extraction
- Performance: < 3 seconds
- Accuracy: Highest

### 2. trafilatura
**General-purpose extractor** - Uses trafilatura library with markdown output
- Best for: News articles, blog posts
- Performance: < 1 second

### 3. readability
**Firefox Reader View** - Uses readability-lxml (Mozilla's Reader View algorithm)
- Best for: Articles with complex layouts
- Performance: < 1 second

### 4. scrapling
**Built-in extraction** - Uses Scrapling's native Markdown conversion
- Best for: Simple pages, fast extraction
- Performance: < 0.5 seconds

### 5. search_engine
**Search engine optimization** - Specialized for SERP (Search Engine Results Pages)
- Routes: Google, Bing, DuckDuckGo
- Optimized for: Search result listings

### 6. developer_platform
**Developer platforms** - Specialized for code repositories and Q&A sites
- Routes: GitHub, GitLab, StackOverflow
- Features: Preserves code blocks, tables

### 7. documentation
**Technical documentation** - Optimized for docs sites
- Routes: docs.python.org, developer.mozilla.org
- Features: Preserves API docs, code examples

## URL Routing Rules

airead uses intelligent URL routing to automatically select the best strategy:

```yaml
# Built-in rules (simplified)
url_rules:
  # Search engines
  - match:
      type: domain_suffix
      pattern: ".google.com"
    strategy: search_engine

  # Developer platforms
  - match:
      type: domain
      pattern: "github.com"
    strategy: developer_platform

  # Documentation
  - match:
      type: regex
      pattern: ".*docs\\.python\\.org.*"
    strategy: documentation

# Default strategy
default_strategy: dual
```

## Matching Types

### domain
Exact domain match with `www.` prefix support:
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
Smart suffix matching:
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

### regex
Full URL regex matching:
```yaml
- match:
    type: regex
    pattern: ".*docs\\.python\\.org.*"
  strategy: documentation
```
Matches:
- `https://docs.python.org/3/library/` ✅
- `https://docs.python.org/3/tutorial/` ✅

## Custom Rules

### Configuration File

Create `custom_rules.yaml`:

```yaml
# Custom URL routing rules
default_strategy: dual

url_rules:
  # Your custom rules
  - match:
      type: domain
      pattern: "mycompany.com"
    strategy: trafilatura

  - match:
      type: domain_suffix
      pattern: ".mycompany.com"
    strategy: readability

custom_strategies: []
```

### Using Custom Rules

**Environment variable:**
```bash
export SCRAPLING_RULES_CONFIG=/path/to/custom_rules.yaml
scrapling-fetch-mcp
```

**CLI parameter:**
```bash
scrapling-fetch-mcp --rules-config /path/to/custom_rules.yaml
```

## Performance

### Token Reduction
- **Standard markdown**: 100% baseline
- **airead format**: 30-50% reduction
- **Content preservation**: >90% core content

### Extraction Speed
- **Single strategy** (trafilatura/readability/scrapling): < 1 second
- **Dual strategy**: < 3 seconds
- **Accuracy**: >95% for supported site types

### Benchmarks

| Site Type | Standard Markdown | airead Format | Reduction |
|-----------|------------------|---------------|-----------|
| GitHub Repo | ~5000 tokens | ~2500 tokens | 50% |
| Documentation | ~8000 tokens | ~4000 tokens | 50% |
| News Article | ~3000 tokens | ~1800 tokens | 40% |
| Search Results | ~10000 tokens | ~6000 tokens | 40% |

## Best Practices

### 1. Use airead by default
```python
# ✅ Good
await s_fetch_page(url, format="airead")

# ❌ Avoid (unless you need raw HTML)
await s_fetch_page(url, format="markdown")
```

### 2. Configure custom rules for specialized sites
```yaml
# custom_rules.yaml
url_rules:
  - match:
      type: domain_suffix
      pattern: ".internal.company.com"
    strategy: developer_platform  # Preserve code blocks
```

### 3. Monitor extraction quality
```python
result = await s_fetch_page(url, format="airead")

# Check if content looks reasonable
if len(result) < 100:
    # Try with standard markdown
    result = await s_fetch_page(url, format="markdown")
```

## Troubleshooting

### Issue: Content too short
**Cause:** Strategy removed too much
**Solution:** Try different strategy or use `format="markdown"`

### Issue: Important content missing
**Cause:** Strategy misclassified content as navigation
**Solution:** Create custom rule with different strategy

### Issue: Slow extraction
**Cause:** Using dual strategy on many pages
**Solution:** Use single strategy (trafilatura/readability) for faster extraction

## Examples

### Extract GitHub README
```python
readme = await s_fetch_page(
    url="https://github.com/user/repo",
    format="airead"
)
# → ~50% token reduction
# → Preserves: description, features, installation, usage
# → Removes: stars, forks, navigation, footer
```

### Extract Python Documentation
```python
docs = await s_fetch_page(
    url="https://docs.python.org/3/library/json.html",
    format="airead"
)
# → ~40% token reduction
# → Preserves: API docs, examples, parameters
# → Removes: sidebar navigation, footer links
```

### Extract Search Results
```python
results = await s_fetch_page(
    url="https://www.google.com/search?q=python",
    format="airead"
)
# → ~40% token reduction
# → Preserves: result titles, snippets, URLs
# → Removes: ads, sidebars, pagination
```
