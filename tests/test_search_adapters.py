"""搜索引擎适配器的路由与各引擎专项解析测试。"""
import pytest

from scrapling_fetch_mcp._search_engines import (
    BingAdapter,
    DuckDuckGoAdapter,
    GenericSearchAdapter,
    GoogleAdapter,
    SearxAdapter,
    SearchEngineStrategy,
    StartpageAdapter,
    pick_adapter,
)


def test_pick_adapter_routing():
    """按 page_url 路由到对应适配器;具体引擎优先,generic 兜底"""
    assert isinstance(pick_adapter("https://www.google.com/search?q=x"), GoogleAdapter)
    assert isinstance(pick_adapter("https://www.bing.com/search?q=x"), BingAdapter)
    assert isinstance(pick_adapter("https://html.duckduckgo.com/html/?q=x"), DuckDuckGoAdapter)
    assert isinstance(pick_adapter("https://lite.duckduckgo.com/lite/?q=x"), DuckDuckGoAdapter)
    assert isinstance(pick_adapter("https://searx.be/search?q=x"), SearxAdapter)
    assert isinstance(pick_adapter("https://www.startpage.com/sp/search?query=x"), StartpageAdapter)
    # Brave 有专属的 generic 实例;baresearch.org 名字不含 searx,走通用兜底
    brave = pick_adapter("https://search.brave.com/search?q=x")
    assert isinstance(brave, GenericSearchAdapter) and brave.name == "brave"
    other = pick_adapter("https://baresearch.org/search?q=x")
    assert isinstance(other, GenericSearchAdapter) and other.name == "generic"


SEARX_HTML = """
<html><body>
<main>
<article class="result result-default category-general">
  <div class="result_inner">
    <a class="url_header" href="https://news.bjd.com.cn/2026/10/17/11998605.shtml">
      <div class="url_wrapper"><span>https://news.bjd.com.cn › 2026</span></div>
    </a>
    <h3><a href="https://news.bjd.com.cn/2026/10/17/11998605.shtml">北京城区普降暴雨</a></h3>
    <p class="content">截至今天15时，全市平均降雨量48.3毫米，为大雨量级。</p>
  </div>
</article>
</main>
</body></html>
"""


def test_searx_adapter_deterministic_channel():
    """SearXNG article.result 直链条目:标题/URL/摘要/显示地址一次取全"""
    md = SearchEngineStrategy().extract(SEARX_HTML, "https://searx.be/search?q=rain")
    assert "### 1. 北京城区普降暴雨" in md
    assert "[查看原文](https://news.bjd.com.cn/2026/10/17/11998605.shtml)" in md
    assert "全市平均降雨量48.3毫米" in md


STARTPAGE_HTML = """
<html><body>
<div class="result css-abc">
  <a class="favicon-link" href="https://swj.beijing.gov.cn/bmxx/cssq/"></a>
  <div class="wgl-title-link-container">
    <a class="wgl-site-title" href="https://swj.beijing.gov.cn/bmxx/cssq/">
      <span class="link-text">雨情 - 北京市水务局</span>
    </a>
    <a class="wgl-display-url" aria-label="https://swj.beijing.gov.cn/bmxx/cssq/"
       href="https://swj.beijing.gov.cn/bmxx/cssq/">
      <span class="link-text">https://swj.beijing.gov.cn</span>
    </a>
  </div>
  <p class="description">北京市水务局雨情信息发布页。</p>
</div>
<div class="result css-abc">
  <a class="wgl-site-title" href="/clev?event=Sp_x9&payload=abc">
    <span class="link-text">新浪财经</span>
  </a>
  <a class="wgl-display-url" href="/clev?event=Sp_x9&payload=def">
    <span class="link-text">https://finance.sina.com.cn/jjxw/2026-10-17/doc-x.shtml</span>
    <span class="link-text">https://finance.sina.com.cn › jjxw › 2026-10-17</span>
  </a>
  <p class="description">降雨实况和天气速递。</p>
</div>
</body></html>
"""


def test_startpage_adapter_direct_links():
    """wgl-site-title 直链条目:标题/URL/摘要正常提取"""
    md = SearchEngineStrategy().extract(STARTPAGE_HTML, "https://www.startpage.com/sp/search?query=x")
    assert "### 1. 雨情 - 北京市水务局" in md
    assert "[查看原文](https://swj.beijing.gov.cn/bmxx/cssq/)" in md
    assert "降雨实况和天气速递" in md


def test_startpage_adapter_tracking_link_resolved():
    """/clev 点击追踪链接不含目标,应从展示 URL 文本还原真实地址

    展示 URL 文本含真实地址与面包屑两段,只取第一段 http token。
    """
    md = SearchEngineStrategy().extract(STARTPAGE_HTML, "https://www.startpage.com/sp/search?query=x")
    assert "[查看原文](https://finance.sina.com.cn/jjxw/2026-10-17/doc-x.shtml)" in md
    assert "/clev" not in md
    assert "›" not in md


