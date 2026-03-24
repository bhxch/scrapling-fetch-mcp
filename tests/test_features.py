"""Feature registry consistency tests and feature resolution tests."""

import logging

from scrapling_fetch_mcp._features import FEATURES, TOOL_PARAMS
from scrapling_fetch_mcp._config import config


class TestFeatureRegistry:
    """Verify internal consistency of the feature registry."""

    def test_all_feature_references_valid(self):
        """Every feature name referenced in TOOL_PARAMS must exist in FEATURES.

        Params with feature=None are core params and are not checked.
        """
        valid_features = set(FEATURES.keys())
        for tool_name, params in TOOL_PARAMS.items():
            for param_name, param_def in params.items():
                feature = param_def["feature"]
                if feature is not None:
                    assert feature in valid_features, (
                        f"{tool_name}.{param_name} references unknown feature "
                        f"'{feature}'. Valid features: {valid_features}"
                    )

    def test_each_tool_has_core_params(self):
        """Every tool must have at least one core parameter (feature=None).

        Core parameters are always visible regardless of feature toggles.
        """
        for tool_name, params in TOOL_PARAMS.items():
            core_params = [
                name for name, pdef in params.items() if pdef["feature"] is None
            ]
            assert len(core_params) >= 1, (
                f"Tool '{tool_name}' has no core parameters. "
                f"Every tool needs at least one param with feature=None."
            )

    def test_all_params_have_required_fields(self):
        """Every parameter definition must contain all required metadata fields."""
        required_fields = {"type", "required", "default", "feature", "description"}
        for tool_name, params in TOOL_PARAMS.items():
            for param_name, param_def in params.items():
                missing = required_fields - set(param_def.keys())
                assert not missing, (
                    f"{tool_name}.{param_name} is missing required fields: {missing}"
                )


class TestResolveFeatures:
    """Verify Config.resolve_features() behavior."""

    def setup_method(self):
        """Reset Config singleton state before each test."""
        config._enabled_features = set()
        config._disable_features_raw = []
        config._enable_features_raw = []

    def test_defaults_match_spec(self):
        """resolve_features([], []) should enable stealth, format, pagination."""
        config.resolve_features([], [])
        assert config.enabled_features == {"stealth", "format", "pagination"}

    def test_disable_overrides_default(self):
        """Disabling a default-enabled feature should remove it."""
        config.resolve_features(["pagination"], [])
        assert "pagination" not in config.enabled_features
        assert "stealth" in config.enabled_features
        assert "format" in config.enabled_features

    def test_enable_overrides_default(self):
        """Enabling a default-disabled feature should add it."""
        config.resolve_features([], ["save"])
        assert "save" in config.enabled_features
        assert config.enabled_features == {"stealth", "format", "pagination", "save"}

    def test_enable_overrides_disable(self):
        """Enable should win over disable (enable > disable priority)."""
        config.resolve_features(["stealth"], ["stealth"])
        assert "stealth" in config.enabled_features

    def test_unknown_feature_ignored(self, caplog):
        """Unknown feature names should be logged as warnings and ignored."""
        with caplog.at_level(logging.WARNING):
            config.resolve_features(["nonexistent"], [])
        assert "Unknown feature 'nonexistent'" in caplog.text
        assert config.enabled_features == {"stealth", "format", "pagination"}

    def test_empty_lists_use_defaults(self):
        """Empty disable/enable lists should produce default feature set."""
        config.resolve_features([], [])
        assert config.enabled_features == {"stealth", "format", "pagination"}

    def test_all_features_disabled(self):
        """Disabling all features should produce an empty set."""
        config.resolve_features(
            ["stealth", "format", "pagination", "save"], []
        )
        assert config.enabled_features == set()

    def test_all_features_enabled(self):
        """Enabling all features should produce the full set."""
        config.resolve_features(
            [], ["stealth", "format", "pagination", "save"]
        )
        assert config.enabled_features == {"stealth", "format", "pagination", "save"}
