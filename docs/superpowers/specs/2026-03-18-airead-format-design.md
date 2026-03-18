# airead 格式设计文档

**日期**: 2026-03-18
**状态**: 设计完成，待实现
**作者**: Claude Sonnet 4.6

## 背景

当前 `scrapling-fetch-mcp` 项目支持两种输出格式：
- `html`：原始 HTML 内容
- `markdown`：转换后的 Markdown 内容

这两种格式都包含大量冗余数据，不利于 AI 读取：
- **HTML 结构冗余**：过多的 div、span 标签，深层嵌套，保留不必要的属性（class、id 等）
- **导航和广告**：页面顶部导航栏、侧边栏、底部链接、广告、弹窗等非核心内容
- **格式化空白**：过多的空行、缩进、空白字符

这导致 AI 在处理时浪费大量 token，增加了成本和处理时间。

## 目标

设计并实现 `airead` 格式，提供 AI 优化的内容提取能力：

1. **智能内容提取**：自动识别并提取页面核心内容，去除导航、广告等冗余
2. **最大化精简度**：在保留语义结构的前提下，最小化 token 消耗
3. **灵活可扩展**：支持针对不同网站类型的专门优化策略
4. **用户可控**：提供配置机制让用户自定义提取规则

## 设计方案

### 核心架构

采用**策略模式 + URL 路由**的架构：

```
用户请求 (format="airead", url="...")
    ↓
URLMatcher（根据配置匹配 URL）
    ↓
StrategyFactory（获取策略实例）
    ↓
ExtractorStrategy（执行内容提取）
    ↓
Markdown 后处理（统一优化）
    ↓
返回精简的 Markdown 内容
```

### 1. 策略接口

**文件**: `src/scrapling_fetch_mcp/_extractor_strategy.py`

```python
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

### 2. 内置策略

共 7 个内置策略：

#### 2.1 dual（默认策略）

同时运行三个提取器（trafilatura、readability-lxml、scrapling），对比有效字数，取最优结果。

**有效字符统计方法**：
```python
def count_effective_characters(text: str) -> int:
    """
    计算有效字符数（纯文本内容）

    步骤：
    1. 移除所有 Markdown 标记字符（标题、粗体、链接等）
    2. 保留链接/图片的文本内容
    3. 移除所有空白字符（包括 Unicode 空白）
    4. 统计剩余字符
    """
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

**实现**：
```python
class DualExtractorStrategy(ExtractorStrategy):
    """三重提取器对比策略"""

    def extract(self, html: str, url: str) -> str:
        # 运行三个提取器
        result_trafilatura = self._extract_with_trafilatura(html, url)
        result_readability = self._extract_with_readability(html, url)
        result_scrapling = self._extract_with_scrapling(html, url)

        # 对比有效字数
        results = [
            (count_effective_characters(result_trafilatura), result_trafilatura),
            (count_effective_characters(result_readability), result_readability),
            (count_effective_characters(result_scrapling), result_scrapling)
        ]

        # 返回字数最多的结果
        return max(results, key=lambda x: x[0])[1]
```

#### 2.2 trafilatura

仅使用 trafilatura 库提取内容。

**适用场景**：通用网页，技术文档，新闻文章

#### 2.3 readability

仅使用 readability-lxml 库提取内容。

**适用场景**：通用网页，博客文章

#### 2.4 scrapling

使用 Scrapling 内置的 Markdown 转换功能。

**适用场景**：Scrapling 原生支持的场景

#### 2.5 search_engine

搜索引擎专用策略。

**适用场景**：Google、Bing、DuckDuckGo 等搜索引擎结果页

**实现特点**：
- 使用 trafilatura 的 `favor_precision=True` 参数
- 优化搜索结果的提取精确度

#### 2.6 developer_platform

开发者平台专用策略。

**适用场景**：GitHub、GitLab、StackOverflow 等

**实现特点**：
- 保留代码块、README、issue 讨论
- 保留表格结构
- 使用 `include_tables=True` 参数

#### 2.7 documentation

