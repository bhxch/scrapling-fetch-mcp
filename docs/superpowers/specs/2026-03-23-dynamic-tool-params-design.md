# Dynamic Tool Parameter Visibility

**Date**: 2026-03-23
**Status**: Approved

## Problem

MCP tool schemas (parameter definitions + descriptions) are included in every LLM request. Parameters like `save_content` and `scraping_dir` that are rarely used still consume ~80-100 tokens per request across the entire conversation.

## Goal

Allow users to control which tool parameters are visible in the MCP tool schema, reducing per-request token costs by hiding unused parameters from the LLM.

## Design

### Feature Registry

A declarative registry maps parameters to feature groups. Each feature can be independently enabled/disabled. Parameters with `feature: None` are core parameters, always visible.

```python
FEATURES = {
    "stealth":    {"default": "enabled",  "description": "Anti-bot-detection mode control"},
    "format":     {"default": "enabled",  "description": "Output format selection (airead/markdown/html)"},
    "pagination": {"default": "enabled",  "description": "Pagination support for large pages"},
    "save":       {"default": "disabled", "description": "Save page content to local filesystem"},
}
```

Each tool defines its parameter metadata:

```python
TOOL_PARAMS = {
    "s_fetch_page": {
        "url":           {"type": str,  "required": True,  "default": None,              "feature": None,        "description": "URL to fetch"},
        "mode":          {"type": str,  "required": False, "default": "basic",           "feature": "stealth",   "description": "Fetching mode (basic/stealth/max-stealth)..."},
        "format":        {"type": str,  "required": False, "default": None,              "feature": "format",    "description": "Output format (airead/markdown/html)..."},
        "max_length":    {"type": int,  "required": False, "default": 8000,              "feature": None,        "description": "Maximum characters to return"},
        "start_index":   {"type": int,  "required": False, "default": 0,                 "feature": "pagination","description": "Starting character index for pagination"},
        "save_content":  {"type": bool, "required": False, "default": False,             "feature": "save",      "description": "If True, save content to filesystem"},
        "scraping_dir":  {"type": str,  "required": False, "default": ".temp/scrapling/", "feature": "save",      "description": "Directory path for saved content"},
    },
    "s_fetch_pattern": {
        "url":            {"type": str, "required": True,  "default": None, "feature": None,        "description": "URL to fetch"},
        "search_pattern": {"type": str, "required": True,  "default": None, "feature": None,        "description": "Regex pattern to search for in the content"},
        "mode":           {"type": str, "required": False, "default": "basic","feature": "stealth",  "description": "Fetching mode (basic/stealth/max-stealth)..."},
        "format":         {"type": str, "required": False, "default": None, "feature": "format",     "description": "Output format (html or markdown)..."},
        "max_length":     {"type": int, "required": False, "default": 8000, "feature": None,         "description": "Maximum characters to return"},
        "context_chars":  {"type": int, "required": False, "default": 200,  "feature": None,         "description": "Characters before and after each match"},
    },
}
```

### Recommended Default Configuration

- `stealth`: enabled
- `format`: enabled
- `pagination`: enabled
- `save`: **disabled** (rarely used, saves ~80-100 tokens per request)

### Configuration

CLI arguments and environment variables, consistent with existing config patterns:

```bash
# CLI
--disable-features save               # disable save feature
--enable-features save                # enable save feature
--disable-features save,pagination    # disable multiple

# Environment variables
SCRAPLING_DISABLE_FEATURES=save
SCRAPLING_ENABLE_FEATURES=save,pagination
```

**Priority**: `--enable-features` > `--disable-features` > recommended defaults

### Config Class Extension

```python
class Config:
    _enabled_features: set[str]

    def resolve_features(self, disable: list[str], enable: list[str]):
        enabled = {f for f, cfg in FEATURES.items() if cfg["default"] == "enabled"}
        enabled -= set(disable)
        enabled |= set(enable)
        # Validate against known features
        self._enabled_features = enabled
```

Environment variable support: `SCRAPLING_DISABLE_FEATURES` and `SCRAPLING_ENABLE_FEATURES` (comma-separated).

### Dynamic Tool Factory

Tool registration moves from module-level decorators into `run_server()`, after config is fully resolved.

```python
def build_tool_function(tool_name, param_configs, enabled_features, base_description, impl_func):
    """Build a tool function with only enabled parameters in its signature."""
    
    # Filter to enabled params only
    enabled_params = [
        name for name, cfg in param_configs.items()
        if cfg["feature"] is None or cfg["feature"] in enabled_features
    ]
    
    # Build signature string
    sig_parts = []
    for name in enabled_params:
        cfg = param_configs[name]
        if cfg["default"] is not None:
            sig_parts.append(f"{name}={repr(cfg['default'])}")
        else:
            sig_parts.append(name)
    
    # Build call with defaults for disabled params
    call_kwargs = {}
    for name in enabled_params:
        call_kwargs[name] = name
    for name, cfg in param_configs.items():
        if name not in call_kwargs:
            call_kwargs[name] = repr(cfg["default"])
    
    # Dynamic docstring with only enabled param descriptions
    docstring = _build_docstring(base_description, enabled_params, param_configs)
    
    # Build function via exec
    source = f'''async def {tool_name}({", ".join(sig_parts)}) -> str:
    """{docstring}"""
    return await _impl({", ".join(f"{k}={v}" for k, v in call_kwargs.items())})'''
    
    namespace = {"_impl": impl_func}
    exec(source, namespace)
    return namespace[tool_name]
```

Key points:
- `impl_func` always accepts all parameters; disabled ones receive their default values
- Docstring is dynamically generated, only describing enabled parameters
- `exec()` is the most reliable way to create functions with dynamic signatures in Python

### Startup Flow Change

```
Before: module load → @mcp.tool() decorators → run_server() → mcp.run()
After:  module load → run_server() → parse config → resolve_features() → factory builds functions → mcp.tool() registers → mcp.run()
```

### Files Changed

| File | Change |
|------|--------|
| `src/scrapling_fetch_mcp/_features.py` | **New** — feature registry + recommended defaults |
| `src/scrapling_fetch_mcp/_tool_factory.py` | **New** — dynamic function factory |
| `src/scrapling_fetch_mcp/mcp.py` | Remove `@mcp.tool()` decorators; register tools in `run_server()`; add CLI args |
| `src/scrapling_fetch_mcp/_config.py` | Add `enabled_features` + `resolve_features()` + env var support |
| `src/scrapling_fetch_mcp/_fetcher.py` | No changes (implementation signatures unchanged) |

### Token Savings

With default recommended config (`save` disabled):

- `s_fetch_page`: ~75-100 fewer tokens per request (2 parameter definitions + docstring lines removed)
- `s_fetch_pattern`: no change (no save-related parameters)
- Additional savings possible by disabling more features per user preference

### Testing

1. Verify disabled features' parameters are absent from tool schema
2. Verify tools function correctly (disabled params use defaults)
3. Verify CLI and env var configuration works
4. Verify priority logic (enable > disable > default)
5. Verify unknown feature names are handled gracefully (warning log, ignored)
