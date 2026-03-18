# Custom Strategy Development

## Overview

airead format supports custom extraction strategies via Python modules. This allows you to implement specialized extraction logic for specific use cases.

## Creating a Custom Strategy

### 1. Implement the Strategy Class

Create a Python file (e.g., `my_strategy.py`):

```python
from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

class MyCustomStrategy(ExtractorStrategy):
    """Custom extraction strategy for specialized content"""

    def extract(self, html: str, url: str) -> str:
        """
        Extract content from HTML

        Args:
            html: Raw HTML content
            url: Page URL (can be used for strategy-specific logic)

        Returns:
            Extracted Markdown content
        """
        # Your custom extraction logic
        # Example: Use BeautifulSoup + custom Markdown converter

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, 'html.parser')

        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'footer']):
            element.decompose()

        # Extract main content
        main = soup.find('main') or soup.find('body')
        text = main.get_text(separator='\n') if main else ''

        # Convert to Markdown (simplified)
        # In production, use proper Markdown converter
        return text.strip()
```

### 2. Register the Strategy

Add to your `custom_rules.yaml`:

```yaml
custom_strategies:
  - name: my_custom
    module: /path/to/my_strategy.py
    class: MyCustomStrategy
```

### 3. Add URL Routing Rules

```yaml
url_rules:
  - match:
      type: domain
      pattern: "example.com"
    strategy: my_custom

  - match:
      type: regex
      pattern: ".*specialsite\\.com/article/.*"
    strategy: my_custom
```

### 4. Load Custom Rules

```bash
# CLI
scrapling-fetch-mcp --rules-config /path/to/custom_rules.yaml

# Environment variable
export SCRAPLING_RULES_CONFIG=/path/to/custom_rules.yaml
scrapling-fetch-mcp
```

## Strategy Best Practices

### 1. Error Handling

Always handle errors gracefully:

```python
def extract(self, html: str, url: str) -> str:
    try:
        # Your extraction logic
        result = self._do_extraction(html)
        return result or ""
    except Exception as e:
        # Log error and return empty string
        import logging
        logging.warning(f"Extraction failed: {e}")
        return ""
```

### 2. Fallback Logic

Implement fallback to simpler extraction:

```python
def extract(self, html: str, url: str) -> str:
    # Try advanced extraction
    result = self._advanced_extract(html)

    # Fallback to simple extraction
    if not result or len(result) < 100:
        result = self._simple_extract(html)

    return result or ""
```

### 3. Performance Optimization

Cache expensive operations:

```python
class MyStrategy(ExtractorStrategy):
    def __init__(self):
        self._converter = None

    @property
    def converter(self):
        if self._converter is None:
            from my_converter import MarkdownConverter
            self._converter = MarkdownConverter()
        return self._converter

    def extract(self, html: str, url: str) -> str:
        return self.converter.convert(html)
```

### 4. Content Quality Metrics

Implement quality checks:

```python
def extract(self, html: str, url: str) -> str:
    markdown = self._extract_markdown(html)

    # Quality check: minimum content length
    if len(markdown) < 50:
        return ""

    # Quality check: content density
    effective_chars = count_effective_characters(markdown)
    if effective_chars / len(markdown) < 0.5:
        # Too much formatting, content might be poor
        return ""

    return markdown
```

## Example: Site-Specific Strategy

### Hacker News Strategy

```python
# hackernews_strategy.py
from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy
from bs4 import BeautifulSoup

class HackerNewsStrategy(ExtractorStrategy):
    """Specialized strategy for Hacker News"""

    def extract(self, html: str, url: str) -> str:
        soup = BeautifulSoup(html, 'html.parser')

        # Extract story title
        title_row = soup.find('span', class_='titleline')
        title = title_row.get_text() if title_row else ''

        # Extract story link
        link = title_row.find('a')['href'] if title_row else ''

        # Extract score and comments
        subtext = soup.find('span', class_='score')
        score = subtext.get_text() if subtext else ''

        # Format as Markdown
        markdown = f"""# {title}

**Link:** {link}
**Score:** {score}

"""
        return markdown
```

Register:

```yaml
custom_strategies:
  - name: hacker_news
    module: ./hackernews_strategy.py
    class: HackerNewsStrategy

url_rules:
  - match:
      type: domain
      pattern: "news.ycombinator.com"
    strategy: hacker_news
```

## Testing Custom Strategies

### Unit Tests

```python
# test_my_strategy.py
import pytest
from my_strategy import MyCustomStrategy

def test_extract_basic():
    html = "<html><body><h1>Title</h1><p>Content</p></body></html>"
    strategy = MyCustomStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Title" in result or "Content" in result

def test_extract_empty():
    html = "<html><body></body></html>"
    strategy = MyCustomStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert result == ""

def test_extract_malformed():
    html = "<html><body><div>unclosed"
    strategy = MyCustomStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)  # Should not crash
```

### Integration Test

```python
@pytest.mark.asyncio
async def test_custom_strategy_via_fetcher():
    result = await s_fetch_page(
        url="https://example.com",
        format="airead",
        # Custom rules loaded via SCRAPLING_RULES_CONFIG
    )

    assert isinstance(result, str)
    assert len(result) > 0
```

## Debugging

### Enable Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger('scrapling_fetch_mcp')

class MyStrategy(ExtractorStrategy):
    def extract(self, html: str, url: str) -> str:
        logger.debug(f"Extracting from {url}")
        logger.debug(f"HTML length: {len(html)}")

        result = self._do_extraction(html)

        logger.debug(f"Result length: {len(result)}")
        return result
```

### Test Strategy Independently

```python
# test_strategy_standalone.py
from my_strategy import MyCustomStrategy

# Load sample HTML
with open('sample.html', 'r') as f:
    html = f.read()

strategy = MyCustomStrategy()
result = strategy.extract(html, "https://example.com")

print(result)
print(f"Length: {len(result)}")
```

## Limitations

1. **Python version**: Strategies must be compatible with Python 3.9+
2. **Dependencies**: Third-party libraries must be installed separately
3. **Performance**: Complex strategies may impact extraction speed
4. **Error handling**: Strategy errors are caught and logged, not propagated

## Advanced: Strategy Composition

Combine multiple extraction libraries:

```python
class ComposedStrategy(ExtractorStrategy):
    """Strategy that tries multiple extractors"""

    def __init__(self):
        self.extractors = [
            self._extract_with_trafilatura,
            self._extract_with_readability,
            self._extract_with_custom,
        ]

    def extract(self, html: str, url: str) -> str:
        for extractor in self.extractors:
            try:
                result = extractor(html)
                if len(result) > 100:  # Quality threshold
                    return result
            except Exception:
                continue

        return ""  # All extractors failed

    def _extract_with_trafilatura(self, html):
        import trafilatura
        return trafilatura.extract(html, output_format='markdown') or ""

    def _extract_with_readability(self, html):
        # Implementation
        pass

    def _extract_with_custom(self, html):
        # Implementation
        pass
```
