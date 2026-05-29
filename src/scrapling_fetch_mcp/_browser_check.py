import importlib.metadata
import logging
import os
import subprocess
import sys

logger = logging.getLogger("scrapling_fetch_mcp")

_CACHE_DIR = os.environ.get(
    "PLAYWRIGHT_BROWSERS_PATH",
    os.path.expanduser("~/.cache/ms-playwright"),
)


def _installed_version(tool: str) -> str | None:
    try:
        return importlib.metadata.version(tool)
    except importlib.metadata.PackageNotFoundError:
        return None


def _sentinel_path(tool: str) -> str:
    return os.path.join(_CACHE_DIR, f".{tool}-browser-checked")


def _sentinel_valid(tool: str) -> bool:
    """Return True when the sentinel records the same version currently installed."""
    version = _installed_version(tool)
    if version is None:
        return False
    path = _sentinel_path(tool)
    try:
        with open(path) as f:
            return f.read().strip() == version
    except (FileNotFoundError, PermissionError):
        return False


def _write_sentinel(tool: str) -> None:
    version = _installed_version(tool)
    if version is None:
        return
    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_sentinel_path(tool), "w") as f:
            f.write(version)
    except OSError:
        pass


def _run_install(tool: str) -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", tool, "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if result.returncode == 0:
            return True
        logger.warning(
            "%s install returned %d: %s",
            tool,
            result.returncode,
            result.stderr.strip(),
        )
    except FileNotFoundError:
        logger.debug("%s module not found, skipping", tool)
    except subprocess.TimeoutExpired:
        logger.warning("%s browser install timed out", tool)
    except Exception as exc:
        logger.warning("Failed to run %s install: %s", tool, exc)
    return False


def ensure_browsers_installed() -> None:
    """Ensure chromium browsers required by scrapling are installed.

    Scrapling uses *patchright* for stealth modes and *playwright* for basic
    mode.  When these libraries are updated (e.g. via ``uvx`` pulling a newer
    version), the expected chromium revision may change.  A sentinel file
    recording the tool version is used to avoid redundant install runs.
    """
    for tool in ("patchright", "playwright"):
        if _sentinel_valid(tool):
            continue
        logger.info("%s version changed or browser not checked, verifying chromium...", tool)
        if _run_install(tool):
            _write_sentinel(tool)
            logger.info("%s chromium browser ready", tool)
        else:
            logger.warning("%s chromium browser may not be available", tool)
