"""SKILL.md 打包数据与 Agent Skills frontmatter 约束测试。"""
from importlib import resources

import pytest
import yaml

from scrapling_fetch_mcp._skills import SKILL_URI


@pytest.fixture(scope="module")
def skill_text() -> str:
    path = resources.files("scrapling_fetch_mcp").joinpath(
        "skills/scrapling-fetch/SKILL.md")
    return path.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontmatter(skill_text) -> dict:
    assert skill_text.startswith("---")
    _, fm_block, _body = skill_text.split("---", 2)
    return yaml.safe_load(fm_block)


def test_frontmatter_has_required_fields(frontmatter):
    assert frontmatter["name"] == "scrapling-fetch"
    assert isinstance(frontmatter["description"], str)
    assert len(frontmatter["description"]) > 20


def test_skill_name_matches_directory(frontmatter):
    # Agent Skills 规范:name 必须等于所在目录名
    assert frontmatter["name"] == "scrapling-fetch"
    # SEP-2640 URI 约定:skill://<skill-path>/<file-path> 中
    # <skill-path> 末段必须等于 frontmatter 的 name
    skill_path = SKILL_URI.removeprefix("skill://").split("/")[0]
    assert skill_path.split("/")[-1] == frontmatter["name"]


def test_skill_body_covers_core_workflows(skill_text):
    for keyword in ("s_fetch_page", "s_fetch_pattern", "is_truncated",
                    "start_index", "查看原文", "stealth"):
        assert keyword in skill_text, keyword
