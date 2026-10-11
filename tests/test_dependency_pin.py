"""Regression guards for the deliberately capped engine dependencies.

Two upstream releases break this fork and are capped in pyproject.toml:

- scrapling 0.3.7+ ships engines that import patchright at module level
  (from 0.3.13 it sits on the stealth fetcher chain), and 0.4.x goes
  further: unconditional patchright imports while declaring it only in
  the optional [fetchers] extra, camoufox engine removed. The fork covers
  fetcher dependencies itself and deliberately does not declare
  patchright, so anything above 0.3.6 breaks fetch modes at import time.
- camoufox 0.5.x drops the launch kwargs scrapling 0.3.x passes through
  (stealth fetch dies inside launch_persistent_context with
  "unexpected keyword argument 'allow_webgl'") and switches to a new,
  incompatible ~/.cache/camoufox layout.

These tests keep both pins from being dropped or resolved away.
"""
import tomllib
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_scrapling_requirement_is_pinned_to_036():
    """pyproject must keep scrapling on the verified 0.3.6 line."""
    assert "<0.3.7" in _requirement_specifier("scrapling")


def test_camoufox_requirement_is_capped_below_05():
    """pyproject must keep the <0.5 ceiling on camoufox."""
    assert "<0.5" in _requirement_specifier("camoufox")


def _requirement_specifier(name: str) -> str:
    data = tomllib.loads(PYPROJECT.read_text())
    requirements = [
        Requirement(dep)
        for dep in data["project"]["dependencies"]
        if Requirement(dep).name == name
    ]
    assert len(requirements) == 1, f"{name} should be declared exactly once"
    return str(requirements[0].specifier)


def test_installed_scrapling_stays_on_036():
    """The resolved environment must never pick up scrapling 0.3.7+."""
    installed = Version(version("scrapling"))
    assert installed < Version("0.3.7"), installed


def test_installed_camoufox_stays_below_05():
    """The resolved environment must never pick up a camoufox 0.5.x."""
    installed = Version(version("camoufox"))
    assert installed < Version("0.5"), installed


def test_fetchers_import_without_patchright():
    """The import path that breaks under 0.4.x must stay usable in this
    environment, whose dependency set intentionally has no patchright."""
    if find_spec("patchright") is not None:
        pytest.skip("patchright is installed; the guard is only meaningful without it")
    from scrapling.fetchers import AsyncFetcher  # noqa: F401
