"""
Layer 1 tests — domain-agnostic streaming runtime.

Pure asyncio, driven through asyncio.run() so no pytest-asyncio plugin is
needed.  Timings use short real sleeps; thresholds are loose enough to be
stable while still exercising the genuine async timing path (same approach
as the existing WebSocket tests).

Nothing here imports a twin — if the runtime needed domain knowledge these
tests could not be written against opaque integer samples.
"""

import asyncio
import time

from streaming_runtime import LatestWinsMailbox, StreamingRuntime


# ── Mailbox ──────────────────────────────────────────────────────────

def test_mailbox_latest_wins():
    mb = LatestWinsMailbox()
    mb.submit("a")
    mb.submit("b")
    mb.submit("c")            # b was never consumed → dropped
    assert mb.take() == "c"   # only the freshest survives
    assert mb.take() is None  # slot now empty
    assert mb.submitted == 3
    assert mb.dropped == 2


def test_mailbox_consume_then_resubmit():
    mb = LatestWinsMailbox()
    mb.submit(1)
    assert mb.take() == 1
    mb.submit(2)              # slot was empty → not a drop
    assert mb.take() == 2
    assert mb.dropped == 0


# ── Fixed-rate cadence ───────────────────────────────────────────────

def test_runtime_fires_at_fixed_rate():
    async def scenario():
        rt = StreamingRuntime(lambda s: s, period_s=0.02)
        rt.start()
        await asyncio.sleep(0.20)          # ~10 periods
        await rt.stop()
        return rt.cycles

    cycles = asyncio.run(scenario())
    assert 6 <= cycles <= 16, f"expected ~10 cycles, got {cycles}"


def test_runtime_refractory_floors_spacing():
    """With period 0 the loop would spin; the refractory interval imposes a
    hard minimum spacing between cycles (the neuron-cannot-re-fire rule)."""
    async def scenario():
        rt = StreamingRuntime(lambda s: s, period_s=0.0, refractory_s=0.02)
        rt.start()
        await asyncio.sleep(0.20)          # ~10 refractory windows
        await rt.stop()
        return rt.cycles

    cycles = asyncio.run(scenario())
    assert 6 <= cycles <= 16, f"refractory should pace ~10 cycles, got {cycles}"


def test_runtime_runs_even_without_samples():
    """The loop keeps regulating on current state with no new input."""
    async def scenario():
        seen = []
        rt = StreamingRuntime(lambda s: seen.append(s), period_s=0.02)
        rt.start()
        await asyncio.sleep(0.10)
        await rt.stop()
        return seen

    seen = asyncio.run(scenario())
    assert len(seen) >= 3
    assert all(s is None for s in seen)    # every cycle saw an empty mailbox


# ── Coalescing (latest-wins under load) ──────────────────────────────

def test_runtime_coalesces_overlapping_samples():
    """Ingest far faster than the control rate: the controller must see
    only the freshest values, and the mailbox must report drops."""
    async def scenario():
        seen = []
        rt = StreamingRuntime(
            lambda s: seen.append(s) if s is not None else None,
            period_s=0.03,
        )
        rt.start()
        for i in range(20):
            rt.submit(i)
            await asyncio.sleep(0.003)     # 10x faster than the 30ms cycle
        await asyncio.sleep(0.05)
        await rt.stop()
        return seen, rt.mailbox

    seen, mb = asyncio.run(scenario())
    assert mb.submitted == 20
    assert mb.dropped > 0                  # overlapping samples collapsed
    assert len(seen) < 20                  # far fewer cycles than samples
    assert seen == sorted(seen)            # monotonic — always the freshest
    assert seen[-1] >= 17                  # last processed is near the newest


# ── Backpressure / overrun ───────────────────────────────────────────

def test_runtime_slow_cycle_does_not_block_ingestion_when_offloaded():
    """With offload=True a slow synchronous cycle runs off the event loop,
    so ingestion keeps accepting samples while a cycle grinds."""
    async def scenario():
        def slow(_sample):
            time.sleep(0.04)               # blocking 40ms cycle
            return None

        rt = StreamingRuntime(slow, period_s=0.005, offload=True)
        rt.start()
        # Ingest every 5ms for 60ms — if the loop were blocked these
        # submits could not be interleaved with the running cycle.
        for i in range(12):
            rt.submit(i)
            await asyncio.sleep(0.005)
        await rt.stop()
        return rt.mailbox.submitted

    submitted = asyncio.run(scenario())
    assert submitted == 12                 # ingestion never stalled


def test_runtime_overrun_counts_and_bounds_backlog():
    """A cycle slower than its period registers overruns but never builds a
    queue — only the latest sample is ever processed.  Offloaded so the
    slow cycle does not block the fast ingestion that creates the overlap."""
    async def scenario():
        processed = []

        def slow(s):
            time.sleep(0.02)               # 20ms cycle vs 5ms period
            if s is not None:
                processed.append(s)
            return None

        rt = StreamingRuntime(slow, period_s=0.005, offload=True)
        rt.start()
        for i in range(30):
            rt.submit(i)
            await asyncio.sleep(0.002)      # 30 samples over ~60ms
        await asyncio.sleep(0.03)
        await rt.stop()
        return processed, rt

    processed, rt = asyncio.run(scenario())
    assert rt.mailbox.submitted == 30
    assert rt.overruns > 0                       # cycles ran past their period
    # No backlog: only a handful of (freshest) samples were ever processed,
    # the rest coalesced away in the one-slot mailbox.
    assert len(processed) < 30
    assert rt.mailbox.dropped > 0
    assert processed == sorted(processed)        # always the freshest


# ── Emit sink ────────────────────────────────────────────────────────

def test_runtime_emits_only_non_none_results():
    async def scenario():
        emitted = []
        # process returns the sample; None samples produce no emit.
        rt = StreamingRuntime(
            process=lambda s: s,
            emit=lambda r: emitted.append(r),
            period_s=0.02,
        )
        rt.start()
        rt.submit("x")
        await asyncio.sleep(0.05)
        await rt.stop()
        return emitted

    emitted = asyncio.run(scenario())
    assert "x" in emitted
    assert None not in emitted


def test_runtime_supports_async_emit():
    async def scenario():
        emitted = []

        async def aemit(r):
            await asyncio.sleep(0)
            emitted.append(r)

        rt = StreamingRuntime(lambda s: s, emit=aemit, period_s=0.02)
        rt.start()
        rt.submit(42)
        await asyncio.sleep(0.05)
        await rt.stop()
        return emitted

    emitted = asyncio.run(scenario())
    assert 42 in emitted
