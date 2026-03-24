"""Feature registry for dynamic tool parameter visibility.

Defines the mapping between tool parameters and toggleable features,
allowing MCP clients to control which parameters appear in tool schemas.
"""

# All defined features and their default states
FEATURES = {
    "stealth":    {"default": "enabled",  "description": "Anti-bot-detection mode control"},
    "format":     {"default": "enabled",  "description": "Output format selection (airead/markdown/html)"},
    "pagination": {"default": "enabled",  "description": "Pagination support for large pages"},
    "save":       {"default": "disabled", "description": "Save page content to local filesystem"},
}

# Parameter definitions for each tool.
# The ``feature`` field links to a key in FEATURES.
# ``feature=None`` means the parameter is a core parameter, always visible.
TOOL_PARAMS = {
    "s_fetch_page": {
        "url": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "URL to fetch",
        },
        "mode": {
            "type": str, "required": False, "default": "basic",
            "feature": "stealth",
            "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
        },
        "format": {
            "type": str, "required": False, "default": None,
            "feature": "format",
            "description": "Output format (airead, markdown, or html). Use airead for AI-optimized extraction, markdown for standard conversion, html only for structure analysis. Defaults to server's default format setting.",
        },
        "max_length": {
            "type": int, "required": False, "default": 8000,
            "feature": None,
            "description": "Maximum number of characters to return.",
        },
        "start_index": {
            "type": int, "required": False, "default": 0,
            "feature": "pagination",
            "description": "On return output starting at this character index, useful if a previous fetch was truncated and more content is required.",
        },
        "save_content": {
            "type": bool, "required": False, "default": False,
            "feature": "save",
            "description": "If True, save complete page content (HTML/Markdown + images) to local filesystem for offline viewing.",
        },
        "scraping_dir": {
            "type": str, "required": False, "default": ".temp/scrapling/",
            "feature": "save",
            "description": "Directory path for saved content (relative or absolute). Default: .temp/scrapling/",
        },
    },
    "s_fetch_pattern": {
        "url": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "URL to fetch",
        },
        "search_pattern": {
            "type": str, "required": True, "default": None,
            "feature": None,
            "description": "Regular expression pattern to search for in the content",
        },
        "mode": {
            "type": str, "required": False, "default": "basic",
            "feature": "stealth",
            "description": "Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.",
        },
        "format": {
            "type": str, "required": False, "default": None,
            "feature": "format",
            "description": "Output format (html or markdown). Use markdown for content reading/extraction, html only for structure analysis. Defaults to server's default format setting (airead will be converted to markdown).",
        },
        "max_length": {
            "type": int, "required": False, "default": 8000,
            "feature": None,
            "description": "Maximum number of characters to return.",
        },
        "context_chars": {
            "type": int, "required": False, "default": 200,
            "feature": None,
            "description": "Number of characters to include before and after each match",
        },
    },
}

S_FETCH_PAGE_DOCSTRING = (
    "Fetches a complete web page with pagination support. Retrieves content from "
    "websites with bot-detection avoidance. Content is returned as "
    "'METADATA: {json}\\n\\n[content]' where metadata includes length information "
    "and truncation status.\n"
    "\n"
    "IMPORTANT:\n"
    "- Use format='airead' for AI-optimized content extraction "
    "(removes navigation, ads, etc., 30-50% token reduction)\n"
    "- Use format='markdown' for standard markdown conversion\n"
    "- Use format='html' only when you need raw HTML structure\n"
    "\n"
    "The airead format uses intelligent content extraction with URL-based routing "
    "to specialized strategies for different website types (search engines, "
    "documentation, developer platforms, etc.)."
)

S_FETCH_PATTERN_DOCSTRING = (
    "Extracts content matching regex patterns from web pages. Retrieves specific "
    "content from websites with bot-detection avoidance. Returns matched content as "
    "'METADATA: {json}\\n\\n[content]' where metadata includes match statistics and "
    "truncation information. Each matched content chunk is delimited with special "
    "markers and prefixed with '[Position: start-end]' indicating its byte position "
    "in the original document, allowing targeted follow-up requests with s-fetch-page "
    "using specific start_index values.\n"
    "\n"
    "IMPORTANT: Use format='markdown' for reading or extracting content. Only use "
    "format='html' when you specifically need the raw HTML structure."
)
