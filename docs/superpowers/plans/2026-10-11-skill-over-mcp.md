# Skill over MCP(SEP-2640)与 Tool 描述优化实施计划(spec2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 spec `docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md`:发布 `scrapling-fetch` skill(SEP-2640 扩展 + SKILL.md)并完成 tool 描述四项优化。

**Architecture:** `SkillsExtension(Extension)` 贡献 `skill://scrapling-fetch/SKILL.md` 资源与 `skills/list`/`skills/get` 两个 MethodBinding;SKILL.md 作为包内数据随 wheel 分发(`importlib.resources` 读取);`mcp.py` 注册扩展并在 `instructions` 里给指针;`_features.py` 只做单次调用契约的最小描述修改。

**Tech Stack:** mcp 2.0.0(`Extension`/`MethodBinding`/`ResourceBinding`/`TextResource`)、pyyaml(frontmatter 解析)、hashlib(digest)、pytest、MCP stdio client(真实验证)。

**Spec:** docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md

## Global Constraints

- SEP-2640 关键约定:`identifier = "io.modelcontextprotocol/skills"`;SKILL.md 资源 URI 末段必须等于 frontmatter `name`;entry 形态 `{uri, frontmatter(逐字 JSON), resources: [{uri, digest: "sha256:<hex>", size}]}`;`skills/get` 对未知 URI 返回错误码 `-32602`;`skills/list`/`skills/get` 结果携带 `ttlMs` 与 `cacheScope`(CacheableResult)。
- SKILL.md frontmatter 至少含 `name`/`description`(Agent Skills 规范)。
- SKILL.md 文件缺失时:扩展不注册、不注册方法,server 其余功能不受影响(logger.warning)。
- tool 描述只改 spec 3.3 表列四项,不得把工作流内容塞回描述。
- 临时验证脚本放 `.temp/airead_serp_test/`(gitignore),不入库。
- commit 遵循 Angular 规范;基线测试 `219 passed`(spec1 之后)。

---

### Task 1: SKILL.md 内容与 frontmatter 测试

**Files:**
- Create: `src/scrapling_fetch_mcp/skills/scrapling-fetch/SKILL.md`
- Test: `tests/test_skill_content.py`(新)

**Interfaces:**
- Consumes: 无。
- Produces: 包内数据文件 `scrapling_fetch_mcp/skills/scrapling-fetch/SKILL.md`;frontmatter `name: scrapling-fetch`、`description: <一句话>`;Task 2 的 `_skills.py` 用 `importlib.resources.files("scrapling_fetch_mcp").joinpath("skills/scrapling-fetch/SKILL.md")` 读取它。

- [ ] **Step 1: 写 SKILL.md(完整内容,逐字)**

创建 `src/scrapling_fetch_mcp/skills/scrapling-fetch/SKILL.md`,内容如下:

```markdown
---
name: scrapling-fetch
description: Fetching workflows for the scrapling-fetch-mcp server — search-result harvesting, paginated reading of long pages, format/mode selection, and known site limitations. Use when a task needs web content via the s_fetch_page or s_fetch_pattern tools.
---

# Scrapling Fetch Workflows

How to use the `s_fetch_page` and `s_fetch_pattern` tools effectively.

## Tool selection

- `s_fetch_page`: read a whole page (paginated). Default choice for reading.
- `s_fetch_pattern`: extract regex-matched fragments. Use it to locate specific
  data in a large page, then re-fetch with `start_index` around the match
  positions. Note: `s_fetch_pattern` does NOT support `format="airead"`
  (airead is converted to markdown).

## Search workflow (the main pattern)

1. Fetch a search-engine results page with `format="airead"`, e.g.
   `s_fetch_page(url="https://www.bing.com/search?q=YOUR_QUERY", format="airead")`.
   Works for bing.com, duckduckgo.com, google.com (stealth mode), startpage,
   brave, searx instances.
2. The airead output contains `## Search Results` with `### N. <title>` blocks,
   each ending with `[查看原文](<real-url>)` — the link is already resolved to
   the real destination (Bing `ck/a` base64 and Google `/goto` tokens are
   decoded server-side).
3. Pick URLs from those blocks and fetch each with `s_fetch_page` as usual.
4. Do NOT hand-construct lightweight URLs (`html.duckduckgo.com`,
   `stackprinter.com`, `old.reddit.com`) — the server rewrites known sites
   automatically. Pass the original URL.

