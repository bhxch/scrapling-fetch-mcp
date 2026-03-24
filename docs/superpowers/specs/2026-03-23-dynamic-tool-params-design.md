# 动态工具参数可见性

**日期**: 2026-03-23
**状态**: 设计阶段
**作者**: Claude Sonnet 4.6

## 概述

MCP 工具的 schema（参数定义 + 描述）会包含在每次发给 LLM 的请求中。像 `save_content`、`scraping_dir` 这类低频使用的参数，每轮对话都在白白消耗 token。本设计通过特性注册表（feature registry）机制，允许用户控制哪些参数出现在工具 schema 中，从而减少每轮请求的 token 消耗。

## 目标

### 主要目标
1. **减少 token 消耗**：隐藏不常用的工具参数，每轮请求减少 ~75-100+ tokens
2. **完全可配置**：每个参数都可以通过特性（feature）独立控制显隐
3. **向后兼容**：默认推荐配置下行为与现有版本一致（除 save 功能默认关闭）
4. **与现有配置模式一致**：CLI 参数 + 环境变量，与项目其他配置方式统一

### 非目标
- 不支持运行时动态切换 feature（需要重启服务器生效）
- 不支持按工具粒度控制（feature 是全局的，对所有工具生效）
- 不支持参数级别的条件可见性逻辑（如"A 参数可见但 B 参数不可见"的独立控制，必须通过 feature 分组）
- 不改变现有实现函数（`fetch_page_impl`、`fetch_pattern_impl`）的签名和行为

## 功能需求

### 核心功能
1. 定义特性注册表，将工具参数按功能分组
2. 提供推荐默认配置，平衡 token 节省和功能完整性
3. 通过 CLI 参数和环境变量控制特性开关
4. 动态构建工具函数，只包含启用参数的签名和描述

### 推荐默认配置

| 特性 | 默认状态 | 控制的参数 | 说明 |
|------|----------|-----------|------|
| `stealth` | enabled | `mode` | 常用，LLM 经常需要覆盖 min-mode |
| `format` | enabled | `format` | 常用，LLM 经常需要覆盖 default-format |
| `pagination` | enabled | `start_index` | 常用，分页获取大页面 |
| `save` | **disabled** | `save_content`, `scraping_dir` | 低频使用，省 ~75-100 tokens/请求 |

### 配置方式

**CLI 参数：**
```bash
--disable-features save               # 禁用保存功能
--enable-features save                # 启用保存功能
--disable-features save,pagination    # 同时禁用多个（逗号分隔）
```

**环境变量：**
```bash
SCRAPLING_DISABLE_FEATURES=save
SCRAPLING_ENABLE_FEATURES=save,pagination
```

**优先级**：`--enable-features` > `--disable-features` > 推荐默认值

**冲突消解示例：**
```bash
# 推荐默认：stealth=enabled, format=enabled, pagination=enabled, save=disabled
--disable-features save,pagination --enable-features pagination
# 结果：save=disabled, pagination=enabled, stealth=enabled, format=enabled
# pagination 被 enable 覆盖回 enabled
```

### 启动日志

启动时需记录特性状态，与现有日志风格一致：

```python
logger.info(f"Features enabled: {sorted(enabled_features)}")
logger.info(f"Features disabled: {sorted(all_features - enabled_features)}")
```

### 向后兼容性

- 禁用某个 feature 后，包含该 feature 参数的请求将被 MCP 框架拒绝（参数不在 schema 中）
- 现有 MCP 客户端配置无需更改（除非使用了 save 相关参数）
- `save` feature 默认关闭意味着：之前在 MCP 配置中引用 `save_content` 参数的客户端将收到 schema 错误。用户可通过 `--enable-features save` 恢复原有行为

## 技术设计

### 整体架构

```
服务器启动
    |
    v
解析 CLI 参数 + 环境变量
    |
    v
resolve_features(disable=[], enable=[])
    |  得到 enabled_features 集合
    v
build_tool_function() 遍历每个工具
    |  筛选启用的参数
    |  构建带类型注解的函数签名
    |  生成动态 docstring
    |  通过动态代码构建构建函数
    v
@mcp.tool() 注册动态函数
    |
    v
mcp.run(transport="stdio")
```

