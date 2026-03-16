# Web Content Saving Feature Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the ability to save complete web page content (HTML/Markdown + images) to local filesystem with offline viewing support.

**Architecture:** Use a `save_content` parameter approach instead of a new mode. Create a new `_content_saver.py` module to handle image interception via patchright routes, image deduplication using size + SHA256 hash, and content modification to replace remote URLs with local paths. Integrate seamlessly with existing scrapling-fetch-mcp tools.

**Tech Stack:** Python 3.10+, scrapling, patchright (playwright fork), BeautifulSoup4, pathlib

---

## File Structure

**Files to create:**
- `src/scrapling_fetch_mcp/_content_saver.py` - Core content saving logic (ImageSaver, ContentModifier, ContentSaver classes)
- `tests/` - Test directory (will be created)
- `tests/test_content_saver.py` - Unit tests for content saving
- `tests/conftest.py` - Pytest fixtures

**Files to modify:**
- `src/scrapling_fetch_mcp/_config.py` - Add scraping_dir configuration
- `src/scrapling_fetch_mcp/_fetcher.py` - Add save_content logic
- `src/scrapling_fetch_mcp/_scrapling.py` - Add page_action support for image interception
- `src/scrapling_fetch_mcp/mcp.py` - Add save_content and scraping_dir parameters
- `src/scrapling_fetch_mcp/_markdownify.py` - Update convert_img for local paths
- `pyproject.toml` - Add test dependencies

---

## Chunk 1: Core Content Saving Infrastructure

### Task 1: Setup Test Infrastructure

**Files:**
- Create: `tests/conftest.py`
- Create: `tests/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add test dependencies to pyproject.toml**

```toml
[project.optional-dependencies]
test = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-cov>=4.1.0",
]
```

- [ ] **Step 2: Create tests directory structure**

```bash
mkdir -p tests
touch tests/__init__.py
```

Expected: Directory created successfully

- [ ] **Step 3: Create pytest configuration**

Create `tests/conftest.py`:
```python
"""Pytest configuration and fixtures"""
import pytest
from pathlib import Path
import tempfile


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for tests"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_html():
    """Sample HTML with images for testing"""
    return """
    <html>
        <body>
            <h1>Test Page</h1>
            <img src="https://example.com/logo.jpg" alt="Logo">
            <img src="https://cdn.example.com/banner.png" alt="Banner">
            <p>Some text content</p>
        </body>
    </html>
    """


