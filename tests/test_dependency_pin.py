"""Regression guards for the scrapling version ceiling.

scrapling 0.4.x imports patchright unconditionally at module level while
declaring it only in the optional [fetchers] extra, and drops the camoufox
engine this fork's stealth modes run on. The fork covers fetcher
dependencies itself and deliberately does not declare patchright, so a
0.4.x resolve breaks every fetch mode (basic included) with
ModuleNotFoundError. pyproject.toml caps scrapling below 0.4; these tests
keep that cap from being dropped or resolved away.
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
    data = tomllib.loads(PYPROJECT.read_text())
    requirements = [
        Requirement(dep)
        for dep in data["project"]["dependencies"]
        if Requirement(dep).name == "scrapling"
    ]
    assert len(requirements) == 1, "scrapling should be declared exactly once"
    specifiers = str(requirements[0].specifier)
    assert "<0.4" in specifiers, specifiers


def test_installed_scrapling_stays_below_04():
    """The resolved environment must never pick up a scrapling 0.4.x."""
    installed = Version(version("scrapling"))
    assert installed < Version("0.4"), installed


def test_fetchers_import_without_patchright():
    """The import path that breaks under 0.4.x must stay usable in this
    environment, whose dependency set intentionally has no patchright."""
    if find_spec("patchright") is not None:
        pytest.skip("patchright is installed; the guard is only meaningful without it")
    from scrapling.fetchers import AsyncFetcher  # noqa: F401
