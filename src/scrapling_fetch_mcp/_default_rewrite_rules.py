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
            "pattern": r"^https://(www\.)?duckduckgo\.com/\?(.*)$",
            "replacement": r"https://duckduckgo.com/html/?\2"
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
        "match": {"type": "regex", "pattern": r"https://(?!www\.)([a-z0-9-]+)\.stackexchange\.com/questions/(\d+)/.*$"},
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