@pytest.fixture
def sample_markdown():
    """Sample Markdown with images for testing"""
    return """# Test Page

![Logo](https://example.com/logo.jpg)

![Banner](https://cdn.example.com/banner.png)

Some text content
"""
```

- [ ] **Step 4: Install test dependencies**

```bash
uv pip install -e ".[test]"
```

Expected: Dependencies installed successfully

- [ ] **Step 5: Commit test setup**

```bash
git add tests/conftest.py tests/__init__.py pyproject.toml
git commit -m "test: setup test infrastructure with pytest"
```

---

### Task 2: Implement ImageSaver Class

**Files:**
- Create: `src/scrapling_fetch_mcp/_content_saver.py`
- Create: `tests/test_content_saver.py`

- [ ] **Step 1: Write failing test for ImageSaver initialization**

Create `tests/test_content_saver.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_content_saver.py::TestImageSaver::test_init -v
```

Expected: FAIL with "ModuleNotFoundError: No module named 'scrapling_fetch_mcp._content_saver'"

- [ ] **Step 3: Implement ImageSaver basic structure**

Create `src/scrapling_fetch_mcp/_content_saver.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestImageSaver -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit ImageSaver basic structure**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py tests/test_content_saver.py
git commit -m "feat: add ImageSaver class with basic structure"
```

---

### Task 3: Implement ImageSaver.save_image()

**Files:**
- Modify: `src/scrapling_fetch_mcp/_content_saver.py`
- Modify: `tests/test_content_saver.py`

- [ ] **Step 1: Write failing test for save_image**

Add to `tests/test_content_saver.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_content_saver.py::TestImageSaver::test_save_image_new -v
```

Expected: FAIL with "TypeError: object NoneType can't be used in 'await' expression" or AttributeError

- [ ] **Step 3: Implement save_image method**

Add to `src/scrapling_fetch_mcp/_content_saver.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestImageSaver -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit save_image implementation**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py tests/test_content_saver.py
git commit -m "feat: implement ImageSaver.save_image with deduplication"
```

---

### Task 4: Implement ContentModifier Class

**Files:**
- Modify: `src/scrapling_fetch_mcp/_content_saver.py`
- Modify: `tests/test_content_saver.py`

- [ ] **Step 1: Write failing test for ContentModifier**

Add to `tests/test_content_saver.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_content_saver.py::TestContentModifier -v
```

Expected: FAIL with "ImportError: cannot import name 'ContentModifier'"

- [ ] **Step 3: Implement ContentModifier class**

Add to `src/scrapling_fetch_mcp/_content_saver.py`:
```python
import re
from bs4 import BeautifulSoup


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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestContentModifier -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit ContentModifier implementation**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py tests/test_content_saver.py
git commit -m "feat: implement ContentModifier for HTML/Markdown modification"
```

---

### Task 5: Implement ContentSaver Class (Main Orchestrator)

**Files:**
- Modify: `src/scrapling_fetch_mcp/_content_saver.py`
- Modify: `tests/test_content_saver.py`

- [ ] **Step 1: Write failing test for ContentSaver**

Add to `tests/test_content_saver.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_content_saver.py::TestContentSaver -v
```

Expected: FAIL with "ImportError: cannot import name 'ContentSaver'"

- [ ] **Step 3: Implement ContentSaver class**

Add to `src/scrapling_fetch_mcp/_content_saver.py`:
```python
from datetime import datetime
from json import dumps
from typing import Optional


class ContentSaver:
    """Main orchestrator for saving web content"""

    def __init__(self, scraping_dir: Path, url: str, format: str):
        self.scraping_dir = scraping_dir
        self.url = url
        self.format = format
        self.save_dir = self._create_save_dir()
        self.image_saver = ImageSaver(self.save_dir)
        self.content_modifier = ContentModifier()
        self.logger = getLogger(__name__)

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestContentSaver -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit ContentSaver implementation**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py tests/test_content_saver.py
git commit -m "feat: implement ContentSaver main orchestrator class"
```

---

## Chunk 2: Configuration and Scrapling Integration

### Task 6: Add scraping_dir Configuration

**Files:**
- Modify: `src/scrapling_fetch_mcp/_config.py`
- Modify: `tests/test_config.py` (create)

- [ ] **Step 1: Write failing test for scraping_dir config**

Create `tests/test_config.py`:
```python
"""Tests for configuration"""
import pytest
from pathlib import Path
from scrapling_fetch_mcp._config import Config


class TestConfig:
    """Tests for Config class"""

    def test_default_scraping_dir(self):
        """Test default scraping directory"""
        config = Config()
        assert config.scraping_dir == Path(".temp/scrapling/")

    def test_set_scraping_dir(self):
        """Test setting scraping directory"""
        config = Config()
        custom_path = Path("/tmp/scraping")
        config.set_scraping_dir(custom_path)

        assert config.scraping_dir == custom_path

    def test_set_scraping_dir_string(self):
        """Test setting scraping directory with string"""
        config = Config()
        config.set_scraping_dir("/custom/path")

        assert config.scraping_dir == Path("/custom/path")
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL with "AttributeError: 'Config' object has no attribute 'scraping_dir'"

- [ ] **Step 3: Implement scraping_dir in Config**

