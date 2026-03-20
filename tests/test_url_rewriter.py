"""URL 重写器单元测试"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._url_rewriter import URLRewriter


class TestBasicRewrite:
    """基础重写功能测试"""

    def test_github_blob_to_raw(self):
        """GitHub blob URL 应该重写为 raw URL"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/README.md"
        expected = "https://raw.githubusercontent.com/user/repo/main/README.md"
        assert rewriter.rewrite(url) == expected

    def test_github_tree_not_rewritten(self):
        """GitHub tree URL 不应该重写"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/tree/main/docs"
        assert rewriter.rewrite(url) == url

    def test_github_already_raw(self):
        """已经是 raw 的 URL 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://raw.githubusercontent.com/user/repo/main/file.md"
        assert rewriter.rewrite(url) == url

    def test_duckduckgo_html_version(self):
        """DuckDuckGo 搜索应该重写为 html 版本"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/?q=python"
        expected = "https://duckduckgo.com/html/?q=python"
        assert rewriter.rewrite(url) == expected

    def test_duckduckgo_preserve_query_params(self):
        """DuckDuckGo 重写时应该保留查询参数"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/?q=python&kl=us-en"
        result = rewriter.rewrite(url)
        assert "/html/" in result
        assert "q=python" in result
        assert "kl=us-en" in result

    def test_duckduckgo_already_html(self):
        """已经是 html 版本的 DuckDuckGo 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/html/?q=python"
        assert rewriter.rewrite(url) == url

    def test_duckduckgo_www_prefix(self):
        """DuckDuckGo www 前缀也应该重写"""
        rewriter = URLRewriter()
        url = "https://www.duckduckgo.com/?q=python"
        result = rewriter.rewrite(url)
        assert "/html/" in result
        assert "q=python" in result
        assert "www.duckduckgo.com" not in result

    def test_reddit_old_version(self):
        """Reddit URL 应该重写为 old.reddit.com"""
        rewriter = URLRewriter()
        url = "https://www.reddit.com/r/python/comments/abc123/"
        expected = "https://old.reddit.com/r/python/comments/abc123/"
        assert rewriter.rewrite(url) == expected

    def test_reddit_already_old(self):
        """已经是 old.reddit.com 的 URL 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://old.reddit.com/r/python/"
        assert rewriter.rewrite(url) == url

    def test_reddit_bare_domain(self):
        """Reddit 裸域名（无 www 前缀）也应该重写"""
        rewriter = URLRewriter()
        url = "https://reddit.com/r/python/"
        result = rewriter.rewrite(url)
        assert "old.reddit.com" in result

    def test_stackoverflow_printer(self):
        """StackOverflow 问题应该重写为 StackPrinter"""
        rewriter = URLRewriter()
        url = "https://stackoverflow.com/questions/12345/some-title"
        result = rewriter.rewrite(url)
        assert "stackprinter.com" in result
        assert "question=12345" in result
        assert "service=stackoverflow" in result

    def test_no_match(self):
        """不匹配规则的 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "https://example.com/page"
        assert rewriter.rewrite(url) == url


class TestErrorHandling:
    """错误处理测试"""
    
    def test_invalid_url(self):
        """无效 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "not-a-valid-url"
        assert rewriter.rewrite(url) == url
    
    def test_missing_scheme(self):
        """缺少协议的 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "example.com/page"
        assert rewriter.rewrite(url) == url
    
    def test_unsupported_scheme(self):
        """不支持的协议应该保持不变"""
        rewriter = URLRewriter()
        url = "ftp://example.com/file"
        assert rewriter.rewrite(url) == url
    
    def test_config_file_not_found(self):
        """配置文件不存在时应该使用内置规则"""
        rewriter = URLRewriter(Path("/nonexistent/config.yaml"))
        url = "https://github.com/user/repo/blob/main/file.md"
        result = rewriter.rewrite(url)
        assert "raw.githubusercontent.com" in result


class TestEdgeCases:
    """边界情况测试"""
    
    def test_rewrite_idempotent(self):
        """重写应该是幂等的（多次重写结果相同）"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/file.md"
        result1 = rewriter.rewrite(url)
        result2 = rewriter.rewrite(result1)
        assert result1 == result2
    
    def test_preserve_fragment(self):
        """重写时应该保留 URL fragment"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/README.md#installation"
        result = rewriter.rewrite(url)
        assert "#installation" in result
        assert "raw.githubusercontent.com" in result
    
    def test_github_with_query_params(self):
        """GitHub URL 重写时保留查询参数"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/file.md?raw=true"
        result = rewriter.rewrite(url)
        assert "raw.githubusercontent.com" in result
        # regex_replace 尾部 .* 会捕获查询参数
        assert "?raw=true" in result or "&raw=true" in result