### 特性注册表（_features.py）

新文件 `src/scrapling_fetch_mcp/_features.py`，定义特性与参数的映射关系。

```python
# 所有已定义的特性及其默认状态
FEATURES = {
    "stealth":    {"default": "enabled",  "description": "Anti-bot-detection mode control"},
    "format":     {"default": "enabled",  "description": "Output format selection (airead/markdown/html)"},
    "pagination": {"default": "enabled",  "description": "Pagination support for large pages"},
    "save":       {"default": "disabled", "description": "Save page content to local filesystem"},
}

# 每个工具的参数定义，feature 字段关联到 FEATURES 中的特性名
# feature=None 表示核心参数，始终显示
TOOL_PARAMS = {
    "s_fetch_page": {
        "url": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "URL to fetch",
        },
        "mode": {
            "type": str, "required": False, "default": "basic",
            "feature": "stealth",
            "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
        },
        "format": {
            "type": str, "required": False, "default": None,
            "feature": "format",
            "description": "Output format (airead, markdown, or html). Use airead for AI-optimized extraction, markdown for standard conversion, html only for structure analysis. Defaults to server's default format setting.",
        },
        "max_length": {
            "type": int, "required": False, "default": 8000,
            "feature": None,
            "description": "Maximum number of characters to return.",
        },
        "start_index": {
            "type": int, "required": False, "default": 0,
            "feature": "pagination",
            "description": "On return output starting at this character index, useful if a previous fetch was truncated and more content is required.",
        },
        "save_content": {
            "type": bool, "required": False, "default": False,
            "feature": "save",
            "description": "If True, save complete page content (HTML/Markdown + images) to local filesystem for offline viewing.",
        },
        "scraping_dir": {
            "type": str, "required": False, "default": ".temp/scrapling/",
            "feature": "save",
            "description": "Directory path for saved content (relative or absolute). Default: .temp/scrapling/",
        },
    },
    "s_fetch_pattern": {
        "url": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "URL to fetch",
        },
        "search_pattern": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "Regular expression pattern to search for in the content",
        },
        "mode": {
            "type": str, "required": False, "default": "basic",
            "feature": "stealth",
            "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
        },
        "format": {
            "type": str, "required": False, "default": None,
            "feature": "format",
            "description": "Output format (html or markdown). Use markdown for content reading/extraction, html only for structure analysis. Defaults to server's default format setting (airead will be converted to markdown).",
        },
        "max_length": {
            "type": int, "required": False, "default": 8000,
            "feature": None,
            "description": "Maximum number of characters to return.",
        },
        "context_chars": {
            "type": int, "required": False, "default": 200,
            "feature": None,
            "description": "Number of characters to include before and after each match",
        },
    },
}
```

### Config 扩展（_config.py）

在 `Config` 类中新增特性解析相关的方法和属性：

```python
class Config:
    _enabled_features: set[str] = set()

    @property
    def enabled_features(self) -> set[str]:
        """Get the set of enabled feature names"""
        return self._enabled_features

    def resolve_features(self, disable: list[str], enable: list[str]) -> None:
        """
        Resolve enabled features from recommended defaults + CLI/env overrides.

        Priority: enable > disable > recommended defaults.

        Unknown feature names are logged as warnings and ignored.
        """
        logger = getLogger("scrapling_fetch_mcp")
        all_known = set(FEATURES.keys())

        # Validate
        for f in set(disable) | set(enable):
            if f not in all_known:
                logger.warning(f"Unknown feature '{f}', ignoring")

        # Start from recommended defaults
        enabled = {f for f, cfg in FEATURES.items() if cfg["default"] == "enabled"}

        # Apply overrides
        enabled -= set(disable) & all_known
        enabled |= set(enable) & all_known

        self._enabled_features = enabled
```

环境变量初始化扩展（`init_config_from_env`）：

