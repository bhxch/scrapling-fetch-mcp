# src/scrapling_fetch_mcp/_url_matcher.py
import re
import yaml
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from urllib.parse import urlparse

class URLMatcher:
    """根据配置规则匹配 URL 到策略"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.rules: List[Dict[str, Any]] = []
        self.default_strategy = "dual"
        self._last_load_time = 0
        self._load_config()

    def _load_config(self) -> None:
        """加载配置文件"""
        if self.config_path is None:
            # 使用内置默认规则
            from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
            config = yaml.safe_load(DEFAULT_RULES)
        else:
            if not self.config_path.exists():
                # 文件不存在，使用内置规则
                from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
                config = yaml.safe_load(DEFAULT_RULES)
                return

            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logging.warning(f"Failed to parse YAML config: {e}. Using default rules.")
                from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
                config = yaml.safe_load(DEFAULT_RULES)

        if config:
            self.default_strategy = config.get('default_strategy', 'dual')
            self.rules = config.get('url_rules', [])

    def match(self, url: str) -> str:
        """根据 URL 匹配对应的策略名称"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()

        for rule in self.rules:
            match_config = rule.get('match', {})
            match_type = match_config.get('type')
            pattern = match_config.get('pattern')

            if self._match_url(domain, url, match_type, pattern):
                return rule.get('strategy', self.default_strategy)

        return self.default_strategy

    def _match_url(self, domain: str, full_url: str,
                   match_type: str, pattern: str) -> bool:
        """执行 URL 匹配"""
        if match_type == 'domain':
            # 完整域名匹配（支持 www. 前缀）
            return domain == pattern or domain == f"www.{pattern}"

        elif match_type == 'domain_suffix':
            # 智能域名后缀匹配
            if pattern.startswith('.'):
                # 模式是 ".google.com"
                # 匹配 "google.com" 或 "*.google.com"
                base_domain = pattern[1:]
                return domain == base_domain or domain.endswith(pattern)
            else:
                # 模式是 "google.com"
                # 只精确匹配
                return domain == pattern

        elif match_type == 'regex':
            # 正则表达式匹配
            try:
                return bool(re.search(pattern, full_url))
            except re.error:
                return False

        return False
