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

def test_readability_strategy_outputs_markdown():
    """Readability 抽出的正文应经统一转换器输出 Markdown 而非纯文本"""
    html = """
    <html>
        <body>
            <article>
                <h1>Article Title</h1>
                <p>First paragraph with content.</p>
                <h2>Section</h2>
                <p>More text here.</p>
                <pre><code>print(1)</code></pre>
            </article>
        </body>
    </html>
    """
    result = ReadabilityStrategy().extract(html, "https://example.com")

    assert "# Article Title" in result
    assert "## Section" in result
    assert "```" in result  # 代码块围栏保留


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
from scrapling_fetch_mcp._search_engines import SearchEngineStrategy
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


# DualExtractorStrategy Tests
from scrapling_fetch_mcp._extractor_strategy import DualExtractorStrategy

def test_dual_extractor_selects_best():
    """测试 dual 策略选择最佳结果"""
    html = """
    <html>
        <body>
            <h1>Test</h1>
            <p>Content with enough text to be detected</p>
        </body>
    </html>
    """
    strategy = DualExtractorStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0

def test_dual_extractor_fallback():
    """测试 dual 策略的降级处理"""
    html = "<html><body></body></html>"
    strategy = DualExtractorStrategy()
    result = strategy.extract(html, "https://example.com")

    # 应该返回某个提取器的结果(即使是空字符串)
    assert isinstance(result, str)

def test_dual_extractor_tolerates_extractor_failure(monkeypatch):
    """单路提取器抛异常时 dual 应跳过该路,而不是整体失败"""
    from scrapling_fetch_mcp._extractor_strategy import ReadabilityStrategy

    def boom(self, html, url):
        raise RuntimeError("extractor crashed")

    monkeypatch.setattr(ReadabilityStrategy, "extract", boom)

    html = """
    <html>
        <body>
            <h1>Still Works</h1>
            <p>Surviving extractor output</p>
        </body>
    </html>
    """
    result = DualExtractorStrategy().extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Surviving extractor output" in result


# JinaReaderStrategy Tests
from scrapling_fetch_mcp._extractor_strategy import JinaReaderStrategy

JINA_RESPONSE = (
    "Title: Example Page\n"
    "URL Source: https://example.com/page\n"
    "Markdown Content:\n"
    "# Real Body\n\nparagraph text"
)


class _FakeCurlResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


def test_jina_strategy_parses_markdown_body(monkeypatch):
    """成功响应取 Markdown Content 之后的正文,丢弃元数据头"""
    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(url=url, headers=headers or {}, timeout=timeout)
        return _FakeCurlResponse(200, JINA_RESPONSE)

    monkeypatch.setattr("curl_cffi.requests.get", fake_get)
    result = JinaReaderStrategy().extract("<html>unused</html>", "https://example.com/page")

    assert result == "# Real Body\n\nparagraph text"
    assert captured["url"] == "https://r.jina.ai/https://example.com/page"  # URL 即输入,HTML 被忽略
    assert captured["timeout"] == JinaReaderStrategy.READER_TIMEOUT

def test_jina_strategy_sends_bearer_key(monkeypatch):
    """配置了 JINA_API_KEY 时携带 Bearer 头"""
    from scrapling_fetch_mcp._config import config

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers=headers or {})
        return _FakeCurlResponse(200, JINA_RESPONSE)

    monkeypatch.setattr("curl_cffi.requests.get", fake_get)
    original = config.jina_api_key
    try:
        config.set_jina_api_key("test-key-123")
        JinaReaderStrategy().extract("", "https://example.com")
    finally:
        config.set_jina_api_key(original)

    assert captured["headers"]["Authorization"] == "Bearer test-key-123"

def test_jina_strategy_rate_limited_returns_empty(monkeypatch):
    """429 等非 200 响应返回空串(仲裁场景自然落选,独立策略场景降级)"""
    monkeypatch.setattr(
        "curl_cffi.requests.get",
        lambda url, headers=None, timeout=None: _FakeCurlResponse(429, "rate limited"),
    )
    assert JinaReaderStrategy().extract("", "https://example.com") == ""

def test_jina_strategy_network_error_returns_empty(monkeypatch):
    """网络异常不外抛,返回空串"""
    def boom(url, headers=None, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("curl_cffi.requests.get", boom)
    assert JinaReaderStrategy().extract("", "https://example.com") == ""

def test_jina_strategy_missing_marker_returns_whole_body(monkeypatch):
    """格式漂移(找不到分隔标记)时退回整个响应体,不静默丢正文"""
    monkeypatch.setattr(
        "curl_cffi.requests.get",
        lambda url, headers=None, timeout=None: _FakeCurlResponse(200, "# Just markdown"),
    )
    assert JinaReaderStrategy().extract("", "https://example.com") == "# Just markdown"

def test_jina_strategy_is_remote():
    """remote 标志:管线据此跳过本地抓取"""
    assert getattr(JinaReaderStrategy(), "remote") is True

def test_factory_registers_jina():
    from scrapling_fetch_mcp._strategy_factory import StrategyFactory
    assert "jina" in StrategyFactory.list_strategies()
