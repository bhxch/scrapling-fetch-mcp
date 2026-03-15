# Web Content Saving Feature Design

**Date**: 2026-03-16
**Status**: Draft
**Author**: User + Claude Sonnet 4.6

## Problem Statement

When fetching web pages with images, the current implementation only returns HTML/Markdown content with remote image URLs. This creates several issues:

1. **Not offline-capable**: Images remain as remote URLs, requiring network access to view
2. **Risk of rate limiting**: Large pages fetched in segments make multiple requests to the same URL
3. **No local persistence**: Content cannot be viewed or referenced later without re-fetching

## Goals

1. Save complete web page content (HTML/Markdown + images) to local filesystem
2. Support offline viewing with local image references
3. Preserve original URL information for reference
4. Avoid duplicate storage of identical images (deduplication)
5. Follow MCP roots specification for path resolution
6. Integrate seamlessly with existing scrapling-fetch-mcp tools

## Non-Goals

- Image format conversion or optimization
- Video/audio resource saving (only images for now)
- Full website mirroring (single page at a time)
- Authentication-required content

## Proposed Solution

### Overview

Add a `save_content` parameter to existing fetch tools that:
1. Uses scrapling's `page_action` parameter to access the underlying patchright page object
2. Sets up route interception to capture and save images during page load
3. Deduplicates images using file size + SHA256 hash
4. Modifies HTML/Markdown content to reference local image paths
5. Preserves original URLs in HTML `data-original-src` attributes and `image_mapping.json`
6. Saves content to a structured directory under the configured `scraping_dir`

**Key Architecture Decision**: Use a parameter (`save_content`) instead of a new mode. This allows combining with any browser mode (stealth, max-stealth) and avoids mode proliferation.

### Architecture

#### Component Structure

```
scrapling-fetch-mcp/
├── src/scrapling_fetch_mcp/
│   ├── _config.py              # Add scraping_dir configuration
│   ├── _fetcher.py              # Add mode detection and saving logic
│   ├── _scrapling.py            # Add max-stealth-with-save mode
│   ├── _content_saver.py        # NEW: Image saving and content modification
│   ├── _markdownify.py          # Modify convert_img for local paths
│   └── mcp.py                   # Add scraping_dir parameter
```

#### New Module: `_content_saver.py`

**Responsibilities:**
- Image interception and saving via patchright route
- Image deduplication (size + hash comparison)
- HTML content modification (replace image URLs, add data-original-src)
- Markdown content modification (replace image URLs)
- Directory structure creation
- Metadata generation (metadata.json, image_mapping.json)

**Key Classes/Functions:**

```python
class ImageSaver:
    """Manages image saving with deduplication"""

    def __init__(self, save_dir: Path):
        self.save_dir = save_dir
        self.images_dir = save_dir / "images"
        self.url_to_local: Dict[str, str] = {}  # URL -> local path
        self.hash_to_path: Dict[str, str] = {}  # hash -> local path

    async def save_image(self, url: str, content: bytes, content_type: str) -> str:
        """Save image with deduplication, return local path"""

    def _calculate_hash(self, content: bytes) -> str:
        """Calculate SHA256 hash"""

    def _generate_filename(self, url: str, content_type: str, index: int) -> str:
        """Generate unique filename"""


class ContentModifier:
    """Modifies HTML/Markdown content to use local image paths"""

    def modify_html(self, html: str, url_to_local: Dict[str, str]) -> str:
        """Replace image URLs with local paths, add data-original-src"""

    def modify_markdown(self, markdown: str, url_to_local: Dict[str, str]) -> str:
        """Replace image URLs with local paths"""


class ContentSaver:
    """Main orchestrator for saving web content"""

    def __init__(self, scraping_dir: Path, url: str, format: str):
        self.scraping_dir = scraping_dir
        self.url = url
        self.format = format
        self.save_dir = self._create_save_dir()
        self.image_saver = ImageSaver(self.save_dir)
        self.content_modifier = ContentModifier()

    def _create_save_dir(self) -> Path:
        """Create unique save directory (domain_timestamp)"""

    async def save_with_images(self, page, html_content: str) -> str:
        """Main entry point: save content with images"""

    def create_page_action(self) -> Callable:
        """Create page_action for scrapling"""
```

### Data Flow

