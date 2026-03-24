"""Feature registry consistency tests."""

from scrapling_fetch_mcp._features import FEATURES, TOOL_PARAMS


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