技术文档专用策略。

**适用场景**：Python 文档、MDN、各技术栈官方文档

**实现特点**：
- 保留标题层级、代码示例、API 文档结构
- 使用 `favor_precision=True` 和 `include_code=True`

### 3. URL 路由机制

**文件**: `src/scrapling_fetch_mcp/_url_matcher.py`

#### 3.1 配置文件管理

**配置策略**：
- **内置默认规则**：在代码中内置一套默认的 URL 路由规则
- **用户自定义规则**：用户可通过参数指定自定义配置文件
- **优先级**：用户指定配置 > 内置默认规则

**配置文件来源**：
1. **用户指定**（最高优先级）：
   - CLI 参数：`--rules-config /path/to/custom_rules.yaml`
   - 环境变量：`SCRAPLING_RULES_CONFIG=/path/to/custom_rules.yaml`

2. **内置默认规则**：
   - 当用户未指定配置文件时，使用代码中内置的默认规则
   - 无需任何配置即可开箱即用

#### 3.2 内置默认规则

**文件**: `src/scrapling_fetch_mcp/_default_rules.py`

```python
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
      pattern: ".*docs\\.python\\.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*developer\\.mozilla\\.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*readthedocs\\.io.*"
    strategy: documentation

# 自定义策略（用户可扩展）
custom_strategies: []
"""
```

#### 3.3 用户自定义规则示例

用户可创建自定义配置文件来覆盖或扩展默认规则：

**示例文件**: `my_rules.yaml`

```yaml
# 全局默认策略
default_strategy: dual

# 自定义 URL 匹配规则
url_rules:
  # 维基百科
  - match:
      type: domain_suffix
      pattern: ".wikipedia.org"
    strategy: wiki_extractor

  # 电商网站（使用自定义策略）
  - match:
      type: domain_suffix
      pattern: ".amazon.com"
    strategy: ecommerce

# 自定义策略
custom_strategies:
  - name: "wiki_extractor"
    module: "/home/user/.scrapling/my_strategies.py"
    class: "WikiExtractorStrategy"

  - name: "ecommerce"
    module: "/home/user/.scrapling/my_strategies.py"
    class: "EcommerceStrategy"
```

#### 3.4 匹配方式

支持三种 URL 匹配方式：

1. **domain**：完整域名匹配
   - `github.com` 匹配 `github.com` 和 `www.github.com`
   - 不匹配 `docs.github.com`

2. **domain_suffix**：域名后缀匹配（智能匹配）
   - **模式 `".google.com"`**：匹配 `google.com`、`www.google.com`、`mail.google.com`、`docs.google.com`
   - **模式 `"google.com"`**：只精确匹配 `google.com`
   - **智能逻辑**：如果模式以 `.` 开头，自动匹配顶级域名和所有子域名

   **实现逻辑**：
   ```python
   if match_type == 'domain_suffix':
       if pattern.startswith('.'):
           # 模式是 ".google.com"
           # 匹配 "google.com" 或 "*.google.com"
           base_domain = pattern[1:]  # "google.com"
           return (
               domain == base_domain or  # 匹配顶级域名
               domain.endswith(pattern)   # 匹配子域名
           )
       else:
           # 模式是 "google.com"
           # 只精确匹配
           return domain == pattern
   ```

3. **regex**：正则表达式匹配
   - `.*docs\\.python\\.org.*` 匹配所有包含 `docs.python.org` 的 URL
   - 最灵活但性能稍低

#### 3.5 热加载机制

URLMatcher 会检测配置文件的修改时间：
- 每次匹配请求时检查文件 mtime
- 如果文件被修改，重新加载配置
- 无需重启 MCP 服务器

#### 3.6 错误处理机制

完整的错误处理确保系统在各种异常情况下仍能正常工作。

##### 3.6.1 YAML 解析失败

**场景**：配置文件语法错误

```yaml
# 错误示例：缩进错误
url_rules:
  - match:
      type: domain
    pattern: "github.com"  # 错误的缩进
```