```
1. User calls s_fetch_page(url, mode="max-stealth-with-save", scraping_dir=".temp/scrapling/")
   ↓
2. fetch_page_impl detects mode
   ↓
3. Get root directory from MCP Context (ctx.session.list_roots())
   ↓
4. Resolve scraping_dir path (relative to root or absolute)
   ↓
5. Create ContentSaver instance
   ↓
6. Create page_action closure with image interception
   ↓
7. Call browse_url with mode="max-stealth-with-save" and page_action
   ↓
8. In browse_url:
   a. Setup route interceptor via page_action
   b. Fetch page with scrapling
   c. Images automatically saved during load
   ↓
9. Get HTML content from scrapling Response
   ↓
10. ContentSaver modifies HTML/Markdown (replace URLs)
   ↓
11. Save modified content to page.html or page.md
   ↓
12. Generate metadata.json and image_mapping.json
   ↓
13. Return modified content to user
```

### Directory Structure

```
{scraping_dir}/
├── example.com_20260316_143025/
│   ├── page.html                    # Modified HTML with local image paths
│   ├── metadata.json                # Page metadata
│   ├── images/                      # Downloaded images
│   │   ├── logo.jpg                 # Deduplicated by hash
│   │   ├── screenshot.png
│   │   └── icon.svg
│   └── image_mapping.json           # URL -> local path mapping
│
├── example.com_20260316_143025_2/   # Conflict resolution with _2 suffix
│   └── ...
│
└── docs.python.org_20260316_150000/
    └── ...
```

### File Formats

#### metadata.json

```json
{
  "url": "https://example.com/page",
  "fetch_time": "2026-03-16T14:30:25",
  "mode": "max-stealth-with-save",
  "format": "html"
}
```

#### image_mapping.json

```json
[
  {
    "original_url": "https://example.com/img/logo.jpg",
    "local_path": "images/logo.jpg"
  },
  {
    "original_url": "https://cdn.example.com/photo.png",
    "local_path": "images/photo.png"
  }
]
```

### Modified HTML Example

**Before:**
```html
<img src="https://example.com/img/logo.jpg" alt="Logo">
```

**After:**
```html
<img src="images/logo.jpg" alt="Logo" data-original-src="https://example.com/img/logo.jpg">
```

### Modified Markdown Example

**Before:**
```markdown
![Logo](https://example.com/img/logo.jpg)
```

**After:**
```markdown
![Logo](images/logo.jpg)
```

(Original URL available in `image_mapping.json`)

### Image Deduplication Strategy

1. **First encounter**: Save image, calculate hash, store `hash → local_path`
2. **Subsequent images**:
   - Compare file size first (fast check)
   - If size matches, calculate hash
   - If hash matches existing image, reuse existing file
   - Record both URLs pointing to same file in `image_mapping.json`

### Path Resolution

**Default Path**: `.temp/scrapling/`

**Resolution Logic**:
1. Get MCP roots via `ctx.session.list_roots()`
2. If roots available: use first root as base directory
3. If no roots: fallback to current working directory
4. Resolve `scraping_dir`:
   - If absolute path: use as-is
   - If relative path: resolve relative to base directory

**Examples**:
- Relative: `.temp/scrapling/` → `/project/root/.temp/scrapling/`
- Absolute: `/tmp/scraping/` → `/tmp/scraping/`

### Configuration

**CLI Argument**:
```bash
scrapling-fetch-mcp --scraping-dir .temp/scrapling/
```

**Environment Variable**:
```bash
SCRAPING_DIR=.temp/scrapling/ scrapling-fetch-mcp
```

**MCP Tool Parameter**:
```python
s_fetch_page(
    url="https://example.com",
    mode="max-stealth-with-save",
    scraping_dir=".temp/scrapling/"  # Override default
)
```

### Mode Selection Rationale

**Why `max-stealth-with-save` as a mode?**
1. Only `max-stealth` mode has `disable_resources=False` and `block_images=False`
2. Saving images requires images to be loaded
3. Lower modes (basic, stealth) may not load images
4. Clear semantic: "use max stealth AND save content"

### Implementation Details

#### Image Interception via page_action

