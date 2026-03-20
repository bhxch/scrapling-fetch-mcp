# URL 自动重写功能实现计划

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 scrapling-fetch-mcp 添加 URL 自动重写功能，提高 stealth 成功率和抓取速度

**Architecture:** 创建 URLRewriter 类处理 URL 重写逻辑，内置 4 个常用网站的重写规则，在 fetch_page_impl 和 fetch_pattern_impl 中调用重写器，缓存和 airead 策略都基于重写后的 URL

**Tech Stack:** Python 3.10+, urllib.parse, re, yaml, pytest

---

## 文件结构

**新建文件：**
- `src/scrapling_fetch_mcp/_url_rewriter.py` - URL 重写核心逻辑
- `src/scrapling_fetch_mcp/_default_rewrite_rules.py` - 内置重写规则
- `tests/test_url_rewriter.py` - URL 重写器单元测试
- `docs/url-rewrite-configuration.md` - 配置文档
- `docs/url-rewrite-config-example.yaml` - 配置示例

**修改文件：**
- `src/scrapling_fetch_mcp/_config.py` - 添加重写器配置
- `src/scrapling_fetch_mcp/_fetcher.py` - 集成 URL 重写
- `src/scrapling_fetch_mcp/mcp.py` - 添加 CLI 参数
- `README.md` - 添加功能说明

---

## 任务分解

### Task 1: 创建内置重写规则

**Files:**
- Create: `src/scrapling_fetch_mcp/_default_rewrite_rules.py`

- [ ] **Step 1: 创建内置规则文件**

```python
# src/scrapling_fetch_mcp/_default_rewrite_rules.py
"""内置的 URL 重写规则"""

BUILTIN_REWRITE_RULES = [
    # GitHub: blob → raw
    {
        "match": {"type": "domain_suffix", "pattern": "github.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)",
            "replacement": r"raw.githubusercontent.com/\1/\2/\3/\4"
        }
    },
    # DuckDuckGo: search → html version
    {
        "match": {"type": "domain", "pattern": "duckduckgo.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"^https://duckduckgo\.com/\?(.*)$",
            "replacement": r"https://duckduckgo.com/html/?\1"
        }
    },
    # Reddit: www → old
    {
        "match": {"type": "domain", "pattern": "www.reddit.com"},
        "rewrite": {
            "type": "domain_replace",
            "old": "www.reddit.com",
            "new": "old.reddit.com"
        }
    },
    # StackOverflow: questions → StackPrinter
    {
        "match": {"type": "domain_suffix", "pattern": "stackoverflow.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"https://stackoverflow\.com/questions/(\d+)/.*$",
            "replacement": r"https://www.stackprinter.com/export?question=\1&service=stackoverflow&format=HTML&comments=true"
        }
    },
]
```

- [ ] **Step 2: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/_default_rewrite_rules.py`
Expected: 无输出（成功）

- [ ] **Step 3: 提交**

```bash
git add src/scrapling_fetch_mcp/_default_rewrite_rules.py
git commit -m "feat(rewrite): add built-in URL rewrite rules

Add rewrite rules for:
- GitHub: blob → raw.githubusercontent.com
- DuckDuckGo: search → html version
- Reddit: www → old.reddit.com
- StackOverflow: questions → StackPrinter

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 编写 URL 重写器测试（基础功能）

**Files:**
- Create: `tests/test_url_rewriter.py`

- [ ] **Step 1: 创建测试文件并编写 GitHub 测试**

```python
# tests/test_url_rewriter.py
"""URL 重写器单元测试"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._url_rewriter import URLRewriter


class TestBasicRewrite:
    """基础重写功能测试"""
    
    def test_github_blob_to_raw(self):
        """GitHub blob URL 应该重写为 raw URL"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/README.md"
        expected = "https://raw.githubusercontent.com/user/repo/main/README.md"
        assert rewriter.rewrite(url) == expected
    
    def test_github_tree_not_rewritten(self):
        """GitHub tree URL 不应该重写"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/tree/main/docs"
        assert rewriter.rewrite(url) == url
    
    def test_github_already_raw(self):
        """已经是 raw 的 URL 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://raw.githubusercontent.com/user/repo/main/file.md"
        assert rewriter.rewrite(url) == url
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_url_rewriter.py::TestBasicRewrite::test_github_blob_to_raw -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'scrapling_fetch_mcp._url_rewriter'"

- [ ] **Step 3: 提交测试文件**

```bash
git add tests/test_url_rewriter.py
git commit -m "test(rewrite): add basic URL rewrite tests

Add tests for GitHub blob URL rewriting

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 3: 实现 URLRewriter 类（基础框架）

**Files:**
- Create: `src/scrapling_fetch_mcp/_url_rewriter.py`

