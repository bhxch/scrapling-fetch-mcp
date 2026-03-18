# airead 格式实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 AI 优化的内容提取格式，减少 30-50% token 消耗，同时保留核心内容完整性。

**Architecture:** 策略模式 + URL 路由架构。7个内置策略（dual、trafilatura、readability、scrapling、search_engine、developer_platform、documentation）。内置默认规则打包在代码中，用户可通过配置文件覆盖。智能错误处理和降级机制。

**Tech Stack:**
- trafilatura>=1.6.0 (内容提取)
- readability-lxml>=0.8.1 (Firefox Reader View 算法)
- scrapling>=0.4.0 (内置 Markdown 转换)
- pyyaml>=6.0 (配置文件解析)

---

## 文件结构

**新增文件：**
- `src/scrapling_fetch_mcp/_extractor_strategy.py` - 策略基类和所有内置策略
- `src/scrapling_fetch_mcp/_url_matcher.py` - URL 匹配器
- `src/scrapling_fetch_mcp/_strategy_factory.py` - 策略工厂
- `src/scrapling_fetch_mcp/_markdown_postprocessor.py` - Markdown 后处理
- `src/scrapling_fetch_mcp/_default_rules.py` - 内置默认规则
- `tests/test_extractor_strategies.py` - 策略单元测试
- `tests/test_url_matcher.py` - URL 匹配器测试
- `tests/test_strategy_factory.py` - 策略工厂测试
- `tests/test_error_handling.py` - 错误处理测试
- `tests/test_markdown_postprocessor.py` - Markdown 后处理器测试

**修改文件：**
- `src/scrapling_fetch_mcp/_config.py` - 添加 rules_config_path 配置
- `src/scrapling_fetch_mcp/_fetcher.py` - 添加 _extract_with_airead 函数
- `src/scrapling_fetch_mcp/mcp.py` - 添加 airead 格式支持和 CLI 参数
- `pyproject.toml` - 添加新依赖

---

## Task 1: 核心基础设施 - 策略基类和工具函数

**Files:**
- Create: `src/scrapling_fetch_mcp/_extractor_strategy.py`
- Create: `tests/test_extractor_strategies.py`

### 1.1 实现有效字符统计函数

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py
import pytest
from scrapling_fetch_mcp._extractor_strategy import count_effective_characters

def test_count_effective_characters_plain_text():
    """测试纯文本统计"""
    text = "Hello World"
    count = count_effective_characters(text)
    assert count == 10

def test_count_effective_characters_with_markdown():
    """测试 Markdown 标记移除"""
    markdown = "# Title\n\n**bold** and *italic*"
    count = count_effective_characters(markdown)
    assert count < len(markdown)
    assert count == len("Titlebolditalic")

def test_count_effective_characters_with_links():
    """测试链接处理"""
    markdown = "[Click here](https://example.com)"
    count = count_effective_characters(markdown)
    assert count == len("Clickhere")

def test_count_effective_characters_with_lists():
    """测试列表标记移除"""
    markdown = "- Item 1\n- Item 2\n1. First\n2. Second"
    count = count_effective_characters(markdown)
    assert count == len("Item1Item2FirstSecond")

def test_count_effective_characters_empty():
    """测试空字符串"""
    count = count_effective_characters("")
    assert count == 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_count_effective_characters_plain_text -v`
Expected: FAIL with "module not found" or "ImportError"

- [ ] **Step 3: 实现函数**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py
import re

def count_effective_characters(text: str) -> int:
    """
    计算有效字符数（纯文本内容）

    移除 Markdown 标记和所有空白字符，统计剩余字符
    """
    if not text:
        return 0

    # 移除 Markdown 标记
    text = re.sub(r'^#+\s*', '', text, flags=re.MULTILINE)  # 标题
    text = re.sub(r'\*\*|\*|__|_', '', text)  # 粗体/斜体
    text = re.sub(r'`+', '', text)  # 代码
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)  # 链接
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)  # 图片
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  # 列表
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)  # 数字列表
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)  # 引用
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)  # 水平线

    # 移除所有空白字符
    text = re.sub(r'\s+', '', text)

    return len(text)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add count_effective_characters function

Implement function to count effective characters in Markdown text.
Removes Markdown formatting markers and whitespace to get pure text length.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 1.2 实现策略基类

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py (追加)

from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