**处理方案**：
```python
def _load_config(self) -> None:
    """加载配置文件，处理 YAML 解析错误"""
    try:
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        import logging
        logging.warning(
            f"Failed to parse YAML config {self.config_path}: {e}. "
            f"Falling back to built-in default rules."
        )
        # 降级到内置默认规则
        config = yaml.safe_load(DEFAULT_RULES)
    except FileNotFoundError:
        # 文件不存在，使用内置默认规则（静默处理）
        config = yaml.safe_load(DEFAULT_RULES)

    self._apply_config(config)
```

##### 3.6.2 自定义策略模块加载失败

**场景1**：模块文件不存在

```yaml
custom_strategies:
  - name: "my_strategy"
    module: "/nonexistent/path.py"  # 文件不存在
    class: "MyStrategy"
```

**处理方案**：
```python
try:
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None:
        raise FileNotFoundError(f"Module not found: {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
except FileNotFoundError as e:
    logging.warning(
        f"Custom strategy module not found: {module_path}. "
        f"Strategy '{name}' will not be available."
    )
    continue
```

**场景2**：类不存在

```yaml
custom_strategies:
  - name: "my_strategy"
    module: "/path/to/module.py"
    class: "NonexistentClass"  # 类不存在
```

**处理方案**：
```python
try:
    strategy_class = getattr(module, class_name)
except AttributeError:
    logging.warning(
        f"Class '{class_name}' not found in module {module_path}. "
        f"Available classes: {[x for x in dir(module) if not x.startswith('_')]}. "
        f"Strategy '{name}' will not be available."
    )
    continue
```

**场景3**：类不继承 ExtractorStrategy

```python
# 用户的代码
class MyStrategy:  # 错误：没有继承 ExtractorStrategy
    def extract(self, html, url):
        return ""
```

**处理方案**：
```python
if not issubclass(strategy_class, ExtractorStrategy):
    logging.warning(
        f"Custom strategy '{name}' must inherit from ExtractorStrategy. "
        f"Current base classes: {strategy_class.__bases__}. "
        f"Strategy will not be available."
    )
    continue
```

##### 3.6.3 配置值无效

**场景**：未知的匹配类型或策略名称

```yaml
url_rules:
  - match:
      type: invalid_type  # 无效的匹配类型
    strategy: nonexistent_strategy  # 不存在的策略
```

**处理方案**：
```python
def _validate_rule(self, rule: dict) -> bool:
    """验证规则配置是否有效"""
    match_config = rule.get('match', {})
    match_type = match_config.get('type')
    strategy = rule.get('strategy')

    # 验证匹配类型
    valid_types = ['domain', 'domain_suffix', 'regex']
    if match_type not in valid_types:
        logging.warning(
            f"Invalid match type '{match_type}' in rule. "
            f"Valid types: {valid_types}. Rule will be ignored."
        )
        return False

    # 验证策略是否存在（内置 + 已加载的自定义）
    available_strategies = StrategyFactory.list_strategies()
    if strategy not in available_strategies:
        logging.warning(
            f"Unknown strategy '{strategy}' in rule. "
            f"Available strategies: {available_strategies}. "
            f"Rule will be ignored."
        )
        return False

    return True
```

##### 3.6.4 运行时提取失败

**场景**：提取过程中发生异常

**处理方案**：
```python
def extract(self, html: str, url: str) -> str:
    """提取内容，处理运行时错误"""
    try:
        return self._do_extract(html, url)
    except Exception as e:
        import logging
        logging.error(
            f"Extraction failed for {url} using strategy {self.__class__.__name__}: {e}"
        )
        # 降级到基础提取（简单返回原始 HTML 的纯文本）
        return self._fallback_extract(html)

def _fallback_extract(self, html: str) -> str:
    """降级提取方法：从 HTML 中提取纯文本"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')

    # 移除 script 和 style 标签
    for tag in soup(['script', 'style', 'nav', 'header', 'footer']):
        tag.decompose()

    # 获取纯文本
    text = soup.get_text(separator='\n')

    # 压缩空白
    import re
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' +\n', '\n', text)

    return text.strip()
```

