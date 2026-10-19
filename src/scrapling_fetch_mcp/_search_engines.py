"""搜索引擎结果页(SERP)提取的适配器层。

各引擎的 SERP DOM 差异很大:DuckDuckGo html 版有十年未变的语义 class
(a.result__a),SearXNG 是规整的 article.result > h3 > a,Bing 有结构化
的 li.b_algo,Google 则 class 混淆、只能靠 h3 锚点启发式。按引擎写适配
器,确定性选择器优先,通用 heading 启发式只做兜底。

对外入口仍是 SearchEngineStrategy(接口不变):按 page_url 挑选适配器,
统一做噪音过滤、去重和 Markdown 渲染。
"""
import base64
import re
from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

# 广告类词:标题中出现(整词)即视为广告
_NOISE_KEYWORDS = ['Sponsored', 'Ad', 'Ads', 'Advertisement']
_NOISE_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(k) for k in _NOISE_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# 界面区块词:News/Videos/Images 等是普通英文词,出现在真实结果标题里
# 很常见,仅当标题本身就是这个词(即导航标签被当成标题)时才剔除
_UI_NOISE_TITLES = {
    'people also search for', 'related searches', 'quick settings',
    'sign in', 'accessibility', 'feedback', 'people also ask',
    'web results', 'images', 'videos', 'news', 'shopping', 'maps',
    '网页搜索结果',
}


def is_noise_title(title: str) -> bool:
    """标题是否为广告或界面噪音"""
    if _NOISE_PATTERN.search(title):
        return True
    return title.strip().lower() in _UI_NOISE_TITLES


def is_internal_search_page(url: str) -> bool:
    """是否为搜索引擎自己的搜索页(需跳过;重定向链接不受影响)"""
    return any(p in url for p in (
        'google.com/search', 'bing.com/search',
        'duckduckgo.com/?q', 'yahoo.com/search',
    ))


def has_result_href(href) -> bool:
    """结果链接的 href 形态:完整 URL、协议相对、Google 相对跳转。"""
    return bool(href) and (
        href.startswith('http')
        or href.startswith('//')
        or href.startswith('/goto?')
        or href.startswith('/url?')
    )


def clean_ws(text: str) -> str:
    """压缩全部空白为单空格"""
    return ' '.join(text.split())


def clamp(text: str, limit: int = 400) -> str:
    return text[:limit] + ('...' if len(text) > limit else '')


def _netloc(page_url: str) -> str:
    try:
        return urlparse(page_url).netloc.lower()
    except ValueError:
        return ''


# SERP 提取 0 条时的反爬拦截信号。来源:Google sorry/unusual traffic
# 经典信号,与实测拦截页样本文本(Anubis 质询、Brave 人机检查、
# Cloudflare/通用浏览器检查)。仅小写子串匹配,且只在结果为空时判定。
_INTERCEPTION_PATTERNS = [
    'recaptcha', 'unusual traffic', 'captcha-form', 'g-recaptcha',
    "verifying you're not a bot", "verifying you’re not a bot",
    'verifying your browser', 'checking your browser',
    "making sure you're not a bot", 'making sure you’re not a bot',
    'just a moment', 'attention required', 'confirm you are human',
    'verify you are human', 'are you a robot', 'security check',
]


def detect_interception(html: str, soup: BeautifulSoup) -> Optional[str]:
    """结果为空时判断是否被反爬/验证码拦截,返回可读原因;无信号返回 None。

    正常但无结果的 SERP 不应命中(信号词不会出现在"无结果"提示页),
    误报影响也有限:0 条前提下提示"换引擎重试"不会误导模型。
    """
    if not html:
        return '返回内容为空'

    low = html.lower()
    title = soup.title.get_text(strip=True).lower() if soup.title else ''

    signals = []
    if soup.select_one(
            '#captcha-form, #challenge-form, iframe[src*="recaptcha"], iframe[src*="captcha"]'):
        signals.append('验证码表单元素')
    for pattern in _INTERCEPTION_PATTERNS:
        if pattern in low:
            signals.append(pattern)
    if any(w in title for w in ('sorry', 'captcha', 'verify', 'checking')):
        signals.append(f'title="{title[:40]}"')
    if signals:
        return '、'.join(dict.fromkeys(signals[:4]))
    if len(html) < 3000:
        return '返回内容过短'
    return None


def _host_matches(page_url: str, domain: str) -> bool:
    netloc = _netloc(page_url)
    return netloc == domain or netloc.endswith('.' + domain)


def follow_goto_redirect(token: str, timeout: float = 5.0):
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


