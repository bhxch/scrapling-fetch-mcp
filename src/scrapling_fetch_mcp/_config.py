"""Global configuration for scrapling-fetch-mcp"""

from os import getenv
from time import time
from typing import Any, Optional
from pathlib import Path

# Mode hierarchy: basic < stealth < max-stealth
MODE_LEVELS = {
    "basic": 0,
    "stealth": 1,
    "max-stealth": 2,
}


class PageCache:
    """Simple in-memory cache with TTL for page content"""

    def __init__(self, ttl_seconds: int = 300):
        self._cache: dict[str, tuple[str, float, Any]] = {}  # key -> (mode, timestamp, content)
        self._ttl = ttl_seconds

    def _make_key(self, url: str, mode: str) -> str:
        """Create cache key from URL and mode"""
        return f"{mode}:{url}"

    def get(self, url: str, mode: str) -> Optional[Any]:
        """Get cached page content if not expired"""
        key = self._make_key(url, mode)
        if key in self._cache:
            cached_mode, timestamp, content = self._cache[key]
            if time() - timestamp < self._ttl:
                return content
            else:
                # Remove expired entry
                del self._cache[key]
        return None

    def set(self, url: str, mode: str, content: Any) -> None:
        """Cache page content with current timestamp"""
        key = self._make_key(url, mode)
        self._cache[key] = (mode, time(), content)

    def clear_expired(self) -> int:
        """Remove all expired entries, return count of removed entries"""
        current_time = time()
        expired_keys = [
            key for key, (_, timestamp, _) in self._cache.items()
            if current_time - timestamp >= self._ttl
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)

    def clear_all(self) -> None:
        """Clear all cached entries"""
        self._cache.clear()


class Config:
    """Global configuration singleton"""

    _instance = None
    _min_mode: str = "stealth"
    _cache_ttl: int = 300  # Default 5 minutes
    _cache: Optional[PageCache] = None
    _scraping_dir: Path = Path(".temp/scrapling/")
    _markdown_converter: str = "markitdown"  # Default converter
    _rules_config_path: Optional[Path] = None  # airead 规则配置路径
    _default_format: str = "markdown"  # 默认输出格式

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def min_mode(self) -> str:
        """Get the minimum mode level"""
        return self._min_mode

    @property
    def cache_ttl(self) -> int:
        """Get cache TTL in seconds"""
        return self._cache_ttl

    @property
    def cache(self) -> PageCache:
        """Get or create the page cache"""
        if self._cache is None:
            self._cache = PageCache(self._cache_ttl)
        return self._cache

    @property
    def scraping_dir(self) -> Path:
        """Get the scraping directory"""
        return self._scraping_dir

    def set_min_mode(self, mode: str) -> None:
        """Set the minimum mode level from CLI or environment"""
        if mode not in MODE_LEVELS:
            raise ValueError(
                f"Invalid mode '{mode}'. Must be one of: {list(MODE_LEVELS.keys())}"
            )
        self._min_mode = mode

    def set_cache_ttl(self, ttl_seconds: int) -> None:
        """Set cache TTL in seconds"""
        if ttl_seconds < 0:
            raise ValueError("Cache TTL must be non-negative")
        self._cache_ttl = ttl_seconds
        # Recreate cache with new TTL
        self._cache = PageCache(self._cache_ttl)

    def set_scraping_dir(self, path: Path | str) -> None:
        """Set the scraping directory"""
        if isinstance(path, str):
            path = Path(path)
        self._scraping_dir = path

    @property
    def markdown_converter(self) -> str:
        """Get the markdown converter library name"""
        return self._markdown_converter

    def set_markdown_converter(self, converter: str) -> None:
        """Set the markdown converter from CLI or environment"""
        valid_converters = ["markitdown", "markdownify"]
        if converter not in valid_converters:
            raise ValueError(
                f"Invalid converter '{converter}'. Must be one of: {valid_converters}"
            )
        self._markdown_converter = converter

    @property
    def rules_config_path(self) -> Optional[Path]:
        """Get the airead rules configuration file path"""
        return self._rules_config_path

    def set_rules_config_path(self, path: Path | str | None) -> None:
        """Set the airead rules configuration file path"""
        if path is None:
            self._rules_config_path = None
        elif isinstance(path, str):
            self._rules_config_path = Path(path)
        else:
            self._rules_config_path = path

    @property
    def default_format(self) -> str:
        """Get the default format for fetch operations"""
        return self._default_format

    def set_default_format(self, format: str) -> None:
        """Set the default format from CLI or environment"""
        valid_formats = ["airead", "markdown", "html"]
        if format not in valid_formats:
            raise ValueError(f"Invalid format '{format}'. Must be one of: {valid_formats}")
        self._default_format = format

    def get_effective_mode(self, requested_mode: str) -> str:
        """
        Get the effective mode by comparing requested mode with minimum mode.
        Returns the higher of the two modes.
        """
        if requested_mode not in MODE_LEVELS:
            raise ValueError(
                f"Invalid mode '{requested_mode}'. Must be one of: {list(MODE_LEVELS.keys())}"
            )

        requested_level = MODE_LEVELS[requested_mode]
        min_level = MODE_LEVELS[self._min_mode]

        # Return the higher mode
        if requested_level >= min_level:
            return requested_mode
        else:
            return self._min_mode


# Global config instance
config = Config()


def init_config_from_env() -> None:
    """Initialize configuration from environment variables"""
    env_min_mode = getenv("SCRAPLING_MIN_MODE", "").lower()
    if env_min_mode and env_min_mode in MODE_LEVELS:
        config.set_min_mode(env_min_mode)

    env_cache_ttl = getenv("SCRAPLING_CACHE_TTL", "")
    if env_cache_ttl:
        try:
            ttl = int(env_cache_ttl)
            config.set_cache_ttl(ttl)
        except ValueError:
            pass  # Invalid value, use default

    # Load scraping_dir from environment
    env_scraping_dir = getenv("SCRAPING_DIR", "")
    if env_scraping_dir:
        config.set_scraping_dir(env_scraping_dir)

    # Load markdown_converter from environment
    env_markdown_converter = getenv("SCRAPLING_MARKDOWN_CONVERTER", "").lower()
    if env_markdown_converter:
        config.set_markdown_converter(env_markdown_converter)

    # Load rules_config_path from environment
    env_rules_config = getenv("SCRAPLING_RULES_CONFIG", "")
    if env_rules_config:
        config.set_rules_config_path(env_rules_config)

    # Load default_format from environment
    env_default_format = getenv("SCRAPLING_DEFAULT_FORMAT", "").lower()
    if env_default_format:
        try:
            config.set_default_format(env_default_format)
        except ValueError:
            pass  # Invalid value, use default
