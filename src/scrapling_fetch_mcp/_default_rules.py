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
      type: domain
      pattern: "duckduckgo.com"
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

  - match:
      type: domain
      pattern: "gitlab.com"
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