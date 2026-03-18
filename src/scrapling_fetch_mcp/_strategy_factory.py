import importlib.util
import sys
import logging
from pathlib import Path
from typing import Dict, Type, Optional
import yaml

from scrapling_fetch_mcp._extractor_strategy import (
    ExtractorStrategy,
    DualExtractorStrategy,
    TrafilaturaStrategy,
    ReadabilityStrategy,
    ScraplingStrategy,
    SearchEngineStrategy,
    DeveloperPlatformStrategy,
    DocumentationStrategy,
)


class StrategyFactory:
    """策略工厂：管理和创建提取策略实例"""

    _strategies: Dict[str, Type[ExtractorStrategy]] = {}
    _custom_loaded: bool = False

    @classmethod
    def register_builtin_strategies(cls):
        """注册所有内置策略"""
        cls._strategies = {
            'dual': DualExtractorStrategy,
            'trafilatura': TrafilaturaStrategy,
            'readability': ReadabilityStrategy,
            'scrapling': ScraplingStrategy,
            'search_engine': SearchEngineStrategy,
            'developer_platform': DeveloperPlatformStrategy,
            'documentation': DocumentationStrategy,
        }

    @classmethod
    def load_custom_strategies(cls, config_path: Optional[Path]):
        """从配置文件加载自定义策略"""
        if cls._custom_loaded or not config_path:
            return

        if not config_path.exists():
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logging.warning(f"Failed to load custom strategies config: {e}")
            return

        if not config or 'custom_strategies' not in config:
            return

        for custom in config['custom_strategies']:
            name = custom.get('name')
            module_path = custom.get('module')
            class_name = custom.get('class')

            if not all([name, module_path, class_name]):
                continue

            try:
                spec = importlib.util.spec_from_file_location(
                    f"custom_strategy_{name}",
                    module_path
                )
                if not spec or not spec.loader:
                    raise FileNotFoundError(f"Module not found: {module_path}")

                module = importlib.util.module_from_spec(spec)
                sys.modules[f"custom_strategy_{name}"] = module
                spec.loader.exec_module(module)

                strategy_class = getattr(module, class_name)

                if not issubclass(strategy_class, ExtractorStrategy):
                    logging.warning(
                        f"Custom strategy '{name}' must inherit from ExtractorStrategy"
                    )
                    continue

                cls._strategies[name] = strategy_class
                logging.info(f"Loaded custom strategy: {name}")

            except Exception as e:
                logging.warning(f"Failed to load custom strategy '{name}': {e}")
                continue

        cls._custom_loaded = True

    @classmethod
    def get_strategy(cls, name: str, config_path: Optional[Path] = None) -> ExtractorStrategy:
        """根据名称获取策略实例"""
        if not cls._strategies:
            cls.register_builtin_strategies()

        if config_path and not cls._custom_loaded:
            cls.load_custom_strategies(config_path)

        if name not in cls._strategies:
            raise ValueError(
                f"Unknown strategy: '{name}'. "
                f"Available strategies: {list(cls._strategies.keys())}"
            )

        return cls._strategies[name]()

    @classmethod
    def list_strategies(cls) -> list[str]:
        """列出所有可用的策略名称"""
        if not cls._strategies:
            cls.register_builtin_strategies()
        return list(cls._strategies.keys())