DDG_LITE_HTML = """
<html><body>
<table>
  <tr>
    <td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide&amp;rut=x">Python Guide</a></td>
  </tr>
  <tr>
    <td><a class="result__snippet" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fguide&amp;rut=x">A complete hands-on guide covering python asyncio with runnable examples and practical exercises for developers.</a></td>
  </tr>
</table>
</body></html>
"""


def test_ddg_lite_adapter():
    """lite 版 table 布局: a.result-link 标题 + uddg 解码 + 行内摘要"""
    md = SearchEngineStrategy().extract(DDG_LITE_HTML, "https://lite.duckduckgo.com/lite/?q=python")
    assert "### 1. Python Guide" in md
    assert "[查看原文](https://example.com/guide)" in md
    assert "runnable examples" in md


GENERIC_BRAVE_HTML = """
<html><body>
<div class="snippet" data-type="web">
  <h2><a href="https://example.com/beijing-rain">Beijing sees record October rain</a></h2>
  <div>The city recorded more than 70 millimeters of rainfall on October 17,
  breaking a single-day record that had stood since 1968 in the capital.</div>
</div>
</body></html>
"""


def test_brave_falls_back_to_generic_channel():
    """Brave 走 generic 兜底通道(其确定性结构无法在本环境验证)"""
    md = SearchEngineStrategy().extract(GENERIC_BRAVE_HTML, "https://search.brave.com/search?q=rain")
    assert "### 1. Beijing sees record October rain" in md
    assert "[查看原文](https://example.com/beijing-rain)" in md


# --- 反爬拦截识别:0 条结果时给模型明确信号,而非静默空结果 ---

GOOGLE_SORRY_HTML = """
<html><head><title>Sorry, we're unable to complete your request</title></head>
<body>
<form id="captcha-form" action="/sorry/index">
  <div class="g-recaptcha" data-sitekey="xxx"></div>
  <iframe src="https://www.google.com/recaptcha/api.js"></iframe>
</form>
<p>Our systems have detected unusual traffic from your computer network.</p>
</body></html>
"""


def test_interception_detected_on_google_sorry_page():
    """Google sorry/验证码页应输出拦截提示而非空结果"""
    md = SearchEngineStrategy().extract(GOOGLE_SORRY_HTML, "https://www.google.com/search?q=x")
    assert "反爬拦截" in md
    assert "recaptcha" in md or "unusual traffic" in md
    assert "换用其他搜索引擎" in md


ANUBIS_HTML = """
<html><head><title>Making sure you're not a bot!</title></head>
<body><div id="challenge-error-text">Making sure you're not a bot!
This may take a couple of seconds.</div></body></html>
"""


def test_interception_detected_on_anubis_page():
    """Anubis 质询页(SearXNG 公共实例实测样本)应被识别"""
    md = SearchEngineStrategy().extract(ANUBIS_HTML, "https://baresearch.org/search?q=x")
    assert "反爬拦截" in md
    assert "换用其他搜索引擎" in md


BRAVE_CHALLENGE_HTML = """
<html lang="en-us"><head><title>Brave Search</title></head>
<body><div>Verifying you're not a bot. Quick check before you continue
searching. Your request has been flagged as being suspicious and Brave
Search decided to schedule a captcha for you.</div></body></html>
"""


def test_interception_detected_on_brave_challenge():
    """Brave 429 人机质询页(实测样本)应被识别"""
    md = SearchEngineStrategy().extract(BRAVE_CHALLENGE_HTML, "https://search.brave.com/search?q=x")
    assert "反爬拦截" in md
    assert "换用其他搜索引擎" in md


def test_interception_detected_on_too_short_page():
    """超短空页(如 DDG anomaly 202 空响应)应提示内容异常"""
    md = SearchEngineStrategy().extract(
        "<html><head><title>t</title></head><body><p>hi</p></body></html>",
        "https://duckduckgo.com/html/?q=x")
    assert "反爬拦截" in md


def test_clean_empty_results_not_flagged_as_interception():
    """无任何拦截信号的正常空结果页不误报"""
    filler = ("It looks like there aren't many great matches for your search. "
              * 200)  # 正常 SERP 即使无结果也有完整页面骨架,体量远超 3KB
    html = f"""
    <html><head><title>search - Search</title></head><body>
    <div id="search"><p>No results found for this query. Try different keywords
    or check your spelling, and browse some related suggestions below.</p>
    <p>{filler}</p></div>
    </body></html>
    """
    md = SearchEngineStrategy().extract(html, "https://www.google.com/search?q=x")
    assert "反爬拦截" not in md
    assert "## Search Results" in md