`init_config_from_env` **只存储原始值，不调用 `resolve_features()`**。由 `run_server()` 统一合并 env + CLI 后调用一次 `resolve_features()`，避免重复调用导致配置被重置。

```python
class Config:
    _disable_features_raw: list[str] = []
    _enable_features_raw: list[str] = []

def init_config_from_env():
    ...
    env_disable_features = getenv("SCRAPLING_DISABLE_FEATURES", "")
    env_enable_features = getenv("SCRAPLING_ENABLE_FEATURES", "")
    config._disable_features_raw = [f.strip() for f in env_disable_features.split(",") if f.strip()]
    config._enable_features_raw = [f.strip() for f in env_enable_features.split(",") if f.strip()]
```

`run_server()` 中合并 env + CLI 并调用一次 `resolve_features()`：

```python
    # Merge env raw values with CLI args (CLI takes precedence via order)
    disable_list = config._disable_features_raw + disable_cli_list
    enable_list = config._enable_features_raw + enable_cli_list
    config.resolve_features(disable_list, enable_list)
```

### 动态工具工厂（_tool_factory.py）

新文件 `src/scrapling_fetch_mcp/_tool_factory.py`。

核心函数 `build_tool_function` 根据启用的特性动态构建工具函数。

**关键要求**：生成的函数签名**必须包含 Python 类型注解**（如 `url: str`、`max_length: int`），因为 FastMCP 依赖类型注解生成 JSON Schema。

```python
from typing import Any, Callable
from logging import getLogger

logger = getLogger("scrapling_fetch_mcp")

# Python 类型到签名字符串的映射
_TYPE_MAP = {
    str: "str",
    int: "int",
    bool: "bool",
    float: "float",
}


def build_tool_function(
    tool_name: str,
    param_configs: dict[str, dict],
    enabled_features: set[str],
    base_docstring: str,
    impl_func: Callable,
) -> Callable:
    """
    Dynamically build a tool function with only enabled parameters.

    Args:
        tool_name: Name of the tool (e.g., "s_fetch_page")
        param_configs: Parameter metadata from TOOL_PARAMS
        enabled_features: Set of enabled feature names
        base_docstring: Base description with IMPORTANT sections
        impl_func: The actual implementation function (accepts all params)

    Returns:
        Async function with the correct signature and docstring
    """
    # 1. Filter to enabled params
    enabled_params = []
    for name, cfg in param_configs.items():
        if cfg["feature"] is None or cfg["feature"] in enabled_features:
            enabled_params.append(name)

    # 2. Build signature with TYPE ANNOTATIONS
    sig_parts = []
    for name in enabled_params:
        cfg = param_configs[name]
        type_str = _TYPE_MAP.get(cfg["type"], "str")
        if cfg["default"] is not None:
            sig_parts.append(f"{name}: {type_str} = {repr(cfg['default'])}")
        else:
            sig_parts.append(f"{name}: {type_str}")

    sig_str = ", ".join(sig_parts)

    # 3. Build call kwargs (pass enabled params directly, use defaults for disabled)
    call_kwargs = {}
    for name in enabled_params:
        call_kwargs[name] = name
    for name, cfg in param_configs.items():
        if name not in call_kwargs:
            call_kwargs[name] = repr(cfg["default"])
    call_str = ", ".join(f"{k}={v}" for k, v in call_kwargs.items())

    # 4. Build dynamic docstring (only include enabled params in Args)
    docstring = _build_docstring(base_docstring, enabled_params, param_configs)

    # 5. Build function via dynamic code generation with type-annotated signature
    source = f'''async def {tool_name}({sig_str}) -> str:
    """{docstring}"""
    return await _impl({call_str})'''

    namespace: dict[str, Any] = {"_impl": impl_func}
    # Note: Using Python built-in exec() for dynamic function creation.
    # All inputs come from code constants (TOOL_PARAMS), not from user input.
    # This is safe from code injection.
    exec(source, namespace)
    return namespace[tool_name]


def _build_docstring(
    base_docstring: str,
    enabled_params: list[str],
    param_configs: dict[str, dict],
) -> str:
    """
    Build a docstring that includes base description and only enabled parameter descriptions.

    The base_docstring contains IMPORTANT sections and feature guidance.
    The Args section is generated dynamically, only listing enabled parameters.

    Args:
        base_docstring: Multi-line base description with IMPORTANT sections.
                        Does NOT include Args section - that is generated here.
        enabled_params: List of parameter names that are currently enabled.
        param_configs: Parameter metadata for description lookup.

    Returns:
        Complete docstring for the dynamic function.
    """
    lines = [base_docstring, "", "Args:"]
    for name in enabled_params:
        cfg = param_configs[name]
        desc = cfg.get("description", "")
        lines.append(f"    {name}: {desc}")
    return "\n".join(lines)
```

