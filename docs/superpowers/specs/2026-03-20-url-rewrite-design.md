# URL 自动重写功能设计文档

**日期**: 2026-03-20
**状态**: 设计阶段
**作者**: Claude Sonnet 4.6

## 概述

为 scrapling-fetch-mcp 添加 URL 自动重写功能，通过将特定 URL 重写为更轻量、更易访问的版本来提高 stealth 模式成功率和抓取速度。

## 目标

### 主要目标
1. **提高 stealth 成功率**：轻量级版本的网站更容易抓取，更不容易触发反爬检测
2. **加快抓取速度**：减少 JavaScript 渲染和不必要的资源加载
3. **减少资源消耗**：降低带宽和处理时间

### 非目标
- 不处理需要认证的内容
- 不改变用户的原始意图（内容应该保持一致）
- 不支持复杂的重写逻辑（如需要多次请求的场景）

## 功能需求

### 核心功能
1. 自动识别特定 URL 模式并重写为轻量级版本
2. 默认启用，对用户透明
3. 支持通过启动参数全局禁用
4. 支持自定义重写规则扩展

### 默认规则
内置以下网站的重写规则：

| 网站 | 原始 URL | 重写后 URL | 说明 |
|------|----------|------------|------|
| GitHub | `github.com/user/repo/blob/branch/file` | `raw.githubusercontent.com/user/repo/branch/file` | 直接访问文件内容 |
| DuckDuckGo | `duckduckgo.com/?q=query` | `duckduckgo.com/html/?q=query` | HTML 版本，无需 JavaScript |
| Reddit | `www.reddit.com/r/...` | `old.reddit.com/r/...` | 老版本，更轻量 |
| StackOverflow | `stackoverflow.com/questions/12345/title` | `stackprinter.com/export?question=12345&service=stackoverflow&format=HTML&comments=true` | 打印友好版本 |

**边界情况说明：**

**GitHub 规则：**
- ✅ 匹配：`/blob/` 路径（文件查看）
- ❌ 不匹配：`/tree/` 路径（目录浏览）、`/raw/` 路径（已经是 raw）
- 📝 原因：`/tree/` 是目录页面，不对应单个文件内容；`/raw/` 已经是轻量级版本

**DuckDuckGo 规则：**
- ✅ 匹配：带查询参数的搜索 URL
- ❌ 不匹配：已经是 `/html/` 或 `/lite/` 路径的 URL
- 📝 保留：所有查询参数（如 `?q=python&kl=us-en`）

**Reddit 规则：**
- ✅ 匹配：`www.reddit.com` 的所有路径
- ❌ 不匹配：已经是 `old.reddit.com` 的 URL
- ⚠️  限制：某些新功能（如聊天、投票）在 old 版本可能不可用

**StackOverflow 规则：**
- ✅ 匹配：`stackoverflow.com/questions/{id}/*`
- ❌ 不匹配：其他 StackExchange 站点（如 `serverfault.com`、`askubuntu.com`）
- ⚠️  限制：当前仅支持 `stackoverflow.com`，未覆盖整个 StackExchange 网络
- 📝 建议：未来可通过自定义规则扩展到其他 StackExchange 站点

### 配置选项

**启动参数：**
- `--disable-url-rewrite`: 禁用 URL 重写功能
- `--url-rewrite-config <path>`: 指定自定义规则配置文件路径

**环境变量：**
- `SCRAPLING_DISABLE_URL_REWRITE`: 设置为 `true` 禁用重写
- `SCRAPLING_URL_REWRITE_CONFIG`: 自定义规则配置文件路径

## 技术设计

### 整体架构

```
用户请求 URL
    ↓
fetch_page_impl / fetch_pattern_impl
    ↓
【新增】URL Rewriter.rewrite(url)
    ↓
使用重写后的 URL 进行缓存查询/存储
    ↓
browse_url(rewritten_url, mode)
    ↓
Scrapling 抓取
    ↓
返回内容
```

**关键设计点：**
- URL 重写在 `fetch_page_impl` 和 `fetch_pattern_impl` 中最开始执行
- 缓存基于重写后的 URL（避免重复抓取同一内容的不同 URL 形式）
- airead 策略匹配基于重写后的 URL

