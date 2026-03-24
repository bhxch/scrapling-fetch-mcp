"""Integration tests for feature control via environment variables"""
import pytest
from scrapling_fetch_mcp._config import config, init_config_from_env


class TestConfigFeaturesEnv:
    """Tests for feature enable/disable via environment variables"""

    def setup_method(self):
        """Reset Config singleton state before each test"""
        config._enabled_features = set()
        config._disable_features_raw = []
        config._enable_features_raw = []

    def test_disable_features_env_var(self, monkeypatch):
        """SCRAPLING_DISABLE_FEATURES env var stores raw value in _disable_features_raw"""
        monkeypatch.setenv("SCRAPLING_DISABLE_FEATURES", "save")
        init_config_from_env()
        assert config._disable_features_raw == ["save"]

    def test_enable_features_env_var(self, monkeypatch):
        """SCRAPLING_ENABLE_FEATURES env var stores raw value in _enable_features_raw"""
        monkeypatch.setenv("SCRAPLING_ENABLE_FEATURES", "save")
        init_config_from_env()
        assert config._enable_features_raw == ["save"]

    def test_features_env_and_cli_merged(self, monkeypatch):
        """Env vars and CLI lists are merged correctly via resolve_features"""
        monkeypatch.setenv("SCRAPLING_ENABLE_FEATURES", "save")
        init_config_from_env()

        # Simulate CLI passing additional enable features
        cli_enable = []
        cli_disable = []
        config.resolve_features(
            config._disable_features_raw + cli_disable,
            config._enable_features_raw + cli_enable,
        )

        # "save" is normally disabled by default, but env var enables it
        assert "save" in config.enabled_features
        # Other default-enabled features should still be present
        assert "stealth" in config.enabled_features
        assert "format" in config.enabled_features
        assert "pagination" in config.enabled_features