## Paginated reading

- The tool reply starts with `METADATA: {json}` on its own line. Check
  `is_truncated`.
- To continue reading: `start_index = start_index + max_length`, keep
  `max_length` unchanged. Repeat until `is_truncated` is false.
- `total_length` tells you how much is left; for long pages prefer scanning a
  pattern with `s_fetch_pattern` first.

## Format and mode decisions

- `format="airead"` by default: content-extraction per site type, big token
  savings. Use `format="markdown"` when you need the full document structure;
  `format="html"` only to debug page structure.
- `mode="basic"` first (fast). If you get a challenge page, 403, 202, or an
  empty shell, retry once with `mode="stealth"`. Only use `mode="max-stealth"`
  for the strongest anti-bot sites.

## Known limitations

- Some sites block plain HTTP clients: zhihu.com (login wall), juejin.cn
  (SPA, empty shell), reddit.com (often an empty shell), DuckDuckGo/Bing under
  heavy request bursts (202 challenge pages). These usually need stealth mode
  or are simply unavailable.
- Consecutive requests to the same search engine can trip rate limits — space
  them out; a 202/17-character "## Search Results" reply means you were
  challenged, back off and retry later.
- The server may return `METADATA` saying `is_truncated: true` — that is
  normal pagination, not an error.
```

- [ ] **Step 2: 写 frontmatter 测试**

创建 `tests/test_skill_content.py`:

```python
"""SKILL.md 打包数据与 Agent Skills frontmatter 约束测试。"""
from importlib import resources

import pytest
import yaml


@pytest.fixture(scope="module")
def skill_text() -> str:
    path = resources.files("scrapling_fetch_mcp").joinpath(
        "skills/scrapling-fetch/SKILL.md")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(skill_text) -> dict:
    assert skill_text.startswith("---")
    _, fm_block, _body = skill_text.split("---", 2)
    return yaml.safe_load(fm_block)


def test_frontmatter_has_required_fields(frontmatter):
    assert frontmatter["name"] == "scrapling-fetch"
    assert isinstance(frontmatter["description"], str)
    assert len(frontmatter["description"]) > 20


def test_skill_name_matches_directory(frontmatter):
    # Agent Skills 规范:name 必须等于所在目录名
    assert frontmatter["name"] == "scrapling-fetch"


def test_skill_body_covers_core_workflows(skill_text):
    for keyword in ("s_fetch_page", "s_fetch_pattern", "is_truncated",
                    "start_index", "查看原文", "stealth"):
        assert keyword in skill_text, keyword
```

- [ ] **Step 3: 运行测试**

Run: `.venv/bin/python -m pytest tests/test_skill_content.py -v`
Expected: 3 passed

- [ ] **Step 4: Commit**

```bash
git add src/scrapling_fetch_mcp/skills/ tests/test_skill_content.py
git commit -m "feat(skill): add scrapling-fetch SKILL.md content

Agent Skills 格式的工作流指令:工具选择、搜索-抓取两步工作流、
分页续读、format/mode 决策与已知站点限制。包内数据,随 wheel 分发。
对应 spec: docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md"
```

---

### Task 2: SkillsExtension 实现(`_skills.py`)

**Files:**
- Create: `src/scrapling_fetch_mcp/_skills.py`
- Test: `tests/test_skills_extension.py`(新)

**Interfaces:**
- Consumes: Task 1 的包内 SKILL.md。
- Produces: `SkillsExtension`(`.available() -> bool`、继承 `mcp.server.extension.Extension`),供 Task 3 的 `mcp.py` 注册;常量 `SKILL_URI = "skill://scrapling-fetch/SKILL.md"`、`EXTENSION_ID = "io.modelcontextprotocol/skills"`。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_skills_extension.py`:

```python
"""SkillsExtension(SEP-2640)单元测试。"""
import hashlib

import pytest

from scrapling_fetch_mcp._skills import (
    SKILL_URI,
    SkillsExtension,
    load_skill_markdown,
)


@pytest.fixture()
def ext() -> SkillsExtension:
    return SkillsExtension()


def test_load_skill_markdown_returns_content():
    text = load_skill_markdown()
    assert text is not None
    assert text.startswith("---\nname: scrapling-fetch")


def test_extension_available(ext):
    assert ext.available() is True


def test_extension_identifier(ext):
    assert ext.identifier == "io.modelcontextprotocol/skills"


def test_resources_binding(ext):
    bindings = ext.resources()
    assert len(bindings) == 1
    res = bindings[0].resource
    assert res.uri == SKILL_URI
    assert res.mime_type == "text/markdown"
    assert res.name == "scrapling-fetch"


@pytest.mark.asyncio
async def test_read_resource_returns_markdown(ext):
    bindings = ext.resources()
    text = await bindings[0].resource.read()
    assert "# Scrapling Fetch Workflows" in text


def test_skills_entry_shape(ext):
    entry = ext.skill_entry()
    assert entry["uri"] == SKILL_URI
    fm = entry["frontmatter"]
    assert fm["name"] == "scrapling-fetch"
    assert "description" in fm
    assert isinstance(fm, dict)
    resources = entry["resources"]
    assert len(resources) == 1
    raw = load_skill_markdown().encode()
    assert resources[0]["size"] == len(raw)
    assert resources[0]["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.mark.asyncio
async def test_skills_list_method(ext):
    methods = {m.method: m for m in ext.methods()}
    assert set(methods) == {"skills/list", "skills/get"}
    result = await methods["skills/list"].handler(None, None)
    assert result["resultType"] == "complete"
    assert result["skills"] == [ext.skill_entry()]
    assert "ttlMs" in result and "cacheScope" in result


@pytest.mark.asyncio
async def test_skills_get_method(ext):
    methods = {m.method: m for m in ext.methods()}
    result = await methods["skills/get"].handler(None, type("P", (), {"uri": SKILL_URI})())
    assert result["skill"]["uri"] == SKILL_URI


@pytest.mark.asyncio
async def test_skills_get_unknown_uri_rejected(ext):
    from mcp.shared.exceptions import MCPError
    methods = {m.method: m for m in ext.methods()}
    with pytest.raises(MCPError) as exc:
        await methods["skills/get"].handler(
            None, type("P", (), {"uri": "skill://unknown/SKILL.md"})())
    assert exc.value.code == -32602


def test_missing_skill_file_disables_extension(monkeypatch):
    monkeypatch.setattr("scrapling_fetch_mcp._skills.load_skill_markdown",
                        lambda: None)
    ext = SkillsExtension()
    assert ext.available() is False
    assert ext.resources() == []
    assert ext.methods() == []
    with pytest.raises(ValueError):
        ext.skill_entry()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_extension.py -v`
Expected: FAIL(`ModuleNotFoundError: scrapling_fetch_mcp._skills`)

- [ ] **Step 3: 实现 `_skills.py`**

创建 `src/scrapling_fetch_mcp/_skills.py`,内容如下:

