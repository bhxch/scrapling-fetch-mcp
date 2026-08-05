"""Tests for configuration"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._config import Config, config, init_config_from_env


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


class TestTransportConfig:
    def setup_method(self):
        config._transport = "stdio"
        config._host = "127.0.0.1"
        config._port = 8000
        config._mcp_path = "/mcp"
        config._auth_token = ""
        config._max_concurrent = 5
        config._acquire_timeout = 30.0

    def test_defaults(self):
        assert config.transport == "stdio"
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.mcp_path == "/mcp"
        assert config.auth_token == ""
        assert config.max_concurrent == 5
        assert config.acquire_timeout == 30.0

    def test_set_transport_valid(self):
        config.set_transport("streamable-http")
        assert config.transport == "streamable-http"

    def test_set_transport_invalid(self):
        with pytest.raises(ValueError):
            config.set_transport("ws")

    def test_set_port_bounds(self):
        config.set_port(8080)
        assert config.port == 8080
        with pytest.raises(ValueError):
            config.set_port(0)
        with pytest.raises(ValueError):
            config.set_port(70000)

    def test_set_max_concurrent_invalid(self):
        with pytest.raises(ValueError):
            config.set_max_concurrent(0)

    def test_env_loads_transport_config(self, monkeypatch):
        monkeypatch.setenv("SCRAPLING_TRANSPORT", "streamable-http")
        monkeypatch.setenv("SCRAPLING_HOST", "0.0.0.0")
        monkeypatch.setenv("SCRAPLING_PORT", "9000")
        monkeypatch.setenv("SCRAPLING_MCP_PATH", "/api/mcp")
        monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "TOK")
        monkeypatch.setenv("SCRAPLING_MAX_CONCURRENT", "8")
        monkeypatch.setenv("SCRAPLING_ACQUIRE_TIMEOUT", "12.5")
        init_config_from_env()
        assert config.transport == "streamable-http"
        assert config.host == "0.0.0.0"
        assert config.port == 9000
        assert config.mcp_path == "/api/mcp"
        assert config.auth_token == "TOK"
        assert config.max_concurrent == 8
        assert config.acquire_timeout == 12.5