def normalize_google_href(href: str) -> str:
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
                real = follow_goto_redirect(token)
                if real:
                    return real
            return absolute

        q = params.get('q', [''])[0]
        if q.startswith('http'):
            return q
        return absolute

    return href


def resolve_real_url(container, redirect_url: str) -> str:
    """从条目容器提取真实 URL(处理搜索引擎重定向)。

    - DuckDuckGo: /l/?uddg=<encoded>
    - Bing: /ck/a?...&u=a1<urlsafe_base64>(去 a1 前缀后补 padding 解码)
    - cite 元素、data-url 等属性
    解析失败返回原重定向链接。
    """
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

            # Bing: /ck/a?...&u=a1<base64>
            match = re.search(r'[?&]u=a1([A-Za-z0-9_\-]+)', redirect_url)
            if match:
                payload = match.group(1)
                payload += '=' * (-len(payload) % 4)
                decoded = base64.urlsafe_b64decode(payload).decode('utf-8', 'ignore')
                if decoded.startswith('http'):
                    return decoded
        except Exception:
            pass

    # cite 元素
    cite_elem = container.find('cite')
    if cite_elem:
        cite_text = clean_ws(re.sub(r'\s*[››]\s*', '/', cite_elem.get_text(strip=True)))
        # 带省略号的 cite 是 Google 截断后的显示文本,拼不成可访问的URL
        if (cite_text.startswith('http')
                and '...' not in cite_text and '…' not in cite_text):
            return cite_text

    # data-url 等属性
    for attr in ['data-url', 'data-u', 'u']:
        elem = container.find(attrs={attr: True})
        if elem:
            url = elem.get(attr)
            if url and url.startswith('http'):
                return url

    return redirect_url


def extract_cite(container, url: str) -> str:
    """提取 cite(向用户展示的 URL 路径)"""
    cite_elem = container.find('cite')
    if cite_elem:
        cite_text = clean_ws(re.sub(r'\s*[››]\s*', '/', cite_elem.get_text(strip=True)))
        return cite_text

    for elem in container.find_all(['span', 'div']):
        text = elem.get_text(strip=True)
        if '›' in text and len(text) < 150 and ('http' in text or 'www.' in text):
            return clean_ws(re.sub(r'\s*[››]\s*', '/', text))

    try:
        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}"
    except ValueError:
        return url


def _find_result_container(heading):
    """通用启发式:从标题向上查找单条结果的容器。

    - 容器必须包含结果链接,文本长度 150-2500(须含 snippet)
    - 优先"单标题"容器:罩住多条结果的外层列表容器(DuckDuckGo html 版、
      SearXNG 等)含多个标题,会让所有条目选中同一容器并坍缩成一条
    - 无单标题候选时回退取最长,避免对标题结构特殊的布局直接丢条目
    """
    current = heading.parent
    candidates = []

    for level in range(8):
        if not current:
            break

        if current.name != 'div':
            current = current.parent
            continue

        if not current.find('a', href=has_result_href):
            current = current.parent
            continue

        text_len = len(current.get_text(strip=True))
        if 150 < text_len < 2500:
            candidates.append({
                'element': current,
                'length': text_len,
                'headings': len(current.find_all(['h3', 'h2'])),
            })

        current = current.parent

    if not candidates:
        return None

    single = [c for c in candidates if c['headings'] <= 1]
    return max(single or candidates, key=lambda x: x['length'])['element']


def _extract_snippet_from_container(container, title: str) -> str:
    """通用 snippet 提取:多级回退(原 SearchEngineStrategy._extract_snippet)"""
    snippet_selectors = [
        {'attrs': {'data-sncf': '1'}},   # Google data属性
        {'attrs': {'role': 'text'}},     # role属性
        {'style_pattern': 'webkit-line-clamp'},  # Google 行数限制样式
    ]

    for selector in snippet_selectors:
        if 'style_pattern' in selector:
            for elem in container.find_all('div'):
                if selector['style_pattern'] in (elem.get('style') or ''):
                    text = clean_ws(elem.get_text(separator=' ', strip=True))
                    if len(text) > 20:
                        return clamp(text)
        else:
            snippet_elem = container.find('div', **selector)
            if snippet_elem:
                text = clean_ws(snippet_elem.get_text(separator=' ', strip=True))
                if len(text) > 20:
                    return clamp(text)

    # DuckDuckGo html 版
    snippet_elem = container.find('a', class_='result__snippet')
    if snippet_elem:
        return clamp(clean_ws(snippet_elem.get_text(separator=' ', strip=True)))

    # 通用:不含标题的长文本 div
    for div in container.find_all('div'):
        div_text = clean_ws(div.get_text(separator=' ', strip=True))
        if (len(div_text) > 40 and title not in div_text
                and not div.find('h3') and not div.find('h2')):
            return clamp(div_text)

    # 最后:逐行文本过滤
    lines = [line.strip() for line in container.get_text(separator='\n', strip=True).split('\n') if line.strip()]
    snippet_lines, found_cite = [], False
    for line in lines:
        if line == title or (len(title) > 10 and title in line):
            continue
        if ('›' in line and len(line) < 150) or (line.startswith('http') and '›' in line):
            found_cite = True
            continue
        if line.startswith('http') and len(line) < 200 and ' ' not in line:
            continue
        if line in ['Read more', 'People also ask', 'Related searches']:
            continue
        if len(line) < 20 and not re.match(r'^\w+ \d{1,2}, \d{4}', line):
            continue
        if found_cite and len(line) >= 20:
            snippet_lines.append(line)

    return clamp(' '.join(snippet_lines)) if snippet_lines else ''