##### 3.6.5 错误处理总结

| 错误类型 | 处理策略 | 用户体验 |
|---------|---------|---------|
| YAML 解析失败 | 降级到内置默认规则 | ✅ 功能继续，使用默认规则 |
| 配置文件不存在 | 使用内置默认规则 | ✅ 开箱即用 |
| 自定义模块不存在 | 记录警告，跳过该策略 | ✅ 其他策略仍可用 |
| 自定义类不存在 | 记录警告，跳过该策略 | ✅ 其他策略仍可用 |
| 类继承错误 | 记录警告，跳过该策略 | ✅ 其他策略仍可用 |
| 配置值无效 | 记录警告，跳过该规则 | ✅ 其他规则仍可用 |
| 运行时提取失败 | 降级到基础提取 | ✅ 返回纯文本内容 |

**设计原则**：
- **优雅降级**：任何错误都不应该导致系统完全失败
- **清晰日志**：记录详细的警告和错误信息，便于调试
- **继续运行**：单个组件失败不影响其他组件正常工作

### 4. 策略工厂

**文件**: `src/scrapling_fetch_mcp/_strategy_factory.py`

```python
class StrategyFactory:
    """策略工厂：管理和创建提取策略实例"""

    @classmethod
    def get_strategy(cls, name: str, config_path: Path = None) -> ExtractorStrategy:
        """根据名称获取策略实例"""
        # 1. 确保内置策略已注册
        # 2. 加载自定义策略（如果配置文件存在）
        # 3. 返回策略实例

    @classmethod
    def load_custom_strategies(cls, config_path: Path):
        """从配置文件动态加载自定义策略"""
        # 1. 读取 YAML 配置
        # 2. 使用 importlib 动态加载 Python 模块
        # 3. 验证策略类是否继承自 ExtractorStrategy
        # 4. 注册到策略字典
```

### 5. 自定义策略扩展

用户可以编写自定义提取策略：

```python
# ~/.scrapling/my_custom_strategies.py

from scrapling_fetch_mcp._extractor_strategy import ExtractorStrategy

class WikiExtractorStrategy(ExtractorStrategy):
    """维基百科专用提取策略"""

    def extract(self, html: str, url: str) -> str:
        import trafilatura

        return trafilatura.extract(
            html,
            include_formatting=True,
            output_format='markdown',
            favor_precision=True,
            include_links=True,  # 维基百科保留内部链接
        )
```

在 YAML 中注册：
```yaml
custom_strategies:
  - name: "wiki_extractor"
    module: "/home/user/.scrapling/my_custom_strategies.py"
    class: "WikiExtractorStrategy"

url_rules:
  - match:
      type: domain_suffix
      pattern: ".wikipedia.org"
    strategy: wiki_extractor
```

### 6. Markdown 后处理

**文件**: `src/scrapling_fetch_mcp/_markdown_postprocessor.py`

所有策略提取后统一进行后处理优化。

#### 6.1 迭代实现策略

Markdown 后处理器采用**迭代优化**方法：

**Phase 1：基础版本（首次实现）**
- 实现最常见问题的处理
- 简单、稳定、易测试
- 解决 80% 的格式问题

**Phase 2：测试和收集反馈**
- 在真实网站上测试
- 收集用户反馈
- 统计常见的格式问题

**Phase 3：迭代优化**
- 根据测试反馈添加更多处理步骤
- 保持向后兼容
- 可配置的处理选项

#### 6.2 基础版本实现

