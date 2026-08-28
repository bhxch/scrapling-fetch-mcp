import importlib.metadata
import importlib.util
import io
import logging
import os
import subprocess
import sys
import tarfile
import urllib.request

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


# ---------------------------------------------------------------------------
# browserforge fingerprint/header model data
# ---------------------------------------------------------------------------
# browserforge 1.2.x ships its wheel *without* the Bayesian-network model
# files (input-network.zip, ...). Importing ``browserforge.headers`` loads
# them at module level, so they must exist before any stealth fetch runs.
# The official command ``python -m browserforge update`` pulls them from
# GitHub (apify/fingerprint-suite), which is unreachable in some networks.
# We fall back to the npm registries, which carry the very same data files
# inside the ``header-generator`` / ``fingerprint-generator`` packages.

# local filename -> remote (definition) filename, matching browserforge download.py
_BF_DATA_FILES = {
    "headers": {
        "input-network.zip": "input-network-definition.zip",
        "header-network.zip": "header-network-definition.zip",
        "browser-helper-file.json": "browser-helper-file.json",
        "headers-order.json": "headers-order.json",
    },
    "fingerprints": {
        "fingerprint-network.zip": "fingerprint-network-definition.zip",
    },
}
# Pinned npm package versions (data format compatible with browserforge 1.2.x).
_BF_NPM_PACKAGES = {
    "headers": ("header-generator", "2.1.87"),
    "fingerprints": ("fingerprint-generator", "2.1.87"),
}
# Official npm registry first, China mirror as fallback.
_BF_NPM_MIRRORS = (
    "https://registry.npmjs.org",
    "https://registry.npmmirror.com",
)
_BF_NPM_TIMEOUT = 30


def _browserforge_root() -> str | None:
    """Return the installed browserforge package directory, or None."""
    spec = importlib.util.find_spec("browserforge")
    if spec is None or not spec.submodule_search_locations:
        return None
    return next(iter(spec.submodule_search_locations))


def _bf_data_complete(root: str) -> bool:
    """True when every required model data file is already present."""
    for kind, files in _BF_DATA_FILES.items():
        for local in files:
            if not os.path.exists(os.path.join(root, kind, "data", local)):
                return False
    return True


def _fetch_npm_data_files(pkg: str, version: str) -> dict[str, bytes]:
    """Download an npm tarball and return its ``data_files`` by basename.

    Tries each mirror in turn; a short timeout keeps the fallback prompt when
    the primary registry is unreachable.
    """
    last_error: Exception | None = None
    for mirror in _BF_NPM_MIRRORS:
        url = f"{mirror}/{pkg}/-/{pkg}-{version}.tgz"
        try:
            with urllib.request.urlopen(url, timeout=_BF_NPM_TIMEOUT) as resp:
                blob = resp.read()
            extracted: dict[str, bytes] = {}
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
                for member in tar.getmembers():
                    if "/data_files/" in member.name and member.isfile():
                        handle = tar.extractfile(member)
                        if handle is not None:
                            extracted[os.path.basename(member.name)] = handle.read()
            if extracted:
                return extracted
            last_error = RuntimeError(f"no data_files found in {pkg} tarball")
        except Exception as exc:  # try next mirror
            last_error = exc
    raise last_error  # type: ignore[misc]


def ensure_browserforge_data() -> None:
    """Ensure browserforge model data files exist, fetching from npm if missing.

    No-op when browserforge is absent or the data is already present. Network
    failures only log a warning (stealth mode would then fail at runtime, but
    basic mode keeps working), mirroring :func:`ensure_browsers_installed`.
    """
    root = _browserforge_root()
    if root is None or _bf_data_complete(root):
        return
    logger.info("browserforge model data missing, fetching from npm registry...")
    try:
        bundles = {
            kind: _fetch_npm_data_files(pkg, version)
            for kind, (pkg, version) in _BF_NPM_PACKAGES.items()
        }
    except Exception as exc:
        logger.warning("Could not fetch browserforge data: %s", exc)
        return
    placed = 0
    for kind, files in _BF_DATA_FILES.items():
        dest = os.path.join(root, kind, "data")
        os.makedirs(dest, exist_ok=True)
        for local, remote in files.items():
            blob = bundles[kind].get(remote)
            if blob is None:
                continue
            try:
                with open(os.path.join(dest, local), "wb") as handle:
                    handle.write(blob)
                placed += 1
            except OSError as exc:
                logger.warning("Could not write browserforge data %s: %s", local, exc)
    if placed:
        logger.info("browserforge model data ready (%d files)", placed)
    else:
        logger.warning("browserforge data unavailable; stealth mode may fail")


# ---------------------------------------------------------------------------
# camoufox stealth browser binaries
# ---------------------------------------------------------------------------
# Camoufox (a modified Firefox used by stealth/max-stealth modes) is fetched
# on demand via ``python -m camoufox fetch`` from the daijro/camoufox GitHub
# releases. Without it, importing camoufox fails on a missing version.json.
# We trigger the fetch only when the version marker is absent, so the large
# (~100 MB+) download runs once and an already-installed server starts
# without hitting the network.

_CAMOUFOX_FETCH_TIMEOUT = 600  # Firefox build is large; allow ample time.


def _camoufox_installed() -> bool | None:
    """Return True when a usable camoufox browser install exists.

    None means camoufox is not installed as a dependency (nothing to ensure).
    camoufox >= 0.5 keeps browsers in versioned subdirectories under
    ``browsers/<repo>/<version>`` (each with its own version.json) and never
    writes version.json at the INSTALL_DIR root, so checking that legacy
    path alone made every start re-run ``camoufox fetch``. Ask the multiversion
    manager for the active install first, then fall back to the legacy layout.
    """
    try:
        import camoufox.pkgman as _pkgman
    except ImportError:
        return None
    try:
        from camoufox.multiversion import get_active_path

        if get_active_path() is not None:
            return True
    except ImportError:
        pass
    return os.path.exists(os.path.join(str(_pkgman.INSTALL_DIR), "version.json"))


def ensure_camoufox() -> None:
    """Ensure camoufox stealth browser binaries are installed.

    Runs ``python -m camoufox fetch`` when no install is found.
    camoufox's own fetch is idempotent, but we gate it locally so an
    already-installed server starts without a network round-trip. Failures
    only warn; basic mode is unaffected.
    """
    if _camoufox_installed() is not False:
        return
    logger.info("camoufox browser not found, fetching (first run downloads ~100 MB+)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "camoufox", "fetch"],
            capture_output=True,
            text=True,
            timeout=_CAMOUFOX_FETCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("camoufox fetch timed out after %d s", _CAMOUFOX_FETCH_TIMEOUT)
        return
    except Exception as exc:  # noqa: BLE001 - keep server starting
        logger.warning("Failed to run camoufox fetch: %s", exc)
        return
    # camoufox >= 0.5 may exit 0 even when the download failed mid-way, so
    # verify the install state instead of trusting the return code.
    if _camoufox_installed():
        logger.info("camoufox browser ready")
    else:
        logger.warning(
            "camoufox fetch failed (exit %d): %s",
            result.returncode,
            (result.stderr or "").strip()[:300],
        )