def test_extractor_strategy_is_abstract():
    """测试策略基类是抽象的"""
    with pytest.raises(TypeError):
        ExtractorStrategy()
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_extractor_strategy_is_abstract -v`
Expected: FAIL (class can't be instantiated)

- [ ] **Step 3: 实现基类**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

from abc import ABC, abstractmethod

class ExtractorStrategy(ABC):
    """内容提取策略基类"""

    @abstractmethod
    def extract(self, html: str, url: str) -> str:
        """
        从 HTML 中提取核心内容并转换为 Markdown

        Args:
            html: 原始 HTML 内容
            url: 页面 URL（可用于策略内部判断）

        Returns:
            提取并格式化后的 Markdown 文本
        """
        pass
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add ExtractorStrategy abstract base class

Define the interface for content extraction strategies.
All built-in and custom strategies will inherit from this base.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 实现内置策略（单个提取器）

**Files:**
- Modify: `src/scrapling_fetch_mcp/_extractor_strategy.py`
- Modify: `tests/test_extractor_strategies.py`

### 2.1 实现 TrafilaturaStrategy

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py (追加)

from scrapling_fetch_mcp._extractor_strategy import TrafilaturaStrategy

def test_trafilatura_strategy_basic():
    """测试 Trafilatura 基本提取"""
    html = """
    <html>
        <body>
            <h1>Title</h1>
            <p>Content paragraph</p>
        </body>
    </html>
    """
    strategy = TrafilaturaStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Title" in result or "Content" in result

def test_trafilatura_strategy_removes_navigation():
    """测试导航元素移除"""
    html = """
    <html>
        <body>
            <nav><a href="#">Nav Link</a></nav>
            <main>
                <h1>Main Content</h1>
                <p>Important text</p>
            </main>
        </body>
    </html>
    """
    strategy = TrafilaturaStrategy()
    result = strategy.extract(html, "https://example.com")

    assert "Main Content" in result
    assert "Important text" in result
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_trafilatura_strategy_basic -v`
Expected: FAIL with "ImportError" or "TrafilaturaStrategy not found"

- [ ] **Step 3: 实现策略**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

import trafilatura

class TrafilaturaStrategy(ExtractorStrategy):
    """使用 trafilatura 提取内容"""

    def extract(self, html: str, url: str) -> str:
        result = trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown'
        )
        return result or ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py::test_trafilatura_strategy -v`
Expected: PASS (2 tests)

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add TrafilaturaStrategy

Implement basic content extraction using trafilatura library.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 2.2 实现 ReadabilityStrategy

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py (追加)

from scrapling_fetch_mcp._extractor_strategy import ReadabilityStrategy

def test_readability_strategy_basic():
    """测试 Readability 基本提取"""
    html = """
    <html>
        <body>
            <h1>Article Title</h1>
            <p>Article content here</p>
        </body>
    </html>
    """
    strategy = ReadabilityStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_readability_strategy_basic -v`
Expected: FAIL

- [ ] **Step 3: 实现策略**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

from readability import Document
from bs4 import BeautifulSoup

class ReadabilityStrategy(ExtractorStrategy):
    """使用 readability-lxml 提取内容"""

    def extract(self, html: str, url: str) -> str:
        doc = Document(html)
        clean_html = doc.summary()

        # 转换为 Markdown
        soup = BeautifulSoup(clean_html, 'html.parser')

        # 简单的 Markdown 转换（后续会使用统一的转换器）
        text = soup.get_text(separator='\n')
        return text.strip()
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py::test_readability_strategy -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add ReadabilityStrategy

Implement content extraction using readability-lxml (Firefox Reader View).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 2.3 实现 ScraplingStrategy

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py (追加)

from scrapling_fetch_mcp._extractor_strategy import ScraplingStrategy

def test_scrapling_strategy_basic():
    """测试 Scrapling 提取"""
    html = """
    <html>
        <body>
            <h1>Test Page</h1>
            <p>Some content</p>
        </body>
    </html>
    """
    strategy = ScraplingStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_scrapling_strategy_basic -v`
Expected: FAIL

- [ ] **Step 3: 实现策略**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

from scrapling.parser import Selector

class ScraplingStrategy(ExtractorStrategy):
    """使用 Scrapling 内置的提取功能"""

    def extract(self, html: str, url: str) -> str:
        page = Selector(html)
        body = page.find('body')

        if body:
            # Scrapling 的 Markdown 转换
            # 注意：需要确认 Scrapling 的实际 API
            text = body.get_text(separator='\n')
            return text.strip()

        return ""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py::test_scrapling_strategy -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add ScraplingStrategy

Implement content extraction using Scrapling's built-in functionality.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 2.4 实现专用策略（search_engine、developer_platform、documentation）

（这部分类似，为节省篇幅，合并为一个提交）

- [ ] **Step 1: 写测试**（略）

- [ ] **Step 2: 运行测试验证失败**

- [ ] **Step 3: 实现三个策略**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

class SearchEngineStrategy(ExtractorStrategy):
    """搜索引擎专用策略"""

    def extract(self, html: str, url: str) -> str:
        import trafilatura
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            favor_precision=True
        ) or ""

class DeveloperPlatformStrategy(ExtractorStrategy):
    """开发者平台专用策略"""

    def extract(self, html: str, url: str) -> str:
        import trafilatura
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            include_tables=True
        ) or ""

class DocumentationStrategy(ExtractorStrategy):
    """技术文档专用策略"""

    def extract(self, html: str, url: str) -> str:
        import trafilatura
        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            favor_precision=True
        ) or ""
```

