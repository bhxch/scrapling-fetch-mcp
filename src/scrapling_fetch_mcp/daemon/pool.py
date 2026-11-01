"""浏览器池：按 (eTLD+1 域名, mode) 分桶复用 Firefox 会话，五触发销毁重建。

承重设计（spec §6.2）：

- **桶键** ``(tldextract.registered_domain or netloc, mode)``。mode 入键是
  因为 stealth/max-stealth 启动参数不同，会话身份不可混用；域名取注册域
  （eTLD+1），同域多子页复用收益最大，跨域不共享身份避免 farm 特征。
- **重建触发**（任一满足即整桶销毁重建，阈值判定一律严格大于）：
  空闲 > idle_ttl、累计年龄 > max_age、请求数 > max_requests、fetch 异常
  （销毁后 re-raise）、疑似挑战页（销毁，响应仍交付给管线仲裁）。
- **并发**：同桶 ``asyncio.Lock`` 串行（一个 Firefox context 上的多 tab
  并发会放大资源与关联风险，不做）；不同桶并行，进程级并发仍由
  ``browse_url`` 外层的全局 ``ConcurrencyGuard`` 约束。
- **池上限** LRU 逐出（逐出即 close）；忙碌桶（锁被持有=有在飞 fetch）
  跳过不逐——宁可暂时超限也不拆正在飞行的会话，下次 fetch 再收敛。
- **工厂注入**：会话只经 ``_new_session``（或构造参数 ``session_factory``）
  创建；测试注入 FakeSession，绝不启动真浏览器。生产工厂惰性导入
  scrapling（保持 _scrapling.py 的惰性导入惯例），构造时不钉
  timeout/page_action（二者是逐次 fetch 参数）。

Import 约定：本模块属 daemon 侧；模块级只留轻依赖（asyncio/time/
tldextract/urllib），scrapling 与项目内重模块（``_fetcher`` 的挑战页
谓词）一律调用期惰性导入——``_scrapling`` 会在模块级 import 本模块，
模块级反向依赖会成环。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from typing import Any, Callable, Optional
from urllib.parse import urlsplit

import tldextract

logger = logging.getLogger("scrapling_fetch_mcp.daemon.pool")

# 时钟经模块级引用注入：测试 monkeypatch pool._clock 控制时间流逝，
# 不动全局 time.monotonic（asyncio 内部同样依赖它）。
_clock: Callable[[], float] = time.monotonic

# 只用内置公开后缀快照，零网络依赖（daemon 可能离线运行）；trafilatura
# 已带入 tldextract，无新增安装负担。
_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=())


def _registered_domain(ext: tldextract.ExtractResult) -> str:
    """注册域名（eTLD+1）。新版本属性名变更后仍保持同语义。"""
    top = getattr(ext, "top_domain_under_public_suffix", None)
    if top is not None:
        return top
    return ext.registered_domain  # 旧版 API 兜底（简报钉死的语义）


def bucket_key(url: str, mode: str) -> tuple[str, str]:
    """桶键：解析不出注册域名时退回 netloc（localhost:port、纯 IP 等）。"""
    ext = _EXTRACTOR(url)
    return (_registered_domain(ext) or urlsplit(url).netloc, mode)


async def _new_session(mode: str) -> Any:
    """按 ``_do_browse`` 两分支的启动 kwargs 构造并进入会话。

    timeout/page_action 不在构造时钉死：scrapling 的
    ``AsyncStealthySession.fetch`` 支持逐次覆盖，池的每次 fetch 按调用
    传入（与直连 ``StealthyFetcher.async_fetch`` 语义一致）。构造本身不
    拉浏览器，``__aenter__`` 才创建（同 scrapling ``async with`` 生命周期）。
    """
    from scrapling.engines._browsers._camoufox import AsyncStealthySession

    kwargs: dict[str, Any] = {"headless": True, "network_idle": True}
    if mode == "max-stealth":
        kwargs.update(
            block_webrtc=True,
            disable_resources=False,
            block_images=False,
        )
    session = AsyncStealthySession(**kwargs)
    await session.__aenter__()
    return session


async def _close_session(session: Any) -> None:
    """关闭会话：失败只记日志不反噬调用方（会话即将被丢弃）。"""
    try:
        await session.close()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.warning("池化会话关闭失败", exc_info=True)


def _looks_suspicious(response: Any) -> bool:
    """挑战页检测：委托 _fetcher 管线的可复用谓词（惰性导入防环）。

    检测本身失败（畸形响应等）按"不疑似"处理：挑战页的信号（正文极短）
    是强信号，检测异常不该销毁正常会话。
    """
    from scrapling_fetch_mcp._fetcher import looks_suspicious

    try:
        return looks_suspicious(response)
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.debug("挑战页检测失败, 按不疑似处理", exc_info=True)
        return False


class _Bucket:
    """一个 (域名, mode) 桶：持有一个会话与归属计数。"""

    __slots__ = ("session", "created_at", "last_used", "requests")

    def __init__(self, session: Any) -> None:
        self.session = session
        now = _clock()
        self.created_at = now
        self.last_used = now
        self.requests = 0


class BrowserPool:
    """按 (域名, mode) 分桶的浏览器会话池。

    会话经注入工厂创建；同桶 fetch 串行（桶锁），不同桶并行；池深超限
    LRU 逐出。``close_all`` 供 daemon 空闲退出/版本重拉前统一销毁。
    """

    def __init__(
        self,
        idle_ttl: float,
        max_age: float,
        max_sessions: int,
        max_requests: int,
        *,
        session_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._idle_ttl = idle_ttl
        self._max_age = max_age
        self._max_sessions = max_sessions
        self._max_requests = max_requests
        # 默认取模块级工厂；测试可 monkeypatch pool._new_session 后以缺省
        # 参数构造（本行在构造期解析模块全局，命中的是 patch 后的版本），
        # 或经 session_factory 参数直接注入
        self._session_factory = session_factory if session_factory is not None else _new_session
        # 桶索引：OrderedDict 保持 LRU 序（尾=最近使用，头=最久未用）
        self._buckets: "OrderedDict[tuple[str, str], _Bucket]" = OrderedDict()
        # 桶锁按桶键登记；桶销毁后锁条目保留——等待者可能还挂在锁上，
        # 空锁条目仅几十字节，域名数量级下可忽略（close_all 一并清空）
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._hits = 0
        self._misses = 0

    # ---------- 对外接口 ----------

    async def fetch(
        self,
        url: str,
        mode: str,
        timeout_ms: int,
        page_action: Optional[Callable] = None,
    ) -> Any:
        """经桶化会话抓取；返回 scrapling Response（或工厂定义的响应对象）。"""
        key = bucket_key(url, mode)
        lock = self._locks.get(key)
        if lock is None:
            lock = self._locks[key] = asyncio.Lock()  # 纯字典操作,无 await,天然原子
        async with lock:
            bucket = self._buckets.get(key)
            if bucket is not None and self._needs_rebuild(bucket):
                await self._drop(key, bucket)
                bucket = None
            if bucket is None:
                self._misses += 1
                bucket = await self._build(key, mode)
            else:
                self._hits += 1
            try:
                response = await bucket.session.fetch(
                    url, timeout=timeout_ms, page_action=page_action
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                # 出过错的会话身份不可复用：销毁后原样 re-raise
                await self._drop(key, bucket)
                raise
            bucket.requests += 1
            bucket.last_used = _clock()
            self._buckets.move_to_end(key)  # LRU touch
            if _looks_suspicious(response):
                # 疑似挑战页：响应照常交付（管线可走仲裁），身份立即销毁
                logger.info("响应疑似挑战页, 销毁池化会话 (%s)", key[0])
                await self._drop(key, bucket)
            return response

    async def close_all(self) -> None:
        """销毁全部桶（无在飞 fetch 时调用：daemon 退出/重拉前收口）。"""
        for key, bucket in list(self._buckets.items()):
            del self._buckets[key]
            await _close_session(bucket.session)
        self._locks.clear()

    def stats(self) -> dict:
        """池概况：活跃会话数、命中/未命中、各桶域名（LRU 序）。"""
        return {
            "sessions": len(self._buckets),
            "hits": self._hits,
            "misses": self._misses,
            "buckets": [key[0] for key in self._buckets],
        }

    # ---------- 内部机制 ----------

    def _needs_rebuild(self, bucket: _Bucket) -> bool:
        """命中判定：桶存在且未触发任一重建条件才复用（阈值严格大于）。"""
        now = _clock()
        return (
            now - bucket.last_used > self._idle_ttl
            or now - bucket.created_at > self._max_age
            or bucket.requests > self._max_requests
        )

    async def _build(self, key: tuple[str, str], mode: str) -> _Bucket:
        await self._evict_if_full()
        session = await self._session_factory(mode)
        bucket = _Bucket(session)
        self._buckets[key] = bucket
        return bucket

    async def _evict_if_full(self) -> None:
        """池满先逐出 LRU 空闲桶；忙碌桶跳过（不拆在飞会话），全忙则暂超限。"""
        while len(self._buckets) >= self._max_sessions:
            for bkey, bucket in self._buckets.items():  # 头部=最久未用优先
                lock = self._locks.get(bkey)
                if lock is not None and lock.locked():
                    continue
                logger.info("池满 LRU 逐出会话 (%s)", bkey[0])
                await self._drop(bkey, bucket)
                break
            else:
                break  # 全部忙碌：放弃逐出，接受暂时超限

    async def _drop(self, key: tuple[str, str], bucket: _Bucket) -> None:
        """销毁桶：移出索引并 close 会话（逐出/重建/异常/疑似共用）。"""
        if self._buckets.get(key) is not bucket:
            return  # 已被其他路径替换/移除，不动现桶
        del self._buckets[key]
        await _close_session(bucket.session)
