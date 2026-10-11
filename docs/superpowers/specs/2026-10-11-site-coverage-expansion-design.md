# airead 站点覆盖扩展与提取引擎调研设计

日期:2026-10-11
状态:待评审

## 1. 背景与目标

airead 的策略路由目前只覆盖 Google/Bing/DuckDuckGo(搜索引擎)与
GitHub/StackOverflow/GitLab/docs.python/MDN(技术站点)。用户需求:

1. 支持更多搜索引擎(Brave、Startpage/Searx 类)与常见技术类网站
   (StackExchange 全家桶、Hacker News、中文技术社区、Reddit/V2EX/InfoQ)。
2. 调研当前内置通用文本提取引擎(trafilatura / readability / Scrapling 全文)
   的实际效果,评估是否有必要增加更多提取引擎。

原则(用户明确):**提取不到的站点直接跳过,不死磕**;扩展方式遵循
"声明式规则先行、实测驱动补策略、YAGNI"。

## 2. 提取引擎调研结论(实测数据)

### 2.1 测评方法

9 个真实样本(4 个 SERP + 5 类文章页:官方文档、技术博客、HN 帖子、
StackPrinter 问答页、V2EX 讨论帖×2),7 个引擎在独立 uv 环境运行:
内置三通道(trafilatura、readability、bs4 全文≈Scrapling 通道)+
候选新引擎(goose3、justext、newspaper4k、html2text 基线)。
指标:正文关键词命中(完整性)、噪音词命中、输出非空率、耗时。
脚本与样本:`.temp/airead_serp_test/engine_bench.py`、`samples/`。

### 2.2 结果汇总

| 引擎 | 关键词命中(共20) | 噪音 | 非空率 | 耗时区间 | 备注 |
|---|---|---|---|---|---|
| trafilatura | 17 | 0 | 9/9 | 7–222ms | 各类别全面最优,markdown 保留格式 |
| readability | 14 | 0 | 8/9 | 4–172ms | 最快;文档页截断(1/3)、论坛楼层丢失 |
| bs4 全文 | 18 | 2 | 9/9 | 1–114ms | 不裁剪,保底;噪音随全文带入 |
| goose3 | 9 | 0 | 5/9 | 9–977ms | 论坛/文档页失效,成功面为 trafilatura 子集 |
| justext | 9 | 0 | 4/9 | 2–86ms | 同上 |
| newspaper4k | 8 | 0 | 4/9 | 0.4–10s | 慢(HN 10s);中文需 jieba;博客样本解析失败 |
| html2text | 18 | 2 | 9/9 | 1–92ms | 无损转换基线(与 bs4 同角色) |

### 2.3 结论:不增加新提取引擎

现有 dual 组合已覆盖"质量—速度—保底"三档:trafilatura 是质量主力
(全类别最强、零噪音),readability 提供快速第二意见,bs4 全文兜底
保证内容不丢。三个候选引擎的失败面与 readability 高度重叠、成功面是
trafilatura 的子集,无法补充现有组合的盲区;newspaper4k 还引入中文
依赖(jieba)与严重性能退化。

真正的短板在**站点专用解析通道**(如 Bing 的 `b_algo`、Google 的
`/goto` 重定向),而非缺少通用引擎——这正是本设计的站点扩展工作方向。

## 3. 设计

### 3.1 路由规则扩展(`_default_rules.py`)

- search_engine 新增:`.brave.com`(domain_suffix)、
  `.*startpage\.com.*`(regex)、`.*searx.*`(regex,Searx/SearxNG
  公共实例域名异构,子串式覆盖,置于搜索段末尾降低误伤)。
- developer_platform 新增:`.stackexchange.com`、
  `\b(superuser|serverfault|askubuntu)\.com.*`、`news.ycombinator.com`、
  `.*reddit\.com.*`(含 old.reddit)、`v2ex.com`、`.*infoq\.(cn|com).*`、
  `.*juejin\.cn.*`、`.csdn.net`、`.cnblogs.com`、`zhihu.com`。
- 补漏:重写后的 StackPrinter URL(www.stackprinter.com)此前落到
  dual,新增 `.*stackprinter\.com.*` → developer_platform。

### 3.2 URL 重写规则扩展(`_default_rewrite_rules.py`)

- StackExchange 子域泛化:`https://(?!www\.)({sub}).stackexchange.com/
  questions/{id}/...` → `stackprinter/export?question={id}&service={sub}`,
  排除 www(service 无效)。