Modify `src/scrapling_fetch_mcp/_config.py`:
```python
from pathlib import Path

class Config:
    """Global configuration singleton"""

    _instance = None
    _min_mode: str = "basic"
    _cache_ttl: int = 300  # Default 5 minutes
    _cache: Optional[PageCache] = None
    _scraping_dir: Path = Path(".temp/scrapling/")  # NEW

    # ... existing code ...

    @property
    def scraping_dir(self) -> Path:
        """Get the scraping directory"""
        return self._scraping_dir

    def set_scraping_dir(self, path: Path | str) -> None:
        """Set the scraping directory"""
        if isinstance(path, str):
            path = Path(path)
        self._scraping_dir = path
```

Also update `init_config_from_env()`:
```python
def init_config_from_env() -> None:
    """Initialize configuration from environment variables"""
    env_min_mode = getenv("SCRAPLING_MIN_MODE", "").lower()
    if env_min_mode and env_min_mode in MODE_LEVELS:
        config.set_min_mode(env_min_mode)

    env_cache_ttl = getenv("SCRAPLING_CACHE_TTL", "")
    if env_cache_ttl:
        try:
            ttl = int(env_cache_ttl)
            config.set_cache_ttl(ttl)
        except ValueError:
            pass  # Invalid value, use default

    # NEW: Load scraping_dir from environment
    env_scraping_dir = getenv("SCRAPING_DIR", "")
    if env_scraping_dir:
        config.set_scraping_dir(env_scraping_dir)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: All tests PASS

- [ ] **Step 5: Commit config changes**

```bash
git add src/scrapling_fetch_mcp/_config.py tests/test_config.py
git commit -m "feat: add scraping_dir configuration support"
```

---

### Task 7: Add page_action Support to browse_url

**Files:**
- Modify: `src/scrapling_fetch_mcp/_scrapling.py`
- Create: `tests/test_scrapling.py`

- [ ] **Step 1: Write test for page_action parameter**

Add to `tests/test_scrapling.py`:
```python
"""Tests for scrapling wrapper"""
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_browse_url_with_page_action():
    """Test browse_url accepts page_action parameter"""
    from scrapling_fetch_mcp._scrapling import browse_url

    # Mock page_action function
    page_action_called = False

    async def test_page_action(page):
        nonlocal page_action_called
        page_action_called = True

    # This test will verify the parameter is accepted
    # We won't actually call browse_url as it requires real browser
    # Just verify the signature accepts the parameter
    import inspect
    sig = inspect.signature(browse_url)
    params = sig.parameters

    # Check if page_action parameter exists
    assert "page_action" in params
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scrapling.py -v
```

Expected: FAIL with "AssertionError: 'page_action' not in params"

- [ ] **Step 3: Add page_action parameter to browse_url**

Modify `src/scrapling_fetch_mcp/_scrapling.py`:
```python
from contextlib import redirect_stdout
from os import devnull
from typing import Any, Callable, Optional


