# Markdown Converter Selection Feature Design

**Date**: 2026-03-17
**Status**: Draft
**Author**: Claude (with user collaboration)

## Overview

Add configurable HTML to Markdown conversion support to scrapling-fetch-mcp, allowing users to choose between Microsoft's MarkItDown library and the existing markdownify-based converter.

## Goals

- Support multiple HTML to Markdown conversion libraries
- Make MarkItDown the default converter (with fallback to markdownify if needed)
- Maintain consistency with existing configuration patterns
- Ensure backward compatibility

## Non-Goals

- Per-request converter selection (server-wide default only)
- Advanced converter configuration options
- Support for additional converters beyond markitdown and markdownify

## Design

### Architecture

The feature extends the existing configuration system with a new `markdown_converter` setting that controls which library to use for HTML to Markdown conversion throughout the server's lifetime.

```
Configuration Flow:
CLI Args / Env Vars → Config._markdown_converter → _html_to_markdown() → Converter Selection → Markdown Output
```

### Components

#### 1. Dependency Management

**File**: `pyproject.toml`

Add markitdown as a required dependency alongside the existing markdownify dependency.

```python
dependencies = [
    # ... existing dependencies ...
    "markdownify>=1.2.0",
    "markitdown",  # NEW
    # ... other dependencies ...
]
```

#### 2. Configuration Management

**File**: `src/scrapling_fetch_mcp/_config.py`

Extend the `Config` singleton class:

```python
class Config:
    _markdown_converter: str = "markitdown"  # Default converter

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

Extend `init_config_from_env()`:

```python
def init_config_from_env() -> None:
    # ... existing initialization ...

    # Load markdown_converter from environment
    env_markdown_converter = getenv("SCRAPLING_MARKDOWN_CONVERTER", "").lower()
    if env_markdown_converter:
        config.set_markdown_converter(env_markdown_converter)
```

#### 3. CLI Interface

**File**: `src/scrapling_fetch_mcp/mcp.py`

Add new argument to `run_server()`:

```python
parser.add_argument(
    "--markdown-converter",
    choices=["markitdown", "markdownify"],
    default="markitdown",
    help="Markdown converter library to use. Default: markitdown. "
    "Can also be set via SCRAPLING_MARKDOWN_CONVERTER environment variable.",
)

# After parsing args:
if args.markdown_converter:
    config.set_markdown_converter(args.markdown_converter)

# Add to logging:
logger.info(f"Markdown converter set to: {config.markdown_converter}")
```

#### 4. Converter Implementation

**File**: `src/scrapling_fetch_mcp/_fetcher.py`

Add converter-specific functions:

```python
def _convert_with_markitdown(html: str) -> str:
    """Convert HTML to Markdown using markitdown library"""
    from markitdown import MarkItDown

    converter = MarkItDown()
    result = converter.convert(html)
    return result.text_content


def _convert_with_markdownify(html: str) -> str:
    """Convert HTML to Markdown using markdownify library"""
    soup = BeautifulSoup(html, "lxml")
    for script in soup(["script", "style"]):
        script.extract()
    body_elm = soup.find("body")
    return _CustomMarkdownify().convert_soup(body_elm if body_elm else soup)
```

Modify `_html_to_markdown()`:

```python
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

**Note**: Existing calls to `_html_to_markdown()` in `fetch_page_impl()` and `fetch_pattern_impl()` remain unchanged since the function signature is backward compatible.

#### 5. Documentation

**File**: `README.md`

Add new section after "Content Saving Feature":

```markdown
## Markdown Converter Configuration

Choose which library to use for HTML to Markdown conversion:

- **markitdown** (default): Microsoft's MarkItDown library
- **markdownify**: Custom markdownify-based converter

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

## Configuration Hierarchy

Configuration values are loaded in this order (later values override earlier):

1. Default value: `"markitdown"`
2. Environment variable: `SCRAPLING_MARKDOWN_CONVERTER`
3. CLI argument: `--markdown-converter`

This matches the pattern used by `--min-mode` and other existing configuration options.

## Error Handling

- Invalid converter names raise `ValueError` with clear error message
- Both libraries are required dependencies, so import errors should not occur in normal usage
- If markitdown import fails during conversion, the error propagates (no silent fallback)

## Testing Strategy

1. **Unit tests**:
   - Test `_convert_with_markitdown()` with various HTML inputs
   - Test `_convert_with_markdownify()` (existing implementation)
   - Test `_html_to_markdown()` converter selection logic
   - Test Config markdown_converter property and setter

2. **Integration tests**:
   - Test end-to-end conversion with markitdown
   - Test configuration via environment variable
   - Test configuration via CLI argument
   - Test CLI argument overrides environment variable

3. **Manual testing**:
   - Verify markitdown installation works
   - Compare output quality between converters
   - Test with real-world HTML pages

## Migration Path

No migration needed - this is a new feature. Existing installations will:
- Automatically get markitdown installed on next update
- Start using markitdown as default (behavioral change)
- Can opt back to markdownify via configuration if needed

## Backward Compatibility

- Fully backward compatible at the code level
- Default behavior changes (markdownify → markitdown), but this is the intended feature
- No breaking API changes
- All existing tool calls work unchanged

## Future Considerations

- If needed, could extend to support per-request converter selection
- Could add support for additional converters (html2text, tomd, etc.)
- Could add converter-specific options if advanced customization is needed
- Monitor markitdown library stability and performance

## Success Criteria

- Users can select between markitdown and markdownify converters
- Configuration works via CLI and environment variable
- Both converters produce valid Markdown output
- No performance regression
- Documentation clearly explains the feature
