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