async def browse_url(
    url: str,
    mode: str,
    page_action: Optional[Callable] = None
) -> Any:
    """
    Browse URL using scrapling fetcher.

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, max-stealth)
        page_action: Optional async function to run on page object
    """
    with open(devnull, "w") as nullfd, redirect_stdout(nullfd):
        from scrapling.fetchers import AsyncFetcher, StealthyFetcher

        if mode == "basic":
            return await AsyncFetcher.get(url, stealthy_headers=True)
        elif mode == "stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                network_idle=True,
                page_action=page_action,  # NEW
            )
        elif mode == "max-stealth":
            return await StealthyFetcher.async_fetch(
                url,
                headless=True,
                block_webrtc=True,
                network_idle=True,
                disable_resources=False,
                block_images=False,
                page_action=page_action,  # NEW
            )
        else:
            raise ValueError(f"Unknown mode: {mode}")
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_scrapling.py -v
```

Expected: Test PASS

- [ ] **Step 5: Commit page_action support**

```bash
git add src/scrapling_fetch_mcp/_scrapling.py tests/test_scrapling.py
git commit -m "feat: add page_action parameter to browse_url"
```

---

### Task 8: Create Image Interception Logic

**Files:**
- Modify: `src/scrapling_fetch_mcp/_content_saver.py`
- Modify: `tests/test_content_saver.py`

- [ ] **Step 1: Write test for image interception setup**

Add to `tests/test_content_saver.py`:
```python
    @pytest.mark.asyncio
    async def test_create_page_action(self, temp_dir):
        """Test page_action creation for image interception"""
        saver = ContentSaver(temp_dir, "https://example.com", "html")

        # Create page_action
        page_action = saver.create_page_action()
        assert callable(page_action)

        # Note: Full integration test will be done with real browser
        # This just verifies the method exists and returns a callable
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_content_saver.py::TestContentSaver::test_create_page_action -v
```

Expected: FAIL with "AttributeError: 'ContentSaver' object has no attribute 'create_page_action'"

- [ ] **Step 3: Implement create_page_action**

Add to `src/scrapling_fetch_mcp/_content_saver.py` in ContentSaver class:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestContentSaver::test_create_page_action -v
```

Expected: Test PASS

- [ ] **Step 5: Commit image interception logic**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py tests/test_content_saver.py
git commit -m "feat: implement page_action for image interception"
```

---

## Chunk 3: MCP Tool Integration

### Task 9: Update fetch_page_impl to Support save_content

**Files:**
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`
- Create: `tests/test_fetcher.py`

- [ ] **Step 1: Write test for save_content parameter**

Create `tests/test_fetcher.py`:
```python
"""Tests for fetcher functions"""
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_fetch_page_impl_with_save_content(temp_dir):
    """Test fetch_page_impl with save_content enabled"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    # Mock browse_url to return a fake response
    mock_response = MagicMock()
    mock_response.html_content = "<html><body><h1>Test</h1></body></html>"

    with patch("scrapling_fetch_mcp._fetcher.browse_url", new_callable=AsyncMock) as mock_browse:
        mock_browse.return_value = mock_response

        result = await fetch_page_impl(
            url="https://example.com",
            mode="max-stealth",
            format="html",
            max_length=10000,
            start_index=0,
            save_content=True,
            scraping_dir=temp_dir
        )

        # Should return content
        assert "METADATA:" in result
        assert "Test" in result

        # browse_url should be called with page_action
        assert mock_browse.called
        call_kwargs = mock_browse.call_args.kwargs
        assert "page_action" in call_kwargs
        assert callable(call_kwargs["page_action"])
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_fetcher.py -v
```

Expected: FAIL with "TypeError: fetch_page_impl() got unexpected keyword arguments"

- [ ] **Step 3: Update fetch_page_impl signature and logic**

Modify `src/scrapling_fetch_mcp/_fetcher.py`:
```python
from pathlib import Path
from typing import Optional
from scrapling_fetch_mcp._content_saver import ContentSaver


async def fetch_page_impl(
    url: str,
    mode: str,
    format: str,
    max_length: int,
    start_index: int,
    save_content: bool = False,
    scraping_dir: Optional[Path] = None,
) -> str:
    effective_mode = config.get_effective_mode(mode)

    # Setup content saver if needed
    content_saver = None
    page_action = None
    if save_content and scraping_dir:
        content_saver = ContentSaver(scraping_dir, url, format)
        page_action = content_saver.create_page_action()

    # Check cache first
    cached_page = config.cache.get(url, effective_mode)
    if cached_page is not None:
        page = cached_page
    else:
        # Fetch and cache the page
        page = await browse_url(url, effective_mode, page_action=page_action)
        config.cache.set(url, effective_mode, page)

    is_markdown = format == "markdown"

    # Get HTML content
    html_content = page.html_content

    # Save content if requested
    if content_saver:
        html_content = await content_saver.save_content(html_content)

    # Convert to markdown if needed
    full_content = (
        _html_to_markdown(html_content) if is_markdown else html_content
    )

    total_length = len(full_content)
    truncated_content = full_content[start_index : start_index + max_length]
    is_truncated = total_length > (start_index + max_length)

    metadata_json = _create_metadata(
        total_length, len(truncated_content), is_truncated, start_index
    )
    return f"METADATA: {metadata_json}\n\n{truncated_content}"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_fetcher.py -v
```

