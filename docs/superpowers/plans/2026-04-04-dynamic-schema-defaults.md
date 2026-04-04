# Dynamic Schema Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make three tool parameter defaults (`mode`, `format`, `scraping_dir`) in `tools/list` inputSchema dynamically reflect the server's runtime configuration instead of hardcoded values.

**Architecture:** Add a declarative `config_key` field to `TOOL_PARAMS` entries pointing to `Config` properties. The tool factory resolves effective defaults at function-build time via a new `_resolve_default` helper. The registration layer passes the `config` instance into the factory.

**Tech Stack:** Python, pytest, pytest-asyncio, FastMCP

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/scrapling_fetch_mcp/_features.py` | Modify | Add `config_key` field to 5 parameter entries |
| `src/scrapling_fetch_mcp/_tool_factory.py` | Modify | Add `_resolve_default`, accept `config` param, use dynamic defaults |
| `src/scrapling_fetch_mcp/mcp.py` | Modify | Pass `config` through `_register_tool` to `build_tool_function` |
| `tests/test_tool_factory.py` | Modify | Add `TestResolveDefault` class, update existing tests to pass `config` |

---

### Task 1: Add `config_key` to `TOOL_PARAMS` in `_features.py`

**Files:**
- Modify: `src/scrapling_fetch_mcp/_features.py`

- [ ] **Step 1: Add `config_key` field to 5 parameter entries**

Add `"config_key": "min_mode"` to both `mode` entries, `"config_key": "default_format"` to both `format` entries, and `"config_key": "scraping_dir"` to the `scraping_dir` entry in `s_fetch_page`.

In `src/scrapling_fetch_mcp/_features.py`, the `s_fetch_page` `"mode"` entry (line 27-29) becomes:

```python
"mode": {
    "type": str, "required": False, "default": "basic",
    "feature": "stealth",
    "config_key": "min_mode",
    "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
},
```

The `s_fetch_page` `"format"` entry (line 33-35) becomes:

```python
"format": {
    "type": str, "required": False, "default": None,
    "feature": "format",
    "config_key": "default_format",
    "description": "Output format (airead, markdown, or html). Use airead for AI-optimized extraction, markdown for standard conversion, html only for structure analysis. Defaults to server's default format setting.",
},
```

The `s_fetch_page` `"scraping_dir"` entry (line 49-53) becomes:

```python
"scraping_dir": {
    "type": str, "required": False, "default": ".temp/scrapling/",
    "feature": "save",
    "config_key": "scraping_dir",
    "description": "Directory path for saved content (relative or absolute). Default: .temp/scrapling/",
},
```

The `s_fetch_pattern` `"mode"` entry (line 68-70) becomes:

```python
"mode": {
    "type": str, "required": False, "default": "basic",
    "feature": "stealth",
    "config_key": "min_mode",
    "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
},
```

The `s_fetch_pattern` `"format"` entry (line 73-75) becomes:

```python
"format": {
    "type": str, "required": False, "default": None,
    "feature": "format",
    "config_key": "default_format",
    "description": "Output format (html or markdown). Use markdown for content reading/extraction, html only for structure analysis. Defaults to server's default format setting (airead will be converted to markdown).",
},
```

- [ ] **Step 2: Run existing tests to verify no breakage**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest tests/test_features.py tests/test_tool_factory.py tests/test_mcp_registration.py -v`
Expected: All existing tests PASS (adding a new dict key does not break anything).

- [ ] **Step 3: Commit**

```bash
git add src/scrapling_fetch_mcp/_features.py
git commit -m "feat(features): add config_key field for dynamic schema defaults"
```

---

### Task 2: Add `_resolve_default` helper and update `build_tool_function` in `_tool_factory.py`

**Files:**
- Modify: `src/scrapling_fetch_mcp/_tool_factory.py`

- [ ] **Step 1: Write failing tests for `_resolve_default`**

In `tests/test_tool_factory.py`, add a new test class after `TestTypeMapFallback`:

