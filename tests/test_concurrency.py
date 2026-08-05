"""Tests for ConcurrencyGuard."""
import asyncio

import pytest

from scrapling_fetch_mcp._concurrency import ConcurrencyGuard, ConcurrencyLimitError


class TestConcurrencyGuard:
    @pytest.mark.asyncio
    async def test_allows_up_to_max_concurrent(self):
        guard = ConcurrencyGuard(max_concurrent=2, acquire_timeout=1.0)
        seen_in_flight = []

        async def hold():
            async with guard:
                seen_in_flight.append(guard.in_flight)

        await asyncio.gather(hold(), hold())
        assert max(seen_in_flight) <= 2
        assert guard.total_acquired == 2
        assert guard.in_flight == 0

    @pytest.mark.asyncio
    async def test_blocks_beyond_max(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=1.0)
        started = asyncio.Event()
        proceed = asyncio.Event()

        async def hold():
            async with guard:
                started.set()
                await proceed.wait()

        holder = asyncio.create_task(hold())
        await started.wait()

        entered = asyncio.Event()

        async def waiter():
            async with guard:
                entered.set()

        waiter_task = asyncio.create_task(waiter())
        await asyncio.sleep(0.05)
        assert not entered.is_set()
        assert guard.in_flight == 1

        proceed.set()
        await asyncio.gather(holder, waiter_task)
        assert guard.total_acquired == 2

    @pytest.mark.asyncio
    async def test_timeout_raises_concurrency_limit_error(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=0.05)
        proceed = asyncio.Event()

        async def hold():
            async with guard:
                await proceed.wait()

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.01)

        with pytest.raises(ConcurrencyLimitError):
            async with guard:
                pass

        proceed.set()
        await holder

    @pytest.mark.asyncio
    async def test_exception_releases_slot(self):
        guard = ConcurrencyGuard(max_concurrent=1, acquire_timeout=1.0)

        with pytest.raises(RuntimeError):
            async with guard:
                raise RuntimeError("boom")

        assert guard.in_flight == 0
        async with guard:
            assert guard.in_flight == 1
        assert guard.in_flight == 0

    def test_invalid_construction(self):
        with pytest.raises(ValueError):
            ConcurrencyGuard(max_concurrent=0, acquire_timeout=1.0)
        with pytest.raises(ValueError):
            ConcurrencyGuard(max_concurrent=1, acquire_timeout=-1.0)
