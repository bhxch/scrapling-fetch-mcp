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

    def test_disable_features_multiple_comma_separated(self, monkeypatch):
        """Comma-separated SCRAPLING_DISABLE_FEATURES are parsed into a list"""
        monkeypatch.setenv("SCRAPLING_DISABLE_FEATURES", "save,stealth")
        init_config_from_env()
        assert config._disable_features_raw == ["save", "stealth"]

    def test_enable_features_multiple_comma_separated(self, monkeypatch):
        """Comma-separated SCRAPLING_ENABLE_FEATURES are parsed into a list"""
        monkeypatch.setenv("SCRAPLING_ENABLE_FEATURES", "save,pagination")
        init_config_from_env()
        assert config._enable_features_raw == ["save", "pagination"]

    def test_cli_enable_overrides_env_disable(self, monkeypatch):
        """CLI enable overrides env disable for the same feature"""
        monkeypatch.setenv("SCRAPLING_DISABLE_FEATURES", "save")
        init_config_from_env()

        # Simulate CLI passing enable that conflicts with env disable
        config.resolve_features(
            config._disable_features_raw + ["stealth"],
            config._enable_features_raw + ["save", "stealth"],
        )

        # "save" is enabled via CLI despite being disabled via env
        assert "save" in config.enabled_features
        # "stealth" is enabled via CLI despite being disabled via CLI arg
        assert "stealth" in config.enabled_features

    def test_duplicate_features_in_disable_handled(self):
        """Duplicate features in disable list don't cause errors"""
        config.resolve_features(["save", "save"], [])
        assert "save" not in config.enabled_features

    def test_duplicate_features_in_enable_handled(self):
        """Duplicate features in enable list don't cause errors"""
        config.resolve_features([], ["save", "save"])
        assert "save" in config.enabled_features

    def test_empty_string_env_var_produces_empty_list(self, monkeypatch):
        """Empty string env var produces an empty list, not ['']"""
        monkeypatch.setenv("SCRAPLING_DISABLE_FEATURES", "")
        init_config_from_env()
        assert config._disable_features_raw == []

    def test_whitespace_in_env_var_trimmed(self, monkeypatch):
        """Whitespace around comma-separated feature names is stripped"""
        monkeypatch.setenv("SCRAPLING_ENABLE_FEATURES", " save , stealth ")
        init_config_from_env()
        assert config._enable_features_raw == ["save", "stealth"]
