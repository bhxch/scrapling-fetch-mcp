# Markdown Converter Selection Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable HTML to Markdown conversion supporting both markitdown and markdownify libraries with server-wide default selection via CLI and environment variables.

**Architecture:** Extend existing configuration system with markdown_converter setting. Add converter-specific functions in _fetcher.py that dispatch based on configured default. Configuration follows existing patterns (CLI args + env vars with hierarchy).

**Tech Stack:** Python 3.10+, markitdown library, markdownify library, pytest for testing

---

## File Structure

**Files to modify:**
- `pyproject.toml` - Add markitdown dependency
- `src/scrapling_fetch_mcp/_config.py` - Add markdown_converter configuration
- `src/scrapling_fetch_mcp/_fetcher.py` - Add converter functions and dispatch logic
- `src/scrapling_fetch_mcp/mcp.py` - Add CLI argument and environment variable support
- `tests/test_config.py` - Test configuration for markdown_converter
- `tests/test_fetcher.py` - Test converter functions and selection logic
- `README.md` - Document new configuration option

**Files created:**
- None (all changes to existing files)

---

## Chunk 1: Configuration System

### Task 1: Add markdown_converter to Config class

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py:94-117` (insert after scraping_dir property)
- Test: `tests/test_config.py` (add to TestConfig class)

- [ ] **Step 1: Write failing tests for markdown_converter property**

Add these tests to the `TestConfig` class in `tests/test_config.py`:

```python
# tests/test_config.py
# Add these methods inside the existing TestConfig class (after test_set_scraping_dir_string)

    def test_default_markdown_converter(self):
        """Test default markdown converter"""
        from scrapling_fetch_mcp._config import Config
        config = Config()
        # Reset to default for test isolation
        config._markdown_converter = "markitdown"
        assert config.markdown_converter == "markitdown"

    def test_set_markdown_converter(self):
        """Test setting markdown converter"""
        from scrapling_fetch_mcp._config import Config
        config = Config()
        config.set_markdown_converter("markdownify")

        assert config.markdown_converter == "markdownify"

    def test_set_invalid_markdown_converter(self):
        """Test setting invalid markdown converter raises error"""
        from scrapling_fetch_mcp._config import Config
        config = Config()
        with pytest.raises(ValueError, match="Invalid converter 'invalid_converter'"):
            config.set_markdown_converter("invalid_converter")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py::TestConfig::test_default_markdown_converter -v`
Expected: FAIL with "AttributeError: property 'markdown_converter' not found" or similar

- [ ] **Step 3: Add markdown_converter property and setter to Config class**

Add the private class variable at line 68 (after `_scraping_dir`):

```python
# src/scrapling_fetch_mcp/_config.py:68

    _markdown_converter: str = "markitdown"  # Default converter
```

Add the property and setter after the `scraping_dir` property (after line 94):

```python
# src/scrapling_fetch_mcp/_config.py:95-117

    @property
    def markdown_converter(self) -> str:
        """Get the markdown converter library name"""
        return self._markdown_converter

    def set_markdown_converter(self, converter: str) -> None:
        """Set the markdown converter from CLI or environment"""
        valid_converters = ["markitdown", "markdownify"]
        if converter not in valid_converters:
            raise ValueError(
                f"Invalid converter '{converter}'. Must be one of: {valid_converters}"
            )
        self._markdown_converter = converter
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py::TestConfig -v`
Expected: PASS (6 tests total: 3 existing + 3 new)

- [ ] **Step 5: Commit configuration changes**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat: add markdown_converter configuration property"
```

### Task 2: Add environment variable support

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py:156-160` (extend init_config_from_env function)
- Test: `tests/test_config.py` (add to TestConfig class)

- [ ] **Step 1: Write failing test for environment variable loading**

Add this test to the `TestConfig` class:

```python
# tests/test_config.py
# Add this method inside TestConfig class (after test_set_invalid_markdown_converter)

    def test_markdown_converter_from_env(self, monkeypatch):
        """Test loading markdown converter from environment variable"""
        from scrapling_fetch_mcp._config import init_config_from_env, Config

        # Reset to default for test isolation
        config = Config()
        config._markdown_converter = "markitdown"

        # Set environment variable
        monkeypatch.setenv("SCRAPLING_MARKDOWN_CONVERTER", "markdownify")

        init_config_from_env()

        assert config.markdown_converter == "markdownify"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::TestConfig::test_markdown_converter_from_env -v`
Expected: FAIL (env var not loaded yet)

- [ ] **Step 3: Add environment variable loading to init_config_from_env**

Extend the `init_config_from_env()` function by adding this code at the end (after the scraping_dir loading):

```python
# src/scrapling_fetch_mcp/_config.py:157-160
# Add these lines at the end of init_config_from_env function

    # Load markdown_converter from environment
    env_markdown_converter = getenv("SCRAPLING_MARKDOWN_CONVERTER", "").lower()
    if env_markdown_converter:
        config.set_markdown_converter(env_markdown_converter)
