"""MCP Skills extension (SEP-2640, io.modelcontextprotocol/skills).

Serves the bundled `scrapling-fetch` skill as a `skill://` resource and
implements the `skills/list` / `skills/get` methods required by the spec.
SKILL.md 缺失时扩展整体不启用,server 其余功能不受影响。
"""
import hashlib
import logging
from importlib import resources as importlib_resources
from typing import Any, Optional

import yaml
from pydantic import BaseModel

from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp_types import RequestParams

logger = logging.getLogger(__name__)

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILL_NAME = "scrapling-fetch"
SKILL_URI = f"skill://{SKILL_NAME}/SKILL.md"
_SKILL_PATH = "skills/scrapling-fetch/SKILL.md"
_ENTRY_TTL_MS = 300000
_CACHE_SCOPE = "public"


class GetSkillParams(RequestParams):
    """Params of the skills/get method: the SKILL.md URI.

    继承 SDK 的 RequestParams 以统一解析 `_meta`。
    """
    uri: str


class _ListSkillsParams(BaseModel):
    """skills/list takes no fields (pagination cursor unused, single skill)."""


def load_skill_markdown() -> Optional[str]:
    """Read the packaged SKILL.md; None when the data file is missing."""
    try:
        return importlib_resources.files("scrapling_fetch_mcp").joinpath(
            _SKILL_PATH).read_text(encoding="utf-8")
    except (FileNotFoundError, ModuleNotFoundError, OSError):
        logger.warning("SKILL.md not found at %s, skills extension disabled",
                       _SKILL_PATH)
        return None


class SkillsExtension(Extension):
    """Publishes the bundled skill per SEP-2640."""

    identifier = EXTENSION_ID

    def __init__(self) -> None:
        self._markdown: Optional[str] = load_skill_markdown()
        # 预解析 frontmatter:SKILL.md 畸形时禁用扩展(走 available()=False
        # 路径),而不是让 server 构造期崩溃;也不得降级为空 dict,否则会
        # 发布缺 name/description 的 entry,违反 SEP-2640。
        try:
            if not isinstance(self._frontmatter(), dict):
                raise ValueError("frontmatter is not a mapping")
        except (yaml.YAMLError, ValueError, AttributeError) as exc:
            if self._markdown is not None:
                logger.warning(
                    "Invalid SKILL.md frontmatter (%s), skills extension disabled",
                    exc)
            self._markdown = None

    def available(self) -> bool:
        return self._markdown is not None

    def _frontmatter(self) -> dict[str, Any]:
        text = self._markdown or ""
        if text.startswith("---"):
            _, fm_block, _body = text.split("---", 2)
            return yaml.safe_load(fm_block) or {}
        return {}

    def skill_entry(self) -> dict[str, Any]:
        """SEP-2640 Skill entry: verbatim frontmatter + file manifest."""
        if self._markdown is None:
            raise ValueError("skill content is not available")
        raw = self._markdown.encode("utf-8")
        return {
            "uri": SKILL_URI,
            "frontmatter": self._frontmatter(),
            "resources": [{
                "uri": SKILL_URI,
                "digest": "sha256:" + hashlib.sha256(raw).hexdigest(),
                "size": len(raw),
            }],
        }

    def settings(self) -> dict[str, Any]:
        # 不实现 resources/directory/read
        return {}

    def resources(self) -> list[ResourceBinding]:
        if not self.available():
            return []
        fm = self._frontmatter()
        resource = TextResource(
            uri=SKILL_URI,
            name=fm.get("name"),
            description=fm.get("description"),
            mime_type="text/markdown",
            text=self._markdown,
        )
        return [ResourceBinding(resource=resource)]

    def methods(self) -> list[MethodBinding]:
        if not self.available():
            return []

        async def skills_list(ctx, params):
            return {
                "resultType": "complete",
                "skills": [self.skill_entry()],
                "ttlMs": _ENTRY_TTL_MS,
                "cacheScope": _CACHE_SCOPE,
            }

        async def skills_get(ctx, params: GetSkillParams):
            if params.uri != SKILL_URI:
                raise MCPError(
                    code=-32602,
                    message=f"No skill is served at {params.uri}",
                )
            return {
                "resultType": "complete",
                "skill": self.skill_entry(),
                "ttlMs": _ENTRY_TTL_MS,
                "cacheScope": _CACHE_SCOPE,
            }

        return [
            MethodBinding(method="skills/list",
                          params_type=_ListSkillsParams, handler=skills_list),
            MethodBinding(method="skills/get",
                          params_type=GetSkillParams, handler=skills_get),
        ]


def build_extension() -> Optional[SkillsExtension]:
    """Extension instance, or None when the skill data file is missing."""
    ext = SkillsExtension()
    return ext if ext.available() else None