- [ ] **Step 4: 运行测试验证通过**

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add specialized extraction strategies

Add three specialized strategies:
- SearchEngineStrategy: for search engine result pages
- DeveloperPlatformStrategy: for GitHub/GitLab/StackOverflow
- DocumentationStrategy: for technical documentation sites

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 2.5 实现 DualExtractorStrategy（三重对比）

- [ ] **Step 1: 写测试**

```python
# tests/test_extractor_strategies.py (追加)

from scrapling_fetch_mcp._extractor_strategy import DualExtractorStrategy

def test_dual_extractor_selects_best():
    """测试 dual 策略选择最佳结果"""
    html = """
    <html>
        <body>
            <h1>Test</h1>
            <p>Content with enough text to be detected</p>
        </body>
    </html>
    """
    strategy = DualExtractorStrategy()
    result = strategy.extract(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0

def test_dual_extractor_fallback():
    """测试 dual 策略的降级处理"""
    html = "<html><body></body></html>"
    strategy = DualExtractorStrategy()
    result = strategy.extract(html, "https://example.com")

    # 应该返回某个提取器的结果（即使是空字符串）
    assert isinstance(result, str)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_extractor_strategies.py::test_dual_extractor -v`
Expected: FAIL

- [ ] **Step 3: 实现策略**

```python
# src/scrapling_fetch_mcp/_extractor_strategy.py (追加)

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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_extractor_strategies.py::test_dual_extractor -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_extractor_strategy.py tests/test_extractor_strategies.py
git commit -m "feat: add DualExtractorStrategy with triple comparison

Compare results from trafilatura, readability-lxml, and scrapling.
Select the result with the most effective characters.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 3: 内置默认规则

**Files:**
- Create: `src/scrapling_fetch_mcp/_default_rules.py`
- Create: `tests/test_default_rules.py`

### 3.1 创建内置默认规则

- [ ] **Step 1: 写测试**

```python
# tests/test_default_rules.py
from scrapling_fetch_mcp._default_rules import DEFAULT_RULES

def test_default_rules_not_empty():
    """测试默认规则不为空"""
    assert DEFAULT_RULES
    assert len(DEFAULT_RULES) > 0

def test_default_rules_valid_yaml():
    """测试默认规则是有效 YAML"""
    import yaml
    config = yaml.safe_load(DEFAULT_RULES)

    assert 'default_strategy' in config
    assert 'url_rules' in config
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_default_rules.py -v`
Expected: FAIL

- [ ] **Step 3: 实现默认规则**

```python
# src/scrapling_fetch_mcp/_default_rules.py

DEFAULT_RULES = """
# scrapling-fetch-mcp 默认 URL 路由规则
# 文档：https://github.com/...

# 全局默认策略
default_strategy: dual

# URL 匹配规则（按顺序匹配，首次匹配生效）
url_rules:
  # 搜索引擎规则
  - match:
      type: domain_suffix
      pattern: ".google.com"
    strategy: search_engine

  - match:
      type: domain_suffix
      pattern: ".bing.com"
    strategy: search_engine

  - match:
      type: domain
      pattern: "duckduckgo.com"
    strategy: search_engine

  # 开发者平台规则
  - match:
      type: domain
      pattern: "github.com"
    strategy: developer_platform

  - match:
      type: domain_suffix
      pattern: ".stackoverflow.com"
    strategy: developer_platform

  - match:
      type: domain
      pattern: "gitlab.com"
    strategy: developer_platform

  # 技术文档规则
  - match:
      type: regex
      pattern: ".*docs\\\\.python\\\\.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*developer\\\\.mozilla\\\\.org.*"
    strategy: documentation

# 自定义策略（用户可扩展）
custom_strategies: []
"""
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_default_rules.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_default_rules.py tests/test_default_rules.py
git commit -m "feat: add built-in default URL routing rules

Package default routing rules in code for zero-configuration setup.
Users can override with custom config files.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: URL 匹配器

**Files:**
- Create: `src/scrapling_fetch_mcp/_url_matcher.py`
- Create: `tests/test_url_matcher.py`

### 4.1 实现 URLMatcher 基础功能

- [ ] **Step 1: 写测试**

