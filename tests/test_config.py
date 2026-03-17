"""Tests for configuration"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._config import Config


class TestConfig:
    """Tests for Config class"""

    def test_default_scraping_dir(self):
        """Test default scraping directory"""
        config = Config()
        assert config.scraping_dir == Path(".temp/scrapling/")

    def test_set_scraping_dir(self):
        """Test setting scraping directory"""
        config = Config()
        custom_path = Path("/tmp/scraping")
        config.set_scraping_dir(custom_path)

        assert config.scraping_dir == custom_path

    def test_set_scraping_dir_string(self):
        """Test setting scraping directory with string"""
        config = Config()
        config.set_scraping_dir("/custom/path")

        assert config.scraping_dir == Path("/custom/path")

    def test_default_markdown_converter(self):
        """Test default markdown converter"""
        config = Config()
        # Reset to default for test isolation
        config._markdown_converter = "markitdown"
        assert config.markdown_converter == "markitdown"

    def test_set_markdown_converter(self):
        """Test setting markdown converter"""
        config = Config()
        config.set_markdown_converter("markdownify")

        assert config.markdown_converter == "markdownify"

    def test_set_invalid_markdown_converter(self):
        """Test setting invalid markdown converter raises error"""
        config = Config()
        with pytest.raises(ValueError, match="Invalid converter 'invalid_converter'"):
            config.set_markdown_converter("invalid_converter")
