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


def test_ui_noise_words_only_match_standalone_titles():
    """News/Videos 等普通英文词仅在独立成标题时视为界面噪音"""
    strategy = SearchEngineStrategy()
    assert strategy._is_ad_or_noise("News")
    assert strategy._is_ad_or_noise("Videos")
    assert strategy._is_ad_or_noise("网页搜索结果")
    assert not strategy._is_ad_or_noise("China rainfall news report")
    assert not strategy._is_ad_or_noise("Best videos of the year")
    assert not strategy._is_ad_or_noise("Maps and routing explained")


def test_gstatic_thumbnail_links_skipped():
    """Google 视频缩略图等静态资源链接不作为结果"""
    html = GOTO_HTML.replace("/goto?url=CAES1234token",
                             "https://encrypted-vtbn0.gstatic.com/video?q=tbn:ANd9GcSUklS2T0KZrCv5")
    md = SearchEngineStrategy().extract(html, "https://www.google.com/search?q=asyncio")
    assert "gstatic.com" not in md
    assert "### 1." not in md


def ddg_result(title: str, target: str, snippet: str) -> str:
    """DDG html 版单条结果:uddg 重定向 + 足量 snippet(过 150 字符文本窗口)"""
    from urllib.parse import quote

    href = "//duckduckgo.com/l/?uddg=" + quote(target, safe="") + "&rut=x"
    return f"""
    <div class="result">
      <div class="links_main result__body">
        <h2 class="result__title"><a class="result__a" href="{href}">{title}</a></h2>
        <a class="result__snippet">{snippet}</a>
      </div>
    </div>
    """


DDG_SHARED_LIST_HTML = """
<html><body>
<div class="serp__results"><div class="results">
  {r1}{r2}{r3}
</div></div>
</body></html>
"""


def test_shared_list_container_does_not_collapse_results():
    """外层列表容器罩住多条结果时不得坍缩成 1 条(DDG html/SearXNG 布局)

    旧逻辑对每个标题都取"文本最长的候选容器",三条结果全部选中同一个
    外层列表容器,再从中取第一个链接,去重后 10 条坍缩成 1 条。
    """
    snippets = [
        "A sustained heavy rainfall event hit Beijing with citywide averages "
        "reaching torrential levels and the observatory breaking a record "
        "that had stood since October of 1968 in the capital.",
        "Rainfall continued for sixteen hours across the city with urban "
        "districts recording the strongest autumn rain in recent memory, "
        "prompting the subway system to adjust several flooded lines.",
        "The maximum hourly rain intensity was recorded in mountain areas "
        "where orographic lift and a low level jet focused the convection "
        "over the northern districts throughout the entire afternoon.",
    ]
    html = (
        DDG_SHARED_LIST_HTML
        .replace("{r1}", ddg_result("Beijing rainfall record", "https://a.example.com/1", snippets[0]))
        .replace("{r2}", ddg_result("Sixteen hours of rain", "https://b.example.com/2", snippets[1]))
        .replace("{r3}", ddg_result("Rain intensity in mountains", "https://c.example.com/3", snippets[2]))
    )
    md = SearchEngineStrategy().extract(html, "https://html.duckduckgo.com/html/?q=rain")
    assert "[查看原文](https://a.example.com/1)" in md
    assert "[查看原文](https://b.example.com/2)" in md
    assert "[查看原文](https://c.example.com/3)" in md
    assert md.count("[查看原文]") == 3


def test_extract_real_url_rejects_truncated_cite():
    """cite 显示文本被 Google 截断(省略号)时不得当作真实 URL"""
    strategy = SearchEngineStrategy()
    soup = BeautifulSoup(
        '<div><cite>https://www.chinanews.com.cn/10...</cite></div>', 'lxml')
    fallback = "https://www.google.com/goto?url=x"
    assert strategy._extract_real_url(soup.find("div"), fallback) == fallback

CITE_TRUNCATED_HTML = """
<html><body><div class="container">
  <h3><a href="/goto?url=CAESxyz">China rainfall news report</a></h3>
  <cite>https://www.chinanews.com.cn/10...</cite>
  <div>Heavy rain hit Beijing on October 17 2026, breaking the October
  single-day rainfall record set in 1968, with the observatory recording
  more than seventy millimeters of precipitation in total across the
  entire city area.</div>
</div></body></html>
"""


def test_cite_truncated_text_not_used_as_real_url(monkeypatch):
    """goto 解析失败且 cite 为截断文本时,保留跳转链接而非坏 URL"""
    strategy = SearchEngineStrategy()
    monkeypatch.setattr(strategy, "_follow_goto_redirect", lambda token, timeout=5.0: None)
    md = strategy.extract(CITE_TRUNCATED_HTML, "https://www.google.com/search?q=rain")
    assert "chinanews.com.cn/10..." not in md
    assert "[查看原文](https://www.google.com/goto?url=CAESxyz)" in md
