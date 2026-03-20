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