```

Note: `getenv` is already imported at line 3, no new imports needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::TestConfig::test_markdown_converter_from_env -v`
Expected: PASS

- [ ] **Step 5: Commit environment variable support**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat: add environment variable SCRAPLING_MARKDOWN_CONVERTER support"
```

---

## Chunk 2: Converter Implementation

### Task 3: Add markitdown dependency

**Files:**
- Modify: `pyproject.toml:15-28`

- [ ] **Step 1: Add markitdown to dependencies**

```python
# pyproject.toml

dependencies = [
    "beautifulsoup4>=4.14.2",
    "browserforge>=1.2.3",
    "camoufox>=0.4.11",
    "curl-cffi>=0.13.0",
    "lxml>=6.0.2",
    "markdownify>=1.2.0",
    "markitdown>=0.0.1",  # NEW - HTML to Markdown converter
    "mcp>=1.15.0",
    "msgspec>=0.19.0",
    "packaging>=24.1, <25.0",
    "patchright>=1.58.0",
    "playwright>=1.55.0",
    "scrapling>=0.3.6",
]
```

- [ ] **Step 2: Install the dependency**

Run: `uv sync`
Expected: Successfully installs markitdown package

- [ ] **Step 3: Verify markitdown is installed**

Run: `uv pip list | grep markitdown`
Expected: Shows markitdown with version >= 0.0.1

- [ ] **Step 4: Commit dependency addition**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add markitdown>=0.0.1 as required dependency"
```

### Task 4: Implement converter functions

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py:16-21`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing test for markitdown converter**

```python
# tests/test_fetcher.py

def test_convert_with_markitdown(sample_html):
    """Test HTML to Markdown conversion with markitdown"""
    from scrapling_fetch_mcp._fetcher import _convert_with_markitdown

    result = _convert_with_markitdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetcher.py::test_convert_with_markitdown -v`
Expected: FAIL with "ImportError: cannot import name '_convert_with_markitdown'"

- [ ] **Step 3: Implement _convert_with_markitdown function**

```python
# src/scrapling_fetch_mcp/_fetcher.py

def _convert_with_markitdown(html: str) -> str:
    """Convert HTML to Markdown using markitdown library"""
    from markitdown import MarkItDown

    converter = MarkItDown()
    result = converter.convert(html)
    return result.text_content  # NOTE: Verify this attribute name during implementation
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetcher.py::test_convert_with_markitdown -v`
Expected: PASS

- [ ] **Step 5: Write test for markdownify converter (refactor existing)**

```python
# tests/test_fetcher.py

