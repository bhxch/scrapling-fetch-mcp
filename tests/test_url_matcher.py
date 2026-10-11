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

def test_builtin_rules_extended_sites():
    """扩展站点:新搜索引擎与常见技术社区的内置路由"""
    matcher = URLMatcher()

    # 搜索引擎
    assert matcher.match("https://search.brave.com/search?q=test") == "search_engine"
    assert matcher.match("https://www.startpage.com/sp/search?query=test") == "search_engine"
    assert matcher.match("https://searx.be/search?q=test") == "search_engine"

    # StackExchange 全家桶(含重写后的 StackPrinter)
    assert matcher.match("https://unix.stackexchange.com/questions/1/x") == "developer_platform"
    assert matcher.match("https://superuser.com/questions/1/x") == "developer_platform"
    assert matcher.match("https://serverfault.com/questions/1/x") == "developer_platform"
    assert matcher.match("https://askubuntu.com/questions/1/x") == "developer_platform"
    assert matcher.match(
        "https://www.stackprinter.com/export?question=1&service=unix") == "developer_platform"

    # 其他技术社区
    assert matcher.match("https://news.ycombinator.com/item?id=1") == "developer_platform"
    assert matcher.match("https://old.reddit.com/r/Python/comments/abc/t/") == "developer_platform"
    assert matcher.match("https://v2ex.com/t/1") == "developer_platform"
    assert matcher.match("https://www.infoq.cn/article/abc") == "developer_platform"
    assert matcher.match("https://www.infoq.com/article/abc") == "developer_platform"
    assert matcher.match("https://juejin.cn/post/1") == "developer_platform"
    assert matcher.match("https://blog.csdn.net/u1/article/details/1") == "developer_platform"
    assert matcher.match("https://www.cnblogs.com/t/p/1.html") == "developer_platform"
    assert matcher.match("https://www.zhihu.com/question/1") == "developer_platform"

def test_url_matcher_regex_match():
    """测试正则表达式匹配"""
    matcher = URLMatcher()

    matcher.rules = [{
        'match': {'type': 'regex', 'pattern': r'.*docs\.python\.org.*'},
        'strategy': 'documentation'
    }]

    assert matcher.match("https://docs.python.org/3/library/") == "documentation"
    assert matcher.match("https://docs.python.org/3/") == "documentation"

def test_builtin_rules_anchored_regex_no_substring_false_positive():
    """锚定 host 段的 regex 规则不应被子串误伤(L-1)。"""
    matcher = URLMatcher()

    # host 内含 "searx" 子串的第三方域不命中 search_engine
    assert matcher.match("https://notsearx.example.com/page") == "dual"
    # query 中含 reddit.com 的 URL 不命中 developer_platform
    assert matcher.match("https://example.com/?u=https://reddit.com/x") == "dual"

def test_builtin_rules_anchored_regex_positive_sites():
    """锚定后既有正向路由保持不变(涵盖裸域/www/old 等子域)。"""
    matcher = URLMatcher()

    assert matcher.match("https://search.brave.com/search?q=test") == "search_engine"
    assert matcher.match("https://www.startpage.com/sp/search?query=test") == "search_engine"
    assert matcher.match("https://searx.be/search?q=test") == "search_engine"
    assert matcher.match("https://searxng.site/search?q=test") == "search_engine"
    assert matcher.match("https://reddit.com/r/Python") == "developer_platform"
    assert matcher.match("https://www.reddit.com/r/Python") == "developer_platform"
    assert matcher.match("https://old.reddit.com/r/Python/comments/abc/t/") == "developer_platform"
    assert matcher.match("https://juejin.cn/post/1") == "developer_platform"
    assert matcher.match("https://www.infoq.cn/article/abc") == "developer_platform"
    assert matcher.match("https://www.infoq.com/article/abc") == "developer_platform"
    # github 的 searxng 仓库 path 不应被 searx 兜底规则误路由
    assert matcher.match("https://github.com/searxng/searxng") == "developer_platform"