### 核心组件

#### 1. URLRewriter 类
**位置**: `src/scrapling_fetch_mcp/_url_rewriter.py`

**职责**:
- 加载和管理重写规则（内置 + 自定义）
- 执行 URL 重写
- 处理错误和边界情况

**核心接口**:
```python
class URLRewriter:
    def __init__(self, config_path: Optional[Path] = None):
        """初始化重写器，加载规则"""
        
    def rewrite(self, url: str) -> str:
        """重写 URL（如果匹配规则）"""
        
    def _find_matching_rule(self, url: str) -> Optional[Dict]:
        """查找匹配的重写规则"""
        
    def _apply_rule(self, url: str, rule: Dict) -> str:
        """应用重写规则"""
```

#### 2. 内置规则定义
**位置**: `src/scrapling_fetch_mcp/_default_rewrite_rules.py`

**格式**: Python 常量（方便维护和测试）

```python
BUILTIN_REWRITE_RULES = [
    {
        "match": {"type": "domain_suffix", "pattern": "github.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)",
            "replacement": r"raw.githubusercontent.com/\1/\2/\3/\4"
        }
    },
    # ... 其他规则
]
```

#### 3. 配置管理扩展
**位置**: `src/scrapling_fetch_mcp/_config.py`

**新增属性**:
```python
class Config:
    _url_rewrite_config_path: Optional[Path] = None
    _url_rewriter: Optional[URLRewriter] = None
    _disable_url_rewrite: bool = False
    
    @property
    def url_rewriter(self) -> URLRewriter:
        """获取 URL 重写器实例（懒加载）"""
        
    @property
    def disable_url_rewrite(self) -> bool:
        """是否禁用 URL 重写"""
```

#### 4. 集成点
**位置**: `src/scrapling_fetch_mcp/_fetcher.py`

```python
async def fetch_page_impl(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: Optional[Path] = None,
) -> str:
    # 新增：URL 重写（在最开始执行）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")

    # 使用重写后的 URL 进行后续操作
    effective_mode = config.get_effective_mode(mode)

    # 缓存查询（基于重写后的 URL）
    cached_page = config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    else:
        # Fetch and cache the page
        page = await browse_url(url, effective_mode, page_action=page_action)
        config.cache.set(url, effective_mode, page)

    # 后续处理使用重写后的 URL
    if format == "airead":
        full_content = _extract_with_airead(html_content, url)  # 重写后的 URL
    # ...
```

**说明**：
- URL 重写在函数最开始执行，确保缓存基于重写后的 URL
- airead 策略匹配使用重写后的 URL
- `browse_url` 函数本身不需要修改

### 规则格式

**YAML 配置文件格式**:
```yaml
url_rewrite_rules:
  - match:
      type: domain_suffix | domain | regex
      pattern: "pattern string"
    rewrite:
      type: regex_replace | path_prefix | domain_replace | none
      # 具体参数根据类型而定
```

**匹配类型**:
- `domain`: 完整域名匹配（支持 www 前缀）
- `domain_suffix`: 域名后缀匹配（支持 .前缀表示子域名通配）
- `regex`: 正则表达式匹配

**重写类型**:
- `regex_replace`: 正则表达式替换
  - `pattern`: 正则模式
  - `replacement`: 替换字符串
- `path_prefix`: 路径前缀
  - `prefix`: 要添加的前缀
- `domain_replace`: 域名替换
  - `old`: 旧域名
  - `new`: 新域名
- `none`: 不重写（用于禁用规则）

### 匹配优先级

1. 自定义配置文件中的规则（从上到下，第一个匹配生效）
2. 内置规则（GitHub → DuckDuckGo → Reddit → StackOverflow）
3. 不匹配则返回原 URL

### 与 airead 格式的协同

**执行顺序：**
1. URL 重写（在 `fetch_page_impl` 开始时）
2. airead 策略匹配（基于重写后的 URL）
3. 内容提取（使用匹配的策略）

**设计原则：**
- airead 策略匹配基于**重写后的 URL**
- URL 重写规则和 airead 策略规则是**独立的系统**
- 重写规则关注"如何更高效地获取内容"
- airead 策略关注"如何更智能地提取内容"

**示例场景：**

