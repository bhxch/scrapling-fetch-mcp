"""daemon/pool 浏览器池测试（Task 11）。

FakeSession 全替身：记录构造模式、fetch 调用、close；可注入异常与响应
内容，绝不启动真浏览器。会话工厂经构造参数/pool._new_session 注入，
时钟经 pool._clock 注入（不动全局 time.monotonic——asyncio 内部也在用）。
覆盖简报全部场景：同域复用、跨域/跨模式分桶、五触发重建（TTL 三项 +
fetch 异常 + 疑似挑战页）、LRU 逐出、close_all、同桶串行锁。
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from scrapling_fetch_mcp.daemon import pool as pool_mod
from scrapling_fetch_mcp.daemon.pool import BrowserPool, bucket_key

# 有效字数远超 jina_min_chars 默认阈值(500)——正常页面,不触发挑战页判定
PAGE_HTML = "<html><body><p>" + "word " * 200 + "</p></body></html>"
# Cloudflare interstitial 形态:标题/正文都极短 → 疑似
CHALLENGE_HTML = "<html><head><title>Just a moment...</title></head><body></body></html>"


class FakeClock:
    """可手动推进的单调时钟：替换 pool._clock 供 TTL 判定注入。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, dt: float) -> None:
        self.now += dt


class FakeSession:
    """替身会话：记录调用与并发重叠，可注入异常与响应 HTML。"""

    def __init__(self, mode: str, registry: dict) -> None:
        self.mode = mode
        self.fetch_calls: list[tuple] = []
        self.closed = False
        self.error: Exception | None = None
        self.html = PAGE_HTML
        self._registry = registry

    async def fetch(self, url, timeout=None, page_action=None):
        self.fetch_calls.append((url, timeout, page_action))
        reg = self._registry
        reg["active"] += 1
        reg["max_active"] = max(reg["max_active"], reg["active"])
        try:
            if reg["probing"]:
                # 重叠探测：两个 fetch 同时在飞才放行；串行时必然等超时
                if reg["active"] >= 2:
                    reg["overlap"].set()
                try:
                    await asyncio.wait_for(reg["overlap"].wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
            else:
                await asyncio.sleep(0)  # 让出事件循环,暴露真实并发交错
        finally:
            reg["active"] -= 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(status=200, body=self.html.encode(), html_content=self.html)

    async def close(self):
        self.closed = True


def make_pool(monkeypatch, *, idle_ttl=300.0, max_age=1800.0, max_sessions=4,
              max_requests=50, registry=None) -> tuple[BrowserPool, dict]:
    """构造带 FakeSession 工厂的池；registry 记录 built/会话列表/并发探测。"""
    reg = registry if registry is not None else {
        "built": [], "sessions": [], "active": 0, "max_active": 0,
        "overlap": asyncio.Event(), "probing": False,
    }
    reg.setdefault("built", [])
    reg.setdefault("sessions", [])

    async def factory(mode):
        session = FakeSession(mode, reg)
        reg["built"].append(mode)
        reg["sessions"].append(session)
        return session

    pool = BrowserPool(
        idle_ttl, max_age, max_sessions, max_requests,
        session_factory=factory,
    )
    return pool, reg


# ---------- 桶键 ----------

def test_bucket_key_collapses_subdomains_and_falls_back_to_netloc():
    """eTLD+1 折叠子域;无注册域名(localhost:port)退回 netloc;mode 入键。"""
    assert bucket_key("http://a.example.com/1", "stealth") == ("example.com", "stealth")
    assert bucket_key("http://www.a.example.com/2", "stealth") == ("example.com", "stealth")
    assert bucket_key("http://localhost:8000/x", "stealth") == ("localhost:8000", "stealth")
    assert bucket_key("http://a.example.com/1", "max-stealth") == ("example.com", "max-stealth")


# ---------- 生产工厂（不启动真浏览器:替换 scrapling 会话类） ----------

@pytest.mark.asyncio
async def test_new_session_launch_kwargs_match_browse_branches(monkeypatch):
    """生产工厂 kwargs 与 _do_browse 两分支对齐;__aenter__ 创建会话;
    timeout/page_action 不在构造时钉死(逐次 fetch 传入)。"""
    captured = {}

    class FakeAS:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.entered = False

        async def __aenter__(self):
            self.entered = True
            return self

    monkeypatch.setattr(
        "scrapling.engines._browsers._camoufox.AsyncStealthySession", FakeAS)
    session = await pool_mod._new_session("stealth")
    assert captured == {"headless": True, "network_idle": True}
    assert session.entered is True
    captured.clear()
    await pool_mod._new_session("max-stealth")
    assert captured == {
        "headless": True, "network_idle": True,
        "block_webrtc": True, "disable_resources": False, "block_images": False,
    }


# ---------- 复用 / 分桶 ----------

@pytest.mark.asyncio
async def test_same_domain_reuses_session(monkeypatch):
    pool, reg = make_pool(monkeypatch)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert reg["built"] == ["stealth"]  # 只建一次
    s = reg["sessions"][0]
    assert s.fetch_calls == [
        ("http://a.example.com/1", 1000, None),
        ("http://a.example.com/2", 1000, None),
    ]
    stats = pool.stats()
    assert stats["sessions"] == 1
    assert stats["hits"] == 1
    assert stats["misses"] == 1
    assert stats["buckets"] == ["example.com"]


@pytest.mark.asyncio
async def test_different_domain_or_mode_new_bucket(monkeypatch):
    pool, reg = make_pool(monkeypatch)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    await pool.fetch("http://b.example.org/1", "stealth", 1000)  # 不同域名 → 新桶
    await pool.fetch("http://a.example.com/2", "max-stealth", 1000)  # 不同模式 → 新桶
    assert reg["built"] == ["stealth", "stealth", "max-stealth"]
    stats = pool.stats()
    assert stats["sessions"] == 3
    assert stats["hits"] == 0
    assert stats["misses"] == 3
    assert sorted(stats["buckets"]) == ["example.com", "example.com", "example.org"]


# ---------- TTL / 请求数重建（注入时钟） ----------

@pytest.mark.asyncio
async def test_rebuild_on_idle_ttl_and_max_age_and_max_requests(monkeypatch):
    clock = FakeClock()
    monkeypatch.setattr(pool_mod, "_clock", clock)

    # 空闲 > idle_ttl → 重建
    pool, reg = make_pool(monkeypatch, idle_ttl=300.0)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    clock.advance(300.0)  # 恰好等于阈值:严格大于才触发
    await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert len(reg["built"]) == 1
    clock.advance(300.1)  # 距上次使用 300.1 > 300 → 重建(空闲自上次使用起算)
    await pool.fetch("http://a.example.com/3", "stealth", 1000)
    assert len(reg["built"]) == 2
    assert reg["sessions"][0].closed is True
    assert pool.stats()["hits"] == 1 and pool.stats()["misses"] == 2

    # 年龄 > max_age → 重建(即使一直活跃,空闲从不超限)
    pool, reg = make_pool(monkeypatch, max_age=1800.0)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)  # t=1000 建桶
    for _ in range(15):  # 每 100s 用一次:t=2500,年龄 1500,空闲 100
        clock.advance(100.0)
        await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert len(reg["built"]) == 1
    clock.advance(150.0)  # t=2650:年龄 1650,空闲 150——均未超
    await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert len(reg["built"]) == 1
    clock.advance(150.1)  # t=2800.1:年龄 1800.1 > 1800(空闲仅 150.1)
    await pool.fetch("http://a.example.com/3", "stealth", 1000)
    assert len(reg["built"]) == 2  # 纯年龄触发
    assert reg["sessions"][0].closed is True

    # 请求数 > max_requests → 重建
    pool, reg = make_pool(monkeypatch, max_requests=2)
    for _ in range(3):  # 恰好等于阈值不触发:第 3 次仍复用
        await pool.fetch("http://a.example.com/1", "stealth", 1000)
    assert len(reg["built"]) == 1
    await pool.fetch("http://a.example.com/2", "stealth", 1000)  # 3 > 2 → 重建
    assert len(reg["built"]) == 2
    assert reg["sessions"][0].closed is True
    assert len(reg["sessions"][1].fetch_calls) == 1  # 新会话服务本次请求