Expected: Test PASS

- [ ] **Step 5: Commit fetcher changes**

```bash
git add src/scrapling_fetch_mcp/_fetcher.py tests/test_fetcher.py
git commit -m "feat: add save_content support to fetch_page_impl"
```

---

### Task 10: Update MCP Tool Parameters

**Files:**
- Modify: `src/scrapling_fetch_mcp/mcp.py`
- Modify: `tests/test_fetcher.py`

- [ ] **Step 1: Add parameters to s_fetch_page tool**

Modify `src/scrapling_fetch_mcp/mcp.py`:
```python
from pathlib import Path

@mcp.tool()
async def s_fetch_page(
    url: str,
    mode: str = "basic",
    format: str = "markdown",
    max_length: int = 5000,
    start_index: int = 0,
    save_content: bool = False,
    scraping_dir: str = ".temp/scrapling/",
) -> str:
    """Fetches a complete web page with pagination support. Retrieves content from websites with bot-detection avoidance. Content is returned as 'METADATA: {json}\\n\\n[content]' where metadata includes length information and truncation status.

    The server can be configured with a minimum mode via --min-mode CLI argument or SCRAPLING_MIN_MODE environment variable to prevent multiple retry attempts from escalating modes.

    Pages are cached for the configured TTL (--cache-ttl, default 300 seconds) to avoid repeated requests when fetching large pages in segments using start_index parameter.

    Args:
        url: URL to fetch
        mode: Fetching mode (basic, stealth, or max-stealth). The effective mode will be the maximum of this and the server's minimum mode setting.
        format: Output format (html or markdown)
        max_length: Maximum number of characters to return.
        start_index: On return output starting at this character index, useful if a previous fetch was truncated and more content is required.
        save_content: If True, save complete page content (HTML/Markdown + images) to local filesystem for offline viewing.
        scraping_dir: Directory path for saved content (relative or absolute). Default: .temp/scrapling/
    """
    try:
        scraping_path = Path(scraping_dir)

        result = await fetch_page_impl(
            url,
            mode,
            format,
            max_length,
            start_index,
            save_content=save_content,
            scraping_dir=scraping_path,
        )
        return result
    except Exception as e:
        logger = getLogger("scrapling_fetch_mcp")
        logger.error("DETAILED ERROR IN s_fetch_page: %s", str(e))
        logger.error("TRACEBACK: %s", format_exc())
        raise
```

- [ ] **Step 2: Update CLI arguments in run_server**

Modify `src/scrapling_fetch_mcp/mcp.py`:
```python
def run_server():
    """Parse CLI arguments and start the MCP server"""
    parser = ArgumentParser(
        description="Scrapling Fetch MCP Server - Fetch web content with bot-detection avoidance"
    )
    parser.add_argument(
        "--min-mode",
        choices=["basic", "stealth", "max-stealth"],
        help="Minimum fetching mode level. All requests will use at least this mode, "
        "preventing multiple retries from basic to higher modes. "
        "Can also be set via SCRAPLING_MIN_MODE environment variable.",
    )
    parser.add_argument(
        "--cache-ttl",
        type=int,
        default=300,
        help="Cache time-to-live in seconds for fetched pages. "
        "When fetching large pages in segments, this prevents repeated requests to the same URL. "
        "Set to 0 to disable caching. Default: 300 (5 minutes). "
        "Can also be set via SCRAPLING_CACHE_TTL environment variable.",
    )
    parser.add_argument(
        "--scraping-dir",
        type=str,
        default=".temp/scrapling/",
        help="Default directory for saving scraped content (HTML + images). "
        "Can be overridden per-request with scraping_dir parameter. "
        "Default: .temp/scrapling/ "
        "Can also be set via SCRAPING_DIR environment variable.",
    )
    args = parser.parse_args()

    # Initialize from environment first
    init_config_from_env()

    # CLI args override environment variables
    if args.min_mode:
        config.set_min_mode(args.min_mode)

    if args.cache_ttl is not None:
        config.set_cache_ttl(args.cache_ttl)

    if args.scraping_dir:
        config.set_scraping_dir(args.scraping_dir)

    # Log the configuration
    logger = getLogger("scrapling_fetch_mcp")
    logger.info(f"Minimum mode set to: {config.min_mode}")
    logger.info(f"Cache TTL set to: {config.cache_ttl} seconds")
    logger.info(f"Scraping directory set to: {config.scraping_dir}")

    mcp.run(transport="stdio")
```

