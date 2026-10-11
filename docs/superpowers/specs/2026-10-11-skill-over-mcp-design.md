# scrapling-fetch-mcp 的 Skill 暴露(SKILL over MCP)与 Tool 描述优化设计

日期:2026-10-11
状态:待评审
关联:2026-10-11-site-coverage-expansion-design.md(站点扩展,独立待评审)

## 1. 背景与问题

三个关联需求:

1. 当前 MCP server 版本是否支持 skill over MCP?
2. 能否为 agent 提供一个好用的 skill,让其更灵活地使用本 MCP 的功能?
3. 现有 MCP tool 描述是否需要优化?

## 2. 调查结论

### 2.1 本项目 SDK 能力面(实测确认)

- SDK 为 **mcp 2.0.0**(新版高层接口 `MCPServer`),支持 tools /
  resources / prompts / elicitation / sampling / MCP Apps,以及
  **`Extension` 扩展机制**:`Extension` 子类可贡献 resources
  (`ResourceBinding`)、注册**自定义 JSON-RPC 方法**(`MethodBinding`)
  并以 `capabilities.extensions[identifier]` 自动声明能力;MCPServer
  原生接受 `instructions=` 参数。
- 项目当前只注册了两个 tool,未使用 resources/prompts/extension。

### 2.2 skill over MCP 协议现状(SEP-2640,已定稿)

- MCP 官方扩展 **`io.modelcontextprotocol/skills`**(SEP-2640),
  2026-09-13 标记 **Final**,规范在 `modelcontextprotocol/ext-skills`
  仓库 `specification/stable/skills.mdx`,由 Skills Over MCP 工作组
  (AAIF)维护。
- 核心约定:
  - skill 文件以 **resources** 暴露,URI 约定
    `skill://<skill-path>/<file-path>`,`<skill-path>` 末段必须等于
    SKILL.md frontmatter 的 `name`;`mimeType` SHOULD 为
    `text/markdown`;内容经标准 `resources/read` 读取。
  - server 声明扩展后 **MUST** 实现 `skills/list`(返回完整清单:
    `{uri, frontmatter(逐字 JSON), resources: [{uri, digest: "sha256:...", size}]}`)
    与 `skills/get`(按 URI 查单条),均为自定义 JSON-RPC 方法。
  - 限制:每 skill ≤512 文件、≤16MiB;SKILL.md 必须符合 Agent Skills
    规范(frontmatter 至少 name/description)。
  - **优雅降级**:不支持该扩展的客户端把 `skill://` 资源当普通
    resource;server 还 MAY 在 `instructions` 里直接给 skill URI 指针。
- 结论:**当前 server 版本(mcp 2.0.0)支持实现 skill over MCP**,
  SDK 的 `Extension`/`MethodBinding` 与 SEP-2640 的要求一一对应,
  无需升级 SDK。

## 3. 设计

### 3.1 Skill 内容(`skills/scrapling-fetch/SKILL.md`)

skill 名:`scrapling-fetch`(agent skills 格式;同一份文件同时供
MCP 暴露与本地 skill 目录复用)。frontmatter:
`name: scrapling-fetch`,`description: Web fetching workflows for the
scrapling-fetch-mcp server — search-result harvesting, paginated
reading, format/mode selection, and known limitations`。

正文大纲(指令,非文档):

1. **工具选择**:`s_fetch_page`(读整页/分页)vs `s_fetch_pattern`
   (正则定点提取;先 pattern 定位再用 start_index 取上下文)。
2. **搜索工作流**(核心场景):对搜索引擎结果页 URL
   (`bing.com/search?q=...`、`duckduckgo.com/?q=...`、`search.brave.com/...`)
   用 `format="airead"` → 返回 `## Search Results` 下 `### N. 标题` +
   `[查看原文](真实URL)` 结构化条目(重定向已解析);取 URL 后逐个
   `s_fetch_page` 抓原文。不要自己手工构造 `html.duckduckgo.com` 或
   stackprinter URL——server 的 URL 重写自动完成。
3. **分页工作流**:读 `METADATA` 行的 `is_truncated`;
   翻页 `start_index = start_index + max_length`。
4. **format/mode 决策**:airead 默认(省 token);markdown 用于需要
   完整结构时;html 仅调试。mode:basic 起步;遇 403/202/验证码页
   升级 stealth;反爬极强再 max-stealth。