```python
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

#### 6.3 增强版本（未来迭代）

基于测试反馈，可选添加以下处理：

```python
def postprocess_markdown_enhanced(markdown: str) -> str:
    """
    Markdown 后处理 - 增强版本（Phase 3）

    在基础版本上添加更多优化
    """
    # 基础处理
    markdown = postprocess_markdown(markdown)

    # 根据用户反馈添加的处理
    if CONFIG.get('code_blocks_cleanup', True):
        # 压缩代码块前后的空行（保留1个）
        markdown = re.sub(r'\n{2,}```', '\n```', markdown)
        markdown = re.sub(r'```\n{2,}', '```\n', markdown)

    if CONFIG.get('lists_cleanup', True):
        # 移除列表项前后的多余空行
        markdown = re.sub(r'\n{2,}([-*+])', r'\n\1', markdown)
        markdown = re.sub(r'\n{2,}(\d+\.)', r'\n\1', markdown)

    if CONFIG.get('headers_cleanup', True):
        # 优化标题前后的空行
        markdown = re.sub(r'\n{2,}(#{1,6})', r'\n\n\1', markdown)
        markdown = re.sub(r'(#{1,6}[^\n]+)\n{2,}', r'\1\n\n', markdown)

    return markdown
```

#### 6.4 配置选项（未来）

```python
# 用户可在配置文件中控制后处理行为
markdown_postprocessor:
  code_blocks_cleanup: true
  lists_cleanup: true
  headers_cleanup: false
```

### 7. 集成到现有系统

#### 7.1 配置更新

**文件**: `src/scrapling_fetch_mcp/_config.py`

添加：
```python
class Config:
    _rules_config_path: Optional[Path] = None

    @property
    def rules_config_path(self) -> Path:
        """获取规则配置文件路径"""

    def set_rules_config_path(self, path: Path | str) -> None:
        """设置规则配置文件路径"""
```

#### 7.2 MCP 工具更新

**文件**: `src/scrapling_fetch_mcp/mcp.py`

更新 `s_fetch_page()` 和 `s_fetch_pattern()` 的文档：
```python
"""
IMPORTANT:
- Use format='airead' for AI-optimized content extraction (removes navigation, ads, etc.)
- Use format='markdown' for standard markdown conversion
- Use format='html' only when you need raw HTML structure

The airead format uses intelligent content extraction with URL-based routing
to specialized strategies for different website types (search engines,
documentation, developer platforms, etc.)
"""
```

添加 CLI 参数：
```python
parser.add_argument(
    "--rules-config",
    type=str,
    default=None,
    help="Path to YAML file with URL routing rules for airead format"
)
```

#### 7.3 Fetcher 更新

**文件**: `src/scrapling_fetch_mcp/_fetcher.py`

添加：
```python
async def _extract_with_airead(html: str, url: str) -> str:
    """使用 airead 格式提取内容"""
    # 1. 获取配置文件路径
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

修改 `fetch_page_impl()` 和 `fetch_pattern_impl()`：
```python
if format == "airead":
    full_content = await _extract_with_airead(html_content, url)
elif format == "markdown":
    full_content = _html_to_markdown(html_content)
else:  # html
    full_content = html_content
```

### 8. 依赖管理

**文件**: `pyproject.toml`

添加新依赖：
```toml
dependencies = [
    # 现有依赖...
    "trafilatura>=1.6.0",      # 内容提取库
    "readability-lxml>=0.8.1", # Firefox Reader View 算法
    "pyyaml>=6.0",            # YAML 配置文件解析
]
```

## 文件结构

```
src/scrapling_fetch_mcp/
├── __init__.py
├── _config.py                    # 修改：添加 rules_config_path
├── _content_saver.py
├── _fetcher.py                   # 修改：添加 _extract_with_airead
├── _markdownify.py
├── _scrapling.py
├── _extractor_strategy.py        # 新增：策略基类和所有内置策略
├── _url_matcher.py               # 新增：URL 匹配器
├── _strategy_factory.py          # 新增：策略工厂
├── _markdown_postprocessor.py    # 新增：Markdown 后处理
├── _default_rules.py             # 新增：内置默认规则
└── mcp.py                        # 修改：添加 airead 格式支持

docs/
├── airead-format-guide.md        # 新增：airead 格式使用指南
├── custom-strategies.md          # 新增：自定义策略开发指南
└── configuration.md              # 新增：配置文件详细文档

docs/superpowers/specs/
└── 2026-03-18-airead-format-design.md  # 本设计文档
```

