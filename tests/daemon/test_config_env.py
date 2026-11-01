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

def test_bool_false_equals_unset(monkeypatch):
    """显式 "false" 与未设置同 hash：等于默认值的布尔键不进 hash 输入与 spawn_env。"""
    monkeypatch.delenv("SCRAPLING_BROWSER_POOL", raising=False)
    _, h_unset = resolve_daemon_env()
    monkeypatch.setenv("SCRAPLING_BROWSER_POOL", "false")
    env, h_false = resolve_daemon_env()
    assert h_false == h_unset                 # 不因显式默认值多起一个 daemon
    assert "SCRAPLING_BROWSER_POOL" not in env  # spawn_env 与 hash 同源:两边都不出现
    monkeypatch.setenv("SCRAPLING_BROWSER_POOL", "TRUE")
    _, h_true = resolve_daemon_env()
    assert h_true != h_unset                  # True 仍改变身份

def test_string_values_stripped(monkeypatch):
    """字符串值先 strip 再入 hash 与 spawn_env：" stealth " 与 "stealth" 同 hash。"""
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "  stealth  ")
    env, h_padded = resolve_daemon_env()
    assert env["SCRAPLING_MIN_MODE"] == "stealth"  # spawn_env 带归一化串(daemon 侧不再 strip)
    monkeypatch.setenv("SCRAPLING_MIN_MODE", "stealth")
    _, h_clean = resolve_daemon_env()
    assert h_padded == h_clean

def test_nonfinite_float_treated_as_unset(monkeypatch):
    """float 解析出 nan/inf 按解析失败=未设置处理：不改变 daemon 身份。"""
    monkeypatch.delenv("SCRAPLING_ACQUIRE_TIMEOUT", raising=False)
    _, h_unset = resolve_daemon_env()
    monkeypatch.setenv("SCRAPLING_ACQUIRE_TIMEOUT", "nan")
    env, h_nan = resolve_daemon_env()
    assert h_nan == h_unset and "SCRAPLING_ACQUIRE_TIMEOUT" not in env
    monkeypatch.setenv("SCRAPLING_ACQUIRE_TIMEOUT", "inf")
    _, h_inf = resolve_daemon_env()
    assert h_inf == h_unset