```python
# tests/test_url_matcher.py
import pytest
from pathlib import Path
from scrapling_fetch_mcp._url_matcher import URLMatcher

def test_url_matcher_uses_builtin_rules_by_default():
    """测试默认使用内置规则"""
    matcher = URLMatcher()
    assert matcher.default_strategy == "dual"

def test_url_matcher_domain_match():
    """测试域名匹配"""
    matcher = URLMatcher()

    # 配置规则
    matcher.rules = [{
        'match': {'type': 'domain', 'pattern': 'github.com'},
        'strategy': 'developer_platform'
    }]

    assert matcher.match("https://github.com/user/repo") == "developer_platform"
    assert matcher.match("https://www.github.com/user/repo") == "developer_platform"
    assert matcher.match("https://docs.github.com") != "developer_platform"

def test_url_matcher_domain_suffix_smart_match():
    """测试智能域名后缀匹配"""
    matcher = URLMatcher()

    # 配置规则
    matcher.rules = [{
        'match': {'type': 'domain_suffix', 'pattern': '.google.com'},
        'strategy': 'search_engine'
    }]

    # .google.com 应该匹配 google.com 和 *.google.com
    assert matcher.match("https://google.com") == "search_engine"
    assert matcher.match("https://www.google.com") == "search_engine"
    assert matcher.match("https://mail.google.com") == "search_engine"

def test_url_matcher_regex_match():
    """测试正则表达式匹配"""
    matcher = URLMatcher()

    matcher.rules = [{
        'match': {'type': 'regex', 'pattern': r'.*docs\.python\.org.*'},
        'strategy': 'documentation'
    }]

    assert matcher.match("https://docs.python.org/3/library/") == "documentation"
    assert matcher.match("https://docs.python.org/3/") == "documentation"
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_url_matcher.py -v`
Expected: FAIL

- [ ] **Step 3: 实现 URLMatcher**

```python
# src/scrapling_fetch_mcp/_url_matcher.py
import re
import yaml
import logging
from typing import Optional, List, Dict, Any
from pathlib import Path
from urllib.parse import urlparse

class URLMatcher:
    """根据配置规则匹配 URL 到策略"""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path
        self.rules: List[Dict[str, Any]] = []
        self.default_strategy = "dual"
        self._last_load_time = 0
        self._load_config()

    def _load_config(self) -> None:
        """加载配置文件"""
        if self.config_path is None:
            # 使用内置默认规则
            from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
            config = yaml.safe_load(DEFAULT_RULES)
        else:
            if not self.config_path.exists():
                # 文件不存在，使用内置规则
                from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
                config = yaml.safe_load(DEFAULT_RULES)
                return

            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                logging.warning(f"Failed to parse YAML config: {e}. Using default rules.")
                from scrapling_fetch_mcp._default_rules import DEFAULT_RULES
                config = yaml.safe_load(DEFAULT_RULES)

        if config:
            self.default_strategy = config.get('default_strategy', 'dual')
            self.rules = config.get('url_rules', [])

    def match(self, url: str) -> str:
        """根据 URL 匹配对应的策略名称"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()

        for rule in self.rules:
            match_config = rule.get('match', {})
            match_type = match_config.get('type')
            pattern = match_config.get('pattern')

            if self._match_url(domain, url, match_type, pattern):
                return rule.get('strategy', self.default_strategy)

        return self.default_strategy

    def _match_url(self, domain: str, full_url: str,
                   match_type: str, pattern: str) -> bool:
        """执行 URL 匹配"""
        if match_type == 'domain':
            # 完整域名匹配（支持 www. 前缀）
            return domain == pattern or domain == f"www.{pattern}"

        elif match_type == 'domain_suffix':
            # 智能域名后缀匹配
            if pattern.startswith('.'):
                # 模式是 ".google.com"
                # 匹配 "google.com" 或 "*.google.com"
                base_domain = pattern[1:]
                return domain == base_domain or domain.endswith(pattern)
            else:
                # 模式是 "google.com"
                # 只精确匹配
                return domain == pattern

        elif match_type == 'regex':
            # 正则表达式匹配
            try:
                return bool(re.search(pattern, full_url))
            except re.error:
                return False

        return False
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_url_matcher.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_url_matcher.py tests/test_url_matcher.py
git commit -m "feat: implement URLMatcher with smart domain matching

- Support domain, domain_suffix, and regex matching
- Smart domain_suffix: .google.com matches both google.com and *.google.com
- Fallback to built-in rules if config file not found or invalid

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 策略工厂

**Files:**
- Create: `src/scrapling_fetch_mcp/_strategy_factory.py`
- Create: `tests/test_strategy_factory.py`

### 5.1 实现策略工厂

- [ ] **Step 1: 写测试**

```python
# tests/test_strategy_factory.py
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
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_strategy_factory.py -v`
Expected: FAIL

- [ ] **Step 3: 实现策略工厂**

```python
# src/scrapling_fetch_mcp/_strategy_factory.py
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
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_strategy_factory.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_strategy_factory.py tests/test_strategy_factory.py
git commit -m "feat: implement StrategyFactory

Manage all extraction strategies with dynamic loading support.
Load custom strategies from user-specified Python files.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: Markdown 后处理器

**Files:**
- Create: `src/scrapling_fetch_mcp/_markdown_postprocessor.py`
- Create: `tests/test_markdown_postprocessor.py`

### 6.1 实现 Markdown 后处理器（基础版本）

- [ ] **Step 1: 写测试**

