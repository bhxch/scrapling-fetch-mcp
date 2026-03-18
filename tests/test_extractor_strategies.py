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

def test_count_effective_characters_with_images():
    """测试图片标记移除"""
    markdown = "![Alt text](https://example.com/image.png)"
    count = count_effective_characters(markdown)
    assert count == len("Alttext")

def test_count_effective_characters_with_code():
    """测试代码标记移除"""
    markdown = "`inline code` and ```code block```"
    count = count_effective_characters(markdown)
    assert count == len("inlinecodeandcodeblock")

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


# TrafilaturaStrategy Tests
from scrapling_fetch_mcp._extractor_strategy import TrafilaturaStrategy

def test_trafilatura_strategy_basic():
    """测试 Trafilatura 基本提取"""
    html = """
    <html>
        <body>
            <h1>Title</h1>
            <p>Content paragraph</p>
        </body>
    </html>
    """
    strategy = TrafilaturaStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Title" in result or "Content" in result

def test_trafilatura_strategy_removes_navigation():
    """测试导航元素移除"""
    html = """
    <html>
        <body>
            <nav><a href="#">Nav Link</a></nav>
            <main>
                <h1>Main Content</h1>
                <p>Important text</p>
            </main>
        </body>
    </html>
    """
    strategy = TrafilaturaStrategy()
    result = strategy.extract(html, "https://example.com")

    assert "Main Content" in result
    assert "Important text" in result


# ReadabilityStrategy Tests
from scrapling_fetch_mcp._extractor_strategy import ReadabilityStrategy

def test_readability_strategy_basic():
    """测试 Readability 基本提取"""
    html = """
    <html>
        <body>
            <h1>Article Title</h1>
            <p>Article content here</p>
        </body>
    </html>
    """
    strategy = ReadabilityStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0


# ScraplingStrategy Tests
from scrapling_fetch_mcp._extractor_strategy import ScraplingStrategy

def test_scrapling_strategy_basic():
    """测试 Scrapling 提取"""
    html = """
    <html>
        <body>
            <h1>Test Page</h1>
            <p>Some content</p>
        </body>
    </html>
    """
    strategy = ScraplingStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0


# Specialized Strategies Tests
from scrapling_fetch_mcp._extractor_strategy import SearchEngineStrategy
from scrapling_fetch_mcp._extractor_strategy import DeveloperPlatformStrategy
from scrapling_fetch_mcp._extractor_strategy import DocumentationStrategy

def test_search_engine_strategy_basic():
    """测试搜索引擎专用策略"""
    html = """
    <html>
        <body>
            <h1>Search Results</h1>
            <div class="result"><a href="/link1">Result 1</a></div>
        </body>
    </html>
    """
    strategy = SearchEngineStrategy()
    result = strategy.extract(html, "https://google.com/search?q=test")

    assert isinstance(result, str)

def test_developer_platform_strategy_basic():
    """测试开发者平台专用策略"""
    html = """
    <html>
        <body>
            <h1>GitHub Repo</h1>
            <table><tr><td>Stars</td><td>100</td></tr></table>
        </body>
    </html>
    """
    strategy = DeveloperPlatformStrategy()
    result = strategy.extract(html, "https://github.com/user/repo")

    assert isinstance(result, str)

def test_documentation_strategy_basic():
    """测试文档专用策略"""
    html = """
    <html>
        <body>
            <h1>API Reference</h1>
            <p>Documentation content</p>
        </body>
    </html>
    """
    strategy = DocumentationStrategy()
    result = strategy.extract(html, "https://docs.python.org/3/library/functions.html")

    assert isinstance(result, str)