```python
async def setup_image_interceptor(page, image_saver: ImageSaver):
    """Setup route to intercept and save images"""

    async def handle_route(route):
        # Fetch the image
        response = await route.fetch()
        content_type = response.headers.get('content-type', '')

        if 'image' in content_type:
            # Get image content
            body = await response.body()
            url = route.request.url

            # Save with deduplication
            local_path = await image_saver.save_image(url, body, content_type)

        # Fulfill the request
        await route.fulfill(response=response)

    # Register route for image types
    await page.route("**/*.{png,jpg,jpeg,gif,svg,webp,ico,bmp}", handle_route)


def create_page_action(image_saver: ImageSaver) -> Callable:
    """Create page_action closure for scrapling"""
    async def page_action(page):
        await setup_image_interceptor(page, image_saver)
    return page_action
```

#### HTML Modification

```python
def modify_html(html: str, url_to_local: Dict[str, str]) -> str:
    """Replace image URLs with local paths in HTML"""
    soup = BeautifulSoup(html, 'lxml')

    for img in soup.find_all('img'):
        src = img.get('src')
        if src and src in url_to_local:
            # Add data-original-src attribute
            img['data-original-src'] = src
            # Replace with local path
            img['src'] = url_to_local[src]

    return str(soup)
```

#### Markdown Modification

```python
def modify_markdown(markdown: str, url_to_local: Dict[str, str]) -> str:
    """Replace image URLs with local paths in Markdown"""
    import re

    # Match markdown image syntax: ![alt](url)
    pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'

    def replace_url(match):
        alt = match.group(1)
        url = match.group(2)
        if url in url_to_local:
            return f'![{alt}]({url_to_local[url]})'
        return match.group(0)

    return re.sub(pattern, replace_url, markdown)
```

### Error Handling

1. **Image download failure**: Log warning, continue with original URL
2. **Directory creation failure**: Raise error with clear message
3. **File write failure**: Raise error with clear message
4. **Invalid scraping_dir**: Validate early, provide helpful error message
5. **No roots available**: Fallback to cwd with warning log

### Testing Strategy

**Unit Tests**:
- Image deduplication logic
- HTML/Markdown modification
- Path resolution
- Directory naming and conflict resolution

**Integration Tests**:
- End-to-end content saving with real webpage
- Image interception and saving
- Metadata generation
- Offline viewing verification

**Test Cases**:
1. Page with no images
2. Page with multiple images
3. Page with duplicate images (same image used multiple times)
4. Page with invalid/broken image URLs
5. Large page with many images
6. Relative vs absolute scraping_dir
7. Directory name conflicts
8. Different image formats (jpg, png, svg, webp)

### Performance Considerations

1. **Image interception**: Happens during page load, minimal overhead
2. **Hash calculation**: Only for images of same size (lazy)
3. **Concurrent image saving**: Sequential by default (patchright route limitation)
4. **Memory usage**: Images saved to disk immediately, not held in memory
5. **Disk space**: Deduplication reduces storage for repeated images

### Security Considerations

1. **Path traversal**: Validate and sanitize all paths
2. **File size limits**: Consider max image size to prevent abuse
3. **Content type validation**: Verify image content-type before saving
4. **Symlink safety**: Don't follow symlinks when creating directories

### Migration Path

**Phase 1**: Implement core functionality
- _content_saver.py module
- max-stealth-with-save mode
- Basic HTML/Markdown saving

**Phase 2**: Add configuration
- CLI argument support
- Environment variable support
- Tool parameter support

**Phase 3**: Polish and optimize
- Comprehensive error handling
- Performance optimization
- Documentation updates

### Documentation Updates

**README.md**: Add section on content saving feature
**MCP_CONFIG_EXAMPLES.md**: Add examples with scraping_dir configuration
**Tool docstrings**: Update to mention max-stealth-with-save mode

### Alternative Approaches Considered

1. **Separate tool function**: Rejected - duplicates code, can't reuse cache
2. **Post-processing script**: Rejected - extra step, breaks MCP workflow
3. **Separate image download**: Rejected - triggers anti-bot, wasteful
4. **Using scrapling's storage**: Rejected - deprecated, not designed for this use case

### Open Questions

None at this time. Design is complete and ready for implementation.

### References

- scrapling documentation: https://github.com/D4Vinci/Scrapling
- MCP specification: https://modelcontextprotocol.io/
- patchright (playwright fork): Internal dependency of scrapling
