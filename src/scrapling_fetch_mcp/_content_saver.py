"""Content saving functionality for web pages with images"""
from hashlib import sha256
from pathlib import Path
from typing import Dict
from urllib.parse import urlparse
from logging import getLogger
import re
from bs4 import BeautifulSoup
from datetime import datetime
from json import dumps
from typing import Optional


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


class ContentModifier:
    """Modifies HTML/Markdown content to use local image paths"""

    def modify_html(self, html: str, url_to_local: Dict[str, str]) -> str:
        """Replace image URLs with local paths in HTML, add data-original-src"""
        soup = BeautifulSoup(html, "lxml")

        for img in soup.find_all("img"):
            src = img.get("src")
            if src and src in url_to_local:
                # Add data-original-src attribute
                img["data-original-src"] = src
                # Replace with local path
                img["src"] = url_to_local[src]

        return str(soup)

    def modify_markdown(self, markdown: str, url_to_local: Dict[str, str]) -> str:
        """Replace image URLs with local paths in Markdown"""

        # Match markdown image syntax: ![alt](url)
        pattern = r"!\[([^\]]*)\]\(([^\)]+)\)"

        def replace_url(match):
            alt = match.group(1)
            url = match.group(2)
            if url in url_to_local:
                return f"![{alt}]({url_to_local[url]})"
            return match.group(0)

        return re.sub(pattern, replace_url, markdown)


class ContentSaver:
    """Main orchestrator for saving web content"""

    def __init__(self, scraping_dir: Path, url: str, format: str):
        self.scraping_dir = scraping_dir
        self.url = url
        self.format = format
        self.logger = getLogger(__name__)
        self.save_dir = self._create_save_dir()
        self.image_saver = ImageSaver(self.save_dir)
        self.content_modifier = ContentModifier()

    def _create_save_dir(self) -> Path:
        """Create unique save directory (domain_timestamp)"""
        from urllib.parse import urlparse

        # Extract domain from URL
        parsed = urlparse(self.url)
        domain = parsed.netloc.replace("www.", "")

        # Generate timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dir_name = f"{domain}_{timestamp}"

        # Create base directory
        save_path = self.scraping_dir / dir_name

        # Handle conflicts
        if save_path.exists():
            counter = 2
            while True:
                save_path = self.scraping_dir / f"{dir_name}_{counter}"
                if not save_path.exists():
                    break
                counter += 1

        save_path.mkdir(parents=True, exist_ok=True)
        self.logger.info(f"Created save directory: {save_path}")

        return save_path

    async def save_content(self, html_content: str) -> str:
        """Save content and return modified HTML"""
        # Modify content to use local image paths
        modified_html = self.content_modifier.modify_html(
            html_content, self.image_saver.url_to_local
        )

        # Save HTML file
        html_file = self.save_dir / "page.html"
        html_file.write_text(modified_html, encoding="utf-8")

        # Save metadata
        self._save_metadata()

        # Save image mapping
        self._save_image_mapping()

        return modified_html

    def _save_metadata(self) -> None:
        """Save page metadata"""
        metadata = {
            "url": self.url,
            "fetch_time": datetime.now().isoformat(),
            "format": self.format,
        }

        metadata_file = self.save_dir / "metadata.json"
        metadata_file.write_text(dumps(metadata, indent=2), encoding="utf-8")

    def _save_image_mapping(self) -> None:
        """Save URL to local path mapping"""
        mapping = [
            {"original_url": url, "local_path": path}
            for url, path in self.image_saver.url_to_local.items()
        ]

        mapping_file = self.save_dir / "image_mapping.json"
        mapping_file.write_text(dumps(mapping, indent=2), encoding="utf-8")

    def create_page_action(self):
        """Create page_action closure for scrapling image interception"""

        async def page_action(page):
            """Setup route to intercept and save images"""

            async def handle_route(route):
                """Handle intercepted route requests"""
                try:
                    # Fetch the resource
                    response = await route.fetch()
                    content_type = response.headers.get("content-type", "")

                    # Only process images
                    if "image" in content_type:
                        body = await response.body()
                        url = route.request.url

                        # Save with deduplication
                        await self.image_saver.save_image(url, body, content_type)

                    # Fulfill the request
                    await route.fulfill(response=response)

                except Exception as e:
                    self.logger.warning(f"Failed to intercept image: {e}")
                    # Continue with original request
                    await route.continue_()

            # Register route for image types
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,webp,ico,bmp}", handle_route
            )

        return page_action