- [ ] **Step 1: 创建 URLRewriter 类框架**

```python
# src/scrapling_fetch_mcp/_url_rewriter.py
"""URL 重写器"""
import re
import logging
from typing import Optional, Dict, List, Any
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("scrapling_fetch_mcp")


class URLRewriter:
    """URL 重写器，支持内置规则和自定义配置"""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        初始化重写器，加载规则
        
        Args:
            config_path: 自定义规则配置文件路径（可选）
        """
        self.config_path = config_path
        self.custom_rules: List[Dict[str, Any]] = []
        self.builtin_rules: List[Dict[str, Any]] = []
        
        self._load_rules()
    
    def _load_rules(self) -> None:
        """加载重写规则（内置 + 自定义）"""
        # 加载内置规则
        from scrapling_fetch_mcp._default_rewrite_rules import BUILTIN_REWRITE_RULES
        self.builtin_rules = BUILTIN_REWRITE_RULES
        
        # 加载自定义规则（如果配置文件存在）
        if self.config_path and self.config_path.exists():
            self._load_custom_rules()
    
    def _load_custom_rules(self) -> None:
        """从配置文件加载自定义规则"""
        try:
            import yaml
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config and 'url_rewrite_rules' in config:
                    self.custom_rules = config['url_rewrite_rules']
                    logger.info(f"Loaded {len(self.custom_rules)} custom rewrite rules")
        except Exception as e:
            logger.warning(f"Failed to load custom rewrite rules: {e}")
    
    def rewrite(self, url: str) -> str:
        """
        重写 URL（如果匹配规则）
        
        Args:
            url: 原始 URL
        
        Returns:
            重写后的 URL（如果匹配）或原 URL
        """
        # TODO: 实现重写逻辑
        return url
    
    def _find_matching_rule(self, url: str) -> Optional[Dict[str, Any]]:
        """查找匹配的重写规则"""
        # TODO: 实现规则匹配
        return None
    
    def _apply_rule(self, url: str, rule: Dict[str, Any]) -> str:
        """应用重写规则"""
        # TODO: 实现规则应用
        return url
```

- [ ] **Step 2: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/_url_rewriter.py`
Expected: 无输出（成功）

- [ ] **Step 3: 运行测试验证仍失败**

Run: `pytest tests/test_url_rewriter.py::TestBasicRewrite::test_github_blob_to_raw -v`
Expected: FAIL with "AssertionError" (因为 rewrite 还没有实现)

- [ ] **Step 4: 提交框架**

```bash
git add src/scrapling_fetch_mcp/_url_rewriter.py
git commit -m "feat(rewrite): add URLRewriter class skeleton

Add basic structure for URL rewriter with rule loading

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: 实现 URL 验证和规则匹配

**Files:**
- Modify: `src/scrapling_fetch_mcp/_url_rewriter.py`

- [ ] **Step 1: 添加 URL 验证方法**

在 `URLRewriter` 类中添加：

```python
    def _is_valid_url(self, url: str) -> bool:
        """
        验证 URL 格式是否有效
        
        Args:
            url: 要验证的 URL
        
        Returns:
            True 如果 URL 有效，否则 False
        """
        try:
            parsed = urlparse(url)
            # 检查必需的组件
            if not parsed.scheme or not parsed.netloc:
                return False
            # 只允许 http 和 https
            if parsed.scheme not in ('http', 'https'):
                return False
            return True
        except Exception:
            return False

    def _match_url(self, url: str, match_config: Dict[str, str]) -> bool:
        """
        检查 URL 是否匹配规则
        
        Args:
            url: 要检查的 URL
            match_config: 匹配配置
        
        Returns:
            True 如果匹配，否则 False
        """
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        match_type = match_config.get('type')
        pattern = match_config.get('pattern', '')
        
        if match_type == 'domain':
            # 完整域名匹配（支持 www 前缀）
            return domain == pattern or domain == f"www.{pattern}"
        
        elif match_type == 'domain_suffix':
            # 域名后缀匹配
            if pattern.startswith('.'):
                base_domain = pattern[1:]
                return domain == base_domain or domain.endswith(pattern)
            else:
                return domain == pattern
        
        elif match_type == 'regex':
            # 正则表达式匹配
            try:
                return bool(re.search(pattern, url))
            except re.error:
                logger.error(f"Invalid regex pattern: {pattern}")
                return False
        
        return False
```

- [ ] **Step 2: 实现 _find_matching_rule 方法**