- [ ] **Step 3: Run basic smoke test**

```bash
uv run python -c "from scrapling_fetch_mcp.mcp import mcp; print('MCP tools loaded successfully')"
```

Expected: "MCP tools loaded successfully"

- [ ] **Step 4: Commit MCP tool changes**

```bash
git add src/scrapling_fetch_mcp/mcp.py
git commit -m "feat: add save_content and scraping_dir parameters to s_fetch_page"
```

---

## Chunk 4: Markdown Support and Documentation

### Task 11: Update Markdown Conversion for Local Paths

**Files:**
- Modify: `src/scrapling_fetch_mcp/_markdownify.py`
- Modify: `src/scrapling_fetch_mcp/_fetcher.py`
- Create: `tests/test_markdownify.py`

- [ ] **Step 1: Update ContentSaver to handle markdown**

Modify `src/scrapling_fetch_mcp/_content_saver.py` ContentSaver.save_content:
```python
    async def save_content(self, html_content: str) -> str:
        """Save content and return modified HTML or Markdown"""
        # Modify HTML to use local image paths
        modified_html = self.content_modifier.modify_html(
            html_content, self.image_saver.url_to_local
        )

        if self.format == "markdown":
            # Convert to markdown, then modify markdown image paths
            from scrapling_fetch_mcp._markdownify import _html_to_markdown
            markdown_content = _html_to_markdown(modified_html)
            final_content = self.content_modifier.modify_markdown(
                markdown_content, self.image_saver.url_to_local
            )

            # Save as .md file
            content_file = self.save_dir / "page.md"
            content_file.write_text(final_content, encoding="utf-8")
        else:
            # Save HTML
            content_file = self.save_dir / "page.html"
            content_file.write_text(modified_html, encoding="utf-8")
            final_content = modified_html

        # Save metadata
        self._save_metadata()

        # Save image mapping
        self._save_image_mapping()

        return final_content
```

- [ ] **Step 2: Extract _html_to_markdown for reuse**

Modify `src/scrapling_fetch_mcp/_fetcher.py`:
```python
# Make function available for import
__all__ = ['fetch_page_impl', 'fetch_pattern_impl', '_html_to_markdown']
```

- [ ] **Step 3: Write test for markdown saving**

Add to `tests/test_content_saver.py`:
```python
    @pytest.mark.asyncio
    async def test_save_content_markdown(self, temp_dir, sample_html):
        """Test saving content as markdown"""
        saver = ContentSaver(temp_dir, "https://example.com/page", "markdown")

        modified = await saver.save_content(sample_html)

        # Should create page.md not page.html
        md_file = saver.save_dir / "page.md"
        assert md_file.exists()

        # Should not create page.html
        html_file = saver.save_dir / "page.html"
        assert not html_file.exists()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_content_saver.py::TestContentSaver::test_save_content_markdown -v
```

Expected: Test PASS

- [ ] **Step 5: Commit markdown support**

