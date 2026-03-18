# tests/test_url_matcher.py
import pytest
from pathlib import Path
from scrapling_fetch_mcp._url_matcher import URLMatcher

def test_url_matcher_uses_builtin_rules_by_default():
    """测试默认使用内置规则"""
    matcher = URLMatcher()
    assert matcher.default_strategy == "dual"

def test_url_matcher_domain_match():
    """测试域名匹配"""
    matcher = URLMatcher()

    # 配置规则
    matcher.rules = [{
        'match': {'type': 'domain', 'pattern': 'github.com'},
        'strategy': 'developer_platform'
    }]

    assert matcher.match("https://github.com/user/repo") == "developer_platform"
    assert matcher.match("https://www.github.com/user/repo") == "developer_platform"
    assert matcher.match("https://docs.github.com") != "developer_platform"

def test_url_matcher_domain_suffix_smart_match():
    """测试智能域名后缀匹配"""
    matcher = URLMatcher()

    # 配置规则
    matcher.rules = [{
        'match': {'type': 'domain_suffix', 'pattern': '.google.com'},
        'strategy': 'search_engine'
    }]

    # .google.com 应该匹配 google.com 和 *.google.com
    assert matcher.match("https://google.com") == "search_engine"
    assert matcher.match("https://www.google.com") == "search_engine"
    assert matcher.match("https://mail.google.com") == "search_engine"

def test_url_matcher_regex_match():
    """测试正则表达式匹配"""
    matcher = URLMatcher()

    matcher.rules = [{
        'match': {'type': 'regex', 'pattern': r'.*docs\.python\.org.*'},
        'strategy': 'documentation'
    }]

    assert matcher.match("https://docs.python.org/3/library/") == "documentation"
    assert matcher.match("https://docs.python.org/3/") == "documentation"
