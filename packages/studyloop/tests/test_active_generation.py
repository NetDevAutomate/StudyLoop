"""Tests for the active-generation singleton (U2).

Mirrors :file:`test_active_session.py` -- same lock semantics, same
idempotent-release contract. Reading them side-by-side should make the
parallel obvious.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from studyloop.content import active_gen


@pytest_asyncio.fixture(autouse=True)
async def _reset_active_state():
    """Every test starts with no active generation.

    The module is a singleton; leaking state between tests would cause
    GenerationAlreadyActiveError spuriously. release() is idempotent so
    this is safe even on a clean slate.
    """
    await active_gen.release()
    yield
    await active_gen.release()


@pytest.mark.asyncio
class TestAcquire:
    async def test_returns_active_generation_with_request_and_job_id(self) -> None:
        request = {"course": "DataCamp", "kinds": ["flashcards"]}
        active = await active_gen.acquire(job_id="gen-abc", request=request)
        assert active.job_id == "gen-abc"
        assert active.request is request  # stored by reference, no copy
        assert active.cancel_event is not None
        assert not active.cancel_event.is_set()

    async def test_concurrent_acquire_second_caller_raises(self) -> None:
        await active_gen.acquire(job_id="gen-1", request=None)
        with pytest.raises(active_gen.GenerationAlreadyActiveError, match="gen-1"):
            await active_gen.acquire(job_id="gen-2", request=None)

    async def test_acquire_after_release_succeeds(self) -> None:
        await active_gen.acquire(job_id="gen-1", request=None)
        await active_gen.release()
        # Should not raise -- slot is empty.
        active = await active_gen.acquire(job_id="gen-2", request=None)
        assert active.job_id == "gen-2"


@pytest.mark.asyncio
class TestCurrent:
    async def test_returns_none_when_nothing_active(self) -> None:
        assert await active_gen.current() is None

    async def test_returns_active_after_acquire(self) -> None:
        active = await active_gen.acquire(job_id="gen-1", request="payload")
        retrieved = await active_gen.current()
        assert retrieved is active


@pytest.mark.asyncio
class TestRelease:
    async def test_release_clears_slot(self) -> None:
        await active_gen.acquire(job_id="gen-1", request=None)
        await active_gen.release()
        assert await active_gen.current() is None

    async def test_release_when_idle_is_silent_noop(self) -> None:
        # No prior acquire; should not raise.
        await active_gen.release()
        await active_gen.release()
        assert await active_gen.current() is None


@pytest.mark.asyncio
class TestLockSerialisation:
    async def test_two_concurrent_acquires_only_one_wins(self) -> None:
        # Tight race -- both tasks dispatch before either sees the slot
        # filled. asyncio.Lock guarantees serialisation; one wins, one
        # raises. Without the lock, a check-then-set race would let
        # both succeed.
        async def try_acquire(jid: str) -> str | None:
            try:
                a = await active_gen.acquire(job_id=jid, request=None)
                return a.job_id
            except active_gen.GenerationAlreadyActiveError:
                return None

        results = await asyncio.gather(
            try_acquire("gen-A"), try_acquire("gen-B"), return_exceptions=False
        )
        winners = [r for r in results if r is not None]
        assert len(winners) == 1
        assert winners[0] in {"gen-A", "gen-B"}
