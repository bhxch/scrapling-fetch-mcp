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
