"""Tests for configuration"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._config import (
    Config,
    PageCache,
    config,
    init_config_from_env,
)


def _fresh_config() -> Config:
    """重置配置单例的缓存相关字段后返回单例（沿用本文件的单例重置手法）"""
    cfg = Config()
    cfg._cache_ttl = 300
    cfg._cache = None
    cfg._cache_max_entries = 256
    return cfg


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


class TestJinaArbitrationConfig:
    """Jina 仲裁三项配置的 env 解析"""

    def setup_method(self):
        from scrapling_fetch_mcp._config import Config
        self._instance = Config()
        self._instance._jina_api_key = ""
        self._instance._jina_arbiter_disabled = False
        self._instance._jina_min_chars = 500

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("JINA_API_KEY", "jina_key_abc")
        init_config_from_env()
        assert config.jina_api_key == "jina_key_abc"

    def test_arbiter_disabled_from_env(self, monkeypatch):
        monkeypatch.setenv("SCRAPLING_DISABLE_JINA_ARBITER", "1")
        init_config_from_env()
        assert config.jina_arbiter_disabled is True

    def test_arbiter_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SCRAPLING_DISABLE_JINA_ARBITER", raising=False)
        init_config_from_env()
        assert config.jina_arbiter_disabled is False

    def test_min_chars_from_env(self, monkeypatch):
        monkeypatch.setenv("SCRAPLING_JINA_MIN_CHARS", "200")
        init_config_from_env()
        assert config.jina_min_chars == 200

    def test_min_chars_invalid_env_ignored(self, monkeypatch):
        monkeypatch.setenv("SCRAPLING_JINA_MIN_CHARS", "not-a-number")
        init_config_from_env()
        assert config.jina_min_chars == 500


def test_page_cache_max_entries_fifo_eviction():
    cache = PageCache(ttl_seconds=300, max_entries=3)
    for i in range(3): cache.set(f"u{i}", "basic", f"c{i}")
    cache.set("u3", "basic", "c3")          # 满:先 clear_expired 再 FIFO 逐出 u0
    assert cache.get("u0", "basic") is None
    assert cache.get("u3", "basic") == "c3"

def test_page_cache_max_entries_zero_disables_cache():
    """max_entries<=0 语义为禁用缓存:set 短路,get 恒 miss,_cache 保持空"""
    cache = PageCache(ttl_seconds=300, max_entries=0)
    cache.set("u", "basic", "c")
    assert cache.get("u", "basic") is None
    assert cache._cache == {}

def test_page_cache_live_key_update_no_eviction():
    """满缓存下更新已存在 live key:不逐出任何条目,且该 key 移到末尾"""
    cache = PageCache(ttl_seconds=300, max_entries=3)
    for i in range(3): cache.set(f"u{i}", "basic", f"c{i}")
    cache.set("u0", "basic", "c0-new")      # 更新 live key:计数不变,不触发逐出
    assert len(cache._cache) == 3
    assert list(cache._cache) == ["basic:u1", "basic:u2", "basic:u0"]
    assert cache.get("u0", "basic") == "c0-new"
    cache.set("u3", "basic", "c3")          # 只有新条目才逐出最旧(此时是 u1)
    assert cache.get("u1", "basic") is None
    assert cache.get("u3", "basic") == "c3"

def test_page_cache_evicts_expired_before_fifo():
    cache = PageCache(ttl_seconds=0, max_entries=2)   # ttl=0 → 立即过期
    cache.set("a", "basic", "1"); cache.set("b", "basic", "2")
    cache.set("c", "basic", "3")            # 全部已过期,应清空而非逐出
    assert cache.get("c", "basic") is None  # 且 c 已入缓存

def test_cache_max_entries_env(monkeypatch):
    monkeypatch.setenv("SCRAPLING_CACHE_MAX_ENTRIES", "16")
    cfg = _fresh_config()                    # 沿用该文件现有的单例重置手法
    init_config_from_env()
    assert cfg.cache_max_entries == 16

def test_pool_and_daemon_defaults_and_env(monkeypatch):
    # browser_pool 等字段自 Task 11 起被 _do_browse/worker status 运行期消费,
    # 单例泄漏会改变后续测试行为——测试结束必须还原(文件惯例的单例手法
    # 保留,只补还原步骤)
    cfg = _fresh_config()
    saved = (cfg._browser_pool, cfg._pool_max_sessions,
             cfg._daemon_dir, cfg._daemon_idle_timeout)
    try:
        assert cfg.browser_pool is False
        assert (cfg.pool_idle_ttl, cfg.pool_max_age, cfg.pool_max_sessions, cfg.pool_max_requests) == (300.0, 1800.0, 4, 50)
        assert cfg.daemon_idle_timeout == 600.0 and cfg.daemon_dir is None
        monkeypatch.setenv("SCRAPLING_BROWSER_POOL", "true")
        monkeypatch.setenv("SCRAPLING_POOL_MAX_SESSIONS", "2")
        monkeypatch.setenv("SCRAPLING_DAEMON_DIR", "/tmp/xyz")
        monkeypatch.setenv("SCRAPLING_DAEMON_IDLE_TIMEOUT", "60")
        init_config_from_env()
        assert cfg.browser_pool is True and cfg.pool_max_sessions == 2
        assert cfg.daemon_dir == Path("/tmp/xyz") and cfg.daemon_idle_timeout == 60.0
    finally:
        (cfg._browser_pool, cfg._pool_max_sessions,
         cfg._daemon_dir, cfg._daemon_idle_timeout) = saved

def test_pool_setter_validation():
    cfg = _fresh_config()
    with pytest.raises(ValueError): cfg.set_pool_idle_ttl(-1)
    with pytest.raises(ValueError): cfg.set_pool_max_sessions(0)