- superuser/serverfault/askubuntu 独立域:一条合并 regex 规则重写到
  对应 service 的 StackPrinter。
- 其余新增站点不需要重写(HN/V2EX/Reddit(old)/中文社区均为静态
  HTML;Brave/Startpage/Searx 实测确认后如需 HTML 版入口再补)。

### 3.3 策略层

不新增策略类。范围结论(由第 2 节实测数据支撑):

- **技术类网站(HN/Reddit/V2EX/InfoQ/中文社区/StackPrinter)零策略
  代码**:六类文章样本上 trafilatura(或 dual 择优到 bs4 全文)全部
  达标,这些站点的"支持"= 3.1/3.2 的路由与重写规则 + 端到端确认。
- **搜索引擎是仅存的策略增强点,且不确定**:search_engine 的通用
  启发式(h3/h2 定位 + 容器窗口 + 确定性通道)对 Brave/Startpage/
  Searx 可能直接可用,也可能需要小通道或重写入口——逐站实测,
  实测不达标的站点**不写专用通道、不死磕**,保留路由并记录为
  已知限制。

### 3.4 验证与测试

- 单元测试:新增路由用例(`test_url_matcher`)与重写用例
  (`test_url_rewriter`):SE 子域泛化、www 排除、superuser 系、
  stackprinter 路由、全部新站点路由。
- 端到端:临时脚本逐站真实抓取(fetch_page_impl),按"条目数/正文
  保留/噪音"评估;结论记录于本文档附录;失败站点直接标记跳过。
- 引擎测评脚本与样本留存于 `.temp/`(gitignore),spec 中只保留结论。

## 4. 已知限制(实测确认,按用户原则跳过)

"跳过"指不再为该站点投入适配工作(不写专用通道、不对抗风控),
路由规则保留——developer_platform 的 trafilatura 仍是这些站点的
最优兜底。

逐站端到端实测结论(2026-10-11,12 站点各抓取一次,无重试)。
"✅ 达标"指满足完整判读标准(SERP 条目数/关键词命中,文章正文
字数与 METADATA 检查);"✅ 路由生效"仅指 B 层标准(列表页非空、
无 error),内容深度未单独评估,两种强度不可混同。

| 站点 | 结论 | 依据 |
|---|---|---|
| startpage(stealth) | ✅ 达标 | entries=10(≥5),asyncio 命中,样例 URL 为真实结果 |
| v2ex | ✅ 达标 | chars=3104,Babel 命中,无 METADATA 异常 |
| stackoverflow(经 StackPrinter 重写) | ✅ 达标 | chars=60000(总 68690,正常截断于 max_length),subprocess 命中,重写链路工作正常 |
| hn_item | ✅ 可用(样本页本身短) | chars=720 未过 1000 字线,但 MSVCRT 命中、无 METADATA 异常,内容真实 |
| infoq | ✅ 路由生效 | chars=1868 非空,无 error(B 层标准) |
| cnblogs | ✅ 路由生效 | chars=2999 非空,无 error(B 层标准) |
| juejin | ✅ 路由生效 | chars=2787 非空,无 error(B 层标准) |
| brave | ⏭️ 跳过 | 本次实测返回挑战页式空 SERP(17 字符正文),结合本机 IP 风控背景推断;路由本身生效。风控冷却后可复测 |
| searx | ⏭️ 跳过 | 本次实测返回挑战页式空 SERP(17 字符正文),结合本机 IP 风控背景推断;路由本身生效。风控冷却后可复测 |
| reddit | ⏭️ 跳过 | 空壳/登录墙(未登录 403 类拦截),chars=340 壳页,关键词未命中 |
| zhihu | ⏭️ 跳过 | 空壳/登录墙(未登录 403 类拦截),chars=35 壳页 |
| csdn | ⚠️ 路由生效但内容薄 | 404 字符,登录墙/动态化存疑,按跳过原则不再投入 |

其他已知限制:

- stackexchange.com 域本身对非浏览器 UA 返回 403,依赖重写到
  StackPrinter 后抓取(重写规则已覆盖,经上表 stackoverflow 行
  实测确认)。
- searx/reddit/superuser 路由使用子串式 regex,URL 中含这些域名
  字符串的无关站点可能误伤(spec 3.1 的既有取舍)。

## 5. 实施状态

- 规则已提交(commit 1bce741):3.1 路由规则扩展、3.2 重写规则
  扩展及对应单元测试(全量 217 通过)。
- 端到端实测完成(2026-10-11,12 站点各抓取一次,无重试)。
- 逐站结论已回填本文档第 4 节附录。