### 工具描述模板

每个工具的 `base_docstring` 不包含 Args 部分（由 `_build_docstring` 动态生成），只包含工具描述和 IMPORTANT 段落。

**s_fetch_page base_docstring：**

```python
S_FETCH_PAGE_DOCSTRING = (
    "Fetches a complete web page with pagination support. Retrieves content from "
    "websites with bot-detection avoidance. Content is returned as "
    "'METADATA: {json}\\n\\n[content]' where metadata includes length information "
    "and truncation status.\n"
    "\n"
    "IMPORTANT:\n"
    "- Use format='airead' for AI-optimized content extraction "
    "(removes navigation, ads, etc., 30-50% token reduction)\n"
    "- Use format='markdown' for standard markdown conversion\n"
    "- Use format='html' only when you need raw HTML structure\n"
    "\n"
    "The airead format uses intelligent content extraction with URL-based routing "
    "to specialized strategies for different website types (search engines, "
    "documentation, developer platforms, etc.)."
)
```

**s_fetch_pattern base_docstring：**

```python
S_FETCH_PATTERN_DOCSTRING = (
    "Extracts content matching regex patterns from web pages. Retrieves specific "
    "content from websites with bot-detection avoidance. Returns matched content as "
    "'METADATA: {json}\\n\\n[content]' where metadata includes match statistics and "
    "truncation information. Each matched content chunk is delimited with special "
    "markers and prefixed with '[Position: start-end]' indicating its byte position "
    "in the original document, allowing targeted follow-up requests with s-fetch-page "
    "using specific start_index values.\n"
    "\n"
    "IMPORTANT: Use format='markdown' for reading or extracting content. Only use "
    "format='html' when you specifically need the raw HTML structure."
)
```

### 中间件包装函数

当前 `s_fetch_page` 和 `s_fetch_pattern` 装饰器函数包含关键中间件逻辑（format 默认值解析、Path 转换、airead 回退、错误处理）。动态工厂生成的函数直接透传参数给 `impl_func`，因此这些逻辑不能丢失。

解决方案：在 `_fetcher.py` 中新增包装函数，包含原有中间件逻辑，作为 `build_tool_function` 的 `impl_func`：

```python
# _fetcher.py 新增

async def fetch_page_wrapper(
    url: str, mode: str, format: str, max_length: int, start_index: int,
    save_content: bool = False, scraping_dir: str = ".temp/scrapling/",
) -> str:
    """Wrapper: format resolution, Path conversion, error handling."""
    try:
        effective_format = format if format is not None else config.default_format
        scraping_path = Path(scraping_dir)
        result = await fetch_page_impl(
            url, mode, effective_format, max_length, start_index,
            save_content=save_content, scraping_dir=scraping_path,
        )
        return result
    except Exception as e:
        logger = getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_page: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise


async def fetch_pattern_wrapper(
    url: str, search_pattern: str, mode: str, format: str,
    max_length: int, context_chars: int = 200,
) -> str:
    """Wrapper: format resolution, airead fallback, error handling."""
    try:
        effective_format = format if format is not None else config.default_format
        if effective_format == "airead":
            effective_format = "markdown"
        result = await fetch_pattern_impl(
            url, search_pattern, mode, effective_format, max_length, context_chars
        )
        return result
    except Exception as e:
        logger = getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_pattern: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise
```

