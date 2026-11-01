"""Import 边界守卫（Task 9）：前端 `scrapling_fetch_mcp.mcp` 保持瘦 import。

stdio/streamable-http 前端只保留 MCP SDK + 工具 schema + BackendClient；
trafilatura/numpy/onnxruntime/playwright/camoufox 等重依赖与项目内重模块
（``_fetcher``/``_scrapling``/``_extractor_strategy``）只允许出现在 daemon
进程。子进程干净探针防止回归。
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

HEAVY = (
    "trafilatura",
    "markitdown",
    "numpy",
    "onnxruntime",
    "playwright",
    "camoufox",
    "scrapling.fetchers",
    "scrapling_fetch_mcp._fetcher",
    "scrapling_fetch_mcp._scrapling",
    "scrapling_fetch_mcp._extractor_strategy",
)


def test_frontend_import_stays_thin():
    code = (
        "import sys; import scrapling_fetch_mcp.mcp; "
        "bad=[m for m in %r for k in sys.modules if k == m or k.startswith(m + '.')]; "
        "raise SystemExit('heavy: ' + ','.join(bad) if bad else 0)"
    ) % (HEAVY,)
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert r.returncode == 0, r.stdout + r.stderr
