"""Tests for browser/browserforge data bootstrapping in _browser_check.py."""
import io
import subprocess
import sys
import tarfile
import types
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scrapling_fetch_mcp._browser_check import (
    _BF_DATA_FILES,
    _bf_data_complete,
    _browserforge_root,
    _camoufox_supported,
    _fetch_npm_data_files,
    ensure_browserforge_data,
    ensure_camoufox,
)


def _make_tgz(files: dict[str, bytes]) -> bytes:
    """Build an in-memory .tgz with the given member paths -> contents."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _url_mock(tgz: bytes) -> MagicMock:
    cm = MagicMock()
    cm.__enter__.return_value.read.return_value = tgz
    return cm


class TestBrowserforgeRoot:
    def test_returns_none_when_not_installed(self):
        with patch(
            "scrapling_fetch_mcp._browser_check.importlib.util.find_spec",
            return_value=None,
        ):
            assert _browserforge_root() is None

    def test_returns_path_when_installed(self, tmp_path):
        spec = MagicMock()
        spec.submodule_search_locations = (str(tmp_path),)
        with patch(
            "scrapling_fetch_mcp._browser_check.importlib.util.find_spec",
            return_value=spec,
        ):
            assert _browserforge_root() == str(tmp_path)


class TestFetchNpmDataFiles:
    def test_extracts_data_files_only(self):
        tgz = _make_tgz(
            {
                "package/src/data_files/input-network-definition.zip": b"NET",
                "package/src/data_files/headers-order.json": b"{}",
                "package/package.json": b'{"name": "header-generator"}',
                "package/dist/index.js": b"console.log(1)",
            }
        )
        with patch(
            "scrapling_fetch_mcp._browser_check.urllib.request.urlopen",
            return_value=_url_mock(tgz),
        ) as mock_open:
            result = _fetch_npm_data_files("header-generator", "2.1.87")
        assert result == {
            "input-network-definition.zip": b"NET",
            "headers-order.json": b"{}",
        }
        # primary mirror (official npm) is tried first
        assert mock_open.call_args.args[0].startswith("https://registry.npmjs.org/")

    def test_falls_back_to_second_mirror(self):
        good = _make_tgz({"pkg/src/data_files/x.zip": b"D"})
        with patch(
            "scrapling_fetch_mcp._browser_check.urllib.request.urlopen",
            side_effect=[urllib.error.URLError("boom"), _url_mock(good)],
        ) as mock_open:
            result = _fetch_npm_data_files("header-generator", "2.1.87")
        assert result == {"x.zip": b"D"}
        assert mock_open.call_count == 2
        assert mock_open.call_args_list[0].args[0].startswith(
            "https://registry.npmjs.org/"
        )
        assert mock_open.call_args_list[1].args[0].startswith(
            "https://registry.npmmirror.com/"
        )

    def test_raises_when_all_mirrors_fail(self):
        with patch(
            "scrapling_fetch_mcp._browser_check.urllib.request.urlopen",
            side_effect=urllib.error.URLError("down"),
        ):
            with pytest.raises(urllib.error.URLError):
                _fetch_npm_data_files("header-generator", "2.1.87")


class TestEnsureBrowserforgeData:
    def test_noop_when_browserforge_absent(self):
        with patch(
            "scrapling_fetch_mcp._browser_check._browserforge_root",
            return_value=None,
        ), patch(
            "scrapling_fetch_mcp._browser_check._fetch_npm_data_files"
        ) as mock_fetch:
            ensure_browserforge_data()
        mock_fetch.assert_not_called()

    def test_noop_when_data_already_complete(self, tmp_path):
        # Pre-create every required file so the tree looks complete.
        for kind, files in _BF_DATA_FILES.items():
            d = tmp_path / kind / "data"
            d.mkdir(parents=True)
            for local in files:
                (d / local).write_bytes(b"exists")

        with patch(
            "scrapling_fetch_mcp._browser_check._browserforge_root",
            return_value=str(tmp_path),
        ), patch(
            "scrapling_fetch_mcp._browser_check._fetch_npm_data_files"
        ) as mock_fetch:
            ensure_browserforge_data()
        mock_fetch.assert_not_called()
        assert _bf_data_complete(str(tmp_path))

    def test_fetches_and_writes_when_missing(self, tmp_path):
        # Build a remote bundle keyed by the *remote* (definition) filenames.
        remote_bundles = {
            "headers": {
                "input-network-definition.zip": b"IN",
                "header-network-definition.zip": b"HN",
                "browser-helper-file.json": b"{}",
                "headers-order.json": b"[]",
            },
            "fingerprints": {
                "fingerprint-network-definition.zip": b"FN",
            },
        }

        def fake_fetch(pkg, version):
            if pkg == "header-generator":
                return remote_bundles["headers"]
            return remote_bundles["fingerprints"]

        with patch(
            "scrapling_fetch_mcp._browser_check._browserforge_root",
            return_value=str(tmp_path),
        ), patch(
            "scrapling_fetch_mcp._browser_check._fetch_npm_data_files",
            side_effect=fake_fetch,
        ) as mock_fetch:
            ensure_browserforge_data()

        # both npm packages were queried
        called_pkgs = [call.args[0] for call in mock_fetch.call_args_list]
        assert called_pkgs == ["header-generator", "fingerprint-generator"]
        # files were written with the *local* names, remapped from remote names
        assert (
            tmp_path / "headers" / "data" / "input-network.zip"
        ).read_bytes() == b"IN"
        assert (
            tmp_path / "headers" / "data" / "header-network.zip"
        ).read_bytes() == b"HN"
        assert (
            tmp_path / "fingerprints" / "data" / "fingerprint-network.zip"
        ).read_bytes() == b"FN"
        assert _bf_data_complete(str(tmp_path))

    def test_only_warns_when_fetch_fails(self, tmp_path, caplog):
        with patch(
            "scrapling_fetch_mcp._browser_check._browserforge_root",
            return_value=str(tmp_path),
        ), patch(
            "scrapling_fetch_mcp._browser_check._fetch_npm_data_files",
            side_effect=urllib.error.URLError("offline"),
        ):
            # Must not raise: basic mode must still be able to start.
            ensure_browserforge_data()
        assert any(
            "Could not fetch browserforge data" in r.message for r in caplog.records
        )


class TestCamoufoxSupported:
    @staticmethod
    def _fake_pkgman(from_path):
        return types.SimpleNamespace(
            INSTALL_DIR=Path("/fake/camoufox"),
            Version=types.SimpleNamespace(from_path=from_path),
        )

    @staticmethod
    def _pin_legacy_layout(monkeypatch):
        # Force the legacy branch even if the venv's camoufox ships a
        # multiversion module later (None makes the import raise ImportError).
        monkeypatch.setitem(sys.modules, "camoufox.multiversion", None)

    def test_true_when_version_supported(self, monkeypatch):
        version = types.SimpleNamespace(is_supported=lambda: True)
        from_path = MagicMock(return_value=version)
        self._pin_legacy_layout(monkeypatch)
        with patch(
            "scrapling_fetch_mcp._browser_check._import_camoufox_pkgman",
            return_value=self._fake_pkgman(from_path),
        ):
            assert _camoufox_supported() is True
        from_path.assert_called_once_with(Path("/fake/camoufox"))

    def test_false_when_marker_missing(self, monkeypatch):
        from_path = MagicMock(side_effect=FileNotFoundError("no version.json"))
        self._pin_legacy_layout(monkeypatch)
        with patch(
            "scrapling_fetch_mcp._browser_check._import_camoufox_pkgman",
            return_value=self._fake_pkgman(from_path),
        ):
            assert _camoufox_supported() is False

    def test_false_when_marker_corrupt(self, monkeypatch):
        from_path = MagicMock(side_effect=ValueError("bad json"))
        self._pin_legacy_layout(monkeypatch)
        with patch(
            "scrapling_fetch_mcp._browser_check._import_camoufox_pkgman",
            return_value=self._fake_pkgman(from_path),
        ):
            assert _camoufox_supported() is False

    def test_none_when_pkgman_not_installed(self, monkeypatch):
        # None in sys.modules makes `import camoufox.pkgman` raise ImportError.
        monkeypatch.setitem(sys.modules, "camoufox.pkgman", None)
        assert _camoufox_supported() is None

    def test_true_when_multiversion_active(self, monkeypatch, tmp_path):
        active = tmp_path / "browsers" / "official" / "152.0.4"
        active.mkdir(parents=True)
        (active / "version.json").write_text("{}")
        multiversion = types.ModuleType("camoufox.multiversion")
        multiversion.get_active_path = lambda: active
        monkeypatch.setitem(sys.modules, "camoufox.multiversion", multiversion)
        with patch(
            "scrapling_fetch_mcp._browser_check._import_camoufox_pkgman",
            return_value=types.SimpleNamespace(INSTALL_DIR=tmp_path),
        ):
            assert _camoufox_supported() is True

    def test_false_when_multiversion_reports_no_active(self, monkeypatch, tmp_path):
        multiversion = types.ModuleType("camoufox.multiversion")
        multiversion.get_active_path = lambda: None
        monkeypatch.setitem(sys.modules, "camoufox.multiversion", multiversion)
        with patch(
            "scrapling_fetch_mcp._browser_check._import_camoufox_pkgman",
            return_value=types.SimpleNamespace(INSTALL_DIR=tmp_path),
        ):
            assert _camoufox_supported() is False


class TestEnsureCamoufox:
    """ensure_camoufox 只负责拉起后台线程,自身绝不阻塞调用方"""

    @pytest.fixture(autouse=True)
    def _reset_fetch_state(self):
        from scrapling_fetch_mcp import _browser_check as mod

        mod._camoufox_fetch_thread = None
        mod._camoufox_fetch_state = "idle"
        yield
        mod._camoufox_fetch_thread = None
        mod._camoufox_fetch_state = "idle"

    def test_noop_when_camoufox_absent(self):
        with patch(
            "scrapling_fetch_mcp._browser_check._camoufox_supported",
            return_value=None,
        ), patch(
            "scrapling_fetch_mcp._browser_check.threading.Thread"
        ) as mock_thread:
            ensure_camoufox()
        mock_thread.assert_not_called()

    def test_noop_when_installed_version_supported(self):
        with patch(
            "scrapling_fetch_mcp._browser_check._camoufox_supported",
            return_value=True,
        ), patch(
            "scrapling_fetch_mcp._browser_check.threading.Thread"
        ) as mock_thread:
            ensure_camoufox()
        mock_thread.assert_not_called()

    def test_spawns_daemon_thread_when_missing(self):
        from scrapling_fetch_mcp import _browser_check as mod

        with patch(
            "scrapling_fetch_mcp._browser_check._camoufox_supported",
            return_value=False,
        ), patch(
            "scrapling_fetch_mcp._browser_check.threading.Thread"
        ) as mock_thread, patch(
            "scrapling_fetch_mcp._browser_check.subprocess.run"
        ) as mock_run:
            ensure_camoufox()
        mock_run.assert_not_called()  # 启动路径同步零下载
        mock_thread.assert_called_once_with(
            target=mod._run_camoufox_fetch, name="camoufox-fetch", daemon=True
        )
        mock_thread.return_value.start.assert_called_once()

    def test_no_second_thread_while_download_in_flight(self):
        from scrapling_fetch_mcp import _browser_check as mod

        living = MagicMock()
        living.is_alive.return_value = True
        mod._camoufox_fetch_thread = living
        with patch(
            "scrapling_fetch_mcp._browser_check._camoufox_supported",
            return_value=False,
        ), patch(
            "scrapling_fetch_mcp._browser_check.threading.Thread"
        ) as mock_thread:
            ensure_camoufox()
        mock_thread.assert_not_called()


class TestRunCamoufoxFetch:
    """后台线程 worker 的同步行为:状态机 + 日志"""

    @pytest.fixture(autouse=True)
    def _reset_fetch_state(self):
        from scrapling_fetch_mcp import _browser_check as mod

        mod._camoufox_fetch_state = "idle"
        yield
        mod._camoufox_fetch_state = "idle"

    @staticmethod
    def _run(supported_side_effects, run_result=None, run_side_effect=None):
        from scrapling_fetch_mcp import _browser_check as mod

        kwargs = {"side_effect": run_side_effect} if run_side_effect else {
            "return_value": run_result
        }
        with patch(
            "scrapling_fetch_mcp._browser_check._camoufox_supported",
            side_effect=supported_side_effects,
        ), patch(
            "scrapling_fetch_mcp._browser_check.subprocess.run", **kwargs
        ) as mock_run:
            mod._run_camoufox_fetch()
        return mock_run

    def test_success_marks_ready(self, caplog):
        success = subprocess.CompletedProcess(args=[], returncode=0)
        mock_run = self._run([True], run_result=success)  # 仅抓取后校验一次
        assert mock_run.call_args.args[0][-2:] == ["camoufox", "fetch"]
        from scrapling_fetch_mcp import _browser_check as mod

        assert mod.camoufox_fetch_state() == "ready"

    def test_exit_zero_but_no_usable_install_marks_failed(self, caplog):
        # camoufox >= 0.5 exits 0 even when the download failed mid-way.
        fake_success = subprocess.CompletedProcess(args=[], returncode=0)
        self._run([False], run_result=fake_success)
        from scrapling_fetch_mcp import _browser_check as mod

        assert mod.camoufox_fetch_state() == "failed"
        assert any("produced no usable install" in r.message for r in caplog.records)

    def test_nonzero_exit_marks_failed(self, caplog):
        failure = subprocess.CompletedProcess(
            args=[], returncode=1, stderr="network error"
        )
        self._run([False], run_result=failure)
        from scrapling_fetch_mcp import _browser_check as mod

        assert mod.camoufox_fetch_state() == "failed"
        assert any("network error" in r.message for r in caplog.records)

    def test_timeout_marks_failed(self, caplog):
        self._run(
            [False],
            run_side_effect=subprocess.TimeoutExpired(cmd="camoufox", timeout=1),
        )
        from scrapling_fetch_mcp import _browser_check as mod

        assert mod.camoufox_fetch_state() == "failed"
        assert any("timed out" in r.message for r in caplog.records)

    def test_spawn_failure_marks_failed(self, caplog):
        self._run([False], run_side_effect=OSError("no camoufox module"))
        from scrapling_fetch_mcp import _browser_check as mod

        assert mod.camoufox_fetch_state() == "failed"
        assert any("Failed to run camoufox fetch" in r.message for r in caplog.records)


class TestResolveStealthDegradation:
    """stealth 请求在浏览器未就绪时降级 basic 并给出原因"""

    @staticmethod
    def _resolve(monkeypatch, supported, state, mode):
        import scrapling_fetch_mcp._browser_check as mod

        monkeypatch.setattr(mod, "_camoufox_supported", lambda: supported)
        monkeypatch.setattr(mod, "camoufox_fetch_state", lambda: state)
        return mod.resolve_stealth_degradation(mode)

    def test_basic_passes_through(self, monkeypatch):
        assert self._resolve(monkeypatch, False, "downloading", "basic") == (
            "basic",
            None,
        )

    def test_stealth_untouched_when_browser_usable(self, monkeypatch):
        assert self._resolve(monkeypatch, True, "ready", "stealth") == ("stealth", None)
        assert self._resolve(monkeypatch, True, "ready", "max-stealth") == (
            "max-stealth",
            None,
        )

    def test_stealth_degrades_while_downloading(self, monkeypatch):
        mode, note = self._resolve(monkeypatch, False, "downloading", "stealth")
        assert mode == "basic"
        assert "后台下载" in note

    def test_stealth_degrades_when_unavailable(self, monkeypatch):
        for state in ("idle", "failed"):
            mode, note = self._resolve(monkeypatch, False, state, "max-stealth")
            assert mode == "basic"
            assert "不可用" in note
