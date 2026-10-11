"""Regression guards for the deliberately capped engine dependencies.

Two upstream releases break this fork and are capped in pyproject.toml:

- scrapling 0.4.x imports patchright unconditionally at module level while
  declaring it only in the optional [fetchers] extra, and drops the
  camoufox engine. The fork covers fetcher dependencies itself and
  deliberately does not declare patchright, so a 0.4.x resolve breaks
  every fetch mode (basic included) with ModuleNotFoundError.
- camoufox 0.5.x drops the launch kwargs scrapling 0.3.x passes through
  (stealth fetch dies inside launch_persistent_context with
  "unexpected keyword argument 'allow_webgl'") and switches to a new,
  incompatible ~/.cache/camoufox layout.

These tests keep both ceilings from being dropped or resolved away.
"""
import tomllib
from importlib.metadata import version
from importlib.util import find_spec
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_scrapling_requirement_is_capped_below_04():
    """pyproject must keep the <0.4 ceiling on scrapling."""
    assert "<0.4" in _requirement_specifier("scrapling")


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


def test_installed_scrapling_stays_below_04():
    """The resolved environment must never pick up a scrapling 0.4.x."""
    installed = Version(version("scrapling"))
    assert installed < Version("0.4"), installed


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