class SearchEngineAdapter(ABC):
    """单引擎适配器:从 SERP 提取结构化条目。

    子类优先用本引擎的确定性 DOM 通道;确定性通道落空时调用
    _generic_collect 兜底。条目为 dict: title/url/cite/snippet。
    """

    name = 'generic'

    @abstractmethod
    def matches(self, page_url: str) -> bool:
        """page_url 是否属于本引擎"""

    @abstractmethod
    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        """提取结果条目列表"""

    def extract_featured(self, soup: BeautifulSoup) -> str:
        """提取精选内容(AI Overview / Featured Snippet),无则返回 ''"""
        return ''

    # -- 通用 heading 启发式通道,供各适配器兜底 --

    def _generic_collect(self, soup: BeautifulSoup, page_url: str) -> list:
        results, seen_hrefs = [], set()

        for heading in soup.find_all(['h3', 'h2']):
            title = heading.get_text(' ', strip=True)
            if is_noise_title(title):
                continue

            # 标题自身的链接优先(DuckDuckGo/SearXNG/Google 的标题都含 <a>),
            # 拿不到再向上找容器取链接(个别布局标题与链接分离)
            link = heading.find('a', href=has_result_href)
            container = None
            if link is None:
                container = _find_result_container(heading)
                if not container:
                    continue
                link = container.find('a', href=has_result_href)
                if not link:
                    continue
            else:
                container = _find_result_container(heading) or link.parent

            href = link.get('href')
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            url = normalize_google_href(href)
            if 'gstatic.com' in url:
                continue
            if is_internal_search_page(url):
                continue

            real_url = resolve_real_url(container, url)
            if real_url and real_url != url:
                url = real_url

            results.append({
                'title': title,
                'url': url,
                'cite': extract_cite(container, url),
                'snippet': _extract_snippet_from_container(container, title),
            })

        return results

    def _dedupe(self, results: list) -> list:
        seen, out = set(), []
        for r in results:
            if r['url'] in seen:
                continue
            seen.add(r['url'])
            out.append(r)
        return out


class GoogleAdapter(SearchEngineAdapter):
    """Google:class 混淆且常变,用 h3 锚点启发式 + AI Overview 提取。"""

    name = 'google'

    def matches(self, page_url: str) -> bool:
        return _host_matches(page_url, 'google.com')

    def extract_featured(self, soup: BeautifulSoup) -> str:
        for selector in ['div[data-content-feature]', 'div.IScJfd', 'div[data-sncf]']:
            elem = soup.select_one(selector)
            if elem:
                text = clean_ws(elem.get_text(separator=' ', strip=True))
                if len(text) > 100:
                    return clamp(text, 800)
        return ''

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        return self._dedupe(self._generic_collect(soup, page_url))


