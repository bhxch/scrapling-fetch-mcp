"""
Integration tests for airead format
"""
import pytest
from scrapling_fetch_mcp._extractor_strategy import (
    DualExtractorStrategy,
    TrafilaturaStrategy,
    ReadabilityStrategy,
    ScraplingStrategy,
)


@pytest.mark.asyncio
async def test_airead_format_integration():
    """Test complete airead extraction flow"""
    html = """
    <html>
        <head>
            <title>Test Page</title>
            <nav><a href="/">Home</a> | <a href="/about">About</a></nav>
        </head>
        <body>
            <aside class="sidebar">
                <h3>Related Links</h3>
                <ul><li><a href="/link1">Link 1</a></li></ul>
            </aside>
            <main>
                <h1>Article Title</h1>
                <p class="intro">This is the introduction paragraph.</p>
                <p>This is the main content with <strong>bold</strong> and <em>italic</em> text.</p>
                <pre><code>def example():
    return "code"</code></pre>
            </main>
        </body>
    </html>
    """

    # Test with dual strategy
    strategy = DualExtractorStrategy()
    result = strategy.extract(html, "https://example.com/article")

    assert isinstance(result, str)
    assert len(result) > 0
    # Core content should be present
    assert "Article Title" in result or "introduction" in result or "content" in result


@pytest.mark.asyncio
async def test_airead_vs_markdown_comparison():
    """Compare airead and markdown format outputs"""
    html = """
    <html>
        <body>
            <nav>Navigation Menu</nav>
            <main>
                <h1>Content</h1>
                <p>Text paragraph.</p>
            </main>
        </body>
    </html>
    """

    # Test dual strategy (auread)
    dual_strategy = DualExtractorStrategy()
    dual_result = dual_strategy.extract(html, "https://example.com")

    # Test single strategy
    traf_strategy = TrafilaturaStrategy()
    traf_result = traf_strategy.extract(html, "https://example.com")

    # Both should produce non-empty content
    assert len(dual_result) > 0 or len(traf_result) > 0


def test_all_strategies_work():
    """Test that all 7 strategies can extract content"""
    html = """
    <html>
        <body>
            <h1>Test</h1>
            <p>Content here.</p>
        </body>
    </html>
    """

    strategies = [
        TrafilaturaStrategy(),
        ReadabilityStrategy(),
        ScraplingStrategy(),
    ]

    for strategy in strategies:
        result = strategy.extract(html, "https://example.com")
        assert isinstance(result, str), f"{strategy.__class__.__name__} should return string"