# ---------- 异常 / 疑似挑战页重建 ----------

@pytest.mark.asyncio
async def test_rebuild_on_fetch_error(monkeypatch):
    pool, reg = make_pool(monkeypatch)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    reg["sessions"][0].error = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert reg["sessions"][0].closed is True  # 出错身份不可复用:销毁
    assert pool.stats()["sessions"] == 0
    await pool.fetch("http://a.example.com/3", "stealth", 1000)  # 下次重建新会话
    assert len(reg["built"]) == 2
    assert reg["sessions"][1].closed is False


@pytest.mark.asyncio
async def test_rebuild_on_suspicious_response(monkeypatch):
    """疑似挑战页:响应照常返回(管线可仲裁),但桶立即销毁。"""
    pool, reg = make_pool(monkeypatch)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    reg["sessions"][0].html = CHALLENGE_HTML
    resp = await pool.fetch("http://a.example.com/2", "stealth", 1000)
    assert resp.html_content == CHALLENGE_HTML  # 响应本身交付
    assert reg["sessions"][0].closed is True  # 疑被标记的身份不复用
    assert pool.stats()["sessions"] == 0
    await pool.fetch("http://a.example.com/3", "stealth", 1000)
    assert len(reg["built"]) == 2


# ---------- LRU 逐出 ----------