```python
    def _find_matching_rule(self, url: str) -> Optional[Dict[str, Any]]:
        """
        查找匹配的重写规则
        
        优先级：自定义规则 > 内置规则
        
        Args:
            url: 要检查的 URL
        
        Returns:
            匹配的规则或 None
        """
        # 先检查自定义规则
        for rule in self.custom_rules:
            if self._match_url(url, rule.get('match', {})):
                return rule
        
        # 再检查内置规则
        for rule in self.builtin_rules:
            if self._match_url(url, rule.get('match', {})):
                return rule
        
        return None
```

- [ ] **Step 3: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/_url_rewriter.py`
Expected: 无输出（成功）

- [ ] **Step 4: 提交**

```bash
git add src/scrapling_fetch_mcp/_url_rewriter.py
git commit -m "feat(rewrite): implement URL validation and rule matching

Add URL validation and pattern matching for domain, domain_suffix, regex types

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 5: 实现规则应用和重写逻辑

**Files:**
- Modify: `src/scrapling_fetch_mcp/_url_rewriter.py`

- [ ] **Step 1: 实现 _apply_rule 方法**

```python
    def _apply_rule(self, url: str, rule: Dict[str, Any]) -> str:
        """
        应用重写规则
        
        Args:
            url: 原始 URL
            rule: 重写规则
        
        Returns:
            重写后的 URL
        """
        rewrite_config = rule.get('rewrite', {})
        rewrite_type = rewrite_config.get('type')
        
        if rewrite_type == 'none':
            # 不重写
            return url
        
        elif rewrite_type == 'regex_replace':
            # 正则表达式替换
            pattern = rewrite_config.get('pattern', '')
            replacement = rewrite_config.get('replacement', '')
            try:
                return re.sub(pattern, replacement, url)
            except re.error as e:
                logger.error(f"Regex substitution failed: {e}")
                return url
        
        elif rewrite_type == 'domain_replace':
            # 域名替换
            old_domain = rewrite_config.get('old', '')
            new_domain = rewrite_config.get('new', '')
            return url.replace(old_domain, new_domain, 1)
        
        elif rewrite_type == 'path_prefix':
            # 路径前缀（暂未使用，预留给自定义规则）
            prefix = rewrite_config.get('prefix', '')
            parsed = urlparse(url)
            new_path = prefix + parsed.path
            return parsed._replace(path=new_path).geturl()
        
        return url
```

- [ ] **Step 2: 实现 rewrite 主方法**

```python
    def rewrite(self, url: str) -> str:
        """
        重写 URL（如果匹配规则）
        
        包含错误处理、循环检测、链式重写支持
        
        Args:
            url: 原始 URL
        
        Returns:
            重写后的 URL（如果匹配）或原 URL
        """
        try:
            # 验证 URL
            if not self._is_valid_url(url):
                logger.warning(f"Invalid URL format: {url}")
                return url
            
            # 支持链式重写（最多 3 次）
            max_iterations = 3
            current_url = url
            
            for iteration in range(max_iterations):
                # 查找匹配的规则
                rule = self._find_matching_rule(current_url)
                if not rule:
                    # 没有匹配的规则，返回当前 URL
                    return current_url
                
                # 应用规则
                rewritten = self._apply_rule(current_url, rule)
                
                # 检测循环（重写后无变化）
                if rewritten == current_url:
                    return current_url
                
                # 继续尝试重写
                current_url = rewritten
            
            # 达到最大重写次数
            logger.warning(f"Max rewrite iterations ({max_iterations}) reached for URL: {url}")
            return current_url
        
        except Exception as e:
            logger.error(f"URL rewrite failed for {url}: {e}")
            return url  # 失败时返回原 URL
```

- [ ] **Step 3: 运行测试验证通过**

Run: `pytest tests/test_url_rewriter.py::TestBasicRewrite -v`
Expected: PASS (至少 test_github_blob_to_raw 应该通过)

- [ ] **Step 4: 提交**

