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
    # 必须落在 html. 子域:裸域(html 版含裸域 /html/ 路径)会命中
    # DDG 的 anomaly 拦截(202 空页)。
    # 注意:重写器按顺序取第一条 match 命中的规则,DDG 只能有一条规则,
    # 两种 URL 形态须由同一个 pattern 覆盖
    {
        "match": {"type": "domain", "pattern": "duckduckgo.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"^https://(www\.)?duckduckgo\.com(/html)?/\?(.*)$",
            "replacement": r"https://html.duckduckgo.com/html/?\3"
        }
    },
    # Reddit: www → old (also handles bare reddit.com)
    {
        "match": {"type": "domain", "pattern": "reddit.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"^https://(www\.)?reddit\.com",
            "replacement": r"https://old.reddit.com"
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
    # StackExchange 子域 (如 unix.stackexchange.com): questions → StackPrinter
    {
        "match": {"type": "domain_suffix", "pattern": ".stackexchange.com"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"https://(?!www\.)([a-z0-9-]+)\.stackexchange\.com/questions/(\d+)/.*$",
            "replacement": r"https://www.stackprinter.com/export?question=\2&service=\1&format=HTML&comments=true"
        }
    },
    # superuser/serverfault/askubuntu: questions → StackPrinter
    {
        "match": {"type": "regex", "pattern": r"https://(www\.)?(superuser|serverfault|askubuntu)\.com/questions/(\d+)/.*$"},
        "rewrite": {
            "type": "regex_replace",
            "pattern": r"https://(www\.)?(superuser|serverfault|askubuntu)\.com/questions/(\d+)/.*$",
            "replacement": r"https://www.stackprinter.com/export?question=\3&service=\2&format=HTML&comments=true"
        }
    },
]