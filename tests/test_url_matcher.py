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

def test_builtin_rules_route_duckduckgo_subdomains_to_search_engine():
    """内置规则应把 duckduckgo.com 及其子域(如 html.duckduckgo.com)路由到 search_engine"""
    matcher = URLMatcher()

    assert matcher.match("https://duckduckgo.com/?q=test") == "search_engine"
    assert matcher.match("https://www.duckduckgo.com/?q=test") == "search_engine"
    # URL 重写后的目标地址 html.duckduckgo.com 也应命中 search_engine
    assert matcher.match("https://html.duckduckgo.com/html/?q=test") == "search_engine"
    # 不应误伤其他域
    assert matcher.match("https://example.com/?q=test") == "dual"

def test_url_matcher_regex_match():
    """测试正则表达式匹配"""
    matcher = URLMatcher()

    matcher.rules = [{
        'match': {'type': 'regex', 'pattern': r'.*docs\.python\.org.*'},
        'strategy': 'documentation'
    }]

    assert matcher.match("https://docs.python.org/3/library/") == "documentation"
    assert matcher.match("https://docs.python.org/3/") == "documentation"