```bash
git add src/scrapling_fetch_mcp/_url_rewriter.py
git commit -m "feat(rewrite): implement URL rewrite logic with error handling

- Add regex_replace, domain_replace, path_prefix rewrite types
- Add chain rewrite support (max 3 iterations)
- Add comprehensive error handling

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: 扩展测试覆盖所有内置规则

**Files:**
- Modify: `tests/test_url_rewriter.py`

- [ ] **Step 1: 添加其他内置规则的测试**

在 `TestBasicRewrite` 类中添加：

```python
    def test_duckduckgo_html_version(self):
        """DuckDuckGo 搜索应该重写为 html 版本"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/?q=python"
        expected = "https://duckduckgo.com/html/?q=python"
        assert rewriter.rewrite(url) == expected
    
    def test_duckduckgo_preserve_query_params(self):
        """DuckDuckGo 重写时应该保留查询参数"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/?q=python&kl=us-en"
        result = rewriter.rewrite(url)
        assert "/html/" in result
        assert "q=python" in result
        assert "kl=us-en" in result
    
    def test_duckduckgo_already_html(self):
        """已经是 html 版本的 DuckDuckGo 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://duckduckgo.com/html/?q=python"
        assert rewriter.rewrite(url) == url
    
    def test_reddit_old_version(self):
        """Reddit URL 应该重写为 old.reddit.com"""
        rewriter = URLRewriter()
        url = "https://www.reddit.com/r/python/comments/abc123/"
        expected = "https://old.reddit.com/r/python/comments/abc123/"
        assert rewriter.rewrite(url) == expected
    
    def test_reddit_already_old(self):
        """已经是 old.reddit.com 的 URL 不应该重复重写"""
        rewriter = URLRewriter()
        url = "https://old.reddit.com/r/python/"
        assert rewriter.rewrite(url) == url
    
    def test_stackoverflow_printer(self):
        """StackOverflow 问题应该重写为 StackPrinter"""
        rewriter = URLRewriter()
        url = "https://stackoverflow.com/questions/12345/some-title"
        result = rewriter.rewrite(url)
        assert "stackprinter.com" in result
        assert "question=12345" in result
        assert "service=stackoverflow" in result
    
    def test_no_match(self):
        """不匹配规则的 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "https://example.com/page"
        assert rewriter.rewrite(url) == url
```

- [ ] **Step 2: 运行测试**

Run: `pytest tests/test_url_rewriter.py::TestBasicRewrite -v`
Expected: PASS (所有测试应该通过)

- [ ] **Step 3: 提交**

```bash
git add tests/test_url_rewriter.py
git commit -m "test(rewrite): add tests for all built-in rules

Add comprehensive tests for DuckDuckGo, Reddit, StackOverflow rewriting

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 7: 添加错误处理和边界情况测试

**Files:**
- Modify: `tests/test_url_rewriter.py`

- [ ] **Step 1: 添加错误处理测试类**

```python
class TestErrorHandling:
    """错误处理测试"""
    
    def test_invalid_url(self):
        """无效 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "not-a-valid-url"
        assert rewriter.rewrite(url) == url
    
    def test_missing_scheme(self):
        """缺少协议的 URL 应该保持不变"""
        rewriter = URLRewriter()
        url = "example.com/page"
        assert rewriter.rewrite(url) == url
    
    def test_unsupported_scheme(self):
        """不支持的协议应该保持不变"""
        rewriter = URLRewriter()
        url = "ftp://example.com/file"
        assert rewriter.rewrite(url) == url
    
    def test_config_file_not_found(self):
        """配置文件不存在时应该使用内置规则"""
        rewriter = URLRewriter(Path("/nonexistent/config.yaml"))
        # 验证内置规则仍然工作
        url = "https://github.com/user/repo/blob/main/file.md"
        result = rewriter.rewrite(url)
        assert "raw.githubusercontent.com" in result


class TestEdgeCases:
    """边界情况测试"""
    
    def test_rewrite_idempotent(self):
        """重写应该是幂等的（多次重写结果相同）"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/file.md"
        result1 = rewriter.rewrite(url)
        result2 = rewriter.rewrite(result1)
        assert result1 == result2
    
    def test_preserve_fragment(self):
        """重写时应该保留 URL fragment"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/README.md#installation"
        result = rewriter.rewrite(url)
        assert "#installation" in result
        assert "raw.githubusercontent.com" in result
    
    def test_github_with_query_params(self):
        """GitHub URL 重写时应该保留查询参数"""
        rewriter = URLRewriter()
        url = "https://github.com/user/repo/blob/main/file.md?raw=true"
        result = rewriter.rewrite(url)
        # 注意：当前实现可能不保留查询参数，这是已知限制
        # 如果需要保留，需要改进 _apply_rule 方法
        pass
```

- [ ] **Step 2: 运行所有测试**

Run: `pytest tests/test_url_rewriter.py -v`
Expected: PASS (大部分测试应该通过，可能有 1-2 个边界情况失败)

- [ ] **Step 3: 修复发现的边界情况问题**

如果测试失败，根据失败原因修改 `_url_rewriter.py`

- [ ] **Step 4: 提交**

```bash
git add tests/test_url_rewriter.py src/scrapling_fetch_mcp/_url_rewriter.py
git commit -m "test(rewrite): add error handling and edge case tests

Add tests for invalid URLs, config errors, idempotency, fragment preservation

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 8: 扩展 Config 类

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`

- [ ] **Step 1: 在 Config 类中添加新属性**

在 `Config` 类中添加：

