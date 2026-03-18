import re
from abc import ABC, abstractmethod
import trafilatura
from readability import Document
from bs4 import BeautifulSoup
from scrapling import Selector


def count_effective_characters(text: str) -> int:
    """
    计算有效字符数(纯文本内容)

    移除 Markdown 标记和所有空白字符,统计剩余字符
    """
    if not text:
        return 0

    # 移除 Markdown 标记
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # 标题
    text = re.sub(r'\*\*|\*|__|_', '', text)  # 粗体/斜体
    text = re.sub(r'`+', '', text)  # 代码
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)  # 图片 (先处理)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 链接 (后处理)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  # 列表
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)  # 数字列表
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)  # 引用
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)  # 水平线

    # 移除所有空白字符
    text = re.sub(r'\s+', '', text)

    return len(text)


class ExtractorStrategy(ABC):
    """内容提取策略基类"""

    @abstractmethod
    def extract(self, html: str, url: str) -> str:
        """
        从 HTML 中提取核心内容并转换为 Markdown

        Args:
            html: 原始 HTML 内容
            url: 页面 URL(可用于策略内部判断)

        Returns:
            提取并格式化后的 Markdown 文本
        """
        pass


class TrafilaturaStrategy(ExtractorStrategy):
    """使用 trafilatura 提取内容"""

    def extract(self, html: str, url: str) -> str:
        result = trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown'
        )
        return result or ""


class ReadabilityStrategy(ExtractorStrategy):
    """使用 readability-lxml 提取内容"""

    def extract(self, html: str, url: str) -> str:
        doc = Document(html)
        clean_html = doc.summary()

        # 转换为 Markdown
        soup = BeautifulSoup(clean_html, 'html.parser')

        # 简单的 Markdown 转换(后续会使用统一的转换器)
        text = soup.get_text(separator='\n')
        return text.strip()


class ScraplingStrategy(ExtractorStrategy):
    """使用 Scrapling 内置的提取功能"""

    def extract(self, html: str, url: str) -> str:
        page = Selector(html)
        body = page.find('body')

        if body:
            # Scrapling 的文本提取
            text = body.get_all_text()
            return text.strip()

        return ""


class SearchEngineStrategy(ExtractorStrategy):
    """搜索引擎专用策略"""

    def extract(self, html: str, url: str) -> str:
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            favor_precision=True
        ) or ""


class DeveloperPlatformStrategy(ExtractorStrategy):
    """开发者平台专用策略"""

    def extract(self, html: str, url: str) -> str:
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            include_tables=True
        ) or ""


class DocumentationStrategy(ExtractorStrategy):
    """技术文档专用策略"""

    def extract(self, html: str, url: str) -> str:
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            favor_precision=True
        ) or ""


class DualExtractorStrategy(ExtractorStrategy):
    """三重提取器对比策略"""

    def extract(self, html: str, url: str) -> str:
        # 运行三个提取器
        trafilatura_strategy = TrafilaturaStrategy()
        readability_strategy = ReadabilityStrategy()
        scrapling_strategy = ScraplingStrategy()

        result_trafilatura = trafilatura_strategy.extract(html, url)
        result_readability = readability_strategy.extract(html, url)
        result_scrapling = scrapling_strategy.extract(html, url)

        # 对比有效字数
        results = [
            (count_effective_characters(result_trafilatura), result_trafilatura),
            (count_effective_characters(result_readability), result_readability),
            (count_effective_characters(result_scrapling), result_scrapling)
        ]

        # 返回字数最多的结果
        return max(results, key=lambda x: x[0])[1]
