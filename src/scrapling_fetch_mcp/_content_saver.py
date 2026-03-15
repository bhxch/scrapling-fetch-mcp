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

    async def save_image(self, url: str, content: bytes, content_type: str) -> str:
        """Save image with deduplication, return relative local path"""

        # Check if we already saved this URL
        if url in self.url_to_local:
            self.logger.debug(f"Image URL already saved: {url}")
            return self.url_to_local[url]

        # Calculate hash for deduplication
        content_hash = self._calculate_hash(content)

        # Check if identical image already exists (different URL, same content)
        if content_hash in self.hash_to_path:
            existing_path = self.hash_to_path[content_hash]
            self.logger.info(f"Duplicate image found: {url} -> {existing_path}")
            self.url_to_local[url] = existing_path
            return existing_path

        # Create images directory
        self.images_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        index = len(self.url_to_local)
        filename = self._generate_filename(url, content_type, index)
        relative_path = f"images/{filename}"
        full_path = self.images_dir / filename

        # Save the image
        full_path.write_bytes(content)
        self.logger.info(f"Saved image: {url} -> {relative_path}")

        # Update mappings
        self.url_to_local[url] = relative_path
        self.hash_to_path[content_hash] = relative_path

        return relative_path
