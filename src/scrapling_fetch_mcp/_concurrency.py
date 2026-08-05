"""Concurrency control: semaphore-based limiting for browser fetch operations."""

import asyncio


class ConcurrencyLimitError(Exception):
    """Raised when a fetch cannot acquire a concurrency slot within the timeout."""


class ConcurrencyGuard:
    """Limit how many fetch/browser operations run at once.

    Requests beyond ``max_concurrent`` wait up to ``acquire_timeout`` seconds;
    on timeout they raise :class:`ConcurrencyLimitError`. Designed for a single
    asyncio event loop (the stdio and streamable-http transports both run on
    one). ``in_flight`` / ``total_acquired`` are exposed for observability.
    """

    def __init__(self, max_concurrent: int, acquire_timeout: float):
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if acquire_timeout < 0:
            raise ValueError("acquire_timeout must be >= 0")
        self._max = max_concurrent
        self._timeout = acquire_timeout
        self._sem = asyncio.Semaphore(max_concurrent)
        self.in_flight = 0
        self.total_acquired = 0

    async def __aenter__(self) -> "ConcurrencyGuard":
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._timeout)
        except asyncio.TimeoutError:
            raise ConcurrencyLimitError(
                f"并发已达上限({self._max})，等待 {self._timeout}s 超时"
            )
        self.in_flight += 1
        self.total_acquired += 1
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.in_flight -= 1
        self._sem.release()