## 测试策略

### 单元测试

1. **test_extractor_strategies.py**
   - 测试有效字符统计函数
   - 测试每个内置策略的基本功能
   - 测试双重提取器的对比逻辑

2. **test_url_matcher.py**
   - 测试域名匹配（domain）
   - 测试智能域名后缀匹配（domain_suffix）
     - `.google.com` 匹配 `google.com` 和 `www.google.com`
     - `google.com` 只匹配 `google.com`
   - 测试正则表达式匹配（regex）
   - 测试配置文件加载和热加载
   - 测试使用内置默认规则

3. **test_strategy_factory.py**
   - 测试策略注册
   - 测试自定义策略加载
   - 测试错误处理

4. **test_error_handling.py**（新增）
   - 测试 YAML 解析失败时的降级行为
   - 测试自定义策略模块不存在的处理
   - 测试自定义策略类不存在的处理
   - 测试策略类继承验证
   - 测试无效配置值的验证
   - 测试运行时提取失败的降级

5. **test_markdown_postprocessor.py**（新增）
   - 测试基础版本的所有处理步骤
   - 测试空输入和边界情况

### 集成测试

**test_airead_integration.py**：
- 测试 airead 格式的完整流程
- 测试真实网站的提取效果
- 测试配置文件热加载
- 测试自定义策略

### 功能验证

使用真实网站测试：

1. **搜索引擎**：
   ```python
   await s_fetch_page(
       url="https://www.google.com/search?q=python",
       format="airead"
   )
   ```

2. **开发者平台**：
   ```python
   await s_fetch_page(
       url="https://github.com/D4Vinci/Scrapling",
       format="airead"
   )
   ```

3. **技术文档**：
   ```python
   await s_fetch_page(
       url="https://docs.python.org/3/library/json.html",
       format="airead"
   )
   ```

对比 `format="airead"` 和 `format="markdown"` 的输出，验证：
- 内容精简度提升
- 导航、广告被移除
- 核心内容保留完整
- 格式化空白被优化

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

## 风险与缓解

### 风险 1: 提取器可能误删重要内容

**场景**：某些网站的内容结构特殊，提取器可能误判并删除重要内容

**缓解措施**：
- 默认使用 dual 策略（三重对比取最优），降低误删概率
- 提供降级机制：用户可以选择 `format="markdown"` 或 `format="html"`
- 提供 7 个不同的策略，用户可以根据网站类型选择
- 支持自定义策略，用户可以针对特殊网站编写专门逻辑

### 风险 2: 新增依赖可能增加安装复杂度

**场景**：trafilatura 和 readability-lxml 有各自的依赖树

**缓解措施**：
- trafilatura 和 readability-lxml 都是成熟稳定的库，PyPI 下载量大
- 在 README 中清晰说明依赖用途和安装步骤
- 提供 Docker 镜像避免手动安装
- 提供 `pip install scrapling-fetch-mcp[all]` 一键安装所有依赖

### 风险 3: URL 匹配规则可能不够灵活

**场景**：某些网站的 URL 规则复杂，三种匹配方式无法满足需求

**缓解措施**：
- 三种匹配方式已覆盖大部分场景（domain、domain_suffix、regex）
- 支持自定义策略扩展，用户可以在 Python 代码中实现任意复杂的匹配逻辑
- 支持配置文件热加载，可以快速调整规则
- 可以在策略内部根据 URL 内容进一步判断

### 风险 4: 性能影响（三个提取器顺序运行）

**场景**：dual 策略需要运行三个提取器，可能增加响应时间

**缓解措施**：
- 单个提取器通常只需 100-500ms，三个提取器总计 < 2 秒
- 提供单独的策略选项（trafilatura、readability、scrapling），用户可以选择只用一个
- 利用现有的页面缓存机制，避免重复提取
- 未来优化：考虑并行运行三个提取器（需要测试资源消耗）

### 风险 5: 配置文件格式错误导致系统无法启动

**场景**：YAML 语法错误或路径错误

