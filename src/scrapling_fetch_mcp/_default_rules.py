# src/scrapling_fetch_mcp/_default_rules.py

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
      type: domain_suffix
      pattern: ".duckduckgo.com"
    strategy: search_engine

  - match:
      type: domain_suffix
      pattern: ".brave.com"
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

  # StackPrinter(重写后的 StackOverflow/StackExchange 问题页)
  - match:
      type: regex
      pattern: '.*stackprinter\\.com.*'
    strategy: developer_platform

  - match:
      type: domain
      pattern: "gitlab.com"
    strategy: developer_platform

  - match:
      type: domain_suffix
      pattern: ".stackexchange.com"
    strategy: developer_platform

  - match:
      type: regex
      pattern: '\\b(superuser|serverfault|askubuntu)\\.com.*'
    strategy: developer_platform

  - match:
      type: domain
      pattern: "news.ycombinator.com"
    strategy: developer_platform

  # 锚定 host 段:裸域/www/old 等子域命中,query 中含 reddit.com 的 URL 不误伤
  - match:
      type: regex
      pattern: '^https?://([^/]+\\.)?reddit\\.com(/|\\?|$)'
    strategy: developer_platform

  - match:
      type: domain
      pattern: "v2ex.com"
    strategy: developer_platform

  - match:
      type: regex
      pattern: '^https?://[^/]*infoq\\.(cn|com)'
    strategy: developer_platform

  # 中文技术社区
  - match:
      type: regex
      pattern: '^https?://([^/]+\\.)?juejin\\.cn'
    strategy: developer_platform

  - match:
      type: domain_suffix
      pattern: ".csdn.net"
    strategy: developer_platform

  - match:
      type: domain_suffix
      pattern: ".cnblogs.com"
    strategy: developer_platform

  - match:
      type: domain
      pattern: "zhihu.com"
    strategy: developer_platform

  # 技术文档规则
  - match:
      type: regex
      pattern: ".*docs.python.org.*"
    strategy: documentation

  - match:
      type: regex
      pattern: ".*developer.mozilla.org.*"
    strategy: documentation

  # 搜索引擎兜底:startpage 域名异构(锚定 host 段,避免子串误伤)
  - match:
      type: regex
      pattern: '^https?://[^/]*startpage\\.com'
    strategy: search_engine

  # Searx/SearxNG 公共实例域名异构(如 searx.be、searxng.site),
  # 锚定 host 段覆盖;词边界防住 notsearx.example.com 这类 host 内子串误伤;
  # 置于全部站点规则之后:先让更具体的站点规则命中,此条仅兜底
  # (github.com/searxng/searxng 的 path 段不会命中)
  - match:
      type: regex
      pattern: '^https?://[^/]*\\bsearx[^/]*'
    strategy: search_engine

# 自定义策略（用户可扩展）
custom_strategies: []
"""