5. **已知限制**:部分站点风控(DDG 短时高频 202、知乎未登录 403)、
   SPA 空壳(juejin)、`s_fetch_pattern` 不支持 airead。

### 3.2 SEP-2640 服务端实现(`_skills.py` 新文件)

`SkillsExtension(Extension)`,`identifier = "io.modelcontextprotocol/skills"`:

- `settings()` → `{}`(不实现 `resources/directory/read`)。
- `resources()` → `ResourceBinding` 贡献
  `skill://scrapling-fetch/SKILL.md`(mimeType `text/markdown`,
  name/description 取自 frontmatter)。
- `methods()` → 两个 `MethodBinding`:
  - `skills/list`:返回单条 Skill entry;
  - `skills/get`(params: `{uri}`):URI 匹配则返回同一 entry,
    否则按规范返回 `-32602`。
  - entry 的 `resources` 为数组形态(SKILL.md 是静态打包文件,
    digest 用 `sha256:` + 文件字节哈希,size 为字节数)。
- SKILL.md 随包分发(`importlib.resources` 读取),保证 wheel 安装后
  仍可用;文件缺失时扩展不注册并告警(不影响 tools 服务)。
- 注册:`MCPServer("scrapling-fetch-mcp", instructions=..., extensions=[SkillsExtension()])`;
  instructions 追加一句 skill URI 指针(规范允许的零成本发现路径)。

### 3.3 Tool 描述优化(`_features.py`)

| 位置 | 问题 | 改法 |
|---|---|---|
| S_FETCH_PAGE_DOCSTRING | 未提搜索工作流与 SERP 输出形态 | 增补:搜索引擎 URL + airead 返回 `### N.` 结构化条目与真实链接;这是做"搜索→抓原文"的正确入口 |
| S_FETCH_PAGE_DOCSTRING | URL 重写自动化不可见 | 增补一句:常见重站点(DDG/Bing/Reddit/StackOverflow/StackExchange)自动改写为轻量形态,直接传原始 URL 即可 |
| S_FETCH_PAGE_DOCSTRING | 分页工作流不显式 | 增补:`is_truncated=true` 时以 `start_index += max_length` 续读 |
| mode 参数(两处重复) | 冗长且无决策指引 | 精简为 "basic(快,默认)/ stealth(轻反爬)/ max-stealth(强反爬);403/202 时升级" |
| S_FETCH_PATTERN_DOCSTRING | 未说明 pattern 匹配的文本域 | 增补:pattern 作用于 format 决定的转换后文本(markdown 或 html) |
| 两个 DOCSTRING | 未指向 skill | 尾部加一行:详见 `skill://scrapling-fetch/SKILL.md`(支持 skills 扩展的 host 可加载;其他 host 忽略无害) |

### 3.4 测试与验证

- 单元测试:extension 的 entry shape(frontmatter 逐字、digest/size
  与文件一致、URI 末段=name)、skills/get 对未知 URI 返回
  `-32602`、skill 文件符合 agent skills frontmatter 约束。
- 集成测试:MCP stdio client → `list_resources` 看到
  `skill://scrapling-fetch/SKILL.md`;`skills/list`、`skills/get`
  (含错误路径);`resources/read` 读回 SKILL.md 原文。
- tool 描述断言更新(现有 test_tool_factory / test_features 相关用例)。
- 真实验证:MCP stdio client 脚本(置于 `.temp/`)按上述顺序调用
  一遍,确认 wire 行为与规范示例一致。

## 4. 已知限制与风险

- Host 支持度:SEP-2640 定稿仅一个月(2026-09-13),多数 host 尚未
  实现 skills 加载路径;因此保留三层降级——instructions 指针、普通
  resource 读取、tool 描述自包含关键工作流。任何 host 下功能不受损。
- Skill 内容是注入面:规范把加载批准/校验职责划给 host;server 端
  只保证 entry 与文件一致(digest/size)。
- `skills/list|get` 为扩展方法:不支持扩展的旧客户端调用会得到
  method-not-found,属规范预期行为。

## 5. 实施清单

1. `skills/scrapling-fetch/SKILL.md`(新)。
2. `src/scrapling_fetch_mcp/_skills.py`:SkillsExtension + entry 构造。
3. `mcp.py`:注册 extension + instructions 指针。
4. `_features.py`:3.3 的描述优化。
5. 测试:单元 + MCP client 集成;pyproject 打包配置纳入 skills/。
