import base64
import logging
import re
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, unquote, urlparse
import trafilatura
from readability import Document
from scrapling import Selector

from scrapling_fetch_mcp._config import config
from scrapling_fetch_mcp._html_converter import html_to_markdown

logger = logging.getLogger("scrapling_fetch_mcp")


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

        # readability 只负责圈定正文区块,Markdown 结构仍由统一转换器补全
        # (此前用 get_text() 输出纯文本,在 dual 字数对比中丢掉标题/列表/代码块)
        return html_to_markdown(clean_html).strip()


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
    """多重提取器对比策略"""

    def extract(self, html: str, url: str) -> str:
        # 运行多个提取器;单路失败不拖垮整体,该路计 0 分自然落选
        extractors = [
            ("trafilatura", TrafilaturaStrategy()),
            ("readability", ReadabilityStrategy()),
            ("scrapling", ScraplingStrategy()),
        ]

        results = []
        for name, strategy in extractors:
            try:
                result = strategy.extract(html, url)
            except Exception:
                logger.warning("dual: 提取器 %s 对 %s 抛出异常,按 0 分处理", name, url, exc_info=True)
                result = ""
            results.append((count_effective_characters(result), result))

        # 返回字数最多的结果
        return max(results, key=lambda x: x[0])[1]


class JinaReaderStrategy(ExtractorStrategy):
    """Jina Reader 远程抽取策略。

    忽略传入的本地 HTML,直接把 URL 交给 r.jina.ai 获取现成 Markdown
    (由 Jina 服务端完成渲染与正文抽取)。两条用途:
    - 站点规则显式指定 strategy: jina,作为纯远程通道
    - 作为 Jina 按需仲裁的仲裁者(本地结果可疑时才外发,见 _fetcher)
    """

    remote = True
    READER_TIMEOUT = 20  # 仲裁是附加延迟,不吃满 fetch_timeout
    CONTENT_MARKER = "Markdown Content:"  # r.jina.ai 默认文本格式的正文分隔

    def extract(self, html: str, url: str) -> str:
        # 局部导入:让不需要 Jina 的部署不被 curl_cffi 初始化路径牵连
        from curl_cffi import requests as curl_requests

        headers = {}
        api_key = config.jina_api_key
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            resp = curl_requests.get(
                f"https://r.jina.ai/{url}",
                headers=headers,
                timeout=self.READER_TIMEOUT,
            )
        except Exception:
            logger.warning("jina reader 请求失败: %s", url, exc_info=True)
            return ""

        if resp.status_code != 200:
            logger.warning("jina reader 返回 %s: %s", resp.status_code, url)
            return ""

        text = resp.text or ""
        idx = text.find(self.CONTENT_MARKER)
        # 找不到分隔标记时退回整个响应体:格式漂移好过静默丢失正文
        body = text[idx + len(self.CONTENT_MARKER):] if idx >= 0 else text
        return body.strip()