class BingAdapter(SearchEngineAdapter):
    """Bing:新版布局条目是 li.b_algo,按结构直接提取;该布局下 h2 的
    父级链上没有落入文本窗口的 div,通用启发式会全部落空。链接为
    bing.com/ck/a 重定向,需解码。"""

    name = 'bing'

    def matches(self, page_url: str) -> bool:
        return _host_matches(page_url, 'bing.com')

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        results, seen_urls = [], set()

        for li in soup.select('li.b_algo'):
            heading = li.find(['h2', 'h3'])
            if not heading:
                continue
            title = heading.get_text(' ', strip=True)
            if is_noise_title(title):
                continue

            link = li.find('a', href=has_result_href)
            if not link:
                continue

            url = normalize_google_href(link.get('href'))
            if 'bing.com/ck/' in url:
                real_url = resolve_real_url(li, url)
                if real_url and real_url != url:
                    url = real_url

            if url in seen_urls:
                continue
            seen_urls.add(url)

            snippet = ''
            p = li.find('p')
            if p:
                snippet = clean_ws(p.get_text(' ', strip=True))[:400]
            if not snippet:
                snippet = _extract_snippet_from_container(li, title)

            results.append({
                'title': title,
                'url': url,
                'cite': extract_cite(li, url),
                'snippet': snippet,
            })

        if results:
            return results
        # b_algo 落空(布局变体/风控页)时回退通用通道
        return self._dedupe(self._generic_collect(soup, page_url))


class DuckDuckGoAdapter(SearchEngineAdapter):
    """DuckDuckGo html/lite 版:无 JS 服务页,语义 class 十分稳定
    (a.result__a / result__snippet),直接按 class 提取,不走容器启发式。"""

    name = 'duckduckgo'

    def matches(self, page_url: str) -> bool:
        return _host_matches(page_url, 'duckduckgo.com')

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        results = self._collect_html_version(soup) or self._collect_lite(soup)
        return self._dedupe(results or self._generic_collect(soup, page_url))

    def _collect_html_version(self, soup: BeautifulSoup) -> list:
        results = []
        for div in soup.select('div.result'):
            link = div.select_one('a.result__a[href]')
            if not link:
                continue
            title = clean_ws(link.get_text(' ', strip=True))
            if is_noise_title(title):
                continue

            url = resolve_real_url(div, 'https:' + link['href']
                                   if link['href'].startswith('//') else link['href'])

            snippet_elem = div.select_one('a.result__snippet')
            snippet = clean_ws(snippet_elem.get_text(' ', strip=True)) if snippet_elem else ''

            cite_elem = div.select_one('a.result__url')
            cite = clean_ws(cite_elem.get_text(' ', strip=True)) if cite_elem else ''
            if not cite:
                try:
                    parsed = urlparse(url)
                    cite = f"{parsed.netloc}{parsed.path}"
                except ValueError:
                    cite = url

            results.append({'title': title, 'url': url, 'cite': cite, 'snippet': clamp(snippet)})
        return results

    def _collect_lite(self, soup: BeautifulSoup) -> list:
        """lite 版为 table 布局:标题链接 a.result-link,摘要 a.result__snippet"""
        results = []
        for link in soup.select('a.result-link[href]'):
            title = clean_ws(link.get_text(' ', strip=True))
            if is_noise_title(title):
                continue
            href = link['href']
            url = resolve_real_url(link.parent, 'https:' + href if href.startswith('//') else href)

            # lite 版摘要独立成行,取标题链接之后最近的 snippet(文档序对齐)
            sn = link.find_next('a', class_='result__snippet') or link.find_next('td', class_='result__snippet')
            snippet = clean_ws(sn.get_text(' ', strip=True)) if sn else ''

            try:
                parsed = urlparse(url)
                cite = f"{parsed.netloc}{parsed.path}"
            except ValueError:
                cite = url

            results.append({'title': title, 'url': url, 'cite': cite, 'snippet': clamp(snippet)})
        return results


class SearxAdapter(SearchEngineAdapter):
    """Searx/SearxNG(公共实例域名异构,以 netloc 含 searx 判定):
    条目是规整的 article.result,标题 h3 > a 即真实直链。"""

    name = 'searx'

    def matches(self, page_url: str) -> bool:
        return 'searx' in _netloc(page_url)

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        results = []
        for article in soup.select('article.result'):
            link = article.select_one('h3 a[href]')
            if not link:
                continue
            title = clean_ws(link.get_text(' ', strip=True))
            if is_noise_title(title):
                continue
            url = link['href']

            content = article.select_one('p.content')
            snippet = clean_ws(content.get_text(' ', strip=True)) if content else ''

            cite_elem = article.select_one('a.url_header[href]')
            if cite_elem:
                try:
                    parsed = urlparse(cite_elem['href'])
                    cite = f"{parsed.netloc}{parsed.path}"
                except ValueError:
                    cite = url
            else:
                cite = url

            results.append({'title': title, 'url': url, 'cite': cite, 'snippet': clamp(snippet)})

        return self._dedupe(results or self._generic_collect(soup, page_url))