**注意**：`impl_func` 传入的是包装函数（`fetch_page_wrapper`），不是 `fetch_page_impl`。

### mcp.py 改动

工具注册从模块级别装饰器移入 `run_server()`：

```python
from scrapling_fetch_mcp._features import TOOL_PARAMS
from scrapling_fetch_mcp._tool_factory import build_tool_function
from scrapling_fetch_mcp._fetcher import fetch_page_wrapper, fetch_pattern_wrapper

def run_server():
    parser = ArgumentParser(...)
    # ... 现有参数 ...
    parser.add_argument("--disable-features", type=str, default="")
    parser.add_argument("--enable-features", type=str, default="")
    args = parser.parse_args()

    # Initialize config (existing logic)
    init_config_from_env()

    # Resolve features (merge env raw values + CLI args, call once)
    disable_cli_list = [f.strip() for f in args.disable_features.split(",") if f.strip()]
    enable_cli_list = [f.strip() for f in args.enable_features.split(",") if f.strip()]
    disable_list = config._disable_features_raw + disable_cli_list
    enable_list = config._enable_features_raw + enable_cli_list
    config.resolve_features(disable_list, enable_list)

    # Log feature status
    all_features = set(FEATURES.keys())
    logger.info(f"Features enabled: {sorted(config.enabled_features)}")
    logger.info(f"Features disabled: {sorted(all_features - config.enabled_features)}")

    # Build and register tools dynamically (use wrappers as impl_func)
    _register_tool("s_fetch_page", TOOL_PARAMS["s_fetch_page"],
                   S_FETCH_PAGE_DOCSTRING, fetch_page_wrapper)
    _register_tool("s_fetch_pattern", TOOL_PARAMS["s_fetch_pattern"],
                   S_FETCH_PATTERN_DOCSTRING, fetch_pattern_wrapper)

    # ... existing logging ...
    mcp.run(transport="stdio")


def _register_tool(name, param_configs, base_docstring, impl_func):
    """Build a dynamic tool function and register it with FastMCP."""
    func = build_tool_function(
        tool_name=name,
        param_configs=param_configs,
        enabled_features=config.enabled_features,
        base_docstring=base_docstring,
        impl_func=impl_func,
    )
    mcp.tool()(func)
```

### 启动流程变化

```
之前：模块加载 -> @mcp.tool() 装饰器注册 -> run_server() -> mcp.run()
之后：模块加载 -> run_server() -> 解析配置 -> resolve_features() -> 工厂构建函数 -> mcp.tool() 注册 -> mcp.run()
```

## 文件变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `src/scrapling_fetch_mcp/_features.py` | 新增 | 特性注册表 + 推荐默认配置 + 参数元数据 |
| `src/scrapling_fetch_mcp/_tool_factory.py` | 新增 | 动态函数工厂 + docstring 构建 |
| `src/scrapling_fetch_mcp/mcp.py` | 修改 | 移除 @mcp.tool() 装饰器；在 run_server() 中动态注册；新增 CLI 参数 |
| `src/scrapling_fetch_mcp/_config.py` | 修改 | 新增 enabled_features 属性 + resolve_features() + 环境变量支持 |
| `src/scrapling_fetch_mcp/_fetcher.py` | 修改 | 新增 fetch_page_wrapper / fetch_pattern_wrapper 包装函数，包含中间件逻辑 |

## Token 节省分析

默认推荐配置（save 禁用）下：

| 工具 | 移除的参数 | 估计节省 tokens/请求 |
|------|-----------|---------------------|
| `s_fetch_page` | `save_content`, `scraping_dir` | ~75-100 |
| `s_fetch_pattern` | 无 | 0 |
| **合计** | | **~75-100** |

用户可通过禁用更多特性进一步节省：

| 禁用的特性 | 额外节省 |
|-----------|---------|
| `pagination` | ~50-70 (start_index 参数 + 描述) |
| `stealth` | ~50-70 (mode 参数 + 描述) |
| `format` | ~50-70 (format 参数 + 描述) |
| `save + pagination` | ~125-170 |
| 全部禁用（仅保留核心参数） | ~225-310 |

