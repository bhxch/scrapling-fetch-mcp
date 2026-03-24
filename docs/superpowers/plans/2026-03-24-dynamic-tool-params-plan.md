# 动态工具参数可见性 实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox syntax for tracking.

**Goal:** 通过特性注册表机制，允许用户控制 MCP 工具参数的显隐，减少每轮请求的 token 消耗。

**Architecture:** 定义 feature registry 将参数按功能分组，启动时根据 CLI/环境变量配置解析启用特性，用动态函数工厂构建只包含启用参数的工具函数，注册到 FastMCP。

**Tech Stack:** Python 3.10+, FastMCP, pytest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `src/scrapling_fetch_mcp/_features.py` | **New** — 特性定义 + 参数元数据 + docstring 模板 |
| `src/scrapling_fetch_mcp/_tool_factory.py` | **New** — 动态函数构建 + docstring 生成 |
| `src/scrapling_fetch_mcp/_config.py` | **Modify** — 新增 feature 解析相关属性和方法 |
| `src/scrapling_fetch_mcp/_fetcher.py` | **Modify** — 新增 wrapper 函数封装中间件逻辑 |
| `src/scrapling_fetch_mcp/mcp.py` | **Modify** — 移除装饰器，改用动态注册 + 新增 CLI 参数 |
| `tests/test_features.py` | **New** — 特性注册表一致性 + 配置解析测试 |
| `tests/test_tool_factory.py` | **New** — 动态工厂测试 |

---

### Task 1: 创建特性注册表 `_features.py`

**Files:**
- Create: `src/scrapling_fetch_mcp/_features.py`
- Test: `tests/test_features.py`

- [ ] **Step 1: 编写注册表一致性测试**

创建 `tests/test_features.py`，包含 `TestFeatureRegistry` 类：
- `test_all_feature_references_valid`：TOOL_PARAMS 中引用的 feature 都在 FEATURES 中
- `test_each_tool_has_core_params`：每个工具至少有一个 core 参数
- `test_all_params_have_required_fields`：每个参数都有 type/required/default/feature/description

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_features.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 创建 `_features.py`**

创建 `src/scrapling_fetch_mcp/_features.py`，内容参照设计文档 spec 中的「特性注册表」和「工具描述模板」章节。包含：
- `FEATURES` dict：4 个特性定义
- `TOOL_PARAMS` dict：s_fetch_page 和 s_fetch_pattern 的参数元数据
- `S_FETCH_PAGE_DOCSTRING` 和 `S_FETCH_PATTERN_DOCSTRING`：基础 docstring 模板

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_features.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_features.py tests/test_features.py
git commit -m "feat: add feature registry for dynamic tool parameter visibility"
```

---

### Task 2: 扩展 Config 支持 feature 解析

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`
- Modify: `tests/test_features.py`

- [ ] **Step 1: 编写 feature 解析测试**

在 `tests/test_features.py` 中添加 `TestResolveFeatures` 类，每个测试在 `setup_method` 中重置 Config 单例状态（`config._enabled_features = set()`、`config._disable_features_raw = []`、`config._enable_features_raw = []`）：
- `test_defaults_match_spec`：默认值与 spec 一致
- `test_disable_overrides_default`：disable 覆盖默认值
- `test_enable_overrides_default`：enable 覆盖默认值
- `test_enable_overrides_disable`：enable > disable 优先级
- `test_unknown_feature_ignored`：未知特性被忽略
- `test_empty_lists_use_defaults`：空列表使用默认值
- `test_all_features_disabled`：全部禁用
- `test_all_features_enabled`：全部启用

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_features.py::TestResolveFeatures -v`
Expected: FAIL

- [ ] **Step 3: 在 `_config.py` 中实现**

在 Config 类中添加：
- 类属性：`_enabled_features: set[str] = set()`、`_disable_features_raw: list[str] = []`、`_enable_features_raw: list[str] = []`
- `enabled_features` property
- `resolve_features(disable, enable)` 方法
- `init_config_from_env()` 末尾添加环境变量解析

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_features.py -v`
Expected: PASS

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_airead_integration.py`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_features.py
git commit -m "feat(config): add feature resolution with CLI/env support"
```

---

### Task 2b: 环境变量集成测试

**Files:**
- Create: `tests/test_config_features_env.py`

- [ ] **Step 1: 编写环境变量测试**

创建 `tests/test_config_features_env.py`，使用 `monkeypatch` 设置环境变量。每个测试在 `setup_method` 中重置 Config 单例状态：
- `test_disable_features_env_var`：设置 `SCRAPLING_DISABLE_FEATURES=save`，调用 `init_config_from_env()`，验证 `_disable_features_raw` 为 `["save"]`
- `test_enable_features_env_var`：设置 `SCRAPLING_ENABLE_FEATURES=save`，验证 `_enable_features_raw` 为 `["save"]`
- `test_features_env_and_cli_merged`：设置环境变量 + 调用 `resolve_features()` 合并 CLI 列表，验证结果正确

- [ ] **Step 2: 运行测试验证通过**

Run: `pytest tests/test_config_features_env.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_config_features_env.py
git commit -m "test: add env var integration tests for feature control"
```

---

### Task 3: 实现动态工具工厂 `_tool_factory.py`

**Files:**
- Create: `src/scrapling_fetch_mcp/_tool_factory.py`
- Create: `tests/test_tool_factory.py`

- [ ] **Step 1: 编写工厂测试**