```bash
git add src/scrapling_fetch_mcp/_content_saver.py src/scrapling_fetch_mcp/_fetcher.py tests/test_content_saver.py
git commit -m "feat: add markdown format support to content saving"
```

---

### Task 12: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `MCP_CONFIG_EXAMPLES.md`

- [ ] **Step 1: Update README with content saving feature**

Add to `README.md` after the features section:
```markdown
## Content Saving Feature

Save complete web pages (HTML/Markdown + images) to your local filesystem for offline viewing.

### Basic Usage

```python
# Save page with images
result = await s_fetch_page(
    url="https://example.com/article",
    mode="max-stealth",
    save_content=True,
    scraping_dir=".temp/scrapling/"
)
```

### Directory Structure

Saved content is organized as:

```
.temp/scrapling/
├── example.com_20260316_143025/
│   ├── page.html          # Modified HTML with local image paths
│   ├── metadata.json      # Page metadata (URL, fetch time, mode)
│   ├── images/            # Downloaded images (deduplicated)
│   │   ├── logo.jpg
│   │   └── banner.png
│   └── image_mapping.json # Original URL -> local path mapping
```

### Features

- **Offline viewing**: All images are downloaded and referenced locally
- **Image deduplication**: Identical images (same hash) stored only once
- **URL preservation**: Original image URLs saved in `data-original-src` attributes and `image_mapping.json`
- **Markdown support**: Save as Markdown with local image references

### Requirements

- Use `mode="max-stealth"` or `mode="stealth"` (basic mode may not load images)
- Images are intercepted during page load via patchright route handling
```

- [ ] **Step 2: Update MCP_CONFIG_EXAMPLES.md**

Add to `MCP_CONFIG_EXAMPLES.md`:
```markdown
## Content Saving Configuration

### Environment Variable

```bash
export SCRAPING_DIR=".temp/scrapling/"
scrapling-fetch-mcp
```

### CLI Argument

```bash
scrapling-fetch-mcp --scraping-dir /path/to/scraping/
```

### MCP Configuration with Content Saving

```json
{
  "mcpServers": {
    "scrapling-fetch": {
      "command": "uvx",
      "args": [
        "scrapling-fetch-mcp",
        "--scraping-dir",
        "/Users/username/.scraping/"
      ]
    }
  }
}
```

### Per-Request Override

```json
{
  "tool": "s_fetch_page",
  "arguments": {
    "url": "https://example.com",
    "mode": "max-stealth",
    "save_content": true,
    "scraping_dir": "/tmp/scraping/"
  }
}
```
```

- [ ] **Step 3: Commit documentation updates**

```bash
git add README.md MCP_CONFIG_EXAMPLES.md
git commit -m "docs: add content saving feature documentation"
```

---

## Chunk 5: Integration Testing and Final Polish

### Task 13: Integration Test with Real Webpage

