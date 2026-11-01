"""daemon 运行目录与包版本工具（前端与 daemon 共用的定位模块）。

``pkg_version()`` 取发行版本——socket 命名隔离的一部分（升级即换名，
旧 daemon 不会被误连）；``daemon_dir()`` 解析 daemon 运行目录：显式配置
（``SCRAPLING_DAEMON_DIR`` 经 config 单例）优先，缺省 platformdirs 用户
数据目录，并负责 mkdir。

Import 边界约束：与 ``config_env``/``protocol`` 同列前端 import 白名单，
模块级只允许 stdlib 与 ``platformdirs``；``_config``（单例配置）在函数内
延迟 import，使 ``import scrapling_fetch_mcp.daemon.lifecycle`` 不牵入
项目配置链，也不引入任何重依赖。
"""

from __future__ import annotations

import importlib.metadata
from pathlib import Path

import platformdirs

__all__ = [
    "daemon_dir",
    "pkg_version",
]

_PKG_NAME = "scrapling-fetch-mcp"


def pkg_version() -> str:
    """本包发行版本（socket 名 ``daemon-<ver>-<hash>`` 的版本段）。"""
    return importlib.metadata.version(_PKG_NAME)


def daemon_dir() -> Path:
    """daemon 运行目录：显式配置优先，缺省 platformdirs 用户数据目录。

    每次调用都确保目录存在（``mkdir(parents=True, exist_ok=True)``），
    调用方可直接在其下创建 socket/lock/log。
    """
    from scrapling_fetch_mcp._config import config  # 延迟 import：保持本模块轻

    configured = config.daemon_dir
    d = Path(configured) if configured is not None else Path(platformdirs.user_data_dir(_PKG_NAME))
    d.mkdir(parents=True, exist_ok=True)
    return d