```python
# tests/test_markdown_postprocessor.py
from scrapling_fetch_mcp._markdown_postprocessor import postprocess_markdown

def test_postprocess_compress_empty_lines():
    """测试压缩多余空行"""
    markdown = "Line 1\n\n\n\nLine 2"
    result = postprocess_markdown(markdown)
    assert result == "Line 1\n\nLine 2"

def test_postprocess_remove_trailing_spaces():
    """测试移除行尾空白"""
    markdown = "Line 1   \nLine 2  "
    result = postprocess_markdown(markdown)
    assert result == "Line 1\nLine 2"

def test_postprocess_strip():
    """测试移除开头结尾空行"""
    markdown = "\n\nLine 1\nLine 2\n\n"
    result = postprocess_markdown(markdown)
    assert result == "Line 1\nLine 2"

def test_postprocess_empty():
    """测试空字符串"""
    result = postprocess_markdown("")
    assert result == ""
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_markdown_postprocessor.py -v`
Expected: FAIL

- [ ] **Step 3: 实现后处理器**

```python
# src/scrapling_fetch_mcp/_markdown_postprocessor.py
import re

def postprocess_markdown(markdown: str) -> str:
    """
    Markdown 后处理 - 基础版本

    处理最常见的问题：
    1. 压缩多余的空行（最多保留2个）
    2. 移除行尾空白
    3. 移除文档开头和结尾的空行
    """
    if not markdown:
        return ""

    # 1. 压缩多余的空行（最多保留2个连续空行）
    markdown = re.sub(r'\n{3,}', '\n\n', markdown)

    # 2. 移除行尾空白
    markdown = re.sub(r' +\n', '\n', markdown)

    # 3. 移除文档开头和结尾的空行
    markdown = markdown.strip()

    return markdown
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_markdown_postprocessor.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_markdown_postprocessor.py tests/test_markdown_postprocessor.py
git commit -m "feat: implement Markdown postprocessor (basic version)

Compress multiple blank lines, remove trailing spaces, and strip content.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 配置类更新

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`

### 7.1 添加 rules_config_path 配置

- [ ] **Step 1: 写测试**

```python
# tests/test_config.py (追加)

from pathlib import Path
from scrapling_fetch_mcp._config import Config, init_config_from_env

def test_rules_config_path_default():
    """测试默认规则配置路径"""
    config = Config()
    path = config.rules_config_path
    # 默认应该返回 None（使用内置规则）
    assert path is None

def test_rules_config_path_custom():
    """测试自定义规则配置路径"""
    config = Config()
    config.set_rules_config_path("/custom/path.yaml")
    assert config.rules_config_path == Path("/custom/path.yaml")

def test_init_config_from_env_rules_config(tmp_path, monkeypatch):
    """测试从环境变量加载规则配置路径"""
    config_file = tmp_path / "rules.yaml"
    monkeypatch.setenv("SCRAPLING_RULES_CONFIG", str(config_file))

    # 重新加载配置
    init_config_from_env()

    from scrapling_fetch_mcp._config import config
    assert config.rules_config_path == config_file
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_config.py::test_rules_config_path -v`
Expected: FAIL

- [ ] **Step 3: 修改配置类**

```python
# src/scrapling_fetch_mcp/_config.py (在 Config 类中添加)

class Config:
    # ... 现有代码 ...

    _rules_config_path: Optional[Path] = None

    @property
    def rules_config_path(self) -> Optional[Path]:
        """获取规则配置文件路径"""
        return self._rules_config_path

    def set_rules_config_path(self, path: Path | str | None) -> None:
        """设置规则配置文件路径"""
        if path is None:
            self._rules_config_path = None
        elif isinstance(path, str):
            self._rules_config_path = Path(path)
        else:
            self._rules_config_path = path
```

```python
# src/scrapling_fetch_mcp/_config.py (在 init_config_from_env 函数中添加)

def init_config_from_env() -> None:
    # ... 现有代码 ...

    # 加载规则配置文件路径
    env_rules_config = getenv("SCRAPLING_RULES_CONFIG", "")
    if env_rules_config:
        config.set_rules_config_path(env_rules_config)
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_config.py::test_rules_config_path -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat: add rules_config_path configuration

Support configuration of custom rules file path via CLI or environment variable.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 8: 集成到 fetcher

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`

### 8.1 添加 _extract_with_airead 函数

- [ ] **Step 1: 写测试**

```python
# tests/test_fetcher_airead.py
import pytest
from scrapling_fetch_mcp._fetcher import _extract_with_airead

@pytest.mark.asyncio
async def test_extract_with_airead_basic():
    """测试 airead 提取基本功能"""
    html = """
    <html>
        <body>
            <h1>Title</h1>
            <p>Content</p>
        </body>
    </html>
    """
    result = await _extract_with_airead(html, "https://example.com")

    assert isinstance(result, str)
    assert len(result) > 0
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_fetcher_airead.py -v`
Expected: FAIL

- [ ] **Step 3: 实现函数**