| 原始 URL | 重写后 URL | airead 策略 |
|----------|------------|-------------|
| `github.com/user/repo/blob/main/README.md` | `raw.githubusercontent.com/user/repo/main/README.md` | `markdown` (默认) |
| `duckduckgo.com/?q=python` | `duckduckgo.com/html/?q=python` | `search-engine` |
| `stackoverflow.com/questions/12345/title` | `stackprinter.com/export?question=12345&...` | `dual` (默认) |

**注意事项：**
- 某些重写后的 URL 可能不再需要特殊的 airead 策略（如 StackPrinter 已经是简化格式）
- 重写规则优先于 airead 策略考虑，确保先获得轻量级版本
- 配置文件可以分开管理（`url-rewrite-config.yaml` 和 `rules-config.yaml`）

### 与 content_saver 的协同

**保存逻辑：**
- `save_content` 功能基于**重写后的 URL** 创建目录和保存文件
- 目录命名：使用重写后的 URL 生成唯一标识
- 元数据记录：在 `metadata.json` 中同时记录原始 URL 和重写后的 URL

**示例：**
```json
{
  "original_url": "https://github.com/user/repo/blob/main/README.md",
  "rewritten_url": "https://raw.githubusercontent.com/user/repo/main/README.md",
  "fetch_time": "2026-03-20T10:30:00Z",
  "mode": "stealth"
}
```

### 错误处理

**关键场景**:

1. **无效 URL**
   - 检测：缺少 scheme 或 netloc，或 scheme 不在允许列表中
   - 允许的 scheme：`http`、`https`（其他如 `ftp`、`file` 等不支持）
   - 验证方法：使用 `urllib.parse.urlparse` 解析 URL
   - 处理：返回原 URL，记录警告

2. **正则表达式错误**
   - 检测：编译正则时抛出异常
   - 处理：跳过该规则，记录错误，继续其他规则

3. **配置文件错误**
   - 检测：文件不存在或 YAML 解析失败
   - 处理：降级到内置规则，记录警告

4. **重写循环和链式重写**
   - 检测：重写后的 URL 等于原 URL，或达到最大重写次数
   - 处理：直接返回，不再重写
   - 最大重写次数：3 次（防止无限循环）
   - 实现：
     ```python
     def rewrite(self, url: str, max_iterations: int = 3) -> str:
         for _ in range(max_iterations):
             rewritten = self._apply_first_matching_rule(url)
             if rewritten == url:  # 无变化，停止
                 return url
             url = rewritten
         logger.warning(f"Max rewrite iterations reached: {url}")
         return url
     ```

5. **保留 URL 组件**
   - 查询参数：重写时保留
   - Fragment：重写时保留
   - 协议：保持原协议

**错误处理代码模式**:
```python
def rewrite(self, url: str) -> str:
    try:
        # 验证 URL
        if not self._is_valid_url(url):
            logger.warning(f"Invalid URL: {url}")
            return url
        
        # 查找规则
        rule = self._find_matching_rule(url)
        if not rule:
            return url
        
        # 应用规则
        rewritten = self._apply_rule(url, rule)
        
        # 防止循环
        if rewritten == url:
            return url
        
        return rewritten
        
    except Exception as e:
        logger.error(f"URL rewrite failed: {e}")
        return url  # 失败时返回原 URL
```

### 日志规范

**日志级别：**

| 级别 | 场景 | 示例 |
|------|------|------|
| DEBUG | URL 重写成功 | `"URL rewritten: {original} → {rewritten}"` |
| INFO | 不使用 | （避免过多日志） |
| WARNING | 可恢复的错误 | `"Invalid URL format: {url}"`<br>`"Custom rewrite config not found, using built-in rules"` |
| ERROR | 严重错误但继续运行 | `"Failed to load rewrite config: {error}"`<br>`"Regex compilation failed in rule: {rule}"` |

**日志格式：**
```python
# 重写成功（DEBUG 级别）
logger.debug(f"URL rewritten: {original_url} → {rewritten_url}")

# 规则匹配失败（不记录，静默返回原 URL）

# 配置文件错误（WARNING 级别）
logger.warning(f"URL rewrite config file not found: {config_path}, using built-in rules")

# 正则错误（ERROR 级别）
logger.error(f"Invalid regex in rewrite rule: {rule_name}, error: {error}")
```

