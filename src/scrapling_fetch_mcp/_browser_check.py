import importlib.util
import io
import logging
import os
import subprocess
import sys
import tarfile
import threading
import urllib.request

logger = logging.getLogger("scrapling_fetch_mcp")


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
    basic mode keeps working), mirroring :func:`ensure_camoufox`.
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
# releases. Without it, scrapling's stealth engines fail on the missing
# version.json. We trigger the fetch when no usable install is found: either
# the marker is absent, or its version falls outside the range the installed
# camoufox package supports (e.g. after a package upgrade). camoufox >= 0.5
# keeps browsers in versioned subdirectories under ``browsers/<repo>/<version>``
# and never writes version.json at the INSTALL_DIR root, so the multiversion
# manager is asked for the active install before falling back to the legacy
# layout. The ~1.2 GB download runs in a background thread so a fresh
# install never blocks startup; until it lands, stealth requests degrade to
# basic via :func:`resolve_stealth_degradation`.

# Background-download safety net only: nothing waits on it, so a generous
# limit just reaps a wedged fetch (the download has no resume support).
_CAMOUFOX_FETCH_TIMEOUT = 1800

# Fetch lifecycle: "idle" (never needed), "downloading", "ready", "failed".
_camoufox_fetch_state = "idle"
_camoufox_fetch_lock = threading.Lock()
_camoufox_fetch_thread: threading.Thread | None = None


def camoufox_fetch_state() -> str:
    """Current stealth-browser download lifecycle (see module constants)."""
    with _camoufox_fetch_lock:
        return _camoufox_fetch_state


def _set_camoufox_fetch_state(state: str) -> None:
    global _camoufox_fetch_state
    with _camoufox_fetch_lock:
        _camoufox_fetch_state = state


def _import_camoufox_pkgman():
    """Return ``camoufox.pkgman``, or None when camoufox is not installed."""
    try:
        import camoufox.pkgman as _pkgman
    except ImportError:
        return None
    return _pkgman


def _camoufox_supported() -> bool | None:
    """Whether the installed camoufox browser is usable, or None if unknown.

    None means camoufox is not installed as a dependency (nothing to ensure).
    False covers a missing install and legacy-layout markers outside the
    range the installed camoufox package supports — both must refetch;
    otherwise scrapling's stealth engines break at runtime instead.
    """
    pkgman = _import_camoufox_pkgman()
    if pkgman is None:
        return None
    try:
        from camoufox.multiversion import get_active_path
    except ImportError:
        # Legacy layout (camoufox < 0.5): version.json at the INSTALL_DIR root.
        try:
            return pkgman.Version.from_path(pkgman.INSTALL_DIR).is_supported()
        except Exception:  # noqa: BLE001 - missing/corrupt marker => refetch
            return False
    # Multiversion layout (camoufox >= 0.5): the manager resolves the active
    # versioned install itself; presence means usable.
    try:
        return get_active_path() is not None
    except Exception:  # noqa: BLE001 - broken manager state => refetch
        return False


def _run_camoufox_fetch() -> None:
    """Blocking camoufox fetch worker; runs on the background thread only.

    Runs ``python -m camoufox fetch`` and verifies the install state instead
    of trusting the return code (camoufox >= 0.5 may exit 0 even when the
    download failed mid-way). Never raises: failures end in the "failed"
    state and a warning, leaving basic mode unaffected.
    """
    _set_camoufox_fetch_state("downloading")
    logger.info("camoufox browser missing or outdated, fetching (~1.2 GB)...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "camoufox", "fetch"],
            capture_output=True,
            text=True,
            timeout=_CAMOUFOX_FETCH_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("camoufox fetch timed out after %d s", _CAMOUFOX_FETCH_TIMEOUT)
        _set_camoufox_fetch_state("failed")
        return
    except Exception as exc:  # noqa: BLE001 - keep server serving
        logger.warning("Failed to run camoufox fetch: %s", exc)
        _set_camoufox_fetch_state("failed")
        return
    if _camoufox_supported():
        logger.info("camoufox browser ready")
        _set_camoufox_fetch_state("ready")
    else:
        logger.warning(
            "camoufox fetch produced no usable install (exit %d): %s",
            result.returncode,
            (result.stderr or "").strip()[:300],
        )
        _set_camoufox_fetch_state("failed")


def ensure_camoufox() -> None:
    """Ensure camoufox stealth browser binaries are installed and supported.

    When no usable install is found — the browser is missing or its version
    no longer matches the camoufox package's supported range — the fetch is
    started on a daemon thread and this returns immediately, so a fresh
    install never delays server startup. Requests that ask for stealth
    degrade to basic (see :func:`resolve_stealth_degradation`) until the
    download lands. Failures only warn; basic mode is unaffected.
    """
    global _camoufox_fetch_thread
    supported = _camoufox_supported()
    if supported is None or supported:
        return
    logger.info("camoufox browser missing, downloading in background (~1.2 GB)...")
    with _camoufox_fetch_lock:
        if _camoufox_fetch_thread is not None and _camoufox_fetch_thread.is_alive():
            return
        _camoufox_fetch_thread = threading.Thread(
            target=_run_camoufox_fetch, name="camoufox-fetch", daemon=True
        )
        _camoufox_fetch_thread.start()


def resolve_stealth_degradation(mode: str) -> tuple[str, str | None]:
    """Degrade stealth/max-stealth to basic when the browser is not usable.

    Returns ``(mode, None)`` untouched for basic requests or a usable browser.
    Otherwise returns ``("basic", reason)`` — the reason is meant for the
    tool's METADATA so callers know the response came from the lighter engine
    and why. Covers both the download-in-progress window and a permanently
    missing/failed browser (which would otherwise surface as an opaque
    scrapling launch error).
    """
    if mode not in ("stealth", "max-stealth"):
        return mode, None
    if _camoufox_supported():
        return mode, None
    if camoufox_fetch_state() == "downloading":
        return "basic", (
            "已降级为 basic 模式：stealth 浏览器 camoufox（约 1.2 GB）正在后台下载，"
            "完成后 stealth 请求自动恢复"
        )
    return "basic", (
        "已降级为 basic 模式：stealth 浏览器 camoufox 不可用（未下载或后台下载失败），"
        "反爬站点的抓取效果可能下降"
    )
