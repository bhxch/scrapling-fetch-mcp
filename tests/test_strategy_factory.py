import pytest
from scrapling_fetch_mcp._strategy_factory import StrategyFactory
from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy


def test_list_strategies():
    """测试列出所有策略"""
    strategies = StrategyFactory.list_strategies()

    assert 'dual' in strategies
    assert 'trafilatura' in strategies
    assert 'readability' in strategies
    assert 'scrapling' in strategies
    assert 'search_engine' in strategies
    assert 'developer_platform' in strategies
    assert 'documentation' in strategies


def test_get_strategy_dual():
    """测试获取 dual 策略"""
    strategy = StrategyFactory.get_strategy('dual')
    assert isinstance(strategy, ExtractorStrategy)


def test_get_strategy_unknown():
    """测试获取未知策略"""
    with pytest.raises(ValueError, match="Unknown strategy"):
        StrategyFactory.get_strategy('nonexistent')
