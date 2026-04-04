"""Tests for _register_tool and feature merge logic in mcp.py"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from scrapling_fetch_mcp.mcp import _register_tool, mcp
from scrapling_fetch_mcp._config import config


class TestRegisterTool:
    """Tests for _register_tool function"""

    def setup_method(self):
        """Reset Config singleton state before each test"""
        config._enabled_features = set()
        config._disable_features_raw = []
        config._enable_features_raw = []

    @patch("scrapling_fetch_mcp.mcp.mcp")
    @patch("scrapling_fetch_mcp.mcp.build_tool_function")
    def test_register_tool_calls_build_tool_function(self, mock_build, mock_mcp_obj):
        """_register_tool should call build_tool_function with correct arguments"""
        # Set up enabled_features so we can verify it's passed
        config._enabled_features = {"stealth", "format"}

        # Make build_tool_function return a fake async function
        fake_func = AsyncMock()
        mock_build.return_value = fake_func

        # Make mcp.tool() return a decorator that applies the function
        mock_decorator = MagicMock(return_value=fake_func)
        mock_mcp_obj.tool.return_value = mock_decorator

        # Define a dummy impl_func
        impl_func = lambda: None
        param_configs = {"url": {"type": str}}
        base_docstring = "test docstring"

        _register_tool("test_tool", param_configs, base_docstring, impl_func)

        # Assert build_tool_function was called with correct args
        mock_build.assert_called_once_with(
            tool_name="test_tool",
            param_configs=param_configs,
            enabled_features=config.enabled_features,
            base_docstring=base_docstring,
            impl_func=impl_func,
            config=config,
        )

    @patch("scrapling_fetch_mcp.mcp.build_tool_function")
    def test_register_tool_registers_with_mcp(self, mock_build):
        """_register_tool should register the built function via mcp.tool()"""
        # Create a real async function for build_tool_function to return
        async def fake_tool_func(url: str):
            return url

        mock_build.return_value = fake_tool_func

        impl_func = lambda: None
        param_configs = {"url": {"type": str}}
        base_docstring = "test docstring"

        # Should not raise any exception
        _register_tool("test_tool", param_configs, base_docstring, impl_func)

        # Verify build_tool_function was called and the result was used
        mock_build.assert_called_once()

        # Verify that mcp.tool() was called (decorator applied)
        # The real mcp.tool() should have been invoked without error
        # We can verify by checking mcp's internal tool registry
        # FastMCP uses the function's __name__ as the registered tool name
        registered_tool_names = list(mcp._tool_manager._tools.keys())
        assert "fake_tool_func" in registered_tool_names


class TestFeatureMergeLogic:
    """Tests for env + CLI feature merge logic used in run_server"""

    def setup_method(self):
        """Reset Config singleton state before each test"""
        config._enabled_features = set()
        config._disable_features_raw = []
        config._enable_features_raw = []

    def test_env_disable_cli_enable_cli_wins(self):
        """When env disables a feature and CLI enables it, CLI wins (enable > disable)"""
        # Simulate env raw values
        config._disable_features_raw = ["save"]
        config._enable_features_raw = []

        # Simulate CLI args
        disable_cli = ["stealth"]
        enable_cli = ["save"]

        # Merge as run_server does
        disable_list = config._disable_features_raw + disable_cli
        enable_list = config._enable_features_raw + enable_cli

        config.resolve_features(disable_list, enable_list)

        # "save" was disabled by env but enabled by CLI -> enable wins
        assert "save" in config.enabled_features
        # "stealth" was disabled by CLI with no enable override -> disabled
        assert "stealth" not in config.enabled_features
        # Other default-enabled features should still be present
        assert "format" in config.enabled_features
        assert "pagination" in config.enabled_features

    def test_env_enable_cli_disable_cli_wins(self):
        """When env enables a feature and CLI disables it, env wins (enable > disable)"""
        # Simulate env raw values
        config._disable_features_raw = []
        config._enable_features_raw = ["save"]

        # Simulate CLI args
        disable_cli = ["save"]
        enable_cli = []

        # Merge as run_server does
        disable_list = config._disable_features_raw + disable_cli
        enable_list = config._enable_features_raw + enable_cli

        config.resolve_features(disable_list, enable_list)

        # Both env and CLI have "save" in enable and disable lists.
        # In resolve_features: first disable removes it, then enable adds it back.
        # So "save" should be enabled (enable > disable priority).
        assert "save" in config.enabled_features
        # Default-enabled features should still be present
        assert "stealth" in config.enabled_features
        assert "format" in config.enabled_features
        assert "pagination" in config.enabled_features
