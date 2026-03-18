"""Markdown postprocessor module."""


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