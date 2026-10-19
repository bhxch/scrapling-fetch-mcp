"""Markdown postprocessor module."""

from re import MULTILINE, compile, sub


def postprocess_markdown(markdown: str) -> str:
    """
    Post-process markdown text by applying cleaning rules.

    Args:
        markdown: The input markdown text to process.

    Returns:
        The cleaned markdown text.
    """
    if not markdown:
        return ""

    # Remove trailing spaces from each line
    lines = [line.rstrip() for line in markdown.split('\n')]

    # Use regex to compress multiple blank lines
    import re
    # Replace 3+ consecutive newlines with exactly 2 newlines
    result = re.sub(r'\n{3,}', '\n\n', '\n'.join(lines))

    # Then replace 2 consecutive newlines followed by content and then 2+ newlines with 2 newlines
    # This handles the case where multiple empty sequences should be compressed
    result = re.sub(r'\n\n\n+', '\n\n', result)

    # Strip leading and trailing newlines
    result = result.strip('\n')

    return result


# --- LLM 内容瘦身:链接与图片标记对文本模型几乎纯烧 token ---

_IMAGE_RE = compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_RE = compile(r"(?<!\!)\[([^\]]+)\]\([^)]*\)")
_AUTOLINK_RE = compile(r"<https?://[^>\s]+>")
_REF_DEF_RE = compile(r"^\s*\[[^\]]+\]:\s*\S+.*$", MULTILINE)


def _outside_code_fences(markdown: str, transform) -> str:
    """仅对 ``` 围栏外的内容应用 transform,围栏内(代码示例)原样保留。"""
    parts = markdown.split("```")
    for i in range(0, len(parts), 2):  # 偶数段在围栏外
        parts[i] = transform(parts[i])
    return "```".join(parts)


def strip_markdown_images(markdown: str) -> str:
    """删除 ![alt](src) 图片标记(文本模型无法消费,alt 多为文件名噪声)。"""
    return _outside_code_fences(markdown, lambda t: _IMAGE_RE.sub("", t))


def strip_markdown_links(markdown: str) -> str:
    """[text](url) 降为纯文本;autolink 与引用式链接定义一并移除。"""
    def transform(text: str) -> str:
        text = _AUTOLINK_RE.sub("", text)
        text = _REF_DEF_RE.sub("", text)
        return _LINK_RE.sub(r"\1", text)

    return _outside_code_fences(markdown, transform)


def apply_markdown_slimming(
    markdown: str, no_links: bool = False, no_images: bool = False
) -> str:
    """按需瘦身 Markdown,返回值传给模型前调用以节省 token。"""
    if not markdown:
        return markdown
    # 先图片后链接:`![alt](src)` 会被链接正则误留下 `!alt`
    if no_images:
        markdown = strip_markdown_images(markdown)
    if no_links:
        markdown = strip_markdown_links(markdown)
    if no_links or no_images:
        markdown = sub(r"\n{3,}", "\n\n", markdown).strip("\n")
    return markdown