def test_convert_with_markdownify(sample_html):
    """Test HTML to Markdown conversion with markdownify"""
    from scrapling_fetch_mcp._fetcher import _convert_with_markdownify

    result = _convert_with_markdownify(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result
```

- [ ] **Step 6: Implement _convert_with_markdownify function (extract existing logic)**

```python
# src/scrapling_fetch_mcp/_fetcher.py

def _convert_with_markdownify(html: str) -> str:
    """Convert HTML to Markdown using markdownify library"""
    soup = BeautifulSoup(html, "lxml")
    for script in soup(["script", "style"]):
        script.extract()
    body_elm = soup.find("body")
    return _CustomMarkdownify().convert_soup(body_elm if body_elm else soup)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_fetcher.py::test_convert_with_markdownify -v`
Expected: PASS

- [ ] **Step 8: Commit converter functions**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher.py
git commit -m "feat: add _convert_with_markitdown and _convert_with_markdownify functions"
```

### Task 5: Implement converter selection in _html_to_markdown

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py:16-21`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write failing tests for converter selection**

```python
# tests/test_fetcher.py

def test_html_to_markdown_with_markitdown(sample_html, monkeypatch):
    """Test _html_to_markdown uses markitdown when configured"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markitdown
    config.set_markdown_converter("markitdown")

    result = _html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result

def test_html_to_markdown_with_markdownify(sample_html, monkeypatch):
    """Test _html_to_markdown uses markdownify when configured"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown
    from scrapling_fetch_mcp._config import config

    # Configure to use markdownify
    config.set_markdown_converter("markdownify")

    result = _html_to_markdown(sample_html)

    assert "# Test Page" in result
    assert "Some text content" in result

def test_html_to_markdown_with_explicit_converter(sample_html):
    """Test _html_to_markdown with explicit converter parameter"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown

    result = _html_to_markdown(sample_html, converter="markdownify")

    assert "# Test Page" in result
    assert "Some text content" in result

def test_html_to_markdown_invalid_converter(sample_html):
    """Test _html_to_markdown raises error for invalid converter"""
    from scrapling_fetch_mcp._fetcher import _html_to_markdown

    with pytest.raises(ValueError, match="Unknown converter"):
        _html_to_markdown(sample_html, converter="invalid")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetcher.py::test_html_to_markdown_with_markitdown -v`
Expected: FAIL (function signature doesn't support converter parameter yet)

- [ ] **Step 3: Modify _html_to_markdown to support converter selection**

```python
# src/scrapling_fetch_mcp/_fetcher.py

def _html_to_markdown(html: str, converter: Optional[str] = None) -> str:
    """
    Convert HTML to Markdown using configured converter.

    Args:
        html: HTML content to convert
        converter: Converter to use ('markitdown' or 'markdownify').
                   If None, uses configured default.

    Returns:
        Markdown formatted string
    """
    if converter is None:
        converter = config.markdown_converter

    if converter == "markitdown":
        return _convert_with_markitdown(html)
    elif converter == "markdownify":
        return _convert_with_markdownify(html)
    else:
        raise ValueError(f"Unknown converter: {converter}")
```

Add import for Optional at top of file:

```python
# src/scrapling_fetch_mcp/_fetcher.py
from typing import Optional
```

- [ ] **Step 4: Run all new tests to verify they pass**

Run: `pytest tests/test_fetcher.py::test_html_to_markdown -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Run existing tests to ensure no regression**

Run: `pytest tests/test_fetcher.py -v`
Expected: PASS (all tests including existing ones)

- [ ] **Step 6: Commit converter selection logic**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher.py
git commit -m "feat: add converter selection to _html_to_markdown function"
```

---

## Chunk 3: CLI Integration

### Task 6: Add CLI argument and logging

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py:99-148`

- [ ] **Step 1: Add --markdown-converter CLI argument**

```python
# src/scrapling_fetch_mcp/mcp.py

def run_server():
    """Parse CLI arguments and start the MCP server"""
    parser = ArgumentParser(
        description="Scrapling Fetch MCP Server - Fetch web content with bot-detection avoidance"
    )
    parser.add_argument(
        "--min-mode",
        choices=["basic", "stealth", "max-stealth"],
        help="Minimum fetching mode level. All requests will use at least this mode, "
        "preventing multiple retries from basic to higher modes. "
        "Can also be set via SCRAPLING_MIN_MODE environment variable.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=300,
        help="Cache time-to-live in seconds for fetched pages. "
        "When fetching large pages in segments, this prevents repeated requests to the same URL. "
        "Set to 0 to disable caching. Default: 300 (5 minutes). "
        "Can also be set via SCRAPLING_CACHE_TTL environment variable.",
    )
    parser.add_argument(
        "--scraping-dir",
        type=str,
        default=".temp/scrapling/",
        help="Default directory for saving scraped content (HTML + images). "
        "Can be overridden per-request with scraping_dir parameter. "
        "Default: .temp/scrapling/ "
        "Can also be set via SCRAPING_DIR environment variable.",
    )
    parser.add_argument(
        "--markdown-converter",
        choices=["markitdown", "markdownify"],
        default="markitdown",
        help="Markdown converter library to use. Default: markitdown. "
        "Can also be set via SCRAPLING_MARKDOWN_CONVERTER environment variable.",
    )
    args = parser.parse_args()

    # Initialize from environment first
    init_config_from_env()

    # CLI args override environment variables
    if args.min_mode:
        config.set_min_mode(args.min_mode)

    if args.cache_ttl is not None:
        config.set_cache_ttl(args.cache_ttl)

    if args.scraping_dir:
        config.set_scraping_dir(args.scraping_dir)

    if args.markdown_converter:
        config.set_markdown_converter(args.markdown_converter)

    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    logger.info(f"Minimum mode set to: {config.min_mode}")
    logger.info(f"Cache TTL set to: {config.cache_ttl} seconds")
    logger.info(f"Scraping directory set to: {config.scraping_dir}")
    logger.info(f"Markdown converter set to: {config.markdown_converter}")

    mcp.run(transport="stdio")
```

- [ ] **Step 2: Verify CLI help shows new argument**

Run: `uvx --from scrapling-fetch-mcp scrapling-fetch-mcp --help`
Expected: Shows `--markdown-converter` in help text with description

- [ ] **Step 3: Test CLI argument works**

Run: `SCRAPLING_MARKDOWN_CONVERTER=markdownify uvx --from scrapling-fetch-mcp scrapling-fetch-mcp --markdown-converter markitdown &`
Expected: Server starts with markdown converter set to markitdown (CLI overrides env)

Kill the server: `pkill -f scrapling-fetch-mcp`

- [ ] **Step 4: Commit CLI integration**

```bash
git add src/scrapling_fetch_mcp/mcp.py
git commit -m "feat: add --markdown-converter CLI argument"
```

---

## Chunk 4: Documentation

### Task 7: Update README with markdown converter configuration

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add Markdown Converter Configuration section after Page Caching**

Find the line number after "Page Caching" section ends (around line 166), then add:

```markdown
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
```

Insert this section after "Page Caching" section and before "Content Saving Feature" section.

- [ ] **Step 2: Verify README formatting**

Run: `cat README.md | grep -A 30 "## Markdown Converter"`
Expected: Shows the new section with proper formatting

- [ ] **Step 3: Commit documentation updates**

```bash
git add README.md
git commit -m "docs: add markdown converter configuration documentation"
```

---

## Chunk 5: Final Verification

### Task 8: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: PASS (all tests pass)

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_integration.py -v`
Expected: PASS (integration tests pass)

- [ ] **Step 3: Manual test with both converters**

Create a test script:

```python
# test_manual.py
import asyncio
from scrapling_fetch_mcp._fetcher import fetch_page_impl
from scrapling_fetch_mcp._config import config

async def test_both_converters():
    # Test with markitdown
    config.set_markdown_converter("markitdown")
    result1 = await fetch_page_impl(
        url="https://example.com",
        mode="basic",
        format="markdown",
        max_length=1000,
        start_index=0,
        save_content=False,
        scraping_dir=None
    )
    print("markitdown result:", result1[:200])

    # Test with markdownify
    config.set_markdown_converter("markdownify")
    result2 = await fetch_page_impl(
        url="https://example.com",
        mode="basic",
        format="markdown",
        max_length=1000,
        start_index=0,
        save_content=False,
        scraping_dir=None
    )
    print("markdownify result:", result2[:200])

asyncio.run(test_both_converters())
```

Run: `python test_manual.py`
Expected: Both converters produce valid markdown output

Clean up: `rm test_manual.py`

### Task 9: Final commit and summary

- [ ] **Step 1: Create summary of changes**

Run: `git log --oneline --decorate | head -10`
Expected: Shows all the commits made during implementation

- [ ] **Step 2: Review all changed files**

Run: `git diff main --stat`
Expected: Shows all modified files with line counts

- [ ] **Step 3: Final verification of spec requirements**

Check that all requirements from spec are met:
- [x] markitdown added as dependency
- [x] Configuration system supports markdown_converter
- [x] Environment variable SCRAPLING_MARKDOWN_CONVERTER works
- [x] CLI argument --markdown-converter works
- [x] Both markitdown and markdownify converters implemented
- [x] Converter selection in _html_to_markdown works
- [x] Tests cover all functionality
- [x] Documentation updated

---

## Success Criteria

- [x] Users can select between markitdown and markdownify converters
- [x] Configuration works via CLI and environment variable
- [x] CLI arguments override environment variables
- [x] Both converters produce valid Markdown output
- [x] All tests pass
- [x] No regression in existing functionality
- [x] Documentation clearly explains the feature