**性能考虑：**
- URL 重写可能被频繁调用，避免在热路径中使用 INFO 或更高级别的日志
- 使用 DEBUG 级别记录每次重写，可通过配置启用
- 只在错误情况使用 WARNING/ERROR

## 测试策略

### 单元测试

**文件**: `tests/test_url_rewriter.py`

**测试分类**:

1. **基本功能测试**
   - `test_github_blob_to_raw`: GitHub blob → raw
   - `test_duckduckgo_html_version`: DuckDuckGo → html
   - `test_reddit_old_version`: Reddit → old
   - `test_stackoverflow_printer`: StackOverflow → StackPrinter
   - `test_no_match`: 不匹配规则时保持原 URL

2. **错误处理测试**
   - `test_invalid_url`: 无效 URL
   - `test_missing_scheme`: 缺少协议
   - `test_invalid_regex_in_custom_rules`: 无效正则
   - `test_config_file_not_found`: 配置文件不存在
   - `test_malformed_config_file`: 配置文件格式错误

3. **边界情况测试**
   - `test_rewrite_idempotent`: 幂等性
   - `test_preserve_query_params`: 保留查询参数
   - `test_preserve_fragment`: 保留 fragment
   - `test_multiple_custom_rules_priority`: 多规则优先级
   - `test_github_already_raw`: 不重复重写
   - `test_duckduckgo_already_html`: 不重复重写
   - `test_reddit_already_old`: 不重复重写

4. **自定义规则测试**
   - `test_custom_rules_override`: 自定义规则优先
   - `test_disable_rewrite_via_config`: 配置文件禁用

### 集成测试

**文件**: `tests/test_fetcher.py`（扩展）

- 测试重写后的 URL 能够正常抓取
- 验证缓存基于重写后的 URL

**文件**: `tests/test_integration.py`（扩展）

- 端到端测试完整流程
- 验证 MCP 工具调用时重写生效

### 测试数据

为每个内置规则准备真实的 URL 样本：
- GitHub: 不同分支、不同文件类型
- DuckDuckGo: 带查询参数的搜索 URL
- Reddit: 不同子版块、不同帖子类型
- StackOverflow: 不同问题 ID

## 文档计划

### 1. README.md 更新

在 "Tips for Best Results" 后添加新章节：

```markdown
## URL Rewriting

The server automatically rewrites certain URLs to lighter, more accessible versions:

- **GitHub**: `blob` URLs → `raw.githubusercontent.com` (direct file content)
- **DuckDuckGo**: Search pages → HTML version (no JavaScript)
- **Reddit**: `www.reddit.com` → `old.reddit.com` (lighter version)
- **StackOverflow**: Question pages → StackPrinter format (printer-friendly)

This improves both stealth success rates and fetch speed.

### Disable URL Rewriting

If you need to access the original URLs:

\`\`\`json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--disable-url-rewrite"]
    }
  }
}
\`\`\`

Or via environment variable:

\`\`\`json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp"],
      "env": {
        "SCRAPLING_DISABLE_URL_REWRITE": "true"
      }
    }
  }
}
\`\`\`

### Custom Rewrite Rules

Add your own rewrite rules via configuration file:

\`\`\`json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--url-rewrite-config", "/path/to/rewrite-rules.yaml"
      ]
    }
  }
}
\`\`\`

See [URL Rewrite Configuration](docs/url-rewrite-configuration.md) for details.
```

### 2. 新建文档

**文件**: `docs/url-rewrite-configuration.md`

**内容**:
- URL 重写功能详细说明
- 配置文件格式参考
- 内置规则列表
- 自定义规则示例
- 常见问题解答

### 3. 配置示例

**文件**: `docs/url-rewrite-config-example.yaml`

提供完整的配置示例，包含：
- 注释说明
- 各种重写类型的示例
- 常见场景的配置

## 实施计划

### 阶段 1: 核心实现
1. 创建 `_url_rewriter.py` 模块
2. 创建 `_default_rewrite_rules.py` 内置规则
3. 扩展 Config 类
4. 集成到 `_scrapling.py`
5. 添加启动参数解析（`mcp.py`）

