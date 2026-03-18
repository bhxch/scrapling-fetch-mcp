# tests/test_default_rules.py
from scrapling_fetch_mcp._default_rules import DEFAULT_RULES

def test_default_rules_not_empty():
    """测试默认规则不为空"""
    assert DEFAULT_RULES
    assert len(DEFAULT_RULES) > 0

def test_default_rules_valid_yaml():
    """测试默认规则是有效 YAML"""
    import yaml
    config = yaml.safe_load(DEFAULT_RULES)

    assert 'default_strategy' in config
    assert 'url_rules' in config