## 风险与缓解

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| 动态代码构建安全风险 | 低 | 输入全部来自代码常量（TOOL_PARAMS、FEATURES），不接受外部输入。不存在代码注入风险 |
| FastMCP 版本升级破坏动态签名 | 中 | 类型注解是 Python 标准特性，FastMCP 依赖函数签名生成 schema 是其核心行为，不太可能改变。如有需要可回退到静态注册 |
| 禁用参数后客户端兼容性 | 低 | 文档明确说明禁用行为，用户可通过 --enable-features 恢复 |
| IMPORTANT 段落引用被禁用参数 | 中 | IMPORTANT 段落使用功能描述而非参数名引用。format 相关的 IMPORTANT 段落与 format 特性绑定，format 默认启用 |

## 测试计划

### tests/test_features.py

测试特性注册表和配置解析：

| 测试函数 | 说明 |
|---------|------|
| `test_default_features_match_spec` | 验证 FEATURES 和 TOOL_PARAMS 中的 feature 引用一致 |
| `test_resolve_features_defaults` | 不传 disable/enable 时使用推荐默认值 |
| `test_resolve_features_disable` | disable 覆盖默认值 |
| `test_resolve_features_enable` | enable 覆盖默认值和 disable |
| `test_resolve_features_priority` | enable > disable 优先级 |
| `test_resolve_features_unknown_warning` | 未知特性名产生 warning 日志并被忽略 |
| `test_resolve_features_empty_lists` | 空 disable/enable 列表正常工作 |
| `test_all_features_disabled` | 所有特性都禁用时只剩核心参数 |

### tests/test_tool_factory.py

测试动态函数工厂：

| 测试函数 | 说明 |
|---------|------|
| `test_function_has_type_annotations` | 验证生成函数的签名包含类型注解 |
| `test_function_signature_only_enabled_params` | 禁用的参数不出现在函数签名中 |
| `test_function_docstring_only_enabled_params` | docstring 的 Args 部分只包含启用的参数描述 |
| `test_function_delegates_to_impl_with_defaults` | 调用动态函数时，禁用参数正确传入默认值 |
| `test_function_returns_impl_result` | 动态函数正确返回 impl_func 的结果 |
| `test_base_docstring_preserved` | IMPORTANT 段落和基础描述被保留在 docstring 中 |
| `test_no_params_disabled_full_signature` | 无参数禁用时，签名包含所有参数 |
| `test_required_params_always_present` | required=True 的参数始终出现在签名中 |

### tests/test_config_features_env.py

测试环境变量集成：

| 测试函数 | 说明 |
|---------|------|
| `test_disable_features_env_var` | SCRAPLING_DISABLE_FEATURES 环境变量生效 |
| `test_enable_features_env_var` | SCRAPLING_ENABLE_FEATURES 环境变量生效 |
| `test_features_env_override_by_cli` | CLI 参数覆盖环境变量 |

## 文档更新计划

实现完成后需更新以下文档：

1. **README.md**：新增「Feature Control」章节，说明 --disable-features / --enable-features 用法
2. **docs/configuration.md**：新增 feature control 配置说明和 token 节省参考表
3. **MCP_CONFIG_EXAMPLES.md**（如有）：新增 feature control 配置示例

## 实施阶段

1. **阶段 1**：创建 _features.py 特性注册表
2. **阶段 2**：扩展 _config.py 支持 feature 解析
3. **阶段 3**：实现 _tool_factory.py 动态函数工厂
4. **阶段 4**：改造 mcp.py，移除装饰器，使用动态注册
5. **阶段 5**：编写测试
6. **阶段 6**：更新文档

## 成功标准

1. 默认推荐配置下，save_content 和 scraping_dir 不出现在 s_fetch_page 的工具 schema 中
2. 启用 save feature 后，这两个参数恢复出现
3. 工具功能不受影响（禁用参数使用默认值，行为与之前一致）
4. 每轮请求 token 消耗减少 ~75-100 tokens（默认配置下）
5. 所有测试通过