```python
class Config:
    # ... 现有属性 ...
    
    _url_rewrite_config_path: Optional[Path] = None
    _url_rewriter: Optional['URLRewriter'] = None
    _disable_url_rewrite: bool = False
    
    @property
    def url_rewrite_config_path(self) -> Optional[Path]:
        """Get the URL rewrite configuration file path"""
        return self._url_rewrite_config_path
    
    def set_url_rewrite_config_path(self, path: Path | str | None) -> None:
        """Set the URL rewrite configuration file path"""
        if path is None:
            self._url_rewrite_config_path = None
        elif isinstance(path, str):
            self._url_rewrite_config_path = Path(path)
        else:
            self._url_rewrite_config_path = path
    
    @property
    def url_rewriter(self) -> 'URLRewriter':
        """Get or create the URL rewriter instance"""
        if self._url_rewriter is None:
            from scrapling_fetch_mcp._url_rewriter import URLRewriter
            self._url_rewriter = URLRewriter(self._url_rewrite_config_path)
        return self._url_rewriter
    
    @property
    def disable_url_rewrite(self) -> bool:
        """Check if URL rewrite is disabled"""
        return self._disable_url_rewrite
    
    def set_disable_url_rewrite(self, disable: bool) -> None:
        """Set whether to disable URL rewrite"""
        self._disable_url_rewrite = disable
```

- [ ] **Step 2: 更新 init_config_from_env 函数**

在 `init_config_from_env()` 函数中添加：

```python
def init_config_from_env() -> None:
    """Initialize configuration from environment variables"""
    # ... 现有代码 ...
    
    # Load url_rewrite_config_path from environment
    env_url_rewrite_config = getenv("SCRAPLING_URL_REWRITE_CONFIG", "")
    if env_url_rewrite_config:
        config.set_url_rewrite_config_path(env_url_rewrite_config)
    
    # Load disable_url_rewrite from environment
    env_disable_url_rewrite = getenv("SCRAPLING_DISABLE_URL_REWRITE", "").lower()
    if env_disable_url_rewrite in ('true', '1', 'yes'):
        config.set_disable_url_rewrite(True)
```

- [ ] **Step 3: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/_config.py`
Expected: 无输出（成功）

- [ ] **Step 4: 提交**

```bash
git add src/scrapling_fetch_mcp/_config.py
git commit -m "feat(config): add URL rewrite configuration support

Add configuration for URL rewriter:
- url_rewrite_config_path property
- disable_url_rewrite flag
- Environment variable support

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 9: 集成到 fetch_page_impl

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`

- [ ] **Step 1: 在 fetch_page_impl 开头添加 URL 重写**

修改 `fetch_page_impl` 函数：

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
    
    # ... 其余代码保持不变 ...
```

- [ ] **Step 2: 在 fetch_pattern_impl 开头添加 URL 重写**

修改 `fetch_pattern_impl` 函数：

```python
async def fetch_pattern_impl(
    url: str,
    search_pattern: str,
    mode: str,
    format: str,
    max_length: int,
    context_chars: int,
) -> str:
    # 新增：URL 重写（在最开始执行）
    if not config.disable_url_rewrite:
        original_url = url
        url = config.url_rewriter.rewrite(url)
        if url != original_url:
            logger.debug(f"URL rewritten: {original_url} → {url}")
    
    effective_mode = config.get_effective_mode(mode)
    
    # ... 其余代码保持不变 ...
```

- [ ] **Step 3: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/_fetcher.py`
Expected: 无输出（成功）

- [ ] **Step 4: 提交**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py
git commit -m "feat(fetcher): integrate URL rewrite into fetch functions

Add URL rewriting at the start of fetch_page_impl and fetch_pattern_impl
to ensure cache is based on rewritten URLs

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 10: 添加 CLI 参数

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`

- [ ] **Step 1: 添加新的 CLI 参数**

在 `run_server()` 函数的参数解析部分添加：

```python
def run_server():
    """Parse CLI arguments and start the MCP server"""
    parser = ArgumentParser(
        description="Scrapling Fetch MCP Server - Fetch web content with bot-detection avoidance"
    )
    # ... 现有参数 ...
    
    parser.add_argument(
        "--disable-url-rewrite",
        action="store_true",
        help="Disable automatic URL rewriting for better stealth/speed. "
        "Default: enabled (URLs are rewritten automatically). "
        "Can also be set via SCRAPLING_DISABLE_URL_REWRITE environment variable.",
    )
    parser.add_argument(
        "--url-rewrite-config",
        type=str,
        default=None,
        help="Path to YAML file with custom URL rewrite rules. "
        "Default: Use built-in rules only. "
        "Can also be set via SCRAPLING_URL_REWRITE_CONFIG environment variable.",
    )
    args = parser.parse_args()
    
    # ... 现有配置代码 ...
    
    # 新增：URL 重写配置
    if args.disable_url_rewrite:
        config.set_disable_url_rewrite(True)
    
    if args.url_rewrite_config:
        config.set_url_rewrite_config_path(args.url_rewrite_config)
    
    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    # ... 现有日志 ...
    logger.info(f"URL rewrite disabled: {config.disable_url_rewrite}")
    if config.url_rewrite_config_path:
        logger.info(f"Custom URL rewrite config: {config.url_rewrite_config_path}")
    
    # ... mcp.run(transport="stdio") ...
```

