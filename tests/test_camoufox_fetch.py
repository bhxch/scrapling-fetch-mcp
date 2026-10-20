"""Resumable camoufox browser downloader (_camoufox_fetch.py) 的单元测试。

网络层打桩:urlopen 返回脚本化的 FakeResponse(chunks 可在流中抛
TimeoutError 模拟停滞);camoufox.pkgman 以 stub 模块注入 sys.modules,
无需真实安装与网络。
"""
import io
import sys
import types
import urllib.error
from zipfile import ZipFile, ZipInfo

import pytest

from scrapling_fetch_mcp import _camoufox_fetch as cf

URL = "https://example.org/camoufox-1.0-beta.1-lin.x86_64.zip"
PART_NAME = "camoufox-1.0-beta.1-lin.x86_64.zip.part"


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr(ZipInfo("camoufox/camoufox-bin"), b"\x7fELF fake browser")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, status=200, chunks=(), headers=None):
        self.status = status
        self._chunks = iter(chunks)
        self.headers = headers or {}

    def read(self, n):
        try:
            return next(self._chunks)
        except StopIteration:
            return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _stall_stream(*chunks):
    """吐完 chunks 后连接停滞(socket 读超时)。"""
    def gen():
        yield from chunks
        raise TimeoutError("simulated stall")
    return gen()


def _patch_urlopen(monkeypatch, responses):
    calls = []
    stream = iter(responses)

    def fake_urlopen(request, timeout=None):
        calls.append({"range": request.get_header("Range"), "timeout": timeout})
        result = next(stream)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cf.urllib.request, "urlopen", fake_urlopen)
    return calls


@pytest.fixture
def install_env(monkeypatch, tmp_path):
    """stub camoufox.pkgman:INSTALL_DIR 指向 tmp,Fetcher 记录安装调用。"""
    install_dir = tmp_path / "camoufox"
    calls = []

    class StubFetcher:
        def __init__(self):
            self.url = URL

        def cleanup(self):
            calls.append("cleanup")

        def extract_zip(self, fh):
            calls.append(("extract", fh.read()))

        def set_version(self):
            calls.append("set_version")

    stub = types.ModuleType("camoufox.pkgman")
    stub.CamoufoxFetcher = StubFetcher
    stub.INSTALL_DIR = install_dir
    monkeypatch.setitem(sys.modules, "camoufox.pkgman", stub)
    return install_dir, tmp_path / "camoufox-fetch" / PART_NAME, calls


def test_full_download_and_install(install_env, monkeypatch):
    install_dir, part, calls = install_env
    data = _zip_bytes()
    calls_log = _patch_urlopen(
        monkeypatch,
        [FakeResponse(200, [data[:4], data[4:]], {"Content-Length": str(len(data))})],
    )

    cf.fetch_camoufox_browser()

    assert calls_log[0]["range"] is None  # 首次不带 Range
    assert calls == ["cleanup", ("extract", data), "set_version"]
    assert not part.exists()  # 安装成功后断点文件清除


def test_resume_from_existing_part(install_env, monkeypatch):
    install_dir, part, _ = install_env
    data = _zip_bytes()
    part.parent.mkdir(parents=True)
    part.write_bytes(data[:6])
    calls_log = _patch_urlopen(
        monkeypatch,
        [
            FakeResponse(
                206,
                [data[6:]],
                {"Content-Range": f"bytes 6-{len(data) - 1}/{len(data)}"},
            )
        ],
    )

    result = cf.download_release_zip(URL, install_dir)

    assert calls_log[0]["range"] == "bytes=6-"
    assert result.read_bytes() == data