```python
"""MCP Skills extension (SEP-2640, io.modelcontextprotocol/skills).

Serves the bundled `scrapling-fetch` skill as a `skill://` resource and
implements the `skills/list` / `skills/get` methods required by the spec.
SKILL.md 缺失时扩展整体不启用,server 其余功能不受影响。
"""
import hashlib
import logging
from importlib import resources as importlib_resources
from typing import Any, Optional

import yaml
from pydantic import BaseModel

from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError

logger = logging.getLogger(__name__)

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILL_NAME = "scrapling-fetch"
SKILL_URI = f"skill://{SKILL_NAME}/SKILL.md"
_SKILL_PATH = "skills/scrapling-fetch/SKILL.md"
_ENTRY_TTL_MS = 300000
_CACHE_SCOPE = "public"


class GetSkillParams(BaseModel):
    """Params of the skills/get method: the SKILL.md URI."""
    uri: str


class _ListSkillsParams(BaseModel):
    """skills/list takes no fields (pagination cursor unused, single skill)."""


def load_skill_markdown() -> Optional[str]:
    """Read the packaged SKILL.md; None when the data file is missing."""
    try:
        return importlib_resources.files("scrapling_fetch_mcp").joinpath(
            _SKILL_PATH).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        logger.warning("SKILL.md not found at %s, skills extension disabled",
                       _SKILL_PATH)
        return None


class SkillsExtension(Extension):
    """Publishes the bundled skill per SEP-2640."""

    identifier = EXTENSION_ID

    def __init__(self) -> None:
        self._markdown: Optional[str] = load_skill_markdown()

    def available(self) -> bool:
        return self._markdown is not None

    def _frontmatter(self) -> dict[str, Any]:
        text = self._markdown or ""
        if text.startswith("---"):
            _, fm_block, _body = text.split("---", 2)
            return yaml.safe_load(fm_block) or {}
        return {}

    def skill_entry(self) -> dict[str, Any]:
        """SEP-2640 Skill entry: verbatim frontmatter + file manifest."""
        if self._markdown is None:
            raise ValueError("skill content is not available")
        raw = self._markdown.encode("utf-8")
        return {
            "uri": SKILL_URI,
            "frontmatter": self._frontmatter(),
            "resources": [{
                "uri": SKILL_URI,
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }],
        }

    def settings(self) -> dict[str, Any]:
        # 不实现 resources/directory/read
        return {}

    def resources(self) -> list[ResourceBinding]:
        if not self.available():
            return []
        fm = self._frontmatter()
        resource = TextResource(
            uri=SKILL_URI,
            name=fm.get("name"),
            description=fm.get("description"),
            mime_type="text/markdown",
            text=self._markdown,
        )
        return [ResourceBinding(resource=resource)]

    def methods(self) -> list[MethodBinding]:
        if not self.available():
            return []

        async def skills_list(ctx, params):
            return {
                "resultType": "complete",
                "skills": [self.skill_entry()],
                "ttlMs": _ENTRY_TTL_MS,
                "cacheScope": _CACHE_SCOPE,
            }

        async def skills_get(ctx, params: GetSkillParams):
            if params.uri != SKILL_URI:
                raise MCPError(
                    code=-32602,
                    message=f"No skill is served at {params.uri}",
                )
            return {
                "resultType": "complete",
                "skill": self.skill_entry(),
                "ttlMs": _ENTRY_TTL_MS,
                "cacheScope": _CACHE_SCOPE,
            }

        return [
            MethodBinding(method="skills/list",
                          params_type=_ListSkillsParams, handler=skills_list),
            MethodBinding(method="skills/get",
                          params_type=GetSkillParams, handler=skills_get),
        ]


def build_extension() -> Optional[SkillsExtension]:
    """Extension instance, or None when the skill data file is missing."""
    ext = SkillsExtension()
    return ext if ext.available() else None
```

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_extension.py tests/test_skill_content.py -v`
Expected: 全部 passed(约 11 个)

- [ ] **Step 5: 全量回归 + Commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `219 + 新增数量 passed`,无失败

```bash
git add src/scrapling_fetch_mcp/_skills.py tests/test_skills_extension.py
git commit -m "feat(skill): implement SEP-2640 SkillsExtension

skill://scrapling-fetch/SKILL.md 资源 + skills/list、skills/get 方法;
entry 含逐字 frontmatter 与 sha256 manifest;SKILL.md 缺失时扩展整体
禁用(降级不注册)。对应 spec: docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md"
```

---

### Task 3: mcp.py 注册扩展 + instructions 指针

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`(模块级 `mcp = MCPServer(...)` 处,约 L24)
- Test: `tests/test_skills_extension.py`(追加注册断言)

**Interfaces:**
- Consumes: Task 2 的 `build_extension()`、`SKILL_URI`。
- Produces: `mcp` 实例带扩展与 instructions;Task 5 的 stdio 真实验证依赖本任务。

- [ ] **Step 1: 写注册断言测试(追加到 `tests/test_skills_extension.py` 末尾)**

```python
def test_mcp_server_registers_extension_and_instruction():
    from scrapling_fetch_mcp.mcp import mcp, SERVER_INSTRUCTIONS

    assert SKILL_URI in SERVER_INSTRUCTIONS
    registered = getattr(mcp, "_extensions", [])
    assert any(e.identifier == "io.modelcontextprotocol/skills"
               for e in registered)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_extension.py -v`
Expected: 新用例 FAIL(无 `SERVER_INSTRUCTIONS`)

- [ ] **Step 3: 修改 `mcp.py`**

在 `mcp = MCPServer("scrapling-fetch-mcp")` 处改为:

```python
from scrapling_fetch_mcp._skills import SKILL_URI, build_extension

_skill_extension = build_extension()

SERVER_INSTRUCTIONS = (
    "Fetch pages with s_fetch_page / s_fetch_pattern. Prefer "
    "format='airead'. Load skill " + SKILL_URI + " via the skills "
    "extension for detailed fetching workflows."
)

mcp = MCPServer(
    "scrapling-fetch-mcp",
    instructions=SERVER_INSTRUCTIONS,
    extensions=[_skill_extension] if _skill_extension else [],
)
```

注意:保持该文件其余部分不变;`from scrapling_fetch_mcp._skills import ...` 加入既有 import 区。

- [ ] **Step 4: 运行测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_skills_extension.py tests/test_mcp_registration.py -v`
Expected: 全部 passed(现有 mcp_registration 用例不受影响)

- [ ] **Step 5: 全量回归 + Commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed

```bash
git add src/scrapling_fetch_mcp/mcp.py tests/test_skills_extension.py
git commit -m "feat(skill): register skills extension with instructions pointer

MCPServer 挂载 SkillsExtension 并在 instructions 里给出 skill URI
指针(规范允许的零成本发现路径);SKILL.md 缺失时不注册。"
```

---

### Task 4: tool 描述优化(`_features.py`)

**Files:**
- Modify: `src/scrapling_fetch_mcp/_features.py`(mode 描述两处、S_FETCH_PAGE_DOCSTRING、S_FETCH_PATTERN_DOCSTRING)
- Test: `tests/test_skills_extension.py`(追加描述断言)

**Interfaces:**
- Consumes: 无。
- Produces: 更新后的 tool schema 描述;Task 5 验证依赖。

- [ ] **Step 1: 追加描述断言(追加到 `tests/test_skills_extension.py` 末尾)**

```python
def test_fetch_page_docstring_covers_contract():
    from scrapling_fetch_mcp._features import S_FETCH_PAGE_DOCSTRING
    assert "### N." in S_FETCH_PAGE_DOCSTRING          # SERP 输出契约
    assert "skill://scrapling-fetch/SKILL.md" in S_FETCH_PAGE_DOCSTRING
    assert "is_truncated" not in S_FETCH_PAGE_DOCSTRING  # 工作流归 skill


def test_mode_description_concise():
    from scrapling_fetch_mcp._features import TOOL_PARAMS
    for tool in ("s_fetch_page", "s_fetch_pattern"):
        desc = TOOL_PARAMS[tool]["mode"]["description"]
        assert "403" in desc and "stealth" in desc
        assert len(desc) < 200


def test_pattern_docstring_states_text_domain():
    from scrapling_fetch_mcp._features import S_FETCH_PATTERN_DOCSTRING
    assert "markdown" in S_FETCH_PATTERN_DOCSTRING
```

- [ ] **Step 2: 运行测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_skills_extension.py -v`
Expected: 新用例 FAIL

- [ ] **Step 3: 修改 `_features.py`**

四处修改(保持英文、只动契约):

`S_FETCH_PAGE_DOCSTRING` 改为:

```python
S_FETCH_PAGE_DOCSTRING = (
    "Fetches a complete web page with pagination support. Retrieves content from "
    "websites with bot-detection avoidance. Content is returned as "
    "'METADATA: {json}\\n\\n[content]' where metadata includes length information "
    "and truncation status.\n"
    "\n"
    "IMPORTANT:\n"
    "- Use format='airead' for AI-optimized content extraction "
    "(removes navigation, ads, etc., 30-50% token reduction). On search-engine "
    "pages it returns structured entries: '### N. <title>' blocks with resolved "
    "real links ('[查看原文](<url>)').\n"
    "- Use format='markdown' for standard markdown conversion\n"
    "- Use format='html' only when you need raw HTML structure\n"
    "\n"
    "The airead format routes by URL to specialized strategies (search engines, "
    "developer platforms, documentation). Known sites (DuckDuckGo, Reddit, "
    "StackOverflow/StackExchange) are automatically rewritten to lighter "
    "variants — pass the original URL. Fetching workflows: load skill "
    "skill://scrapling-fetch/SKILL.md."
)
```

`S_FETCH_PATTERN_DOCSTRING` 在末尾 `\n` 前追加一段:

```python
    "\n"
    "The pattern is matched against the text produced by the chosen format "
    "(markdown or html). Fetching workflows: load skill "
    "skill://scrapling-fetch/SKILL.md."
)
```

两处 `mode` 的 description 改为:

```python
"description": "Fetching mode: basic (fast, default), stealth (light anti-bot), max-stealth (strong anti-bot). Escalate to stealth when you get 403/202 or challenge pages.",
```

- [ ] **Step 4: 运行测试确认通过 + 全量回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
git add src/scrapling_fetch_mcp/_features.py tests/test_skills_extension.py
git commit -m "docs(tools): tighten tool descriptions to call contracts

S_FETCH_PAGE 增补 SERP 输出形态与 skill 指针;mode 描述精简并给出
403/202 升级指引;s_fetch_pattern 声明 pattern 作用于 format 转换后
文本。工作流内容保留在 skill,不进描述。"
```

---

### Task 5: 端到端真实验证(stdio client)

**Files:**
- Create: `.temp/airead_serp_test/verify_skill_mcp.py`(临时,不入库)

**Interfaces:**
- Consumes: Task 1-4 的全部产出(server 完整行为)。
- Produces: wire 层验证记录,回填 spec 第 5 节。

- [ ] **Step 1: 写验证脚本**

```python
"""真实验证:MCP stdio client 验证 skills 扩展的 wire 行为。"""
import asyncio
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

SERVER = Path(__file__).resolve().parents[2] / ".venv" / "bin" / "scrapling-fetch-mcp"


async def main():
    params = StdioServerParameters(command=str(SERVER), args=["--transport", "stdio"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            print("1) initialize OK, protocol:", init.protocolVersion)

            resources = await session.list_resources()
            uris = [str(r.uri) for r in resources.resources]
            print("2) list_resources:", uris)
            assert "skill://scrapling-fetch/SKILL.md" in uris

            contents = await session.read_resource("skill://scrapling-fetch/SKILL.md")
            text = contents.contents[0].text
            print(f"3) read_resource OK, {len(text)} chars, starts:",
                  text[:40].replace("\n", "|"))
            assert text.startswith("---\nname: scrapling-fetch")

            # skills/list 与 skills/get 为扩展方法;client 库未内置时用低层会话
            try:
                result = await session.request(
                    {"method": "skills/list", "params": {}}, )
                print("4) skills/list:", result)
            except Exception as e:
                print("4) skills/list via request failed:", e)

            # 降级路径回归:普通工具调用仍正常
            tools = await session.list_tools()
            print("5) tools:", [t.name for t in tools.tools])
            assert set(t.name for t in tools.tools) >= {"s_fetch_page", "s_fetch_pattern"}


if __name__ == "__main__":
    asyncio.run(main())
```

注意:`session.request` 的确切签名以安装的 mcp client 版本为准——若高层 `ClientSession` 未暴露任意方法请求,改用 `session.send_request(...)` 或 `ClientSession._request`,以能发出 `skills/list` JSON-RPC 请求为准;若确实无法从高层 API 发出,则把 wire 验证降级为「`list_resources`/`read_resource`/`tools` 三项 + 说明 skills/list|get 属 server 侧已由 Task 2 单测覆盖」,在报告中明确说明验证层级。

- [ ] **Step 2: 运行并保存输出**

Run: `cd .temp/airead_serp_test && ../../.venv/bin/python verify_skill_mcp.py 2>/dev/null | tee skill_mcp_verify.txt`
Expected: 五步全部通过(或按注意条款降级验证)

- [ ] **Step 3: 回填 spec 第 5 节实施状态**

`docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md` 第 5 节"实施清单"改为完成态(逐项打勾 + 验证结果一行 + 实测输出文件路径)。

- [ ] **Step 4: 全量回归 + Commit**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 全部 passed

```bash
git add docs/superpowers/specs/2026-10-11-skill-over-mcp-design.md
git commit -m "docs(spec): mark skill-over-mcp implementation verified"
```

---

## Self-Review 记录

- **Spec 覆盖**:spec 3.1(SKILL.md)→ Task 1;3.2(SkillsExtension)→ Task 2;注册+instructions(3.2 末条)→ Task 3;3.3 描述四项 → Task 4;3.4 验证 → 各任务测试 + Task 5;第 5 节回填 → Task 5。无缺口。
- **占位符扫描**:SKILL.md、_skills.py、测试代码全部给出全文;Task 5 有一处显式声明的 API 适配分支(高层 client 若无任意方法请求 API 时的降级验证),这是对未验证的 client SDK API 的诚实处理,不是占位符。
- **类型一致性**:`load_skill_markdown()`/`skill_entry()`/`available()` 在 Task 2 定义、Task 3(`build_extension`/`SKILL_URI`)与 Task 4(仅常量)引用一致;`SKILL_URI` 与 SKILL.md 目录名一致;`-32602` 与 spec 2.2 一致。
- **测试卫生**:所有新测试有真实断言;`test_missing_skill_file_disables_extension` 用 monkeypatch 隔离,不打文件系统。
