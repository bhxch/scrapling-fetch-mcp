"""
Error handling tests for airead format
"""
import pytest
from pathlib import Path
import tempfile
import yaml
from scrapling_fetch_mcp._url_matcher import URLMatcher
from scrapling_fetch_mcp._strategy_factory import StrategyFactory


def test_yaml_parse_error_fallback():
    """Test fallback to built-in rules when YAML parsing fails"""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    try:
        f.write("invalid: yaml: content:\n  - broken [")
        f.flush()

        matcher = URLMatcher(Path(f.name))
        assert matcher.default_strategy == "dual"  # Should use built-in default
    finally:
        f.close()
        Path(f.name).unlink(missing_ok=True)


def test_custom_strategy_module_not_found():
    """Test handling of missing custom strategy module"""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
    try:
        config = {
            'custom_strategies': [{
                'name': 'test',
                'module': '/nonexistent/path.py',
                'class': 'TestStrategy'
            }]
        }
        yaml.dump(config, f)
        f.flush()

        # Should not crash, just log warning
        StrategyFactory.load_custom_strategies(Path(f.name))
        assert 'test' not in StrategyFactory.list_strategies()
    finally:
        f.close()
        Path(f.name).unlink(missing_ok=True)


def test_invalid_url_match():
    """Test handling of invalid URLs"""
    matcher = URLMatcher()

    # Empty URL
    result = matcher.match("")
    assert result == "dual"  # Should return default

    # Malformed URL
    result = matcher.match("not-a-url")
    assert result == "dual"


def test_unknown_strategy_name():
    """Test handling of unknown strategy names"""
    with pytest.raises(ValueError, match="Unknown strategy"):
        StrategyFactory.get_strategy('nonexistent_strategy')


def test_empty_html_extraction():
    """Test extraction with empty HTML"""
    from scrapling_fetch_mcp._extractor_strategy import TrafilaturaStrategy

    strategy = TrafilaturaStrategy()
    result = strategy.extract("", "https://example.com")
    assert result == ""  # Should handle gracefully


def test_malformed_html_extraction():
    """Test extraction with malformed HTML"""
    from scrapling_fetch_mcp._extractor_strategy import ReadabilityStrategy

    strategy = ReadabilityStrategy()
    result = strategy.extract("<html><body><div>unclosed", "https://example.com")
    assert isinstance(result, str)  # Should not crash


def test_url_matcher_config_not_found():
    """Test URLMatcher with non-existent config file"""
    matcher = URLMatcher(Path("/nonexistent/config.yaml"))
    assert matcher.default_strategy == "dual"  # Should use built-in rules
