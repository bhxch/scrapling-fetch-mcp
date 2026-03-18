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
    """搜索引擎专用策略 - 通用启发式方法，适用于Google/Bing/DuckDuckGo"""

    def extract(self, html: str, url: str) -> str:
        """
        从搜索引擎结果页面提取内容

        使用启发式方法，不依赖特定搜索引擎的DOM结构
        适用于 Google、Bing、DuckDuckGo 等
        """
        soup = BeautifulSoup(html, 'lxml')
        markdown_parts = []

        # 1. 提取 AI Overview / Featured Snippet（如果有）
        ai_content = self._extract_featured_content(soup)
        if ai_content:
            markdown_parts.append("## Featured Content\n\n")
            markdown_parts.append(ai_content)
            markdown_parts.append("\n\n")

        # 2. 提取搜索结果
        markdown_parts.append("## Search Results\n\n")
        results = self._extract_search_results(soup, url)

        for i, result in enumerate(results, 1):
            markdown_parts.append(f"### {i}. {result['title']}\n\n")

            if result['snippet']:
                markdown_parts.append(f"{result['snippet']}\n\n")

            # 添加可点击的链接（使用完整URL）
            markdown_parts.append(f"[查看原文]({result['url']})\n\n")
            markdown_parts.append("---\n\n")

        return ''.join(markdown_parts)

    def _extract_featured_content(self, soup):
        """
        提取精选内容（AI Overview、Featured Snippet等）
        简化版本：直接查找包含大段文本的特定容器
        """
        # 查找Google的AI Overview容器（使用启发式class名）
        for selector in ['div[data-content-feature]', 'div.IScJfd', 'div[data-sncf]']:
            elem = soup.select_one(selector)
            if elem:
                # 提取纯文本，去除重复
                text = elem.get_text(separator=' ', strip=True)
                # 清理多余空格
                text = ' '.join(text.split())
                # 限制长度
                if len(text) > 100:
                    return text[:800] + ('...' if len(text) > 800 else '')

        return None

    def _extract_search_results(self, soup, page_url):
        """
        提取搜索结果条目（通用启发式方法）

        策略：
        1. 通过h3/h2标签定位标题（所有搜索引擎都有）
        2. 向上查找包含标题和链接的容器
        3. 从容器中启发式提取：标题、URL、cite、snippet
        """
        results = []
        seen_urls = set()  # 去重

        # 查找所有h3和h2标签（搜索结果标题）
        # 优先h3（Google），然后h2（Bing）
        heading_tags = soup.find_all(['h3', 'h2'])

        for heading in heading_tags:
            title = heading.get_text(strip=True)

            # 跳过广告和无关内容
            if self._is_ad_or_noise(title):
                continue

            # 向上查找包含链接的容器
            container = self._find_result_container(heading)

            if not container:
                continue

            # 从容器中提取链接（支持http和协议相对URL）
            link = container.find('a', href=lambda x: x and (x.startswith('http') or x.startswith('//')))
            if not link:
                continue

            url = link.get('href')

            # 处理协议相对URL（DuckDuckGo使用）
            if url.startswith('//'):
                url = 'https:' + url

            # 去重
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # 跳过搜索引擎自己的链接（但允许重定向链接）
            # Bing使用ck/作为重定向，Google使用url，DuckDuckGo使用uddg
            if self._is_search_engine_search_page(url, page_url):
                continue

            # 对于搜索引擎重定向链接，尝试从cite获取真实URL
            real_url = self._extract_real_url(container, url)
            if real_url and real_url != url:
                url = real_url  # 使用真实URL

            # 提取cite（显示的URL）
            cite = self._extract_cite(container, url)

            # 提取snippet（摘要）
            snippet = self._extract_snippet(container, title)

            results.append({
                'title': title,
                'url': url,
                'cite': cite,
                'snippet': snippet
            })

        return results

    def _find_result_container(self, heading):
        """
        向上查找搜索结果的容器

        启发式规则：
        - 容器必须包含链接
        - 容器文本长度在200-1500字符之间（必须包含snippet）
        - 向上最多查找8层
        - 优先选择包含最多文本的容器
        """
        current = heading.parent
        candidates = []

        for level in range(8):
            if not current:
                break

            if current.name != 'div':
                current = current.parent
                continue

            # 检查是否包含链接（支持http和协议相对URL）
            if not current.find('a', href=lambda x: x and (x.startswith('http') or x.startswith('//'))):
                current = current.parent
                continue

            # 检查文本长度（必须足够大以包含snippet）
            text_len = len(current.get_text(strip=True))

            # 收集候选容器（放宽上限以适应Bing）
            if 150 < text_len < 2500:
                candidates.append({
                    'element': current,
                    'level': level,
                    'length': text_len
                })

            current = current.parent

        # 选择最佳容器：优先选择文本最长的（通常包含最完整的信息）
        if candidates:
            best = max(candidates, key=lambda x: x['length'])
            return best['element']

        return None

    def _extract_cite(self, container, url):
        """
        提取cite（显示的URL）

        启发式规则：
        1. 优先查找<cite>标签
        2. 清理Google的显示符号（› ›）及其周围的空格
        3. 返回干净的URL路径
        """
        # 1. 查找cite标签
        cite_elem = container.find('cite')
        if cite_elem:
            cite_text = cite_elem.get_text(strip=True)
            # 清理Google的显示符号 › › 及其周围的空格
            cite_text = re.sub(r'\s*[››]\s*', '/', cite_text)
            # 清理多余空格
            cite_text = ' '.join(cite_text.split())
            return cite_text

        # 2. 查找包含›的文本（可能是URL显示）
        for elem in container.find_all(['span', 'div']):
            text = elem.get_text(strip=True)
            if '›' in text and len(text) < 150 and ('http' in text or 'www.' in text):
                # 清理符号及空格
                text = re.sub(r'\s*[››]\s*', '/', text)
                text = ' '.join(text.split())
                return text

        # 3. 备选：从完整URL提取域名+路径
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return f"{parsed.netloc}{parsed.path}"
        except:
            return url

    def _extract_snippet(self, container, title):
        """
        提取snippet（摘要）

        策略：
        1. 优先查找专门的snippet标签（DuckDuckGo使用<a class="result__snippet">）
        2. 如果没有，使用启发式方法从容器文本中提取
        """
        # 1. 尝试查找专门的snippet标签（DuckDuckGo）
        snippet_elem = container.find('a', class_='result__snippet')
        if snippet_elem:
            # 获取文本，保留空格（使用separator=' '避免单词粘连）
            snippet = snippet_elem.get_text(separator=' ', strip=True)
            # 清理多余空格
            snippet = ' '.join(snippet.split())
            if snippet:
                return snippet[:400] + ('...' if len(snippet) > 400 else '')

        # 2. 查找其他常见的snippet类名
        for class_name in ['snippet', 'result-snippet', 'search-result__snippet']:
            snippet_elem = container.find(class_=class_name)
            if snippet_elem:
                snippet = snippet_elem.get_text(strip=True)
                if snippet:
                    return snippet[:400] + ('...' if len(snippet) > 400 else '')

        # 3. 启发式方法：从文本中提取
        all_text = container.get_text(separator='\n', strip=True)
        lines = [line.strip() for line in all_text.split('\n') if line.strip()]

        snippet_lines = []
        found_cite = False

        for line in lines:
            # 跳过标题（精确匹配或包含）
            if line == title or (len(title) > 10 and title in line):
                continue

            # 检测cite行（包含›符号或单独的URL）
            if ('›' in line and len(line) < 150) or (line.startswith('http') and '›' in line):
                found_cite = True
                continue

            # 跳过独立的URL（没有›）
            if line.startswith('http') and len(line) < 200 and ' ' not in line:
                continue

            # 跳过特殊噪音
            if line in ['Read more', 'Read more', 'People also ask', 'Related searches']:
                continue

            # 跳过过短的行（但保留日期行）
            if len(line) < 20 and not re.match(r'^\w+ \d{1,2}, \d{4}', line):
                continue

            # 保留这一行
            if found_cite and len(line) >= 20:  # cite之后的行才是snippet
                snippet_lines.append(line)

        # 合并所有snippet行
        if snippet_lines:
            snippet = ' '.join(snippet_lines)
            # 限制长度
            if len(snippet) > 400:
                snippet = snippet[:400] + '...'
            return snippet

        return ''

    def _is_search_engine_search_page(self, url, page_url):
        """
        判断是否是搜索引擎自己的搜索页面（需要跳过）
        但允许重定向链接（如bing.com/ck/, google.com/url）
        """
        # 只跳过搜索引擎自己的搜索页面，不跳过重定向链接
        search_page_patterns = [
            'google.com/search',
            'bing.com/search',
            'duckduckgo.com/?q',
            'yahoo.com/search'
        ]

        for pattern in search_page_patterns:
            if pattern in url:
                return True

        return False

    def _extract_real_url(self, container, redirect_url):
        """
        从容器中提取真实URL（处理搜索引擎重定向）

        策略：
        0. 从重定向链接提取（DuckDuckGo的uddg参数，Bing的ck参数）
        1. 从cite元素提取
        2. 从data-url属性提取
        3. 清理›符号
        """
        # 0. 从重定向URL提取真实URL（DuckDuckGo和Bing）
        if 'duckduckgo.com/l/' in redirect_url or 'bing.com/ck/' in redirect_url:
            try:
                from urllib.parse import urlparse, parse_qs, unquote

                parsed = urlparse(redirect_url)

                # DuckDuckGo: /l/?uddg=URL
                if 'uddg' in parsed.query:
                    params = parse_qs(parsed.query)
                    if 'uddg' in params:
                        real_url = unquote(params['uddg'][0])
                        if real_url.startswith('http'):
                            return real_url

                # Bing: /ck/a?!&&p=ENCODED_URL (base64或hex)
                # Bing的URL较难提取，使用备选方案
            except:
                pass

        # 1. 从cite元素提取
        cite_elem = container.find('cite')
        if cite_elem:
            cite_text = cite_elem.get_text(strip=True)
            # 清理Google的显示符号 › ›
            cite_text = re.sub(r'\s*[››]\s*', '/', cite_text)
            # 清理多余空格
            cite_text = ' '.join(cite_text.split())

            # 如果cite包含http，使用它
            if cite_text.startswith('http'):
                return cite_text

        # 2. 从data-url等属性提取
        for attr in ['data-url', 'data-u', 'u']:
            elem = container.find(attrs={attr: True})
            if elem:
                url = elem.get(attr)
                if url and url.startswith('http'):
                    return url

        # 3. 备选：返回原始URL
        return redirect_url

    def _is_ad_or_noise(self, title):
        """判断是否是广告或噪音"""
        noise_keywords = [
            'Sponsored',
            'Ad',
            'Advertisement',
            'People also search for',
            'Related searches',
            'Quick Settings',
            'Sign in',
            'Accessibility',
            'Feedback',
            'People also ask',
            'Images',
            'Videos',
            'News',
            'Shopping',
            'Maps'
        ]

        title_lower = title.lower()
        return any(keyword.lower() in title_lower for keyword in noise_keywords)


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