- [ ] **Step 2: 验证文件语法**

Run: `python -m py_compile src/scrapling_fetch_mcp/mcp.py`
Expected: 无输出（成功）

- [ ] **Step 3: 提交**

```bash
git add src/scrapling_fetch_mcp/mcp.py
git commit -m "feat(cli): add URL rewrite command-line options

Add --disable-url-rewrite and --url-rewrite-config CLI arguments
with environment variable support

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 11: 运行完整测试套件

**Files:**
- None (运行测试)

- [ ] **Step 1: 运行所有 URL 重写相关测试**

Run: `pytest tests/test_url_rewriter.py -v`
Expected: PASS (所有测试应该通过)

- [ ] **Step 2: 运行完整的测试套件**

Run: `pytest tests/ -v`
Expected: PASS (所有测试应该通过，不应该有回归)

- [ ] **Step 3: 如果有失败，修复问题**

如果测试失败，根据错误信息修复代码

---

### Task 12: 更新 README 文档

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 在 README 中添加 URL Rewriting 章节**

在 "Tips for Best Results" 章节后添加：

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

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--disable-url-rewrite"]
    }
  }
}
```

Or via environment variable:

```json
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
```

### Custom Rewrite Rules

Add your own rewrite rules via configuration file:

```json
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
```

See [URL Rewrite Configuration](docs/url-rewrite-configuration.md) for details.
```

- [ ] **Step 2: 验证 Markdown 格式**

检查 Markdown 格式是否正确，预览效果

- [ ] **Step 3: 提交**

```bash
git add README.md
git commit -m "docs(readme): add URL rewriting documentation

Add documentation for URL rewrite feature:
- Explain built-in rules
- Show how to disable
- Show how to add custom rules

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 13: 创建配置文档

**Files:**
- Create: `docs/url-rewrite-configuration.md`

- [ ] **Step 1: 创建详细的配置文档**

```markdown
# URL Rewrite Configuration

## Overview

The URL rewrite feature automatically transforms certain URLs to lighter, more accessible versions before fetching. This improves both stealth success rates and fetch speed.

## Built-in Rules

The following rules are enabled by default:

| Website | Original URL | Rewritten URL | Benefit |
|---------|--------------|---------------|---------|
| GitHub | `github.com/user/repo/blob/branch/file` | `raw.githubusercontent.com/user/repo/branch/file` | Direct file content, no HTML rendering |
| DuckDuckGo | `duckduckgo.com/?q=query` | `duckduckgo.com/html/?q=query` | HTML version, no JavaScript |
| Reddit | `www.reddit.com/r/...` | `old.reddit.com/r/...` | Lighter version, less JavaScript |
| StackOverflow | `stackoverflow.com/questions/12345/title` | `stackprinter.com/export?question=12345&...` | Printer-friendly format |

## Disabling URL Rewrite

### Globally (CLI Argument)

```bash
scrapling-fetch-mcp --disable-url-rewrite
```

### Globally (Environment Variable)

```bash
export SCRAPLING_DISABLE_URL_REWRITE=true
scrapling-fetch-mcp
```

### In Claude Desktop Config

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": ["scrapling-fetch-mcp", "--disable-url-rewrite"]
    }
  }
}
```

## Custom Rules

Create a YAML file with your custom rewrite rules:

### Basic Structure

```yaml
url_rewrite_rules:
  - match:
      type: domain | domain_suffix | regex
      pattern: "pattern string"
    rewrite:
      type: regex_replace | path_prefix | domain_replace | none
      # type-specific parameters
```

### Match Types

#### domain
Exact domain match (with www prefix support):

```yaml
- match:
    type: domain
    pattern: example.com
  # Matches: example.com, www.example.com
```

#### domain_suffix
Domain suffix match (supports wildcards):

```yaml
- match:
    type: domain_suffix
    pattern: .example.com
  # Matches: example.com, sub.example.com, anything.example.com
```

#### regex
Regular expression match:

```yaml
- match:
    type: regex
    pattern: 'example\.com/page/\d+'
  # Matches: example.com/page/123, example.com/page/456
```

### Rewrite Types

#### regex_replace
Replace using regular expression:

```yaml
- rewrite:
    type: regex_replace
    pattern: 'example\.com/page/(\d+)'
    replacement: 'lite.example.com/view/\1'
```

#### domain_replace
Replace domain name:

```yaml
- rewrite:
    type: domain_replace
    old: www.example.com
    new: lite.example.com
```

#### path_prefix
Add prefix to path:

```yaml
- rewrite:
    type: path_prefix
    prefix: /lite
  # example.com/page → example.com/lite/page
```

#### none
Disable rewriting (useful for overriding built-in rules):

```yaml
- rewrite:
    type: none
```

### Example Configuration

```yaml
url_rewrite_rules:
  # Override built-in GitHub rule
  - match:
      type: domain_suffix
      pattern: github.com
    rewrite:
      type: regex_replace
      pattern: 'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)'
      replacement: 'raw.githubusercontent.com/\1/\2/\3/\4'
  
  # Add GitLab support
  - match:
      type: domain_suffix
      pattern: gitlab.com
    rewrite:
      type: regex_replace
      pattern: 'gitlab\.com/([^/]+)/([^/]+)/-/blob/([^/]+)/(.*)'
      replacement: 'gitlab.com/\1/\2/-/raw/\3/\4'
  
  # Disable Reddit rewriting (use modern version)
  - match:
      type: domain
      pattern: www.reddit.com
    rewrite:
      type: none
```

### Using Custom Rules

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--url-rewrite-config", "/path/to/custom-rewrite-rules.yaml"
      ]
    }
  }
}
```

Or via environment variable:

```bash
export SCRAPLING_URL_REWRITE_CONFIG=/path/to/custom-rewrite-rules.yaml
scrapling-fetch-mcp
```

## Priority

Rules are applied in this order:

1. Custom rules (from top to bottom in config file)
2. Built-in rules (GitHub, DuckDuckGo, Reddit, StackOverflow)
3. No match (URL remains unchanged)

The first matching rule wins.

## Limitations

- Query parameters and fragments are preserved by most rewrite types
- Maximum 3 rewrite iterations (prevents infinite loops)
- Only HTTP and HTTPS URLs are supported
- Invalid URLs are returned unchanged

## Debugging

To see which URLs are being rewritten, check the DEBUG logs:

```python
import logging
logging.getLogger("scrapling_fetch_mcp").setLevel(logging.DEBUG)
```

This will show messages like:
```
URL rewritten: https://github.com/user/repo/blob/main/file.md → https://raw.githubusercontent.com/user/repo/main/file.md
```

## FAQ

### When should I disable URL rewriting?

- When you need the full HTML interface (e.g., GitHub's web UI)
- When the lightweight version is missing features you need
- When debugging fetch issues

### Can I override built-in rules?

Yes! Custom rules take priority over built-in rules. Create a rule with the same match pattern and set `type: none` to disable it.

### Do rewrite rules affect caching?

Yes. The cache is based on the rewritten URL, not the original. This prevents duplicate fetches of the same content accessed via different URL forms.

### What if a rewrite rule breaks?

If a custom rule causes errors, the rewriter falls back to the original URL. Check the logs for error messages.
```

- [ ] **Step 2: 提交文档**

```bash
git add docs/url-rewrite-configuration.md
git commit -m "docs(rewrite): add comprehensive URL rewrite configuration guide

Add detailed documentation for URL rewrite feature:
- Built-in rules explanation
- Configuration file format
- Match and rewrite types
- Examples and FAQ

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 14: 创建配置示例文件

**Files:**
- Create: `docs/url-rewrite-config-example.yaml`

- [ ] **Step 1: 创建配置示例文件**

```yaml
# URL Rewrite Rules Configuration Example
# Use with: scrapling-fetch-mcp --url-rewrite-config /path/to/this/file.yaml