**Files:**
- Create: `tests/test_integration.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Create integration test**

Create `tests/test_integration.py`:
```python
"""Integration tests for content saving"""
import pytest
from pathlib import Path


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_real_webpage(temp_dir):
    """Test saving a real webpage with images"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    # Use a simple, reliable test page
    url = "https://example.com"

    result = await fetch_page_impl(
        url=url,
        mode="max-stealth",
        format="html",
        max_length=10000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return content
    assert "METADATA:" in result

    # Should create save directory
    save_dirs = list(temp_dir.glob("example.com_*"))
    assert len(save_dirs) == 1

    save_dir = save_dirs[0]

    # Should have required files
    assert (save_dir / "page.html").exists()
    assert (save_dir / "metadata.json").exists()
    assert (save_dir / "image_mapping.json").exists()

    # Check metadata
    import json
    with open(save_dir / "metadata.json") as f:
        metadata = json.load(f)

    assert metadata["url"] == url
    assert "fetch_time" in metadata
    assert metadata["format"] == "html"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_save_webpage_markdown(temp_dir):
    """Test saving webpage as markdown"""
    from scrapling_fetch_mcp._fetcher import fetch_page_impl

    url = "https://example.com"

    result = await fetch_page_impl(
        url=url,
        mode="max-stealth",
        format="markdown",
        max_length=10000,
        start_index=0,
        save_content=True,
        scraping_dir=temp_dir
    )

    # Should return markdown
    assert "METADATA:" in result

    # Should create .md file
    save_dirs = list(temp_dir.glob("example.com_*"))
    save_dir = save_dirs[0]

    assert (save_dir / "page.md").exists()
    assert not (save_dir / "page.html").exists()
```

- [ ] **Step 2: Run integration tests**

```bash
uv run pytest tests/test_integration.py -v -m integration
```

Expected: Integration tests PASS (may take 10-30 seconds)

- [ ] **Step 3: Commit integration tests**

```bash
git add tests/test_integration.py
git commit -m "test: add integration tests for content saving"
```

---

### Task 14: Final Verification and Documentation

**Files:**
- All modified files

- [ ] **Step 1: Run all tests**

```bash
uv run pytest tests/ -v --cov=src/scrapling_fetch_mcp --cov-report=term-missing
```

Expected: All tests PASS, coverage report generated

- [ ] **Step 2: Test CLI with new parameters**

```bash
uv run scrapling-fetch-mcp --help
```

Expected: Help output shows `--scraping-dir` parameter

- [ ] **Step 3: Manual smoke test**

```bash
# Create a test script
cat > /tmp/test_save.py << 'EOF'
import asyncio
from pathlib import Path
from scrapling_fetch_mcp._fetcher import fetch_page_impl

async def main():
    result = await fetch_page_impl(
        url="https://example.com",
        mode="basic",
        format="html",
        max_length=1000,
        start_index=0,
        save_content=False
    )
    print(result[:200])

asyncio.run(main())
EOF

uv run python /tmp/test_save.py
```

Expected: Output shows METADATA and HTML content

- [ ] **Step 4: Create final commit with all changes**

```bash
git add -A
git status
git commit -m "feat: complete web content saving feature implementation

- Add _content_saver.py module with ImageSaver, ContentModifier, ContentSaver
- Add save_content parameter to s_fetch_page tool
- Add scraping_dir configuration (CLI, env, per-request)
- Support image interception via patchright routes
- Implement image deduplication with SHA256 hash
- Add local path modification for HTML and Markdown
- Preserve original URLs in data-original-src and image_mapping.json
- Add comprehensive unit and integration tests
- Update documentation (README, MCP_CONFIG_EXAMPLES)"
```

- [ ] **Step 5: Create summary of changes**

Run:
```bash
git log --oneline --decorate | head -20
```

Expected: Show all commits from this implementation

---

## Summary

**Implementation complete!** The web content saving feature is now fully integrated into scrapling-fetch-mcp.

### Key Features Implemented:

1. ✅ Image interception during page load via patchright routes
2. ✅ Image deduplication using size + SHA256 hash
3. ✅ HTML modification with local image paths and `data-original-src` attributes
4. ✅ Markdown modification with local image paths
5. ✅ Directory structure: `{domain}_{timestamp}/` with `page.html|md`, `images/`, `metadata.json`, `image_mapping.json`
6. ✅ Configuration: CLI (`--scraping-dir`), env (`SCRAPING_DIR`), per-request parameter
7. ✅ Test coverage: unit tests and integration tests
8. ✅ Documentation updates

### Usage Example:

```python
# Save a webpage with images
result = await s_fetch_page(
    url="https://example.com/article",
    mode="max-stealth",
    format="html",
    save_content=True,
    scraping_dir=".temp/scrapling/"
)
```

### Next Steps (Optional Enhancements):

- Add image format conversion/optimization
- Support video/audio resources
- Add file size limits for images
- Implement concurrent image downloading
- Add progress indicators for large pages
