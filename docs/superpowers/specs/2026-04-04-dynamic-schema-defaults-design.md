# Dynamic Schema Defaults Design

## Summary

When an MCP client calls `tools/list`, the `inputSchema` returned currently uses hardcoded default values from `TOOL_PARAMS`. This design makes three parameter defaults (`mode`, `format`, `scraping_dir`) dynamically reflect the server's actual runtime configuration (set via environment variables or CLI arguments).

## Motivation

- **AI consumers** (Claude, GPT) see schema defaults and use them to decide whether to pass a parameter. If the server's `min_mode` is `stealth` but the schema shows `mode: "basic"`, the AI will pass `mode="stealth"` explicitly, wasting tokens.
- **MCP client UIs** (Claude Desktop, Cursor) display parameter defaults to users. Showing the actual configured default is more accurate.

## Scope

Three parameters with existing config mappings:

| Parameter   | Hardcoded Default | Config Property       | Config Source                |
|-------------|-------------------|-----------------------|------------------------------|
| `mode`      | `"basic"`         | `Config.min_mode`     | `SCRAPLING_MIN_MODE` / CLI   |
| `format`    | `None`            | `Config.default_format` | `SCRAPLING_DEFAULT_FORMAT` / CLI |
| `scraping_dir` | `".temp/scrapling/"` | `Config.scraping_dir` | `SCRAPLING_DIR` / CLI        |

No new environment variables or config properties are introduced.

## Design

### Approach: Declarative `config_key` field (方案 A)

Add a `config_key` field to `TOOL_PARAMS` entries. The tool factory resolves the effective default at function-build time.

### 1. Data Model (`_features.py`)

Add `config_key` to three parameter entries across both tools:

```python
"mode": {
    "type": str, "required": False, "default": "basic",
    "feature": "stealth",
    "config_key": "min_mode",
    "description": "...",
},
"format": {
    "type": str, "required": False, "default": None,
    "feature": "format",
    "config_key": "default_format",
    "description": "...",
},
"scraping_dir": {
    "type": str, "required": False, "default": ".temp/scrapling/",
    "feature": "save",
    "config_key": "scraping_dir",
    "description": "...",
},
```

The existing `default` field is retained as a fallback when `config_key` resolution fails.

### 2. Tool Factory (`_tool_factory.py`)

**New parameter:** `build_tool_function` accepts a `config` argument.

**New helper:** `_resolve_default(cfg, config)` resolves the effective default:

```python
def _resolve_default(cfg: dict, config) -> Any:
    config_key = cfg.get("config_key")
    if config_key and hasattr(config, config_key):
        value = getattr(config, config_key)
        return str(value) if isinstance(value, Path) else value
    return cfg["default"]
```

**Signature building:** Replace `cfg["default"]` with `_resolve_default(cfg, config)` in both:
- Signature string construction (`sig_parts`)
- Call kwargs construction (`call_kwargs`)

### 3. Registration (`mcp.py`)

Pass `config` to `build_tool_function`:

```python
func = build_tool_function(
    tool_name=name,
    param_configs=param_configs,
    enabled_features=config.enabled_features,
    base_docstring=base_docstring,
    impl_func=impl_func,
    config=config,
)
```

### 4. Files Changed

| File              | Change                                              |
|-------------------|-----------------------------------------------------|
| `_features.py`    | Add `config_key` to 3 parameters (5 entries total: mode ×2, format ×2, scraping_dir ×1) |
| `_tool_factory.py` | Add `config` param, `_resolve_default` helper, use it for defaults |
| `mcp.py`          | Pass `config` to `build_tool_function`              |

### 5. Files NOT Changed

- `_config.py` — no new config properties needed
- `_fetcher.py` — runtime logic unchanged
- `_scrapling.py` — no changes

## Testing

### Unit Tests

- `_resolve_default` with `config_key` present and config has value → returns config value
- `_resolve_default` with `config_key` present but config value is falsy → returns config value (not static default)
- `_resolve_default` without `config_key` → returns static default
- `_resolve_default` with Path-typed config value → returns string

### Integration Tests

- Set `config.min_mode = "stealth"` → generated function signature has `mode: str = 'stealth'`
- Set `config.default_format = "airead"` → generated function signature has `format: str = 'airead'`
- Set `config.scraping_dir = Path("/custom")` → generated function signature has `scraping_dir: str = '/custom'`
- Defaults still work when no config overrides are set

## Out of Scope

- Dynamic defaults for `max_length`, `start_index`, `context_chars` (no corresponding config properties)
- Changing runtime behavior of tools (only affects schema presentation)
- New environment variables or CLI arguments
