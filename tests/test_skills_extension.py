"""SkillsExtension(SEP-2640)单元测试。"""
import hashlib

import pytest

from scrapling_fetch_mcp._skills import (
    SKILL_URI,
    SkillsExtension,
    load_skill_markdown,
)


@pytest.fixture()
def ext() -> SkillsExtension:
    return SkillsExtension()


def test_load_skill_markdown_returns_content():
    text = load_skill_markdown()
    assert text is not None
    assert text.startswith("---\nname: scrapling-fetch")


def test_extension_available(ext):
    assert ext.available() is True


def test_extension_identifier(ext):
    assert ext.identifier == "io.modelcontextprotocol/skills"


def test_resources_binding(ext):
    bindings = ext.resources()
    assert len(bindings) == 1
    res = bindings[0].resource
    assert res.uri == SKILL_URI
    assert res.mime_type == "text/markdown"
    assert res.name == "scrapling-fetch"


@pytest.mark.asyncio
async def test_read_resource_returns_markdown(ext):
    bindings = ext.resources()
    text = await bindings[0].resource.read()
    assert "# Scrapling Fetch Workflows" in text


def test_skills_entry_shape(ext):
    entry = ext.skill_entry()
    assert entry["uri"] == SKILL_URI
    fm = entry["frontmatter"]
    assert fm["name"] == "scrapling-fetch"
    assert "description" in fm
    assert isinstance(fm, dict)
    resources = entry["resources"]
    assert len(resources) == 1
    raw = load_skill_markdown().encode()
    assert resources[0]["size"] == len(raw)
    assert resources[0]["digest"] == "sha256:" + hashlib.sha256(raw).hexdigest()


@pytest.mark.asyncio
async def test_skills_list_method(ext):
    methods = {m.method: m for m in ext.methods()}
    assert set(methods) == {"skills/list", "skills/get"}
    result = await methods["skills/list"].handler(None, None)
    assert result["resultType"] == "complete"
    assert result["skills"] == [ext.skill_entry()]
    assert "ttlMs" in result and "cacheScope" in result


@pytest.mark.asyncio
async def test_skills_get_method(ext):
    methods = {m.method: m for m in ext.methods()}
    result = await methods["skills/get"].handler(None, type("P", (), {"uri": SKILL_URI})())
    assert result["skill"]["uri"] == SKILL_URI


@pytest.mark.asyncio
async def test_skills_get_unknown_uri_rejected(ext):
    from mcp.shared.exceptions import MCPError
    methods = {m.method: m for m in ext.methods()}
    with pytest.raises(MCPError) as exc:
        await methods["skills/get"].handler(
            None, type("P", (), {"uri": "skill://unknown/SKILL.md"})())
    assert exc.value.code == -32602


def test_missing_skill_file_disables_extension(monkeypatch):
    monkeypatch.setattr("scrapling_fetch_mcp._skills.load_skill_markdown",
                        lambda: None)
    ext = SkillsExtension()
    assert ext.available() is False
    assert ext.resources() == []
    assert ext.methods() == []
    with pytest.raises(ValueError):
        ext.skill_entry()