创建 `tests/test_tool_factory.py`，包含 `TestBuildToolFunction` 类：
- `test_full_features_all_params_present`：所有 feature 启用时参数完整
- `test_save_disabled_hides_save_params`：save 禁用时隐藏 save_content/scraping_dir
- `test_type_annotations_present`：生成函数有类型注解
- `test_docstring_contains_only_enabled_params`：docstring 只描述启用参数
- `test_docstring_preserves_base_description`：IMPORTANT 段落保留
- `test_delegates_to_impl_with_defaults`：禁用参数传入默认值
- `test_required_params_always_present`：核心参数始终存在
- `test_only_core_params_when_all_disabled`：全部禁用时只剩核心参数

需要一个 `_fake_impl` 异步函数作为 mock impl。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_tool_factory.py -v`
Expected: FAIL

- [ ] **Step 3: 创建 `_tool_factory.py`**

创建 `src/scrapling_fetch_mcp/_tool_factory.py`，包含：
- `_TYPE_MAP`：Python 类型到签名字符串映射
- `build_tool_function()`：动态构建工具函数（参照 spec 中的工厂设计）
- `_build_docstring()`：动态生成 docstring

注意：使用 Python 内置的 `exec` 内置函数进行动态代码生成。输入全部来自代码常量，无注入风险。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_tool_factory.py -v`
Expected: PASS

- [ ] **Step 5: 运行全量测试确认无回归**

Run: `pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_airead_integration.py`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add src/scrapling_fetch_mcp/_tool_factory.py tests/test_tool_factory.py
git commit -m "feat: add dynamic tool factory for parameter visibility control"
```

---

### Task 4: 在 `_fetcher.py` 中添加中间件包装函数

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`
- Modify: `tests/test_fetcher.py`

- [ ] **Step 1: 编写 wrapper 测试**

在 `tests/test_fetcher.py` 中添加：

`TestFetchPageWrapper`:
- `test_format_none_resolves_to_default`：format=None 时用 config.default_format
- `test_format_explicit_not_overridden`：显式 format 不被覆盖
- `test_error_handling_preserves_exceptions`：异常被重新抛出

`TestFetchPatternWrapper`:
- `test_airead_fallback_to_markdown`：airead 回退为 markdown
- `test_explicit_format_not_fallback`：显式 format 不被回退

使用 `unittest.mock.AsyncMock` 和 `patch` mock `fetch_page_impl`/`fetch_pattern_impl` 和 `config`。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_fetcher.py::TestFetchPageWrapper tests/test_fetcher.py::TestFetchPatternWrapper -v`
Expected: FAIL

- [ ] **Step 3: 在 `_fetcher.py` 末尾添加 wrapper 函数**

添加 `fetch_page_wrapper()` 和 `fetch_pattern_wrapper()`，封装现有中间件逻辑（format 解析、Path 转换、airead 回退、错误处理）。参照 spec 中的「中间件包装函数」章节。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_fetcher.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): add middleware wrapper functions for dynamic tool registration"
```

---

### Task 5: 改造 `mcp.py` 使用动态注册

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`

- [ ] **Step 1: 修改 `mcp.py`**

关键改动（参照 spec 中「mcp.py 改动」章节）：

1. 移除 `@mcp.tool()` 装饰器和 `s_fetch_page`、`s_fetch_pattern` 函数定义
2. 移除不再使用的 import（`from traceback import format_exc`、`from pathlib import Path`）
3. 添加 imports：
   - `from scrapling_fetch_mcp._features import TOOL_PARAMS, FEATURES, S_FETCH_PAGE_DOCSTRING, S_FETCH_PATTERN_DOCSTRING`
   - `from scrapling_fetch_mcp._tool_factory import build_tool_function`
   - 修改 `_fetcher` import 为 `fetch_page_wrapper, fetch_pattern_wrapper`
3. 在 `parser` 中添加 `--disable-features` 和 `--enable-features` 参数
4. 在 `run_server()` 中添加 feature 解析和日志
5. 添加 `_register_tool()` 辅助函数
6. 在 `mcp.run()` 之前注册工具

- [ ] **Step 2: 运行全量测试确认无回归**

Run: `pytest tests/ -v --ignore=tests/test_integration.py --ignore=tests/test_airead_integration.py`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add src/scrapling_fetch_mcp/mcp.py
git commit -m "feat(mcp): refactor to dynamic tool registration with feature control"
```

---

### Task 6: 手动验证

- [ ] **Step 1: 验证 CLI 参数**

Run: `scrapling-fetch-mcp --help`
Expected: 显示 `--disable-features` 和 `--enable-features` 参数说明

- [ ] **Step 2: 验证工具 schema**

通过 MCP 客户端或 inspect 工具验证：
- 默认启动时 s_fetch_page 不包含 save_content 和 scraping_dir
- `--enable-features save` 启动时包含这两个参数

- [ ] **Step 3: Commit（如有修复）**

```bash
git add -u
git commit -m "fix: address manual verification findings"
```

---

### Task 7: 更新文档

**Files:**
- Modify: `README.md`
- Modify: `docs/configuration.md`（如存在）
- Modify: `MCP_CONFIG_EXAMPLES.md`

- [ ] **Step 1: 在 README 中添加 Feature Control 章节**

在配置相关章节添加 Feature Control 说明，包括用法示例和特性表。

- [ ] **Step 2: 更新 configuration.md**

添加 feature control 配置说明和 token 节省参考表。

- [ ] **Step 3: 更新 MCP_CONFIG_EXAMPLES.md**

添加 Feature Control 配置示例（默认配置、启用 save、禁用多个 feature）。

- [ ] **Step 4: Commit**

```bash
git add README.md docs/configuration.md MCP_CONFIG_EXAMPLES.md
git commit -m "docs: add feature control documentation for token optimization"
```