class StartpageAdapter(SearchEngineAdapter):
    """Startpage:styled-components 的 hash 类名不可靠,但 wgl- 语义
    命名与 data-testid 稳定:标题 a.wgl-site-title,显示URL a.wgl-display-url,
    摘要 p.description;旧布局为 a.result-link。"""

    name = 'startpage'

    def matches(self, page_url: str) -> bool:
        return _host_matches(page_url, 'startpage.com')

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        results = []

        for div in soup.select('div.result'):
            link = div.select_one('a.wgl-site-title[href]') or div.select_one('a.result-link[href]')
            if not link:
                continue
            title = clean_ws(link.get_text(' ', strip=True))
            if is_noise_title(title):
                continue

            display = div.select_one('a.wgl-display-url')
            # 展示 URL 文本 = 真实地址 + 面包屑路径两段,真实地址在前
            display_text = ''
            if display is not None:
                display_text = next(
                    (t for t in clean_ws(display.get_text(' ', strip=True)).split()
                     if t.startswith('http')), '')

            url = link['href']
            if not url.startswith('http'):
                # /clev?... 是 Startpage 的点击追踪链接,payload 里不含目标;
                # 真实 URL 只在展示 URL 的文本里,拿不到就只能丢弃该条
                if display_text:
                    url = display_text
                else:
                    continue

            cite = display.get('aria-label') or display_text or url

            desc = div.select_one('p.description')
            snippet = clean_ws(desc.get_text(' ', strip=True)) if desc else ''

            results.append({'title': title, 'url': url, 'cite': clean_ws(cite), 'snippet': clamp(snippet)})

        return self._dedupe(results or self._generic_collect(soup, page_url))


class GenericSearchAdapter(SearchEngineAdapter):
    """未知搜索引擎(含 Brave——其 SERP 有反爬质询,结构无法在本环境
    验证)的兜底:通用 heading 启发式。"""

    name = 'generic'

    def __init__(self, name: str = 'generic', domains: tuple = ()):
        self.name = name
        self._domains = domains

    def matches(self, page_url: str) -> bool:
        if not self._domains:
            return True
        return any(_host_matches(page_url, d) for d in self._domains)

    def collect_results(self, soup: BeautifulSoup, page_url: str) -> list:
        return self._dedupe(self._generic_collect(soup, page_url))


ADAPTERS = [
    GoogleAdapter(),
    BingAdapter(),
    DuckDuckGoAdapter(),
    SearxAdapter(),
    StartpageAdapter(),
    GenericSearchAdapter('brave', domains=('brave.com',)),
]


def pick_adapter(page_url: str) -> SearchEngineAdapter:
    """按 page_url 挑选适配器;具体引擎优先,generic 兜底"""
    for adapter in ADAPTERS:
        if adapter.matches(page_url):
            return adapter
    return GenericSearchAdapter()


class SearchEngineStrategy:
    """对外入口(接口与原实现一致):适配器提取 + 统一过滤/去重/渲染。"""

    def extract(self, html: str, url: str) -> str:
        soup = BeautifulSoup(html, 'lxml')
        adapter = pick_adapter(url)

        parts = []
        featured = adapter.extract_featured(soup)
        if featured:
            parts.append("## Featured Content\n\n")
            parts.append(featured)
            parts.append("\n\n")

        parts.append("## Search Results\n\n")
        results = self._filter_results(adapter.collect_results(soup, url))

        if not results:
            # 0 条时区分"查询无果"与"被反爬拦截":给模型明确信号,
            # 引导其换引擎重试而非当作无结果放弃
            reason = detect_interception(html, soup)
            if reason:
                parts.append(
                    f"未获取到搜索结果:疑似被反爬拦截(信号: {reason})。\n\n"
                    "本引擎本次不可用,建议换用其他搜索引擎或稍后重试。\n\n"
                )
            return ''.join(parts)

        for index, result in enumerate(results, 1):
            title = result['title']
            parts.append(f"### {index}. {title}\n\n")
            if result.get('snippet'):
                parts.append(f"{result['snippet']}\n\n")
            parts.append(f"[查看原文]({result['url']})\n\n")
            parts.append("---\n\n")

        return ''.join(parts)

    @staticmethod
    def _filter_results(raw_results: list) -> list:
        """统一过滤(噪音标题/gstatic/引擎自身页)与 URL 去重"""
        seen_urls, out = set(), []
        for result in raw_results:
            if is_noise_title(result['title']):
                continue
            result_url = result['url']
            if 'gstatic.com' in result_url or is_internal_search_page(result_url):
                continue
            if result_url in seen_urls:
                continue
            seen_urls.add(result_url)
            out.append(result)
        return out