@pytest.mark.asyncio
async def test_lru_evicts_beyond_max_sessions(monkeypatch):
    pool, reg = make_pool(monkeypatch, max_sessions=2)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)  # 桶 A
    await pool.fetch("http://b.example.org/1", "stealth", 1000)  # 桶 B
    await pool.fetch("http://a.example.com/2", "stealth", 1000)  # 触碰 A → A 最新
    await pool.fetch("http://c.example.net/1", "stealth", 1000)  # 第 3 桶 → 淘汰 B
    assert reg["sessions"][1].closed is True  # B(最久未用)被逐出即 close
    assert reg["sessions"][0].closed is False
    assert reg["sessions"][2].closed is False
    stats = pool.stats()
    assert stats["sessions"] == 2
    assert stats["buckets"] == ["example.com", "example.net"]
    # 被逐出的域名再来 → 重建
    await pool.fetch("http://b.example.org/2", "stealth", 1000)
    assert len(reg["built"]) == 4
    assert reg["sessions"][3].closed is False


# ---------- close_all ----------

@pytest.mark.asyncio
async def test_close_all_closes_everything(monkeypatch):
    pool, reg = make_pool(monkeypatch)
    await pool.fetch("http://a.example.com/1", "stealth", 1000)
    await pool.fetch("http://b.example.org/1", "stealth", 1000)
    await pool.close_all()
    assert all(s.closed for s in reg["sessions"])
    stats = pool.stats()
    assert stats["sessions"] == 0
    assert stats["buckets"] == []
    await pool.close_all()  # 幂等:再关一次不报错


# ---------- 同桶串行锁 ----------

@pytest.mark.asyncio
async def test_bucket_lock_serializes_same_domain(monkeypatch):
    registry = {
        "built": [], "sessions": [], "active": 0, "max_active": 0,
        "overlap": asyncio.Event(), "probing": True,
    }
    pool, reg = make_pool(monkeypatch, registry=registry)
    await asyncio.gather(
        pool.fetch("http://a.example.com/1", "stealth", 1000),
        pool.fetch("http://a.example.com/2", "stealth", 1000),
    )
    assert reg["max_active"] == 1  # 同桶两 fetch 绝无重叠在飞
    assert len(reg["built"]) == 1  # 且共享同一会话
    assert {call[0] for call in reg["sessions"][0].fetch_calls} == {
        "http://a.example.com/1", "http://a.example.com/2",
    }