```python
from pathlib import Path
from scrapling_fetch_mcp._tool_factory import _resolve_default


class TestResolveDefault:
    """Tests for _resolve_default() helper."""

    def test_no_config_key_returns_static_default(self):
        """When config_key is absent, return the static default."""
        cfg = {"type": str, "required": False, "default": "basic", "feature": None}
        mock_config = type("Config", (), {"min_mode": "stealth"})()
        assert _resolve_default(cfg, mock_config) == "basic"

    def test_config_key_returns_config_value(self):
        """When config_key points to a config attribute, return its value."""
        cfg = {"type": str, "required": False, "default": "basic", "feature": None, "config_key": "min_mode"}
        mock_config = type("Config", (), {"min_mode": "stealth"})()
        assert _resolve_default(cfg, mock_config) == "stealth"

    def test_config_key_path_converted_to_str(self):
        """When config_key returns a Path, convert to string."""
        cfg = {"type": str, "required": False, "default": ".temp/scrapling/", "feature": None, "config_key": "scraping_dir"}
        mock_config = type("Config", (), {"scraping_dir": Path("/custom/path")})()
        assert _resolve_default(cfg, mock_config) == "/custom/path"
        assert isinstance(_resolve_default(cfg, mock_config), str)

    def test_config_key_missing_attribute_returns_static_default(self):
        """When config_key points to a non-existent attribute, fall back to static default."""
        cfg = {"type": str, "required": False, "default": "basic", "feature": None, "config_key": "nonexistent"}
        mock_config = type("Config", (), {})()
        assert _resolve_default(cfg, mock_config) == "basic"

    def test_config_value_none_returns_none(self):
        """When config property returns None, use that None (not the static default)."""
        cfg = {"type": str, "required": False, "default": "markdown", "feature": None, "config_key": "default_format"}
        mock_config = type("Config", (), {"default_format": None})()
        assert _resolve_default(cfg, mock_config) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest tests/test_tool_factory.py::TestResolveDefault -v`
Expected: FAIL — `ImportError: cannot import name '_resolve_default' from 'scrapling_fetch_mcp._tool_factory'`

- [ ] **Step 3: Implement `_resolve_default` and update `build_tool_function`**

In `src/scrapling_fetch_mcp/_tool_factory.py`:

Add import at the top:

```python
from pathlib import Path
```

Add `_resolve_default` function before `build_tool_function`:

```python
def _resolve_default(cfg: dict, config) -> Any:
    """Resolve the effective default value for a parameter.

    If the param config has a ``config_key`` and the config object has
    that attribute, use the config value (converting Path to str).
    Otherwise fall back to the static default in cfg["default"].
    """
    config_key = cfg.get("config_key")
    if config_key and hasattr(config, config_key):
        value = getattr(config, config_key)
        return str(value) if isinstance(value, Path) else value
    return cfg["default"]
```

Update `build_tool_function` signature to accept `config`:

```python
def build_tool_function(
    tool_name: str,
    param_configs: dict[str, dict],
    enabled_features: set[str],
    base_docstring: str,
    impl_func: Callable,
    config,  # NEW: Config instance for dynamic default resolution
) -> Callable:
```

In the signature building loop (around line 53-58), replace `cfg['default']` with `_resolve_default(cfg, config)`:

Change:
```python
        if not cfg["required"]:
            sig_parts.append(f"{name}: {type_str} = {repr(cfg['default'])}")
```
To:
```python
        if not cfg["required"]:
            effective_default = _resolve_default(cfg, config)
            sig_parts.append(f"{name}: {type_str} = {repr(effective_default)}")
```

In the call kwargs building loop (around line 67-69), replace `cfg["default"]` with `_resolve_default(cfg, config)`:

Change:
```python
    for name, cfg in param_configs.items():
        if name not in call_kwargs:
            call_kwargs[name] = repr(cfg["default"])
```
To:
```python
    for name, cfg in param_configs.items():
        if name not in call_kwargs:
            call_kwargs[name] = repr(_resolve_default(cfg, config))
```

- [ ] **Step 4: Run `_resolve_default` tests to verify they pass**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest tests/test_tool_factory.py::TestResolveDefault -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_tool_factory.py tests/test_tool_factory.py
git commit -m "feat(tool-factory): add _resolve_default for dynamic schema defaults"
```

---

### Task 3: Pass `config` through the registration chain in `mcp.py`

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`
- Modify: `tests/test_mcp_registration.py`

- [ ] **Step 1: Update `_register_tool` to pass `config` to `build_tool_function`**

In `src/scrapling_fetch_mcp/mcp.py`, change `_register_tool`:

From:
```python
def _register_tool(name, param_configs, base_docstring, impl_func):
    """Build a dynamic tool function and register it with FastMCP."""
    func = build_tool_function(
        tool_name=name,
        param_configs=param_configs,
        enabled_features=config.enabled_features,
        base_docstring=base_docstring,
        impl_func=impl_func,
    )
    mcp.tool()(func)
```

