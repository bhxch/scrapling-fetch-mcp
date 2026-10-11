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

  - match:
      type: regex
      pattern: '.*startpage\\.com.*'
    strategy: search_engine

  # Searx/SearxNG 公共实例域名异构(如 searx.be、searxng.site),
  # 用子串式 regex 覆盖;规则靠后,降低误伤概率
  - match:
      type: regex
      pattern: ".*searx.*"
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
      pattern: '.*stackprinter\.com.*'
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

  - match:
      type: regex
      pattern: '.*reddit\\.com.*'
    strategy: developer_platform

  - match:
      type: domain
      pattern: "v2ex.com"
    strategy: developer_platform

  - match:
      type: regex
      pattern: '.*infoq\\.(cn|com).*'
    strategy: developer_platform

  # 中文技术社区
  - match:
      type: regex
      pattern: '.*juejin\\.cn.*'
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

# 自定义策略（用户可扩展）
custom_strategies: []
"""