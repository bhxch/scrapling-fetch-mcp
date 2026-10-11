# 站点覆盖扩展实施计划(spec1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 spec `docs/superpowers/specs/2026-10-11-site-coverage-expansion-design.md` 的剩余实施——提交已验证的规则代码,逐站端到端实测并回填 spec 附录。

**Architecture:** 路由/重写均为声明式规则(已在工作区且 217 测试通过);实测走 `fetch_page_impl` 完整管线(重写 → 抓取 → 路由 → 策略提取),按"条目数/正文关键词/噪音"评估;不达标的站点按 spec 原则跳过并记录,不做适配性死磕。

**Tech Stack:** Python 3.12、pytest、scrapling-fetch-mcp 自身管线、MCP stdio(本次不涉及,直连 fetch_page_impl)。

**Spec:** docs/superpowers/specs/2026-10-11-site-coverage-expansion-design.md

## Global Constraints

- 工作区已有改动必须先经全量测试验证(基线:`217 passed`)再提交。
- 跳过原则:实测不达标的站点不写专用通道、不对抗风控,路由保留,结论回填 spec 第 4 节。
- 临时实测脚本一律放 `.temp/airead_serp_test/`(已 gitignore),不入库。
- commit 遵循 Angular 规范,单一目的。
- 新搜索引擎(SERP)实测时短时间只发一次请求,遇 202/403 不重试轰炸,记录为风控限制。

---

### Task 1: 提交路由与重写规则(工作区已有改动)

**Files:**
- Modify: `src/scrapling_fetch_mcp/_default_rules.py`(已改)
- Modify: `src/scrapling_fetch_mcp/_default_rewrite_rules.py`(已改)
- Test: `tests/test_url_matcher.py`(已改)、`tests/test_url_rewriter.py`(已改)

**Interfaces:**
- Consumes: 无(纯规则与测试)。
- Produces: 内置路由规则含 brave/startpage/searx/stackexchange/superuser 系/HN/reddit/v2ex/infoq/juejin/csdn/cnblogs/zhihu/stackprinter;重写规则含 SE 子域泛化与 superuser 系合并规则。后续任务依赖 `fetch_page_impl` 对这些 URL 的正确重写与路由。

- [ ] **Step 1: 审查工作区 diff**

Run: `git diff --stat && git diff src/scrapling_fetch_mcp/_default_rules.py src/scrapling_fetch_mcp/_default_rewrite_rules.py`
Expected: 变更仅限 spec 3.1/3.2 所列规则;无意外文件混入(`.zcodeignore` 为会话前已存在,不提交)。

- [ ] **Step 2: 全量测试**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `217 passed`(基线已确认)。

- [ ] **Step 3: Commit**

```bash
git add src/scrapling_fetch_mcp/_default_rules.py src/scrapling_fetch_mcp/_default_rewrite_rules.py tests/test_url_matcher.py tests/test_url_rewriter.py
git commit -m "feat(rules): route extended search engines and tech sites
- search_engine: brave/startpage/searx(regex 覆盖公共实例)
- developer_platform: stackexchange 子域、superuser/serverfault/askubuntu、
  news.ycombinator、reddit(含 old)、v2ex、infoq、juejin、csdn、cnblogs、zhihu
- 补漏:stackprinter.com(重写后的 SE 问题页)此前落到 dual
- 重写:SE 子域泛化到 StackPrinter(排除 www)、superuser 系合并规则
对应 spec: docs/superpowers/specs/2026-10-11-site-coverage-expansion-design.md"
```

---

### Task 2: 端到端实测脚本并执行

**Files:**
- Create: `.temp/airead_serp_test/site_rollout_e2e.py`(临时,不入库)

**Interfaces:**
- Consumes: `scrapling_fetch_mcp._fetcher.fetch_page_impl(url, mode, format, max_length, start_index)`(签名见 `src/scrapling_fetch_mcp/_fetcher.py:192`);Task 1 的规则。
- Produces: 每站点的评估记录(条数/正文字符/关键词命中/异常),供 Task 3 回填 spec 附录。

- [ ] **Step 1: 写实测脚本**

