"""Pytest configuration and fixtures"""
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_html():
    """Sample HTML with images for testing"""
    return """
    <html>
        <body>
            <h1>Test Page</h1>
            <img src="https://example.com/logo.jpg" alt="Logo">
            <img src="https://cdn.example.com/banner.png" alt="Banner">
            <p>Some text content</p>
        </body>
    </html>
    """


@pytest.fixture
def sample_markdown():
    """Sample Markdown with images for testing"""
    return """# Test Page

![Logo](https://example.com/logo.jpg)

![Banner](https://cdn.example.com/banner.png)

Some text content
"""