def test_stall_retries_from_resume_point(install_env, monkeypatch, caplog):
    install_dir, part, _ = install_env
    data = _zip_bytes()
    calls_log = _patch_urlopen(
        monkeypatch,
        [
            # 第一次尝试:收到 5 字节后连接停滞
            FakeResponse(
                200, _stall_stream(data[:5]), {"Content-Length": str(len(data))}
            ),
            # 第二次尝试:从断点续传到完成
            FakeResponse(
                206,
                [data[5:]],
                {"Content-Range": f"bytes 5-{len(data) - 1}/{len(data)}"},
            ),
        ],
    )

    result = cf.download_release_zip(URL, install_dir)

    assert len(calls_log) == 2
    assert calls_log[1]["range"] == "bytes=5-"
    assert result.read_bytes() == data
    assert any("stalled or interrupted" in r.message for r in caplog.records)


def test_server_ignoring_range_restarts_from_scratch(install_env, monkeypatch):
    install_dir, part, _ = install_env
    data = _zip_bytes()
    part.parent.mkdir(parents=True)
    part.write_bytes(b"stale")
    _patch_urlopen(
        monkeypatch,
        [FakeResponse(200, [data], {"Content-Length": str(len(data))})],
    )

    result = cf.download_release_zip(URL, install_dir)

    # 服务端无视 Range 返回 200:旧断点被清空后按完整响应重写
    assert result.read_bytes() == data


def test_attempts_exhausted_raises_and_keeps_part(install_env, monkeypatch):
    install_dir, part, _ = install_env
    calls_log = _patch_urlopen(
        monkeypatch,
        [
            FakeResponse(200, _stall_stream(b"x" * 3), {"Content-Length": "100"}),
            FakeResponse(
                206, _stall_stream(b"y" * 4), {"Content-Range": "bytes 3-99/100"}
            ),
            FakeResponse(
                206, _stall_stream(b"z" * 5), {"Content-Range": "bytes 7-99/100"}
            ),
        ],
    )

    with pytest.raises(RuntimeError, match="incomplete after 3 attempts: 12/100"):
        cf.download_release_zip(URL, install_dir, max_attempts=3)

    assert len(calls_log) == 3
    assert calls_log[1]["range"] == "bytes=3-"  # 每次重试都从断点续传
    assert calls_log[2]["range"] == "bytes=7-"
    assert part.exists() and part.stat().st_size == 12  # 断点累积保留


def test_corrupt_complete_zip_discards_part(install_env, monkeypatch):
    install_dir, part, _ = install_env
    data = b"GARBAGE_NOT_A_ZIP!"
    _patch_urlopen(
        monkeypatch,
        [FakeResponse(200, [data], {"Content-Length": str(len(data))})],
    )

    with pytest.raises(RuntimeError, match="not a valid zip"):
        cf.download_release_zip(URL, install_dir)

    assert not part.exists()  # 坏缓存不留,避免永久卡死


def test_unknown_total_clean_stream_end_ok(install_env, monkeypatch):
    install_dir, part, _ = install_env
    data = _zip_bytes()
    _patch_urlopen(monkeypatch, [FakeResponse(200, [data[:5], data[5:]])])

    result = cf.download_release_zip(URL, install_dir)

    assert result.read_bytes() == data


def test_416_treated_as_complete(install_env, monkeypatch):
    """断点恰好等于总大小时续传请求会 416:应视为已下完,交给 zip 校验。"""
    install_dir, part, _ = install_env
    data = _zip_bytes()
    part.parent.mkdir(parents=True)
    part.write_bytes(data)
    calls_log = _patch_urlopen(
        monkeypatch,
        [urllib.error.HTTPError(URL, 416, "Range Not Satisfiable", None, io.BytesIO())],
    )

    result = cf.download_release_zip(URL, install_dir)

    assert calls_log[0]["range"] == f"bytes={len(data)}-"
    assert result.read_bytes() == data


def test_stale_parts_pruned(install_env, monkeypatch):
    install_dir, part, _ = install_env
    data = _zip_bytes()
    part.parent.mkdir(parents=True)
    stale = part.parent / "camoufox-0.9-old-lin.x86_64.zip.part"
    stale.write_bytes(b"old release leftovers")
    _patch_urlopen(
        monkeypatch,
        [FakeResponse(200, [data], {"Content-Length": str(len(data))})],
    )

    cf.download_release_zip(URL, install_dir)

    assert not stale.exists()
    assert part.exists()