```python
"""逐站端到端实测:fetch_page_impl 完整管线。

评估标准:SERP 站看结果条数与关键词;文章站看正文字符与关键词;
失败站点(风控/空壳)记录异常即跳过。
"""
import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from scrapling_fetch_mcp._fetcher import fetch_page_impl  # noqa: E402

URL_RE = re.compile(r"\[查看原文\]\(([^)]+)\)")

# (名称, URL, mode, 期望关键词, 类型 serp/article)
CASES = [
    ("brave_serp", "https://search.brave.com/search?q=python+asyncio+tutorial", "stealth", ["asyncio"], "serp"),
    ("startpage_serp", "https://www.startpage.com/sp/search?query=python+asyncio+tutorial", "stealth", ["asyncio"], "serp"),
    ("searx_serp", "https://searx.be/search?q=python+asyncio+tutorial", "basic", ["asyncio"], "serp"),
    ("hn_item", "https://news.ycombinator.com/item?id=35765123", "basic", ["MSVCRT"], "article"),
    ("reddit", "https://www.reddit.com/r/Python/comments/yqrr94/python_asyncio_the_complete_guide/", "basic", ["asyncio"], "article"),
    ("v2ex", "https://www.v2ex.com/t/1", "basic", ["Babel"], "article"),
    ("stackoverflow_via_printer", "https://stackoverflow.com/questions/89228/calling-an-external-command-in-python", "basic", ["subprocess"], "article"),
    # B 层:预期可能失败(风控/动态),失败即记录跳过
    ("infoq", "https://www.infoq.cn/", "basic", [], "article"),
    ("cnblogs", "https://www.cnblogs.com/", "basic", [], "article"),
    ("csdn", "https://www.csdn.net/", "basic", [], "article"),
    ("juejin", "https://juejin.cn/", "basic", [], "article"),
    ("zhihu", "https://www.zhihu.com/question/19554980", "basic", [], "article"),
]


async def run_case(name, url, mode, keywords, kind):
    try:
        result = await fetch_page_impl(
            url=url, mode=mode, format="airead",
            max_length=60000, start_index=0)
        body = result.partition("\n\n")[2]
        meta = result.partition("\n\n")[0]
        record = {
            "name": name, "url": url, "kind": kind,
            "chars": len(body), "meta": meta[:100],
            "keywords": {k: (k.lower() in body.lower()) for k in keywords},
        }
        if kind == "serp":
            record["entries"] = len(URL_RE.findall(body))
            urls = URL_RE.findall(body)[:3]
            record["sample_urls"] = urls
        print(json.dumps(record, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"name": name, "url": url, "kind": kind,
                          "error": f"{type(e).__name__}: {str(e)[:80]}"},
                         ensure_ascii=False))


async def main():
    for args in CASES:
        await run_case(*args)

if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: 运行并保存输出**

Run: `cd .temp/airead_serp_test && ../../.venv/bin/python site_rollout_e2e.py 2>/dev/null | tee site_rollout_results.jsonl`
Expected: 12 行 JSON 记录;允许部分 error 记录(风控/空壳站点)。

- [ ] **Step 3: 人工判读结果**

判读标准(spec 3.4):
- SERP 站:`entries >= 5` 且关键词命中 → 达标;`entries == 0` → 启发式不适用,记"跳过(启发式不适用)"。
- 文章站:正文字符 > 1000 且无 METADATA 异常 → 达标(仅 B 层列表页,只要非空且无 error 即"路由生效")。
- error 记录:403/202 → "风控,跳过";空壳(SPA)→ "动态渲染,跳过"。

---

### Task 3: 回填 spec 附录并提交

**Files:**
- Modify: `docs/superpowers/specs/2026-10-11-site-coverage-expansion-design.md`(第 4 节)

**Interfaces:**
- Consumes: Task 2 的 `site_rollout_results.jsonl` 判读结论。
- Produces: spec 第 4 节"已知限制"替换为逐站实测结论表;每个站点一行(状态:✅ 达标 / ⚠️ 可用但有损 / ⏭️ 跳过 + 原因)。

- [ ] **Step 1: 把判读结论写成附录表**

替换 spec 第 4 节的占位行(如 "CSDN/博客园:登录墙与动态化程度待实测")为实际结论,格式:

```markdown
| 站点 | 结论 | 依据 |
|---|---|---|
| brave | ✅/⏭️ ... | entries=N,关键词命中 ... / 错误记录 |
| ... | ... | ... |
```

- [ ] **Step 2: 确认 spec 第 5 节"实施状态"与实际一致**(已提交规则、实测完成)

- [ ] **Step 3: 全量测试回归**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `217 passed` 或更多(本计划不新增测试,数字不应减少)。

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-10-11-site-coverage-expansion-design.md
git commit -m "docs(spec): backfill per-site rollout results for coverage expansion"
```

---

## Self-Review 记录

- **Spec 覆盖**:spec 3.1/3.2(规则)→ Task 1;spec 3.4 端到端验证 → Task 2;spec 第 4 节回填 → Task 3;spec 第 5 节实施状态 → Task 3 Step 2。无缺口。
- **占位符扫描**:无 TBD/TODO;Task 2 脚本为完整可运行代码;Task 3 附录表格给出格式与判读标准(结论值依赖实测输出,属数据而非占位)。
- **类型一致性**:Task 2 的 CASES 五元组与 `run_case(*args)` 参数序一致;`fetch_page_impl` 关键字参数与源码签名一致。
