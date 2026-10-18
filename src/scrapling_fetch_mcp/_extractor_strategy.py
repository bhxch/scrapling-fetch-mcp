import base64
import re
from abc import ABC, abstractmethod
from urllib.parse import parse_qs, unquote, urlparse
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
        results = self._collect_results(soup, url)

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

    def _collect_results(self, soup, page_url):
        """依次尝试:Bing b_algo 结构通道 → 通用 heading 启发式通道。"""
        results = self._extract_bing_results(soup)
        if results:
            return results
        return self._extract_search_results(soup, page_url)

    def _extract_bing_results(self, soup):
        """Bing 新版布局:结果条目是 <li class="b_algo">,按结构直接提取。

        该布局下 h2 的父级链上没有落入文本窗口的 div,通用启发式会全部
        落空,因此优先走确定性选择器;链接为 bing.com/ck/a 重定向,需解码。
        """
        results = []
        seen_urls = set()

        for li in soup.select('li.b_algo'):
            heading = li.find(['h2', 'h3'])
            if not heading:
                continue
            title = heading.get_text(' ', strip=True)
            if self._is_ad_or_noise(title):
                continue

            link = li.find('a', href=self._has_result_href)
            if not link:
                continue

            url = self._normalize_result_url(link.get('href'))
            if 'bing.com/ck/' in url:
                real_url = self._extract_real_url(li, url)
                if real_url and real_url != url:
                    url = real_url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            snippet = ''
            p = li.find('p')
            if p:
                snippet = ' '.join(p.get_text(' ', strip=True).split())[:400]
            if not snippet:
                snippet = self._extract_snippet(li, title)

            results.append({
                'title': title,
                'url': url,
                'cite': self._extract_cite(li, url),
                'snippet': snippet
            })

        return results

    @staticmethod
    def _has_result_href(href):
        """结果链接的 href 形态:完整 URL、协议相对、Google 相对跳转。"""
        return bool(href) and (
            href.startswith('http')
            or href.startswith('//')
            or href.startswith('/goto?')
            or href.startswith('/url?')
        )

    def _normalize_result_url(self, href: str) -> str:
        """归一化结果链接为尽可能真实的 URL。

        - //example.com        → https://example.com
        - /url?q=<encoded>     → 解析 q 参数(旧版 Google 重定向)
        - /goto?url=<token>    → 服务端跟随 302(新版 Google 重定向,token
                                 为 Tink 加密的 protobuf,本地无法解码)
        失败时保留原始链接,由调用方继续使用。
        """
        if href.startswith('//'):
            return 'https:' + href

        if href.startswith('/goto?') or href.startswith('/url?'):
            absolute = 'https://www.google.com' + href
            params = parse_qs(urlparse(absolute).query)

            if href.startswith('/goto?'):
                token = params.get('url', [''])[0]
                if token:
                    real = self._follow_goto_redirect(token)
                    if real:
                        return real
                return absolute

            q = params.get('q', [''])[0]
            if q.startswith('http'):
                return q
            return absolute

        return href

    def _follow_goto_redirect(self, token: str, timeout: float = 5.0):
        """跟随 Google /goto 重定向获取真实 URL。

        token 由 Google 服务端签名加密且有时效,只能通过请求
        https://www.google.com/goto?url=<token> 读取 302 的 Location 头
        获得;必须使用 www 主机名(裸域会多一层 301)。任何失败都返回
        None,调用方回退为原始链接。
        """
        import urllib.error
        import urllib.request

        req = urllib.request.Request(
            f"https://www.google.com/goto?url={token}",
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:132.0) Gecko/20100101 Firefox/132.0"},
        )

        class _NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None

        try:
            with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
                # 非 3xx 响应(如 200)不包含目标信息
                return None
        except urllib.error.HTTPError as e:
            if e.code in (301, 302, 303, 307, 308):
                location = e.headers.get("Location")
                if location and location.startswith("http"):
                    return location
            return None
        except Exception:
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
        seen_urls = set()  # 去重(基于归一化后的 URL)
        seen_hrefs = set()  # 粗去重(基于原始 href,避免重复解析跳转)

        # 查找所有h3和h2标签（搜索结果标题）
        # 优先h3（Google），然后h2（Bing）
        heading_tags = soup.find_all(['h3', 'h2'])

        for heading in heading_tags:
            title = heading.get_text(' ', strip=True)

            # 跳过广告和无关内容
            if self._is_ad_or_noise(title):
                continue

            # 向上查找包含链接的容器
            container = self._find_result_container(heading)

            if not container:
                continue

            # 从容器中提取链接(支持完整 URL、协议相对 URL 和相对跳转)
            link = container.find('a', href=self._has_result_href)
            if not link:
                continue

            href = link.get('href')
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            # 归一化为真实 URL(协议相对、/url?q=、/goto?url= 等)
            url = self._normalize_result_url(href)

            # 跳过 Google 静态资源链接(视频缩略图等)
            if 'gstatic.com' in url:
                continue

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

            # 检查是否包含链接(支持完整 URL、协议相对 URL 和相对跳转)
            if not current.find('a', href=self._has_result_href):
                current = current.parent
                continue

            # 检查文本长度（必须足够大以包含snippet）
            text_len = len(current.get_text(strip=True))

            # 收集候选容器（放宽上限以适应Bing）
            if 150 < text_len < 2500:
                candidates.append({
                    'element': current,
                    'level': level,
                    'length': text_len,
                    # 罩住多条结果的外层列表容器(DuckDuckGo html 版、SearXNG
                    # 等)含多个标题,会让所有条目选中同一容器并坍缩成一条
                    'headings': len(current.find_all(['h3', 'h2'])),
                })

            current = current.parent

        if not candidates:
            return None

        # 优先"单标题"容器(一条结果一个标题);没有时回退旧行为取最长,
        # 避免对标题结构特殊的布局直接丢条目
        single = [c for c in candidates if c['headings'] <= 1]
        best = max(single or candidates, key=lambda x: x['length'])
        return best['element']

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

        策略（启发式方法，不依赖固定class名）：
        1. 尝试多组常见的snippet选择器（按优先级）
        2. 如果失败，查找容器内长文本div（不包含标题的）
        3. DuckDuckGo专用：result__snippet class
        4. 最后使用文本过滤方法
        """
        # 1. Google和多搜索引擎的snippet选择器（按优先级）
        snippet_selectors = [
            # Google常用选择器（class名可能变化，但特征稳定）
            {'attrs': {'data-sncf': '1'}},  # Google data属性
            {'attrs': {'role': 'text'}},     # role属性
            # CSS样式特征（Google使用webkit-line-clamp限制行数）
            {'style_pattern': 'webkit-line-clamp'},
        ]

        for selector in snippet_selectors:
            # 处理style_pattern选择器
            if 'style_pattern' in selector:
                for elem in container.find_all('div'):
                    style = elem.get('style', '')
                    if selector['style_pattern'] in style:
                        snippet = elem.get_text(separator=' ', strip=True)
                        snippet = ' '.join(snippet.split())
                        if snippet and len(snippet) > 20:
                            return snippet[:400] + ('...' if len(snippet) > 400 else '')
            else:
                # 普通属性选择器
                snippet_elem = container.find('div', **selector)
                if snippet_elem:
                    snippet = snippet_elem.get_text(separator=' ', strip=True)
                    snippet = ' '.join(snippet.split())
                    if snippet and len(snippet) > 20:
                        return snippet[:400] + ('...' if len(snippet) > 400 else '')

        # 2. DuckDuckGo专用：result__snippet class
        snippet_elem = container.find('a', class_='result__snippet')
        if snippet_elem:
            snippet = snippet_elem.get_text(separator=' ', strip=True)
            snippet = ' '.join(snippet.split())
            if snippet:
                return snippet[:400] + ('...' if len(snippet) > 400 else '')

        # 3. 通用方法：查找不包含标题的长文本div
        for div in container.find_all('div'):
            div_text = div.get_text(separator=' ', strip=True)
            # 跳过包含标题的div，且文本长度要足够
            if (len(div_text) > 40 and
                title not in div_text and
                not div.find('h3') and
                not div.find('h2')):
                snippet = ' '.join(div_text.split())
                if snippet:
                    return snippet[:400] + ('...' if len(snippet) > 400 else '')

        # 4. 最后备选：文本过滤方法
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
                parsed = urlparse(redirect_url)

                # DuckDuckGo: /l/?uddg=URL
                if 'uddg' in parsed.query:
                    params = parse_qs(parsed.query)
                    if 'uddg' in params:
                        real_url = unquote(params['uddg'][0])
                        if real_url.startswith('http'):
                            return real_url

                # Bing: /ck/a?...&u=a1<urlsafe_base64>(去 a1 前缀后补 padding 解码)
                match = re.search(r'[?&]u=a1([A-Za-z0-9_\-]+)', redirect_url)
                if match:
                    payload = match.group(1)
                    payload += '=' * (-len(payload) % 4)
                    decoded = base64.urlsafe_b64decode(payload).decode('utf-8', 'ignore')
                    if decoded.startswith('http'):
                        return decoded
            except Exception:
                pass

        # 1. 从cite元素提取
        cite_elem = container.find('cite')
        if cite_elem:
            cite_text = cite_elem.get_text(strip=True)
            # 清理Google的显示符号 › ›
            cite_text = re.sub(r'\s*[››]\s*', '/', cite_text)
            # 清理多余空格
            cite_text = ' '.join(cite_text.split())

            # 如果cite包含http，使用它；带省略号的cite是Google截断后的
            # 显示文本，拼不成可访问的URL，不能作为真实链接
            if (cite_text.startswith('http')
                    and '...' not in cite_text and '…' not in cite_text):
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

    # 噪音关键词按整词匹配,避免子串误杀(如 "Ad" 命中 "AI Mode" 中的 "ad")
    _NOISE_KEYWORDS = [
        'Sponsored',
        'Ad',
        'Ads',
        'Advertisement',
        'People also search for',
        'Related searches',
        'Quick Settings',
        'Sign in',
        'Accessibility',
        'Feedback',
        'People also ask',
        'Web results',
        'Images',
        'Videos',
        'News',
        'Shopping',
        'Maps'
    ]
    _NOISE_PATTERN = re.compile(
        r"\b(?:" + "|".join(re.escape(k) for k in _NOISE_KEYWORDS) + r")\b",
        re.IGNORECASE,
    )

    def _is_ad_or_noise(self, title):
        """判断是否是广告或噪音(整词匹配)"""
        return bool(self._NOISE_PATTERN.search(title))


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
