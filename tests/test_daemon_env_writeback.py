"""C1 回归：run_server 的 CLI 覆盖必须抵达 daemon（env 写回）。

``resolve_daemon_env`` 只读 os.environ，而 CLI 覆盖只写 config 单例——
不写回 env 则 config_hash 与 spawn env 双双漏改，覆盖静默失效（0.2.x
回归）。本文件钉两件事：

1. ``_sync_daemon_env`` 的键级语义：生效值写回、路径绝对化、布尔串化与
   daemon 侧解析对称、None/空串键不写；
2. run_server 全链路接线：CLI flags 过后 env 即反映覆盖、hash 随之变化。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from scrapling_fetch_mcp._config import Config, config
from scrapling_fetch_mcp.daemon.config_env import (
    DAEMON_OWNED_ENV_KEYS,
    normalize_daemon_values,
    resolve_daemon_env,
)


@pytest.fixture
def clean_daemon_env(tmp_path, monkeypatch):
    """daemon-owned env 清零 + 配置单例快照/恢复 + chdir 隔离路径 resolve。

    os.environ 与 config 单例都是进程级全局：快照逐键恢复（sync 写进的
    键一并清掉），不靠 monkeypatch.delenv（它管不到 sync 的直接写入）。
    transport/token 钉回 stdio/空：同进程更早的测试可能把单例留在
    streamable-http+token（test_config 的已知残留），run_server 会走 auth
    分支重绑全局 mcp，污染后续 registration 断言。全局 mcp 一并保存/恢复。
    """
    import scrapling_fetch_mcp.mcp as mcp_mod

    monkeypatch.chdir(tmp_path)
    saved_env = {k: os.environ.get(k) for k in DAEMON_OWNED_ENV_KEYS}
    for k in DAEMON_OWNED_ENV_KEYS:
        os.environ.pop(k, None)
    snapshot = dict(config.__dict__)  # set_* 写实例属性,类级默认不受影响
    saved_mcp = mcp_mod.mcp
    config._transport = "stdio"
    config._auth_token = ""
    yield config
    mcp_mod.mcp = saved_mcp
    config.__dict__.clear()
    config.__dict__.update(snapshot)
    for k, v in saved_env.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def test_cli_overrides_reach_daemon_env_and_hash(clean_daemon_env):
    """config 单例（已被 CLI 覆盖）写回后，env 与 hash 均反映覆盖。"""
    from scrapling_fetch_mcp.mcp import _sync_daemon_env

    cfg = clean_daemon_env
    cfg.set_min_mode("max-stealth")
    cfg.set_cache_ttl(123)
    cfg.set_browser_pool(True)
    cfg.set_max_concurrent(7)
    before = resolve_daemon_env()
    _sync_daemon_env()
    env, h = resolve_daemon_env()
    assert env["SCRAPLING_MIN_MODE"] == "max-stealth"
    assert env["SCRAPLING_CACHE_TTL"] == "123"
    assert env["SCRAPLING_BROWSER_POOL"] == "true"
    assert env["SCRAPLING_MAX_CONCURRENT"] == "7"
    assert h != before[1]  # hash 必须随覆盖变化,否则 daemon 身份不换


def test_path_keys_written_absolute(clean_daemon_env):
    """路径键解析为绝对（daemon 以 cwd="/" spawn,相对路径语义已死）。"""
    from scrapling_fetch_mcp.mcp import _sync_daemon_env

    cfg = clean_daemon_env
    cfg.set_scraping_dir(".temp/scrapling/")  # 相对默认
    cfg.set_rules_config_path("rules.yaml")
    _sync_daemon_env()
    env, _ = resolve_daemon_env()
    assert env["SCRAPING_DIR"] == str((Path.cwd() / ".temp/scrapling").resolve())
    assert Path(env["SCRAPING_DIR"]).is_absolute()
    assert env["SCRAPLING_RULES_CONFIG"] == str((Path.cwd() / "rules.yaml").resolve())


def test_unset_optional_keys_not_written(clean_daemon_env):
    """rules/url_rewrite 未配置(None)、JINA key 空 → 不写（按未设置解析）。"""
    from scrapling_fetch_mcp.mcp import _sync_daemon_env

    assert config.rules_config_path is None
    assert config.url_rewrite_config_path is None
    assert config.jina_api_key == ""
    _sync_daemon_env()
    for key in ("SCRAPLING_RULES_CONFIG", "SCRAPLING_URL_REWRITE_CONFIG", "JINA_API_KEY"):
        assert key not in os.environ


def test_boolean_stringification_symmetric_with_daemon_side(clean_daemon_env):
    """"true"/"false" 串化与 config_env 解析对称：canonical 值一致。"""
    from scrapling_fetch_mcp.mcp import _sync_daemon_env

    cfg = clean_daemon_env
    cfg.set_browser_pool(True)
    cfg.set_disable_url_rewrite(True)
    _sync_daemon_env()
    canon = normalize_daemon_values()
    assert canon["SCRAPLING_BROWSER_POOL"] is True
    assert canon["SCRAPLING_DISABLE_URL_REWRITE"] is True
    assert canon["SCRAPLING_DISABLE_JINA_ARBITER"] is False  # 默认关也入 canonical


def test_all_owned_keys_covered(clean_daemon_env):
    """写回表必须覆盖 DAEMON_OWNED_ENV_KEYS 中所有非 None/空键（防漂移）。"""
    from scrapling_fetch_mcp.mcp import _sync_daemon_env

    cfg = clean_daemon_env
    cfg.set_rules_config_path("r.yaml")
    cfg.set_url_rewrite_config_path("u.yaml")
    cfg.set_jina_api_key("jk")
    _sync_daemon_env()
    missing = [k for k in DAEMON_OWNED_ENV_KEYS if k not in os.environ]
    assert missing == []  # 三个可选键这次都有值,其余键恒有生效值


def test_run_server_wiring_cli_overrides_hit_daemon_env(clean_daemon_env, monkeypatch):
    """run_server 全链路：CLI flags 过后 resolve_daemon_env 即反映覆盖。"""
    import scrapling_fetch_mcp.mcp as mcp_mod

    monkeypatch.setattr(mcp_mod.MCPServer, "run", lambda self, **kw: None)
    monkeypatch.setattr(sys, "argv", [
        "scrapling-fetch-mcp",
        "--min-mode", "max-stealth",
        "--cache-ttl", "123",
        "--scraping-dir", "out/dir",
        "--browser-pool",
    ])
    mcp_mod.run_server()
    env, _ = resolve_daemon_env()
    assert env["SCRAPLING_MIN_MODE"] == "max-stealth"
    assert env["SCRAPLING_CACHE_TTL"] == "123"
    assert env["SCRAPLING_BROWSER_POOL"] == "true"
    assert env["SCRAPING_DIR"] == str((Path.cwd() / "out/dir").resolve())
    assert Path(env["SCRAPING_DIR"]).is_absolute()


def test_run_server_wiring_env_base_kept_when_cli_absent(clean_daemon_env, monkeypatch):
    """env 为底：CLI 未传的键保持 env 值（CLI 默认不得踩 env）。"""
    import scrapling_fetch_mcp.mcp as mcp_mod

    monkeypatch.setenv("SCRAPLING_MARKDOWN_CONVERTER", "markdownify")
    monkeypatch.setattr(mcp_mod.MCPServer, "run", lambda self, **kw: None)
    monkeypatch.setattr(sys, "argv", ["scrapling-fetch-mcp"])
    mcp_mod.run_server()
    env, _ = resolve_daemon_env()
    assert env["SCRAPLING_MARKDOWN_CONVERTER"] == "markdownify"
    cfg = Config()  # 单例真相源同样是 env 值
    assert cfg.markdown_converter == "markdownify"
