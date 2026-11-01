"""daemon/config_env 的配置解析与摘要测试（Task 4）"""

from scrapling_fetch_mcp.daemon.config_env import (
    DAEMON_OWNED_ENV_KEYS,
    resolve_daemon_env,
)


def test_hash_stable_and_paths_absolute(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCRAPING_DIR", ".temp/scrapling/")
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "stealth")
    env, h1 = resolve_daemon_env()
    assert env["SCRAPING_DIR"] == str((tmp_path / ".temp/scrapling").resolve())
    assert len(h1) == 8 and int(h1, 16) >= 0
    _, h2 = resolve_daemon_env()          # 同输入同 hash
    assert h1 == h2

def test_same_string_different_cwd_differs(monkeypatch, tmp_path):
    monkeypatch.setenv("SCRAPING_DIR", ".temp/scrapling/")
    monkeypatch.chdir(tmp_path); _, h_a = resolve_daemon_env()
    monkeypatch.chdir(tmp_path / ".."); _, h_b = resolve_daemon_env()
    assert h_a != h_b                     # 反目标"静默不一致"的钉子

def test_transport_keys_excluded(monkeypatch):
    monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "secret"); monkeypatch.setenv("SCRAPLING_PORT", "9999")
    e1, h1 = resolve_daemon_env()
    monkeypatch.setenv("SCRAPLING_AUTH_TOKEN", "other"); monkeypatch.setenv("SCRAPLING_PORT", "1234")
    _, h2 = resolve_daemon_env()
    assert h1 == h2 and "SCRAPLING_AUTH_TOKEN" not in e1

def test_defaults_when_env_empty(monkeypatch):
    for k in DAEMON_OWNED_ENV_KEYS: monkeypatch.delenv(k, raising=False)
    env, h = resolve_daemon_env()
    assert env.get("SCRAPLING_MIN_MODE") is None      # 未设置不进 env,由 daemon 侧默认值兜底
    assert len(h) == 8
