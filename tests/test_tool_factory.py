"""Tests for dynamic tool factory."""

import inspect
from pathlib import Path

import pytest

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._features import TOOL_PARAMS, S_FETCH_PAGE_DOCSTRING, S_FETCH_PATTERN_DOCSTRING
from scrapling_fetch_mcp._tool_factory import build_tool_function, _build_docstring, _resolve_default


async def _fake_impl(**kwargs):
    """Fake implementation that records all kwargs it receives."""
    _fake_impl.calls.append(kwargs)
    return "test_result"


_fake_impl.calls = []


@pytest.fixture(autouse=True)
def _reset_fake_impl():
    """Reset fake_impl call records before each test."""
    _fake_impl.calls.clear()
    yield


class TestBuildToolFunction:
    """Tests for build_tool_function()."""

    def test_full_features_all_params_present(self):
        """All feature params present when all features enabled."""
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
        param_names = set(sig.parameters.keys())
        # All 7 params should be present
        expected = {"url", "mode", "format", "max_length", "start_index",
                     "save_content", "scraping_dir"}
        assert param_names == expected

    def test_save_disabled_hides_save_params(self):
        """save disabled hides save_content and scraping_dir."""
        enabled = {"stealth", "format", "pagination"}  # no "save"
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        assert "save_content" not in param_names
        assert "scraping_dir" not in param_names

    def test_type_annotations_present(self):
        """Generated function has type annotations in signature."""
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
        # url: str
        assert sig.parameters["url"].annotation is str
        # mode: str
        assert sig.parameters["mode"].annotation is str
        # max_length: int
        assert sig.parameters["max_length"].annotation is int
        # save_content: bool
        assert sig.parameters["save_content"].annotation is bool

    def test_docstring_contains_only_enabled_params(self):
        """Docstring only describes enabled parameters."""
        enabled = {"stealth", "format"}  # no pagination, no save
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        doc = func.__doc__
        # start_index is pagination feature -> should not appear in Args
        assert "start_index" not in doc
        assert "save_content" not in doc
        assert "scraping_dir" not in doc
        # But core params and enabled feature params should appear
        assert "url:" in doc
        assert "max_length:" in doc

    def test_docstring_preserves_base_description(self):
        """IMPORTANT section from base_docstring is preserved."""
        enabled = {"stealth", "format", "pagination", "save"}
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        doc = func.__doc__
        assert "IMPORTANT" in doc

    @pytest.mark.asyncio
    async def test_delegates_to_impl_with_defaults(self):
        """Disabled params are passed to impl with their default values."""
        enabled = {"stealth", "format"}  # no pagination, no save
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        result = await func("https://example.com", format="markdown", mode="stealth")
        assert result == "test_result"
        assert len(_fake_impl.calls) == 1
        call_kwargs = _fake_impl.calls[0]
        # Disabled params should be passed with defaults
        assert call_kwargs["start_index"] == 0
        assert call_kwargs["save_content"] is False
        assert call_kwargs["scraping_dir"] == str(Path(".temp/scrapling/"))
        # Enabled params should be what we passed
        assert call_kwargs["url"] == "https://example.com"
        assert call_kwargs["mode"] == "stealth"
        assert call_kwargs["format"] == "markdown"

    def test_required_params_always_present(self):
        """Core params (feature=None) are always in signature."""
        # No features enabled at all
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=set(),
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        # url (required, core) and max_length (optional, core) must be present
        assert "url" in param_names
        assert "max_length" in param_names


class TestBuildToolFunctionPattern:
    """Tests for build_tool_function() with s_fetch_pattern."""

    def test_pattern_full_features_all_params_present(self):
        """All 6 params present when all features enabled for s_fetch_pattern."""
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
        param_names = set(sig.parameters.keys())
        expected = {"url", "search_pattern", "mode", "format", "max_length", "context_chars"}
        assert param_names == expected

    def test_pattern_stealth_disabled_hides_mode(self):
        """Disabling stealth hides mode param for s_fetch_pattern."""
        enabled = {"format"}
        func = build_tool_function(
            tool_name="s_fetch_pattern",
            param_configs=TOOL_PARAMS["s_fetch_pattern"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PATTERN_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        assert "mode" not in param_names
        assert "url" in param_names
        assert "search_pattern" in param_names
        assert "format" in param_names
        assert "max_length" in param_names
        assert "context_chars" in param_names

    def test_pattern_only_core_when_all_disabled(self):
        """When all features disabled, only core params remain for s_fetch_pattern."""
        func = build_tool_function(
            tool_name="s_fetch_pattern",
            param_configs=TOOL_PARAMS["s_fetch_pattern"],
            enabled_features=set(),
            base_docstring=S_FETCH_PATTERN_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        # Core params: url, search_pattern, max_length, context_chars (feature=None)
        # Feature params: mode (stealth), format (format)
        assert "mode" not in param_names
        assert "format" not in param_names
        assert param_names == {"url", "search_pattern", "max_length", "context_chars"}

    @pytest.mark.asyncio
    async def test_pattern_delegates_to_impl_with_defaults(self):
        """Disabled stealth passes mode='basic' as default to impl for s_fetch_pattern."""
        enabled = {"format"}
        func = build_tool_function(
            tool_name="s_fetch_pattern",
            param_configs=TOOL_PARAMS["s_fetch_pattern"],
            enabled_features=enabled,
            base_docstring=S_FETCH_PATTERN_DOCSTRING,
            impl_func=_fake_impl,
            config=config,
        )
        result = await func("https://example.com", "<title>.*</title>", format="markdown")
        assert result == "test_result"
        assert len(_fake_impl.calls) == 1
        call_kwargs = _fake_impl.calls[0]
        # Disabled stealth param should have default value from config
        assert call_kwargs["mode"] == config.min_mode
        # Enabled params should be what we passed
        assert call_kwargs["url"] == "https://example.com"
        assert call_kwargs["search_pattern"] == "<title>.*</title>"
        assert call_kwargs["format"] == "markdown"


class TestBuildDocstring:
    """Tests for _build_docstring() helper."""

    def test_empty_params_shows_only_args_header(self):
        """With no enabled params, only base text and 'Args:' header appear."""
        result = _build_docstring("base text", [], {})
        assert "base text" in result
        assert "Args:" in result
        # No parameter lines should follow after Args:
        lines = result.split("\n")
        args_idx = lines.index("Args:")
        # Only the base text, empty line, Args:, and nothing after
        remaining = lines[args_idx + 1:]
        assert remaining == []

    def test_missing_description_uses_empty_string(self):
        """Param config without 'description' key does not crash."""
        param_configs = {
            "p1": {"type": str, "required": True, "default": None, "feature": None}
        }
        result = _build_docstring("base", ["p1"], param_configs)
        assert "base" in result
        assert "Args:" in result
        # p1 should appear but with empty description after the colon
        assert "p1:" in result
        # No crash occurred


class TestTypeMapFallback:
    """Tests for _TYPE_MAP fallback behavior."""

    def test_unknown_type_fallback_to_str(self):
        """Type not in _TYPE_MAP falls back to 'str' annotation."""
        custom_configs = {
            "items": {
                "type": list, "required": False, "default": [],
                "feature": None, "description": "List of items",
            },
        }
        func = build_tool_function(
            tool_name="test_tool",
            param_configs=custom_configs,
            enabled_features=set(),
            base_docstring="Test tool",
            impl_func=_fake_impl,
            config=config,
        )
        sig = inspect.signature(func)
        # list is not in _TYPE_MAP, so it should fall back to str
        assert sig.parameters["items"].annotation is str


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