**缓解措施**：
- YAML 解析错误时使用默认配置（dual 策略）
- 自定义策略加载失败时记录警告但继续运行
- 提供 `--validate-config` CLI 命令验证配置文件
- 在文档中提供配置文件示例和最佳实践

## 后续优化方向

1. **性能优化**：
   - 并行运行三个提取器（需要测试资源消耗和线程安全）
   - 提取结果缓存（基于 URL + 内容 hash）
   - 提取器预热机制

2. **策略增强**：
   - 添加更多网站类型的专用策略（电商、新闻、论坛等）
   - 支持策略参数配置（如 trafilatura 的 `favor_recall` vs `favor_precision`）
   - 支持策略链（多个策略组合）

3. **dual 策略优化标准**（优先级：中）：
   当前 dual 策略使用"有效字符数最多"作为最优标准。未来可考虑多维度评分：

   ```python
   def score_extraction_result(result: str, url: str) -> float:
       """多维度评估提取结果质量"""
       score = 0.0

       # 1. 有效字符数（基础分，50% 权重）
       char_count = count_effective_characters(result)
       score += char_count * 0.5

       # 2. 内容密度（有效字符 / 总字符，归一化加权）
       density = char_count / len(result) if len(result) > 0 else 0
       score += density * 1000

       # 3. 结构完整性（是否包含标题、段落等）
       has_headers = bool(re.search(r'^#+', result, re.MULTILINE))
       has_paragraphs = result.count('\n\n') > 2
       structure_score = (has_headers * 100 + has_paragraphs * 100)
       score += structure_score

       return score
   ```

   **最小阈值过滤**：
   ```python
   MIN_THRESHOLD = 500  # 有效字符数最小阈值

   valid_results = [
       (count, result, extractor)
       for count, result, extractor in results
       if count >= MIN_THRESHOLD
   ]

   if not valid_results:
       logging.warning("All extractors produced low-quality results")
       # 返回字数最多的（虽然不够好）
   ```

   **实施建议**：
   - Phase 1：保持当前简单实现（字数最多）
   - Phase 2：收集真实网站测试数据
   - Phase 3：基于测试结果调整评分算法

4. **机器学习**：
   - 使用 ML 模型自动识别网站类型并选择策略
   - 基于用户反馈优化提取算法
   - 自动学习 URL 匹配规则

5. **统计分析**：
   - 添加提取效果统计（token 节省比例、提取时间等）
   - 生成分析报告
   - 可视化对比工具

6. **用户反馈**：
   - 收集用户反馈优化提取算法和规则配置
   - 建立社区共享的规则库
   - 支持规则的导入导出

7. **兼容性**：
   - 支持更多 Markdown 转换库（如 markdownify、html2text）
   - 支持自定义 Markdown 后处理管道
   - 支持输出格式扩展（如 JSON、XML）

## 成功标准

1. **功能完整性**：
   - ✅ airead 格式正常工作
   - ✅ 7 个内置策略全部实现
   - ✅ URL 路由正确工作
   - ✅ 自定义策略扩展正常工作

2. **性能指标**：
   - ✅ 总字符数减少 30-50%（对比 markdown 格式）
   - ✅ 有效字符占比 > 80%
   - ✅ 核心内容保留率 > 90%
   - ✅ 提取时间 < 3 秒（dual 策略）

3. **稳定性**：
   - ✅ 单元测试覆盖率 > 80%
   - ✅ 集成测试通过
   - ✅ 真实网站测试通过（至少 10 个不同类型网站）

4. **易用性**：
   - ✅ 配置文件格式清晰易懂
   - ✅ 文档完整（README + 配置示例）
   - ✅ 错误提示友好

## 参考资料

- [trafilatura 文档](https://trafilatura.readthedocs.io/)
- [readability-lxml 文档](https://github.com/buriy/python-readability)
- [Scrapling 文档](https://scrapling.readthedocs.io/)
- [策略模式（Strategy Pattern）](https://refactoring.guru/design-patterns/strategy)