To:
```python
def _register_tool(name, param_configs, base_docstring, impl_func):
    """Build a dynamic tool function and register it with FastMCP."""
    func = build_tool_function(
        tool_name=name,
        param_configs=param_configs,
        enabled_features=config.enabled_features,
        base_docstring=base_docstring,
        impl_func=impl_func,
        config=config,
    )
    mcp.tool()(func)
```

- [ ] **Step 2: Update the mock assertion in `test_mcp_registration.py`**

In `tests/test_mcp_registration.py`, update `test_register_tool_calls_build_tool_function` — the mock assertion at line 41-47 must now include `config=config`:

Change:
```python
        mock_build.assert_called_once_with(
            tool_name="test_tool",
            param_configs=param_configs,
            enabled_features=config.enabled_features,
            base_docstring=base_docstring,
            impl_func=impl_func,
        )
```

To:
```python
        mock_build.assert_called_once_with(
            tool_name="test_tool",
            param_configs=param_configs,
            enabled_features=config.enabled_features,
            base_docstring=base_docstring,
            impl_func=impl_func,
            config=config,
        )
```

- [ ] **Step 3: Run affected tests**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest tests/test_mcp_registration.py tests/test_tool_factory.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Run full test suite to verify no breakage**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/mcp.py tests/test_mcp_registration.py
git commit -m "feat(mcp): pass config to build_tool_function for dynamic defaults"
```

---

### Task 4: Update existing tests to pass `config` to `build_tool_function`

**Files:**
- Modify: `tests/test_tool_factory.py`

All existing calls to `build_tool_function` in `test_tool_factory.py` lack the new `config` parameter. After Task 2, these will fail with a `TypeError` about missing required argument.

- [ ] **Step 1: Update all existing `build_tool_function` calls to pass `config`**

At the top of `tests/test_tool_factory.py`, add import:

```python
from scrapling_fetch_mcp._config import config
```

Then every call to `build_tool_function(...)` in the existing test classes (`TestBuildToolFunction`, `TestBuildToolFunctionPattern`, `TestTypeMapFallback`) needs a `config=config` argument appended. There are 13 calls total. Example:

```python
# Before
func = build_tool_function(
    tool_name="s_fetch_page",
    param_configs=TOOL_PARAMS["s_fetch_page"],
    enabled_features=enabled,
    base_docstring=S_FETCH_PAGE_DOCSTRING,
    impl_func=_fake_impl,
)

# After
func = build_tool_function(
    tool_name="s_fetch_page",
    param_configs=TOOL_PARAMS["s_fetch_page"],
    enabled_features=enabled,
    base_docstring=S_FETCH_PAGE_DOCSTRING,
    impl_func=_fake_impl,
    config=config,
)
```

Since `config` is a singleton with default values (`min_mode="stealth"`, `default_format="markdown"`, `scraping_dir=Path(".temp/scrapling/")`), the existing assertion in `test_delegates_to_impl_with_defaults` checking `call_kwargs["scraping_dir"] == ".temp/scrapling/"` will still pass because `str(Path(".temp/scrapling/"))` == `".temp/scrapling/"`.

However, `test_delegates_to_impl_with_defaults` checks `call_kwargs["start_index"] == 0` and `call_kwargs["save_content"] is False` — these params have no `config_key` so they use static defaults. No issue.

The existing assertion `call_kwargs["mode"] == "basic"` in `test_pattern_delegates_to_impl_with_defaults` **will fail** because the disabled `mode` param now gets its default from `config.min_mode` which is `"stealth"` by default.

Update that assertion in `test_pattern_delegates_to_impl_with_defaults` (around line 225):

Change:
```python
        assert call_kwargs["mode"] == "basic"
```

To:
```python
        assert call_kwargs["mode"] == config.min_mode
```

- [ ] **Step 2: Run full test suite**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_tool_factory.py
git commit -m "test(tool-factory): update existing tests to pass config for dynamic defaults"
```

---

### Task 5: Add integration tests for dynamic defaults in generated signatures

**Files:**
- Modify: `tests/test_tool_factory.py`

- [ ] **Step 1: Write integration tests**

Add a new test class `TestDynamicDefaults` in `tests/test_tool_factory.py`:

```python
class TestDynamicDefaults:
    """Tests that config values propagate into generated function signatures."""

    def test_mode_default_reflects_min_mode(self):
        """When config.min_mode is 'max-stealth', mode default is 'max-stealth'."""
        config.set_min_mode("max-stealth")
        try:
            enabled = {"stealth", "format", "pagination", "save"}
            func = build_tool_function(
                tool_name="s_fetch_page",
                param_configs=TOOL_PARAMS["s_fetch_page"],
                enabled_features=enabled,
                base_docstring=S_FETCH_PAGE_DOCSTRING,
                impl_func=_fake_impl,
                config=config,
            )
            sig = inspect.signature(func)
            assert sig.parameters["mode"].default == "max-stealth"
        finally:
            config.set_min_mode("stealth")

    def test_format_default_reflects_default_format(self):
        """When config.default_format is 'airead', format default is 'airead'."""
        config.set_default_format("airead")
        try:
            enabled = {"stealth", "format", "pagination", "save"}
            func = build_tool_function(
                tool_name="s_fetch_page",
                param_configs=TOOL_PARAMS["s_fetch_page"],
                enabled_features=enabled,
                base_docstring=S_FETCH_PAGE_DOCSTRING,
                impl_func=_fake_impl,
                config=config,
            )
            sig = inspect.signature(func)
            assert sig.parameters["format"].default == "airead"
        finally:
            config.set_default_format("markdown")

    def test_scraping_dir_default_reflects_config(self):
        """When config.scraping_dir is a custom Path, scraping_dir default is that path as string."""
        config.set_scraping_dir("/custom/scrapling")
        try:
            enabled = {"stealth", "format", "pagination", "save"}
            func = build_tool_function(
                tool_name="s_fetch_page",
                param_configs=TOOL_PARAMS["s_fetch_page"],
                enabled_features=enabled,
                base_docstring=S_FETCH_PAGE_DOCSTRING,
                impl_func=_fake_impl,
                config=config,
            )
            sig = inspect.signature(func)
            assert sig.parameters["scraping_dir"].default == "/custom/scrapling"
        finally:
            config.set_scraping_dir(".temp/scrapling/")

    def test_no_config_key_uses_static_default(self):
        """Parameters without config_key use their static default regardless of config."""
        enabled = {"stealth", "format", "pagination", "save"}
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        assert sig.parameters["max_length"].default == 8000
        assert sig.parameters["start_index"].default == 0
        assert sig.parameters["save_content"].default is False

    @pytest.mark.asyncio
    async def test_disabled_param_gets_config_default(self):
        """Disabled params with config_key receive the config value, not static default."""
        config.set_min_mode("max-stealth")
        config.set_default_format("airead")
        try:
            enabled = {"format"}  # stealth disabled
            func = build_tool_function(
                tool_name="s_fetch_page",
                param_configs=TOOL_PARAMS["s_fetch_page"],
                enabled_features=enabled,
                base_docstring=S_FETCH_PAGE_DOCSTRING,
                impl_func=_fake_impl,
                config=config,
            )
            await func("https://example.com", format="html")
            call_kwargs = _fake_impl.calls[0]
            assert call_kwargs["mode"] == "max-stealth"
        finally:
            config.set_min_mode("stealth")
            config.set_default_format("markdown")

    def test_pattern_tool_mode_reflects_min_mode(self):
        """s_fetch_pattern mode default also reflects config.min_mode."""
        config.set_min_mode("stealth")
        enabled = {"stealth", "format"}
        func = build_tool_function(
            tool_name="s_fetch_pattern",
            param_configs=TOOL_PARAMS["s_fetch_pattern"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PATTERN_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        assert sig.parameters["mode"].default == "stealth"
```

- [ ] **Step 2: Run the new tests**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest tests/test_tool_factory.py::TestDynamicDefaults -v`
Expected: All 6 tests PASS.

- [ ] **Step 3: Run full test suite**

Run: `cd /share/rw/repo/scrapling-fetch-mcp && uvx --from . pytest -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_tool_factory.py
git commit -m "test(tool-factory): add integration tests for dynamic schema defaults"
```

---

## Self-Review

**Spec coverage:**
- `_features.py` `config_key` fields → Task 1 ✓
- `_tool_factory.py` `_resolve_default` helper → Task 2 ✓
- `_tool_factory.py` `config` param + usage → Task 2 ✓
- `mcp.py` pass `config` to factory → Task 3 ✓
- Unit tests for `_resolve_default` → Task 2 ✓
- Integration tests for dynamic defaults → Task 5 ✓
- Existing test compatibility → Task 4 ✓

**Placeholder scan:** No TBD/TODO found. All code blocks contain complete implementations.

**Type consistency:** `config.min_mode` returns `str`, `config.default_format` returns `str`, `config.scraping_dir` returns `Path` → `_resolve_default` converts Path to str. `build_tool_function` accepts `config` parameter → all call sites updated.
