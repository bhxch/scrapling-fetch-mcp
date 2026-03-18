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

    def test_markdown_converter_from_env(self, monkeypatch):
        """Test loading markdown converter from environment variable"""
        from scrapling_fetch_mcp._config import init_config_from_env, Config

        # Reset to default for test isolation
        config = Config()
        config._markdown_converter = "markitdown"

        # Set environment variable
        monkeypatch.setenv("SCRAPLING_MARKDOWN_CONVERTER", "markdownify")

        init_config_from_env()

        assert config.markdown_converter == "markdownify"


class TestDefaultFormat:
    """Tests for default format configuration"""

    def test_default_format_default(self):
        """Test default format is markdown"""
        config = Config()
        config._default_format = "markdown"  # Reset for isolation
        assert config.default_format == "markdown"

    def test_set_default_format(self):
        """Test setting valid format"""
        config = Config()
        config.set_default_format("airead")
        assert config.default_format == "airead"

    def test_set_default_format_html(self):
        """Test setting html format"""
        config = Config()
        config.set_default_format("html")
        assert config.default_format == "html"

    def test_set_default_format_invalid(self):
        """Test setting invalid format raises error"""
        config = Config()
        with pytest.raises(ValueError, match="Invalid format 'json'"):
            config.set_default_format("json")

    def test_default_format_from_env(self, monkeypatch):
        """Test loading default format from environment variable"""
        from scrapling_fetch_mcp._config import init_config_from_env, Config

        config = Config()
        config._default_format = "markdown"  # Reset

        monkeypatch.setenv("SCRAPLING_DEFAULT_FORMAT", "html")
        init_config_from_env()

        assert config.default_format == "html"

    def test_default_format_invalid_env_ignored(self, monkeypatch):
        """Test that invalid environment variable is ignored"""
        from scrapling_fetch_mcp._config import init_config_from_env, Config

        config = Config()
        config._default_format = "markdown"  # Reset

        monkeypatch.setenv("SCRAPLING_DEFAULT_FORMAT", "invalid")
        init_config_from_env()

        # Should remain default
        assert config.default_format == "markdown"
