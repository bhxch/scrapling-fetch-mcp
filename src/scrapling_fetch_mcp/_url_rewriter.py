# src/scrapling_fetch_mcp/_url_rewriter.py
"""URL 重写器"""
import re
import logging
from typing import Optional, Dict, List, Any
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("scrapling_fetch_mcp")


class URLRewriter:
    """URL 重写器，支持内置规则和自定义配置"""

    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化重写器，加载规则

        Args:
            config_path: 自定义规则配置文件路径（可选）
        """
        self.config_path = config_path
        self.custom_rules: List[Dict[str, Any]] = []
        self.builtin_rules: List[Dict[str, Any]] = []

        self._load_rules()

    def _load_rules(self) -> None:
        """加载重写规则（内置 + 自定义）"""
        from scrapling_fetch_mcp._default_rewrite_rules import BUILTIN_REWRITE_RULES
        self.builtin_rules = BUILTIN_REWRITE_RULES

        if self.config_path and self.config_path.exists():
            self._load_custom_rules()

    def _load_custom_rules(self) -> None:
        """从配置文件加载自定义规则"""
        try:
            import yaml
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config and 'url_rewrite_rules' in config:
                    self.custom_rules = config['url_rewrite_rules']
                    logger.info(f"Loaded {len(self.custom_rules)} custom rewrite rules")
        except Exception as e:
            logger.warning(f"Failed to load custom rewrite rules: {e}")

    def _is_valid_url(self, url: str) -> bool:
        """验证 URL 格式是否有效"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            if parsed.scheme not in ('http', 'https'):
                return False
            return True
        except Exception:
            return False

    def _match_url(self, url: str, match_config: Dict[str, str]) -> bool:
        """检查 URL 是否匹配规则"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()

        match_type = match_config.get('type')
        pattern = match_config.get('pattern', '')

        if match_type == 'domain':
            return domain == pattern or domain == f"www.{pattern}"

        elif match_type == 'domain_suffix':
            if pattern.startswith('.'):
                base_domain = pattern[1:]
                return domain == base_domain or domain.endswith(pattern)
            else:
                return domain == pattern

        elif match_type == 'regex':
            try:
                return bool(re.search(pattern, url))
            except re.error:
                logger.error(f"Invalid regex pattern: {pattern}")
                return False

        return False

    def _find_matching_rule(self, url: str) -> Optional[Dict[str, Any]]:
        """查找匹配的重写规则，优先级：自定义规则 > 内置规则"""
        for rule in self.custom_rules:
            if self._match_url(url, rule.get('match', {})):
                return rule
        for rule in self.builtin_rules:
            if self._match_url(url, rule.get('match', {})):
                return rule
        return None

    def _apply_rule(self, url: str, rule: Dict[str, Any]) -> str:
        """应用重写规则"""
        rewrite_config = rule.get('rewrite', {})
        rewrite_type = rewrite_config.get('type')

        if rewrite_type == 'none':
            return url

        elif rewrite_type == 'regex_replace':
            pattern = rewrite_config.get('pattern', '')
            replacement = rewrite_config.get('replacement', '')
            try:
                return re.sub(pattern, replacement, url)
            except re.error as e:
                logger.error(f"Regex substitution failed: {e}")
                return url

        elif rewrite_type == 'domain_replace':
            old_domain = rewrite_config.get('old', '')
            new_domain = rewrite_config.get('new', '')
            return url.replace(old_domain, new_domain, 1)

        elif rewrite_type == 'path_prefix':
            prefix = rewrite_config.get('prefix', '')
            parsed = urlparse(url)
            new_path = prefix + parsed.path
            return parsed._replace(path=new_path).geturl()

        return url

    def rewrite(self, url: str) -> str:
        """重写 URL（如果匹配规则），支持链式重写（最多 3 次）"""
        try:
            if not self._is_valid_url(url):
                logger.warning(f"Invalid URL format: {url}")
                return url

            max_iterations = 3
            current_url = url

            for iteration in range(max_iterations):
                rule = self._find_matching_rule(current_url)
                if not rule:
                    return current_url

                rewritten = self._apply_rule(current_url, rule)

                if rewritten == current_url:
                    return current_url

                current_url = rewritten

            logger.warning(f"Max rewrite iterations ({max_iterations}) reached for URL: {url}")
            return current_url

        except Exception as e:
            logger.error(f"URL rewrite failed for {url}: {e}")
            return url
