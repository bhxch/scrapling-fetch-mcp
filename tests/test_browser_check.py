"""Tests for browser/browserforge data bootstrapping in _browser_check.py."""
import io
import tarfile
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from scrapling_fetch_mcp._browser_check import (
    _BF_DATA_FILES,
    _bf_data_complete,
    _browserforge_root,
    _fetch_npm_data_files,
    ensure_browserforge_data,
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