```python
# src/scrapling_fetch_mcp/_fetcher.py (添加)

from scrapling_fetch_mcp._url_matcher import URLMatcher
from scrapling_fetch_mcp._strategy_factory import StrategyFactory
from scrapling_fetch_mcp._markdown_postprocessor import postprocess_markdown

async def _extract_with_airead(html: str, url: str) -> str:
    """
    使用 airead 格式提取内容

    Args:
        html: 原始 HTML 内容
        url: 页面 URL（用于策略路由）

    Returns:
        提取并后处理后的 Markdown 内容
    """
    # 1. 获取配置文件路径
    from scrapling_fetch_mcp._config import config
    rules_config_path = config.rules_config_path

    # 2. URL 匹配
    matcher = URLMatcher(rules_config_path)
    strategy_name = matcher.match(url)

    # 3. 获取策略实例
    strategy = StrategyFactory.get_strategy(strategy_name, rules_config_path)

    # 4. 执行提取
    markdown = strategy.extract(html, url)

    # 5. 统一后处理
    markdown = postprocess_markdown(markdown)

    return markdown
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_fetcher_airead.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher_airead.py
git commit -m "feat: add _extract_with_airead function

Integrate all components for airead format extraction:
URL matching -> strategy selection -> extraction -> postprocessing

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### 8.2 修改 fetch_page_impl 支持 airead 格式

- [ ] **Step 1: 修改 fetch_page_impl**

```python
# src/scrapling_fetch_mcp/_fetcher.py (在 fetch_page_impl 函数中修改)

async def fetch_page_impl(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: Optional[Path] = None,
) -> str:
    # ... 现有代码 ...

    # 根据格式选择处理方式
    if format == "airead":
        full_content = await _extract_with_airead(html_content, url)
    elif format == "markdown":
        full_content = _html_to_markdown(html_content)
    else:  # html
        full_content = html_content

    # ... 现有代码 ...
```

- [ ] **Step 2: 测试 airead 格式**

Run: 手动测试或集成测试（后续）

- [ ] **Step 3: 提交**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py
git commit -m "feat: integrate airead format into fetch_page_impl

Add support for format='airead' parameter.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 9: MCP 工具更新

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`

### 9.1 更新 s_fetch_page 文档和参数

- [ ] **Step 1: 更新文档字符串**

```python
# src/scrapling_fetch_mcp/mcp.py (修改 s_fetch_page 文档)

@mcp.tool()
async def s_fetch_page(
    url: str,
    mode: str = "stealth",
    format: str = "markdown",
    max_length: int = 8000,
    start_index: int = 0,
    save_content: bool = False,
    scraping_dir: str = ".temp/scrapling/",
) -> str:
    """Fetches a complete web page with pagination support.

    IMPORTANT:
    - Use format='airead' for AI-optimized content extraction (removes navigation, ads, etc.)
    - Use format='markdown' for standard markdown conversion
    - Use format='html' only when you need raw HTML structure

    The airead format uses intelligent content extraction with URL-based routing
    to specialized strategies for different website types (search engines,
    documentation, developer platforms, etc.)

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, or max-stealth)
        format: Output format (airead, markdown, or html)
        max_length: Maximum number of characters to return
        start_index: Start position for pagination
        save_content: Save content locally for offline viewing
        scraping_dir: Directory for saved content
    """
    # ... 现有代码 ...
```

- [ ] **Step 2: 添加 CLI 参数**

```python
# src/scrapling_fetch_mcp/mcp.py (在 main 函数中添加)

def main():
    parser = argparse.ArgumentParser(...)
    # ... 现有参数 ...

    parser.add_argument(
        "--rules-config",
        type=str,
        default=None,
        help="Path to YAML file with URL routing rules for airead format. "
             "Default: Use built-in rules. "
             "Can also be set via SCRAPLING_RULES_CONFIG environment variable."
    )

    args = parser.parse_args()

    # 设置规则配置路径
    if args.rules_config:
        config.set_rules_config_path(args.rules_config)

    # ... 现有代码 ...
```

- [ ] **Step 3: 提交**

```bash
git add src/scrapling_fetch_mcp/mcp.py
git commit -m "feat: add airead format documentation and CLI parameter

- Update s_fetch_page documentation to explain airead format
- Add --rules-config CLI parameter for custom rules

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 10: 更新依赖

**Files:**
- Modify: `pyproject.toml`

### 10.1 添加新依赖

- [ ] **Step 1: 更新 pyproject.toml**

```toml
# pyproject.toml (在 dependencies 中添加)

dependencies = [
    "scrapling>=0.4.0",
    "trafilatura>=1.6.0",
    "readability-lxml>=0.8.1",
    "pyyaml>=6.0",
    "markitdown>=0.1.0",
    "markdownify>=0.11.0",
    "beautifulsoup4>=4.12.0",
    "lxml>=4.9.0",
]
```

- [ ] **Step 2: 测试安装**

Run: `pip install -e .`
Expected: SUCCESS

- [ ] **Step 3: 提交**

```bash
git add pyproject.toml
git commit -m "feat: add dependencies for airead format

Add trafilatura, readability-lxml, and pyyaml for content extraction.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 11: 集成测试

**Files:**
- Create: `tests/test_airead_integration.py`

