"""Tests for content saving functionality"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._content_saver import ImageSaver


class TestImageSaver:
    """Tests for ImageSaver class"""

    def test_init(self, temp_dir):
        """Test ImageSaver initialization"""
        saver = ImageSaver(temp_dir)

        assert saver.save_dir == temp_dir
        assert saver.images_dir == temp_dir / "images"
        assert saver.url_to_local == {}
        assert saver.hash_to_path == {}

    def test_calculate_hash(self, temp_dir):
        """Test hash calculation"""
        saver = ImageSaver(temp_dir)

        content = b"test image content"
        hash1 = saver._calculate_hash(content)
        hash2 = saver._calculate_hash(content)

        # Same content should produce same hash
        assert hash1 == hash2
        # SHA256 produces 64 character hex string
        assert len(hash1) == 64

    def test_generate_filename(self, temp_dir):
        """Test filename generation"""
        saver = ImageSaver(temp_dir)

        # Test JPEG
        filename1 = saver._generate_filename(
            "https://example.com/img/logo.jpg",
            "image/jpeg",
            0
        )
        assert filename1.endswith(".jpg")

        # Test PNG
        filename2 = saver._generate_filename(
            "https://example.com/img/banner.png",
            "image/png",
            1
        )
        assert filename2.endswith(".png")

        # Test with index
        assert "logo" in filename1.lower() or "image_0" in filename1

    @pytest.mark.asyncio
    async def test_save_image_new(self, temp_dir):
        """Test saving a new image"""
        saver = ImageSaver(temp_dir)

        content = b"fake image data for testing"
        url = "https://example.com/img/logo.jpg"

        local_path = await saver.save_image(url, content, "image/jpeg")

        # Should return relative path to images directory
        assert local_path.startswith("images/")
        assert local_path.endswith(".jpg")

        # URL should be mapped
        assert url in saver.url_to_local
        assert saver.url_to_local[url] == local_path

        # File should exist
        full_path = temp_dir / local_path
        assert full_path.exists()
        assert full_path.read_bytes() == content

    @pytest.mark.asyncio
    async def test_save_image_duplicate(self, temp_dir):
        """Test that duplicate images are deduplicated"""
        saver = ImageSaver(temp_dir)

        content = b"same image content"
        url1 = "https://example.com/img/logo.jpg"
        url2 = "https://cdn.example.com/assets/logo.jpg"

        path1 = await saver.save_image(url1, content, "image/jpeg")
        path2 = await saver.save_image(url2, content, "image/jpeg")

        # Should return same path for identical content
        assert path1 == path2

        # Both URLs should map to same file
        assert saver.url_to_local[url1] == path1
        assert saver.url_to_local[url2] == path1

        # Only one file should exist
        files = list((temp_dir / "images").glob("*"))
        assert len(files) == 1

    @pytest.mark.asyncio
    async def test_save_image_different(self, temp_dir):
        """Test that different images are saved separately"""
        saver = ImageSaver(temp_dir)

        content1 = b"first image"
        content2 = b"second image data"
        url1 = "https://example.com/img/a.jpg"
        url2 = "https://example.com/img/b.jpg"

        path1 = await saver.save_image(url1, content1, "image/jpeg")
        path2 = await saver.save_image(url2, content2, "image/jpeg")

        # Should return different paths
        assert path1 != path2

        # Both files should exist
        assert (temp_dir / path1).exists()
        assert (temp_dir / path2).exists()


class TestContentModifier:
    """Tests for ContentModifier class"""

    def test_modify_html(self, sample_html):
        """Test HTML modification"""
        from scrapling_fetch_mcp._content_saver import ContentModifier

        modifier = ContentModifier()
        url_to_local = {
            "https://example.com/logo.jpg": "images/logo.jpg",
            "https://cdn.example.com/banner.png": "images/banner.png",
        }

        modified = modifier.modify_html(sample_html, url_to_local)

        # Should contain local paths
        assert 'src="images/logo.jpg"' in modified
        assert 'src="images/banner.png"' in modified

        # Should preserve original URLs in data attribute
        assert 'data-original-src="https://example.com/logo.jpg"' in modified
        assert 'data-original-src="https://cdn.example.com/banner.png"' in modified

    def test_modify_markdown(self, sample_markdown):
        """Test Markdown modification"""
        from scrapling_fetch_mcp._content_saver import ContentModifier

        modifier = ContentModifier()
        url_to_local = {
            "https://example.com/logo.jpg": "images/logo.jpg",
            "https://cdn.example.com/banner.png": "images/banner.png",
        }

        modified = modifier.modify_markdown(sample_markdown, url_to_local)

        # Should contain local paths
        assert "](images/logo.jpg)" in modified
        assert "](images/banner.png)" in modified

        # Should not contain original URLs
        assert "https://example.com/logo.jpg" not in modified
        assert "https://cdn.example.com/banner.png" not in modified

    def test_modify_html_unknown_url(self):
        """Test that unknown URLs are left unchanged"""
        from scrapling_fetch_mcp._content_saver import ContentModifier

        modifier = ContentModifier()
        html = '<img src="https://unknown.com/img.jpg" alt="Unknown">'
        url_to_local = {"https://example.com/logo.jpg": "images/logo.jpg"}

        modified = modifier.modify_html(html, url_to_local)

        # Unknown URL should remain unchanged
        assert 'src="https://unknown.com/img.jpg"' in modified
        assert "data-original-src" not in modified


class TestContentSaver:
    """Tests for ContentSaver class"""

    def test_create_save_dir(self, temp_dir):
        """Test save directory creation"""
        from scrapling_fetch_mcp._content_saver import ContentSaver
        from datetime import datetime

        url = "https://example.com/page"
        saver = ContentSaver(temp_dir, url, "html")

        # Should create directory
        assert saver.save_dir.exists()
        assert saver.save_dir.parent == temp_dir

        # Should include domain and timestamp
        dir_name = saver.save_dir.name
        assert dir_name.startswith("example.com_")

    def test_create_save_dir_conflict(self, temp_dir):
        """Test directory name conflict resolution"""
        from scrapling_fetch_mcp._content_saver import ContentSaver

        url = "https://example.com/page"
        saver1 = ContentSaver(temp_dir, url, "html")
        saver2 = ContentSaver(temp_dir, url, "html")

        # Should create different directories
        assert saver1.save_dir != saver2.save_dir
        assert saver2.save_dir.name.endswith("_2")

    @pytest.mark.asyncio
    async def test_save_content(self, temp_dir, sample_html):
        """Test saving complete content"""
        from scrapling_fetch_mcp._content_saver import ContentSaver

        url = "https://example.com/page"
        saver = ContentSaver(temp_dir, url, "html")

        # Mock page object (we'll need real page later)
        modified_html = await saver.save_content(sample_html)

        # Should return modified HTML
        assert modified_html is not None

        # Should create page.html
        html_file = saver.save_dir / "page.html"
        assert html_file.exists()

        # Should create metadata.json
        metadata_file = saver.save_dir / "metadata.json"
        assert metadata_file.exists()

    @pytest.mark.asyncio
    async def test_create_page_action(self, temp_dir):
        """Test page_action creation for image interception"""
        from scrapling_fetch_mcp._content_saver import ContentSaver

        saver = ContentSaver(temp_dir, "https://example.com", "html")

        # Create page_action
        page_action = saver.create_page_action()
        assert callable(page_action)

        # Note: Full integration test will be done with real browser
        # This just verifies the method exists and returns a callable

    @pytest.mark.asyncio
    async def test_save_content_markdown(self, temp_dir, sample_html):
        """Test saving content as markdown"""
        from scrapling_fetch_mcp._content_saver import ContentSaver

        saver = ContentSaver(temp_dir, "https://example.com/page", "markdown")

        modified = await saver.save_content(sample_html)

        # Should create page.md not page.html
        md_file = saver.save_dir / "page.md"
        assert md_file.exists()

        # Should not create page.html
        html_file = saver.save_dir / "page.html"
        assert not html_file.exists()
