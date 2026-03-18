"""Tests for Markdown postprocessor."""

import pytest

from scrapling_fetch_mcp._markdown_postprocessor import postprocess_markdown


class TestMarkdownPostprocessor:
    """Test cases for postprocess_markdown function."""

    def test_compress_empty_lines(self):
        """Test compressing multiple blank lines to max 2."""
        input_text = "Line 1\n\n\n\n\nLine 2\n\n\nLine 3"
        expected = "Line 1\n\nLine 2\n\nLine 3"
        result = postprocess_markdown(input_text)
        assert result == expected

    def test_remove_trailing_spaces(self):
        """Test removing trailing spaces from lines."""
        input_text = "Line 1   \nLine 2   \nLine 3\n"
        expected = "Line 1\nLine 2\nLine 3"
        result = postprocess_markdown(input_text)
        assert result == expected

    def test_strip_blank_lines(self):
        """Test stripping leading and trailing blank lines."""
        input_text = "\n\nLine 1\nLine 2\n\n"
        expected = "Line 1\nLine 2"
        result = postprocess_markdown(input_text)
        assert result == expected

    def test_empty_string(self):
        """Test handling empty string input."""
        input_text = ""
        expected = ""
        result = postprocess_markdown(input_text)
        assert result == expected