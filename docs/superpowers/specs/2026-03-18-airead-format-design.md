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

#### 3.1 配置文件格式

**默认路径**: `~/.scrapling/rules.yaml`
**环境变量**: `SCRAPLING_RULES_CONFIG`
**CLI 参数**: `--rules-config`

```yaml
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

  # 技术文档规则
  - match:
      type: regex
      pattern: ".*docs\\.python\\.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*developer\\.mozilla\\.org.*"
    strategy: documentation

# 自定义策略（可选）
custom_strategies:
  - name: "my_wiki_extractor"
    module: "/path/to/my_strategies.py"
    class: "WikiExtractorStrategy"
```

#### 3.2 匹配方式

支持三种 URL 匹配方式：

1. **domain**：完整域名匹配
   - `github.com` 匹配 `github.com` 和 `www.github.com`
   - 不匹配 `docs.github.com`

2. **domain_suffix**：域名后缀匹配
   - `.google.com` 匹配 `www.google.com`、`mail.google.com`、`docs.google.com`
   - 不匹配 `google.com`（需要配置两个规则）

3. **regex**：正则表达式匹配
   - `.*docs\\.python\\.org.*` 匹配所有包含 `docs.python.org` 的 URL
   - 最灵活但性能稍低

#### 3.3 热加载机制

URLMatcher 会检测配置文件的修改时间：
- 每次匹配请求时检查文件 mtime
- 如果文件被修改，重新加载配置
- 无需重启 MCP 服务器

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

所有策略提取后统一进行后处理优化：

```python
def postprocess_markdown(markdown: str) -> str:
    """
    统一的 Markdown 后处理，进一步优化内容精简度

    处理内容：
    1. 压缩多余的空行（最多保留2个连续空行）
    2. 移除行尾空白
    3. 压缩代码块前后的空行（保留1个）
    4. 移除列表项前后的多余空行
    5. 优化标题前后的空行
    6. 移除文档开头和结尾的空行
    7. 移除重复的空行（只保留一个）
    """
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
└── mcp.py                        # 修改：添加 airead 格式支持

~/.scrapling/
└── rules.yaml                    # 默认的 URL 路由规则配置（可选）

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
   - 测试域名匹配
   - 测试域名后缀匹配
   - 测试正则表达式匹配
   - 测试配置文件加载和热加载

3. **test_strategy_factory.py**
   - 测试策略注册
   - 测试自定义策略加载
   - 测试错误处理

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

3. **机器学习**：
   - 使用 ML 模型自动识别网站类型并选择策略
   - 基于用户反馈优化提取算法
   - 自动学习 URL 匹配规则

4. **统计分析**：
   - 添加提取效果统计（token 节省比例、提取时间等）
   - 生成分析报告
   - 可视化对比工具

5. **用户反馈**：
   - 收集用户反馈优化提取算法和规则配置
   - 建立社区共享的规则库
   - 支持规则的导入导出

6. **兼容性**：
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
