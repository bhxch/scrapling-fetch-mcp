"""daemon-owned 配置解析与摘要。

前端（或 CLI）把 daemon-owned 配置归一化成 ``(spawn_env, config_hash8)``：
spawn_env 中相对路径已转绝对路径，config_hash 由 canonical 值 dict 的
sha256 前 8 hex 构成，用于 daemon socket 命名隔离
（``daemon-<pkgver>-<hash8>.sock``）——不同配置各起一个 daemon，同配置
跨进程 hash 稳定。因此本模块对环境变量的解析必须完全确定性：任何
CWD 相关差异（相对路径）都必须体现在 hash 里，绝不静默抹平。

Import 边界约束：本模块在前端 import 白名单上，只允许 stdlib
（hashlib/json/math/pathlib/os），禁止 import 重依赖（trafilatura/markitdown/
numpy/playwright/...）及本项目内会引入它们的模块（含 ``_config``）。
键的归一化容错与 ``init_config_from_env`` 保持一致：解析失败的键按未
设置处理（不进 spawn_env，也不进 hash）。等价于默认值的显式取值同样
按未设置处理——布尔键解析为 False 时（三个布尔键默认全 False）不入
spawn_env 与 hash，显式 "false"/"0"/"no" 与未设置同 hash，不因此多起
一个 daemon；字符串键先 ``strip()``（``" stealth "`` 与 ``"stealth"``
同 hash）；float 键解析出 nan/inf 按"解析失败=未设置"处理（非法超时
不应改变 daemon 身份）。

传输/server 键（SCRAPLING_TRANSPORT/HOST/PORT/MCP_PATH/AUTH_TOKEN）、
features 键（SCRAPLING_DISABLE_FEATURES/ENABLE_FEATURES）与生命周期键
（SCRAPLING_DAEMON_DIR/SCRAPLING_DAEMON_IDLE_TIMEOUT）不归 daemon 所有，
不入 spawn_env 与摘要。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path

__all__ = [
    "DAEMON_OWNED_ENV_KEYS",
    "PROTOCOL_VERSION",
    "normalize_daemon_values",
    "resolve_daemon_env",
]

# daemon 与前端间的握手协议版本（protocol.py 引用）。
PROTOCOL_VERSION: int = 2

# daemon-owned env 键全集（与 _config.init_config_from_env 的 daemon 侧
# 配置一一对应；不含传输/features/生命周期键，见模块 docstring）。
DAEMON_OWNED_ENV_KEYS: tuple[str, ...] = (
    "SCRAPLING_MIN_MODE",
    "SCRAPLING_CACHE_TTL",
    "SCRAPLING_CACHE_MAX_ENTRIES",
    "SCRAPING_DIR",
    "SCRAPLING_MARKDOWN_CONVERTER",
    "SCRAPLING_RULES_CONFIG",
    "SCRAPLING_DEFAULT_FORMAT",
    "SCRAPLING_URL_REWRITE_CONFIG",
    "SCRAPLING_DISABLE_URL_REWRITE",
    "JINA_API_KEY",
    "SCRAPLING_DISABLE_JINA_ARBITER",
    "SCRAPLING_JINA_MIN_CHARS",
    "SCRAPLING_MAX_CONCURRENT",
    "SCRAPLING_ACQUIRE_TIMEOUT",
    "SCRAPLING_FETCH_TIMEOUT",
    "SCRAPLING_BROWSER_POOL",
    "SCRAPLING_POOL_IDLE_TTL",
    "SCRAPLING_POOL_MAX_AGE",
    "SCRAPLING_POOL_MAX_SESSIONS",
    "SCRAPLING_POOL_MAX_REQUESTS",
)

# 路径键：expanduser + resolve 转绝对路径（不存在也 resolve，Path.resolve
# 默认非 strict）。
_PATH_KEYS: frozenset[str] = frozenset(
    {"SCRAPING_DIR", "SCRAPLING_RULES_CONFIG", "SCRAPLING_URL_REWRITE_CONFIG"}
)

# 字符串键：与 init_config_from_env 一致做小写归一（"Stealth" 与 "stealth"
# 生效配置相同，hash 也不应不同）。
_LOWER_KEYS: frozenset[str] = frozenset(
    {"SCRAPLING_MIN_MODE", "SCRAPLING_MARKDOWN_CONVERTER", "SCRAPLING_DEFAULT_FORMAT"}
)

# 布尔键：true/1/yes → True，false/0/no → False，其余按未设置。
_BOOL_KEYS: frozenset[str] = frozenset(
    {
        "SCRAPLING_DISABLE_URL_REWRITE",
        "SCRAPLING_DISABLE_JINA_ARBITER",
        "SCRAPLING_BROWSER_POOL",
    }
)

# 整数键（init_config_from_env 按 int() 解析）。
_INT_KEYS: frozenset[str] = frozenset(
    {
        "SCRAPLING_CACHE_TTL",
        "SCRAPLING_CACHE_MAX_ENTRIES",
        "SCRAPLING_JINA_MIN_CHARS",
        "SCRAPLING_MAX_CONCURRENT",
        "SCRAPLING_POOL_MAX_SESSIONS",
        "SCRAPLING_POOL_MAX_REQUESTS",
    }
)

# 浮点键（init_config_from_env 按 float() 解析）。
_FLOAT_KEYS: frozenset[str] = frozenset(
    {
        "SCRAPLING_ACQUIRE_TIMEOUT",
        "SCRAPLING_FETCH_TIMEOUT",
        "SCRAPLING_POOL_IDLE_TTL",
        "SCRAPLING_POOL_MAX_AGE",
    }
)

# 其余键（JINA_API_KEY）为大小写敏感字符串，原样保留。
_RAW_KEYS: frozenset[str] = frozenset(DAEMON_OWNED_ENV_KEYS) - (
    _PATH_KEYS | _LOWER_KEYS | _BOOL_KEYS | _INT_KEYS | _FLOAT_KEYS
)

# 导入期自检：每个 owned 键恰好归入一类，防止键表增改时漏分类。
assert _PATH_KEYS | _LOWER_KEYS | _BOOL_KEYS | _INT_KEYS | _FLOAT_KEYS | _RAW_KEYS == set(
    DAEMON_OWNED_ENV_KEYS
), "DAEMON_OWNED_ENV_KEYS 存在未分类或重复分类的键"

_TRUE_VALUES: frozenset[str] = frozenset({"true", "1", "yes"})
_FALSE_VALUES: frozenset[str] = frozenset({"false", "0", "no"})


def _parse_value(key: str, raw: str) -> str | int | float | bool | None:
    """把单个 env 原始值归一化为 canonical 值；解析失败返回 None（按未设置）。"""
    if key in _PATH_KEYS:
        try:
            return str(Path(raw).expanduser().resolve())
        except (ValueError, OSError):
            return None
    if key in _INT_KEYS:
        try:
            return int(raw)
        except ValueError:
            return None
    if key in _FLOAT_KEYS:
        try:
            value = float(raw)
        except ValueError:
            return None
        # nan/inf 是 float() 的合法产物但对超时/TTL 毫无意义：按解析失败处理
        return value if math.isfinite(value) else None
    if key in _BOOL_KEYS:
        lowered = raw.lower()
        if lowered in _TRUE_VALUES:
            return True
        if lowered in _FALSE_VALUES:
            return False
        return None
    if key in _LOWER_KEYS:
        return raw.strip().lower()
    # 其余（JINA_API_KEY）：字符串键统一 strip——首尾空白从来不是键值语义，
    # 且 daemon 侧 init_config_from_env 不 strip，spawn_env 必须带归一化值
    return raw.strip()


def _collect_daemon_values() -> tuple[dict[str, str], dict[str, str | int | float | bool]]:
    """单趟扫描环境变量，返回 (spawn_env, canonical_values)。

    两者由同一解析结果生成，保证 daemon 侧从 spawn_env 重新归一化必然
    得到相同 canonical dict（同配置 ⇒ 同 hash）。未设置/空串/解析失败/
    等于默认值（布尔键 False）的键两边都不出现（由 daemon 侧默认值兜底）。
    """
    spawn_env: dict[str, str] = {}
    canonical: dict[str, str | int | float | bool] = {}
    for key in DAEMON_OWNED_ENV_KEYS:
        raw = os.environ.get(key)
        if not raw:
            continue
        parsed = _parse_value(key, raw)
        if parsed is None:
            continue
        if key in _BOOL_KEYS and parsed is False:
            continue  # 等于默认值：显式 "false" 与未设置同 hash,不换 daemon 身份
        canonical[key] = parsed
        # spawn_env 保真转发原始字符串（daemon 侧按同样规则解析）；路径键与
        # 字符串键替换为归一化值（前者转绝对路径,后者 strip 后 daemon 侧
        # init_config_from_env 不再 strip,必须传归一化串才能解析到同值）。
        spawn_env[key] = parsed if isinstance(parsed, str) else raw
    return spawn_env, canonical


def normalize_daemon_values() -> dict[str, str | int | float | bool]:
    """当前环境下 daemon-owned 配置的 canonical 值 dict（config_hash 的输入）。"""
    return _collect_daemon_values()[1]


def resolve_daemon_env(cli: dict[str, object] | None = None) -> tuple[dict[str, str], str]:
    """归一化 daemon-owned 配置，返回 ``(spawn_env, config_hash8)``。

    ``cli`` 参数为前端 CLI 覆盖预留（Task 10 接线：届时覆盖已写回
    os.environ 或直接传入 dict），本任务忽略。

    config_hash = sha256(json.dumps(normalize_daemon_values(),
    sort_keys=True, ensure_ascii=True)).hexdigest()[:8]，跨进程稳定。
    """
    del cli  # 本任务保留签名，忽略
    spawn_env, canonical = _collect_daemon_values()
    config_hash = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, ensure_ascii=True).encode()
    ).hexdigest()[:8]
    return spawn_env, config_hash
