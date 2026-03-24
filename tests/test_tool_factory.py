"""Tests for dynamic tool factory."""

import inspect

import pytest

from scrapling_fetch_mcp._features import TOOL_PARAMS, S_FETCH_PAGE_DOCSTRING
from scrapling_fetch_mcp._tool_factory import build_tool_function


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
        )
        result = await func("https://example.com", format="markdown", mode="stealth")
        assert result == "test_result"
        assert len(_fake_impl.calls) == 1
        call_kwargs = _fake_impl.calls[0]
        # Disabled params should be passed with defaults
        assert call_kwargs["start_index"] == 0
        assert call_kwargs["save_content"] is False
        assert call_kwargs["scraping_dir"] == ".temp/scrapling/"
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
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        # url (required, core) and max_length (optional, core) must be present
        assert "url" in param_names
        assert "max_length" in param_names

    def test_only_core_params_when_all_disabled(self):
        """When all features disabled, only core params remain."""
        func = build_tool_function(
            tool_name="s_fetch_page",
            param_configs=TOOL_PARAMS["s_fetch_page"],
            enabled_features=set(),
            base_docstring=S_FETCH_PAGE_DOCSTRING,
            impl_func=_fake_impl,
        )
        sig = inspect.signature(func)
        param_names = set(sig.parameters.keys())
        # Core params: url (feature=None), max_length (feature=None)
        # Feature params should all be absent
        assert "mode" not in param_names          # stealth
        assert "format" not in param_names         # format
        assert "start_index" not in param_names    # pagination
        assert "save_content" not in param_names   # save
        assert "scraping_dir" not in param_names   # save
        # Core params should be present
        assert "url" in param_names
        assert "max_length" in param_names