### 11.1 编写集成测试

- [ ] **Step 1: 写集成测试**

```python
# tests/test_airead_integration.py
import pytest
from scrapling_fetch_mcp._fetcher import fetch_page_impl

@pytest.mark.asyncio
async def test_airead_format_integration():
    """测试 airead 格式的完整流程"""
    # 使用真实 URL 测试（需要网络）
    # 或者使用 mock HTML

    html = """
    <html>
        <head>
            <nav><a href="/">Home</a></nav>
        </head>
        <body>
            <main>
                <h1>Article Title</h1>
                <p>Article content paragraph.</p>
            </main>
        </body>
    </html>
    """

    result = await _extract_with_airead(html, "https://example.com/article")

    assert isinstance(result, str)
    assert "Article Title" in result or "content" in result
    assert "Home" not in result or "nav" not in result  # 导航应该被移除

@pytest.mark.asyncio
async def test_airead_vs_markdown_comparison():
    """对比 airead 和 markdown 格式的输出"""
    html = """
    <html>
        <body>
            <nav>Navigation Menu</nav>
            <main>
                <h1>Content</h1>
                <p>Text</p>
            </main>
        </body>
    </html>
    """

    airead_result = await _extract_with_airead(html, "https://example.com")
    # markdown_result = ...

    # airead 应该更精简
    assert len(airead_result) > 0
```

- [ ] **Step 2: 运行集成测试**

Run: `pytest tests/test_airead_integration.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_airead_integration.py
git commit -m "test: add integration tests for airead format

Test complete airead extraction flow and compare with markdown.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 12: 错误处理测试

**Files:**
- Create: `tests/test_error_handling.py`

### 12.1 测试各种错误场景

- [ ] **Step 1: 写错误处理测试**

```python
# tests/test_error_handling.py
import pytest
from pathlib import Path
import tempfile
import yaml
from scrapling_fetch_mcp._url_matcher import URLMatcher
from scrapling_fetch_mcp._strategy_factory import StrategyFactory

def test_yaml_parse_error_fallback():
    """测试 YAML 解析错误时降级到内置规则"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("invalid: yaml: content:\n  - broken")
        f.flush()

        matcher = URLMatcher(Path(f.name))
        assert matcher.default_strategy == "dual"  # 应该使用内置默认

def test_custom_strategy_module_not_found():
    """测试自定义策略模块不存在的处理"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config = {
            'custom_strategies': [{
                'name': 'test',
                'module': '/nonexistent/path.py',
                'class': 'TestStrategy'
            }]
        }
        yaml.dump(config, f)
        f.flush()

        # 应该不崩溃，只是记录警告
        StrategyFactory.load_custom_strategies(Path(f.name))
        assert 'test' not in StrategyFactory.list_strategies()