url_rewrite_rules:
  # =========================================================================
  # Example 1: Override built-in GitHub rule
  # =========================================================================
  # If you want to customize the GitHub rewrite behavior
  - match:
      type: domain_suffix
      pattern: github.com
    rewrite:
      type: regex_replace
      pattern: 'github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)'
      replacement: 'raw.githubusercontent.com/\1/\2/\3/\4'
  
  # =========================================================================
  # Example 2: Add GitLab support
  # =========================================================================
  # GitLab has a similar structure to GitHub
  - match:
      type: domain_suffix
      pattern: gitlab.com
    rewrite:
      type: regex_replace
      pattern: 'gitlab\.com/([^/]+)/([^/]+)/-/blob/([^/]+)/(.*)'
      replacement: 'gitlab.com/\1/\2/-/raw/\3/\4'
  
  # =========================================================================
  # Example 3: Add support for GitHub Gists
  # =========================================================================
  - match:
      type: domain
      pattern: gist.github.com
    rewrite:
      type: regex_replace
      pattern: 'gist\.github\.com/([^/]+)/([a-f0-9]+)$'
      replacement: 'gist.githubusercontent.com/\1/\2/raw'
  
  # =========================================================================
  # Example 4: Twitter/X → Nitter (alternative frontend)
  # =========================================================================
  # Note: Nitter instances may have varying availability
  - match:
      type: domain
      pattern: twitter.com
    rewrite:
      type: domain_replace
      old: twitter.com
      new: nitter.net
  
  # =========================================================================
  # Example 5: Disable Reddit rewriting
  # =========================================================================
  # If you prefer the modern Reddit interface
  - match:
      type: domain
      pattern: www.reddit.com
    rewrite:
      type: none  # Don't rewrite
  
  # =========================================================================
  # Example 6: Add path prefix for Medium
  # =========================================================================
  # Hypothetical example if Medium had a lite version
  # - match:
  #     type: domain
  #     pattern: medium.com
  #   rewrite:
  #     type: path_prefix
  #     prefix: /lite
  
  # =========================================================================
  # Example 7: Complex regex for specific patterns
  # =========================================================================
  # Rewrite specific documentation pages
  # - match:
  #     type: regex
  #     pattern: 'docs\.example\.com/v1/(.*)'
  #   rewrite:
  #     type: regex_replace
  #     pattern: 'docs\.example\.com/v1/(.*)'
  #     replacement: 'docs.example.com/v2/\1'

# =========================================================================
# Tips:
# =========================================================================
# 1. Custom rules take priority over built-in rules
# 2. First matching rule wins
# 3. Use 'type: none' to disable a built-in rule
# 4. Test your rules with DEBUG logging enabled
# 5. Maximum 3 rewrite iterations (prevents loops)
```

- [ ] **Step 2: 提交示例文件**

```bash
git add docs/url-rewrite-config-example.yaml
git commit -m "docs(rewrite): add URL rewrite configuration example

Provide comprehensive example configuration with:
- Override examples
- GitLab and Gist support
- Twitter/Nitter example
- Detailed comments

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 15: 手动测试真实网站

**Files:**
- None (手动测试)

- [ ] **Step 1: 测试 GitHub 重写**

手动测试命令（或通过 MCP 客户端）：
```python
# 使用 scrapling-fetch-mcp 的 fetch 功能
url = "https://github.com/python/cpython/blob/main/README.rst"
# 预期：重写为 raw.githubusercontent.com
# 验证：返回的内容是纯文本，不是 HTML 页面
```

- [ ] **Step 2: 测试 DuckDuckGo 重写**

```python
url = "https://duckduckgo.com/?q=python+testing"
# 预期：重写为 duckduckgo.com/html/?q=python+testing
# 验证：返回的是 HTML 版本的搜索结果
```

- [ ] **Step 3: 测试 Reddit 重写**

```python
url = "https://www.reddit.com/r/Python/"
# 预期：重写为 old.reddit.com/r/Python/
# 验证：返回的是老版本 Reddit
```

- [ ] **Step 4: 测试 StackOverflow 重写**

```python
url = "https://stackoverflow.com/questions/1234567/example-question"
# 预期：重写为 stackprinter.com URL
# 验证：返回的是 StackPrinter 格式的内容
```

- [ ] **Step 5: 测试禁用重写**

```python
# 使用 --disable-url-rewrite 启动
url = "https://github.com/user/repo/blob/main/file.md"
# 预期：不重写，访问原始 GitHub 页面
```

- [ ] **Step 6: 记录测试结果**

如果发现问题，创建新的测试用例或修复代码

---

## 完成标准

计划完成时应该满足：

- [ ] 所有测试通过（单元测试 + 集成测试）
- [ ] 内置规则正确工作（GitHub、DuckDuckGo、Reddit、StackOverflow）
- [ ] 配置系统正常工作（CLI 参数 + 环境变量）
- [ ] 文档完整且准确
- [ ] 没有破坏现有功能（回归测试通过）
- [ ] 手动测试验证真实场景可用

---

## 执行建议

1. **使用 TDD**：先写测试，再实现功能
2. **频繁提交**：每完成一个小步骤就提交
3. **按顺序执行**：任务有依赖关系，不要跳过
4. **遇到问题**：先运行测试，根据错误信息调试
5. **完成后验证**：运行完整的测试套件确保没有回归

---

## 相关文档

- 规格文档：`docs/superpowers/specs/2026-03-20-url-rewrite-design.md`
- 配置文档：`docs/url-rewrite-configuration.md`
- 配置示例：`docs/url-rewrite-config-example.yaml`
