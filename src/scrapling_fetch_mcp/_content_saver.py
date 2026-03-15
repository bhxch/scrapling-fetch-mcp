"""Content saving functionality for web pages with images"""
from hashlib import sha256
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse
from logging import getLogger


class ImageSaver:
    """Manages image saving with deduplication"""

    def __init__(self, save_dir: Path):
        self.save_dir = save_dir
        self.images_dir = save_dir / "images"
        self.url_to_local: Dict[str, str] = {}  # URL -> local path
        self.hash_to_path: Dict[str, str] = {}  # hash -> local path
        self.logger = getLogger(__name__)

    def _calculate_hash(self, content: bytes) -> str:
        """Calculate SHA256 hash of content"""
        return sha256(content).hexdigest()

    def _generate_filename(self, url: str, content_type: str, index: int) -> str:
        """Generate unique filename from URL and content type"""
        # Extract extension from content type
        ext_map = {
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/svg+xml": ".svg",
            "image/webp": ".webp",
            "image/x-icon": ".ico",
            "image/bmp": ".bmp",
        }

        ext = ext_map.get(content_type, ".jpg")

        # Try to extract filename from URL
        parsed = urlparse(url)
        path = parsed.path
        if "/" in path:
            base_name = path.split("/")[-1]
            if "." in base_name:
                name_part = base_name.rsplit(".", 1)[0]
                # Sanitize filename
                name_part = "".join(c if c.isalnum() or c in "-_" else "_" for c in name_part)
                return f"{name_part}{ext}"

        # Fallback to index-based name
        return f"image_{index}{ext}"
