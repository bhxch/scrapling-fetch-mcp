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