### 阶段 2: 测试
1. 编写单元测试（`test_url_rewriter.py`）
2. 扩展集成测试
3. 手动测试真实网站

### 阶段 3: 文档
1. 更新 README.md
2. 创建 `url-rewrite-configuration.md`
3. 创建配置示例文件

### 阶段 4: 发布
1. 代码审查
2. 合并到主分支
3. 发布新版本
4. 更新 PyPI

## 风险和缓解

### 风险 1: 重写后的 URL 内容不一致
**描述**: 某些网站的轻量级版本可能缺少部分内容
**缓解**:
- 只选择内容一致的轻量级版本
- 在文档中明确说明每个重写规则的影响
- 提供禁用选项

### 风险 2: 网站更新导致规则失效
**描述**: 网站可能更改 URL 结构，导致重写规则失效
**缓解**:
- 使用稳定的 URL 模式（如 domain、path）
- 避免依赖易变的类名或参数
- 定期测试内置规则
- 提供自定义规则作为后备

### 风险 3: 性能影响
**描述**: URL 重写逻辑可能增加额外开销
**缓解**:
- 使用高效的正则表达式
- 按优先级顺序检查规则（常用规则在前）
- 对性能进行基准测试
- 如有需要，添加规则匹配缓存

### 风险 4: 与现有功能冲突
**描述**: URL 重写可能影响缓存、airead 策略等功能
**缓解**:
- 重写在 browse_url 之前进行，缓存基于重写后的 URL
- 确保 airead 策略能够处理重写后的 URL
- 完整的集成测试

## 未来扩展

### 可能的增强功能
1. **更多内置规则**
   - GitLab raw content
   - Twitter/X → Nitter
   - Medium → 简化版本
   - Wikipedia → 移动版本

2. **重写统计**
   - 记录哪些规则被使用
   - 提供成功率统计
   - 帮助用户优化配置

3. **智能重写**
   - 根据抓取失败自动尝试其他重写
   - 根据网站响应动态选择最佳版本

4. **规则验证工具**
   - 验证自定义规则的正确性
   - 测试规则对 URL 的影响
   - 提供在线规则测试工具

## 参考资料

- [DuckDuckGo HTML Version](https://duckduckgo.com/html/)
- [GitHub Raw Content](https://raw.githubusercontent.com/)
- [Reddit Old Version](https://old.reddit.com/)
- [StackPrinter Documentation](https://www.stackprinter.com/docs/api.txt)
- [Scrapling Documentation](https://github.com/D4Vinci/Scrapling)

## 附录

### A. 内置规则详细说明

#### GitHub: blob → raw
- **原始**: `https://github.com/{user}/{repo}/blob/{branch}/{path}`
- **重写**: `https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}`
- **说明**: 直接返回文件的原始内容，无需渲染 GitHub 页面
- **影响**: 无 HTML 界面，只有文件内容

#### DuckDuckGo: html 版本
- **原始**: `https://duckduckgo.com/?{query_params}`
- **重写**: `https://duckduckgo.com/html/?{query_params}`
- **说明**: 纯 HTML 版本，无 JavaScript
- **影响**: 功能相同，但界面更简洁

#### Reddit: old 版本
- **原始**: `https://www.reddit.com/{path}`
- **重写**: `https://old.reddit.com/{path}`
- **说明**: 使用老版本 Reddit，更轻量
- **影响**: UI 更简单，内容相同

#### StackOverflow: StackPrinter
- **原始**: `https://stackoverflow.com/questions/{id}/{title}`
- **重写**: `https://www.stackprinter.com/export?question={id}&service=stackoverflow&format=HTML&comments=true`
- **说明**: 打印友好版本，包含问题和所有答案
- **影响**: 无侧边栏和导航，只有内容

### B. 性能基准测试计划

**测试场景**:
1. 不启用 URL 重写
2. 启用 URL 重写但无匹配规则
3. 启用 URL 重写且匹配规则

**测试指标**:
- 重写逻辑耗时（毫秒）
- 总抓取时间（秒）
- 内存使用（MB）

**预期结果**:
- 重写逻辑耗时 < 1ms
- 总抓取时间减少 10-50%（取决于网站）
- 内存使用无明显增加
