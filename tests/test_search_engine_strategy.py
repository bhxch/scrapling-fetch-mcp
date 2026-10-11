# tests/test_search_engine_strategy.py
"""SearchEngineStrategy 的 Bing/Google 专项解析测试。"""
import base64

from bs4 import BeautifulSoup

from scrapling_fetch_mcp._extractor_strategy import SearchEngineStrategy


def bing_ck_url(target: str) -> str:
    """构造 Bing ck 重定向链接(u=a1 + urlsafe base64)"""
    payload = base64.urlsafe_b64encode(target.encode()).decode().rstrip("=")
    return f"https://www.bing.com/ck/a?!&&p=x&u=a1{payload}&ntb=1"


BING_HTML = """
<html><body><main><ol>
  <li class="b_algo">
    <h2><a href="{url1}">Hands-On Python 3 Concurrency</a></h2>
    <div class="b_caption"><p>Learn asyncio and concurrent programming with this
    hands-on course covering real examples.</p></div>
    <cite>https://realpython.com/courses/</cite>
  </li>
  <li class="b_algo">
    <h2><a href="{url2}"><span>Deep dive into</span><span>Python asyncio tutorial</span></a></h2>
    <div class="b_caption"><p>A comprehensive guide to async python covering tasks,
    coroutines and the event loop in depth.</p></div>
  </li>
</ol></main></body></html>
"""


def test_bing_b_algo_channel_extracts_and_decodes():
    """b_algo 结构通道:提取条目、解码 u=a1 重定向、修标题粘连"""
    html = BING_HTML.format(
        url1=bing_ck_url("https://realpython.com/courses/python-3-concurrency/"),
        url2=bing_ck_url("https://codesamplez.com/asyncio"),
    )
    md = SearchEngineStrategy().extract(html, "https://www.bing.com/search?q=asyncio")

    assert "### 1. Hands-On Python 3 Concurrency" in md
    assert "[查看原文](https://realpython.com/courses/python-3-concurrency/)" in md
    assert "[查看原文](https://codesamplez.com/asyncio)" in md
    # b_caption 的 p 作为 snippet
    assert "hands-on course" in md
    # 标题由相邻 span 拼接时应有空格
    assert "Deep dive into Python asyncio tutorial" in md


def test_extract_real_url_bing_u_a1():
    """_extract_real_url 应解码 u=a1 base64 重定向"""
    strategy = SearchEngineStrategy()
    soup = BeautifulSoup("<li><cite>realpython.com</cite></li>", "lxml")
    url = bing_ck_url("https://realpython.com/courses/x/")
    assert strategy._extract_real_url(soup.find("li"), url) == "https://realpython.com/courses/x/"


def test_extract_real_url_bing_invalid_payload_falls_back():
    """u=a1 载荷无效时回退原始重定向 URL"""
    strategy = SearchEngineStrategy()
    soup = BeautifulSoup("<li></li>", "lxml")
    url = "https://www.bing.com/ck/a?!&&p=x&u=a1!!!!&ntb=1"
    assert strategy._extract_real_url(soup.find("li"), url) == url


GOTO_HTML = """
<html><body>
<div class="pad"><div class="container">
  <h3><a href="/goto?url=CAES1234token">Understanding Python Asyncio</a></h3>
  <span>https://example.com/asyncio</span>
  <div>Python asyncio gives you coroutines and an event loop for writing
  concurrent code with a very small surface area to learn and reason about
  in practice, which makes it a great fit for network services.</div>
</div></div>
</body></html>
"""


def test_google_goto_followed(monkeypatch):
    """/goto?url= 相对链接应经服务端跟随解析为真实 URL"""
    strategy = SearchEngineStrategy()
    monkeypatch.setattr(
        strategy, "_follow_goto_redirect",
        lambda token, timeout=5.0: "https://example.com/asyncio",
    )
    md = strategy.extract(GOTO_HTML, "https://www.google.com/search?q=asyncio")
    assert "[查看原文](https://example.com/asyncio)" in md


def test_google_goto_fallback_on_failure(monkeypatch):
    """goto 跟随失败时回退为原始跳转链接"""
    strategy = SearchEngineStrategy()
    monkeypatch.setattr(strategy, "_follow_goto_redirect", lambda token, timeout=5.0: None)
    md = strategy.extract(GOTO_HTML, "https://www.google.com/search?q=asyncio")
    assert "[查看原文](https://www.google.com/goto?url=CAES1234token)" in md


def test_normalize_url_q_param():
    """旧版 /url?q= 重定向应本地解析 q 参数"""
    from urllib.parse import quote

    strategy = SearchEngineStrategy()
    href = "/url?sa=t&q=" + quote("https://docs.example.com/guide", safe="")
    assert strategy._normalize_result_url(href) == "https://docs.example.com/guide"


def test_normalize_url_shapes():
    """协议相对/完整/未知相对路径的归一化"""
    strategy = SearchEngineStrategy()
    assert strategy._normalize_result_url("//example.com/x") == "https://example.com/x"
    assert strategy._normalize_result_url("https://example.com/y") == "https://example.com/y"
    unknown = strategy._normalize_result_url("/goto?url=")
    assert unknown == "https://www.google.com/goto?url="


DDG_HTML = """
<html><body>
<div class="result">
  <h2 class="result__title"><a class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide&amp;rut=x">Python Guide</a></h2>
  <a class="result__snippet">A complete hands-on guide covering python asyncio
  with runnable examples, common pitfalls and practical exercises for
  developers who want to write concurrent network services.</a>
</div>
</body></html>
"""


def test_heading_channel_still_extracts_ddg():
    """非 Bing 布局回退到 heading 启发式,uddg 重定向解析为真实 URL"""
    md = SearchEngineStrategy().extract(DDG_HTML, "https://html.duckduckgo.com/html/?q=python")
    assert "[查看原文](https://example.com/guide)" in md


def test_noise_word_boundary():
    """噪音词按整词匹配:不误杀含 ad 子串的正常标题"""
    strategy = SearchEngineStrategy()
    assert strategy._is_ad_or_noise("Sponsored result")
    assert strategy._is_ad_or_noise("Ad · something")
    assert strategy._is_ad_or_noise("People also ask")
    assert strategy._is_ad_or_noise("Web results")
    assert not strategy._is_ad_or_noise("AI Mode reply for python asyncio tutorial")
    assert not strategy._is_ad_or_noise("Understanding Python: Asyncio")
    assert not strategy._is_ad_or_noise("Adobe Photoshop tutorial")


def test_gstatic_thumbnail_links_skipped():
    """Google 视频缩略图等静态资源链接不作为结果"""
    html = GOTO_HTML.replace("/goto?url=CAES1234token",
                             "https://encrypted-vtbn0.gstatic.com/video?q=tbn:ANd9GcSUklS2T0KZrCv5")
    md = SearchEngineStrategy().extract(html, "https://www.google.com/search?q=asyncio")
    assert "gstatic.com" not in md
    assert "### 1." not in md