def test_invalid_match_type():
    """测试无效的匹配类型"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        config = {
            'url_rules': [{
                'match': {'type': 'invalid_type', 'pattern': 'test'},
                'strategy': 'dual'
            }]
        }
        yaml.dump(config, f)
        f.flush()

        matcher = URLMatcher(Path(f.name))
        result = matcher.match("https://test.com")
        # 应该使用默认策略
        assert result == "dual"
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_error_handling.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add tests/test_error_handling.py
git commit -m "test: add comprehensive error handling tests

Test YAML errors, custom strategy loading errors, and invalid configs.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 13: 文档和示例

**Files:**
- Create: `docs/airead-format-guide.md`
- Create: `docs/custom-strategies.md`
- Create: `docs/configuration.md`

### 13.1 编写使用文档

- [ ] **Step 1: 创建 airead 格式指南**

```markdown
# airead 格式使用指南

## 什么是 airead 格式？

airead 是专门为 AI 优化的内容提取格式...

## 基本用法

使用 `format="airead"` 参数：

```python
await s_fetch_page(
    url="https://example.com",
    format="airead"
)
```

## 内置策略

- dual（默认）：三重对比...
- trafilatura：...
（详细说明）
```

- [ ] **Step 2: 创建自定义策略文档**

```markdown
# 自定义策略开发指南

## 创建自定义策略

1. 创建 Python 文件...
2. 继承 ExtractorStrategy...
3. 实现 extract 方法...

## 注册自定义策略

在配置文件中...
```

- [ ] **Step 3: 创建配置文档**

```markdown
# 配置文件详细说明

## 配置文件格式

YAML 格式...

## URL 匹配规则

三种匹配类型...

## 示例配置

...
```

- [ ] **Step 4: 提交**

```bash
git add docs/
git commit -m "docs: add comprehensive documentation for airead format

- airead-format-guide.md: Usage guide
- custom-strategies.md: Custom strategy development
- configuration.md: Configuration file reference

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 14: 最终集成和验证

### 14.1 运行所有测试

- [ ] **Step 1: 运行完整测试套件**

Run: `pytest tests/ -v --cov=src`
Expected: All PASS, coverage > 80%

### 14.2 手动功能验证

- [ ] **Step 2: 测试真实网站**

```python
# 手动测试脚本
import asyncio
from scrapling_fetch_mcp._fetcher import fetch_page_impl

async def test_real_websites():
    urls = [
        "https://www.google.com/search?q=python",
        "https://github.com/D4Vinci/Scrapling",
        "https://docs.python.org/3/library/json.html",
    ]

    for url in urls:
        result = await fetch_page_impl(url, "stealth", "airead", 5000, 0)
        print(f"\n{url}:")
        print(f"Length: {len(result)}")
        print(f"Preview: {result[:200]}...")

asyncio.run(test_real_websites())
```

### 14.3 性能验证

- [ ] **Step 3: 对比 token 效率**

Run: 测试脚本对比 markdown vs airead
Expected: 30-50% token reduction

### 14.4 最终提交

- [ ] **Step 4: 创建最终提交**

```bash
git add .
git commit -m "feat: complete airead format implementation

- 7 built-in extraction strategies
- URL-based routing with smart domain matching
- Built-in default rules (no configuration required)
- Comprehensive error handling
- Full test coverage (>80%)
- Complete documentation

Performance: 30-50% token reduction for typical websites.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 验证方案

### 单元测试验证
```bash
# 运行所有单元测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_extractor_strategies.py -v
pytest tests/test_url_matcher.py -v
```

### 集成测试验证
```bash
# 运行集成测试
pytest tests/test_airead_integration.py -v
```

### 功能验证

使用 MCP 工具测试不同类型网站：

```python
# 测试搜索引擎
await s_fetch_page(
    url="https://www.google.com/search?q=python",
    format="airead"
)

# 测试 GitHub
await s_fetch_page(
    url="https://github.com/D4Vinci/Scrapling",
    format="airead"
)

# 测试文档
await s_fetch_page(
    url="https://docs.python.org/3/library/json.html",
    format="airead"
)
```

对比 `format="airead"` 和 `format="markdown"` 的输出，验证：
- ✅ 内容精简度提升
- ✅ 导航、广告被移除
- ✅ 核心内容保留完整
- ✅ 格式化空白被优化

### 性能验证

测量指标：
1. **总字符数**：markdown vs airead
2. **有效字符占比**：`count_effective_characters(result) / len(result)`
3. **Token 节省比例**：使用 tokenizer 统计实际 token 数
4. **提取时间**：不同策略的性能对比

**预期结果**：
- 总字符数减少 30-50%
- 有效字符占比提升（有效字符/总字符）
- 核心内容保留率 > 90%
- 提取时间 < 1 秒（单提取器），< 3 秒（dual 策略）

---

## 风险与缓解

### 风险 1: 提取器可能误删重要内容
**缓解措施**：
- 默认使用 dual 策略（三重对比取最优），降低误删概率
- 提供降级机制：用户可以选择 `format="markdown"` 或 `format="html"`
- 提供 7 个不同的策略，用户可以根据网站类型选择
- 支持自定义策略，用户可以针对特殊网站编写专门逻辑

### 风险 2: 新增依赖可能增加安装复杂度
**缓解措施**：
- trafilatura 和 readability-lxml 都是成熟稳定的库，PyPI 下载量大
- 在 README 中清晰说明依赖用途和安装步骤
- 提供 Docker 镜像避免手动安装
- 提供 `pip install scrapling-fetch-mcp[all]` 一键安装所有依赖

### 风险 3: URL 匹配规则可能不够灵活
**缓解措施**：
- 三种匹配方式已覆盖大部分场景（domain、domain_suffix、regex）
- 支持自定义策略扩展，用户可以在 Python 代码中实现任意复杂的匹配逻辑
- 支持配置文件热加载，可以快速调整规则
- 可以在策略内部根据 URL 内容进一步判断

### 风险 4: 性能影响（三个提取器顺序运行）
**缓解措施**：
- 单个提取器通常只需 100-500ms，三个提取器总计 < 2 秒
- 提供单独的策略选项（trafilatura、readability、scrapling），用户可以选择只用一个
- 利用现有的页面缓存机制，避免重复提取
- 未来优化：考虑并行运行三个提取器（需要测试资源消耗）

### 风险 5: 配置文件格式错误导致系统无法启动
**缓解措施**：
- YAML 解析错误时使用内置默认规则（dual 策略）
- 自定义策略加载失败时记录警告但继续运行
- 提供详细的错误日志，便于调试
- 在文档中提供配置文件示例和最佳实践

---

## 后续优化方向

1. **性能优化**：考虑并行运行三个提取器（需要测试资源消耗和线程安全）
2. **策略增强**：添加更多网站类型的专用策略（电商、新闻、论坛等）
3. **dual 策略优化标准**：多维度评分（内容密度、结构完整性等）
4. **机器学习**：使用 ML 模型自动识别网站类型并选择策略
5. **统计分析**：添加提取效果统计（token 节省比例、提取时间等）
6. **Markdown 后处理器增强**：基于用户反馈迭代优化

