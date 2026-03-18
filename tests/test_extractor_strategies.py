import pytest
from scrapling_fetch_mcp._extractor_strategy import count_effective_characters, ExtractorStrategy

def test_count_effective_characters_plain_text():
    """测试纯文本统计"""
    text = "Hello World"
    count = count_effective_characters(text)
    assert count == 10

def test_count_effective_characters_with_markdown():
    """测试 Markdown 标记移除"""
    markdown = "# Title\n\n**bold** and *italic*"
    count = count_effective_characters(markdown)
    assert count < len(markdown)
    assert count == len("Titleboldanditalic")

def test_count_effective_characters_with_links():
    """测试链接处理"""
    markdown = "[Click here](https://example.com)"
    count = count_effective_characters(markdown)
    assert count == len("Clickhere")

def test_count_effective_characters_with_lists():
    """测试列表标记移除"""
    markdown = "- Item 1\n- Item 2\n1. First\n2. Second"
    count = count_effective_characters(markdown)
    assert count == len("Item1Item2FirstSecond")

def test_count_effective_characters_empty():
    """测试空字符串"""
    count = count_effective_characters("")
    assert count == 0

def test_extractor_strategy_is_abstract():
    """测试策略基类是抽象的"""
    with pytest.raises(TypeError):
        ExtractorStrategy()
