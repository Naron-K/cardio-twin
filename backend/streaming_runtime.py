"""
Streaming runtime — Layer 1 of the Adaptive Feedback Loop spec.

Domain-agnostic.  Sits ENTIRELY OUTSIDE the twin; the twin must not know
it exists.  Nothing in this file imports a lamina, a controller, or any
cardiovascular concept — it deals in opaque samples and a `process`
callback.  That is what lets the same runtime wrap any lamina.

The problem it solves (spec §"Layer 1"): in a continuous stream, samples
can arrive faster than one control cycle finishes, so a new sample (T2)
shows up while T1 is still being processed.  Treating every sample as its
own feedback computation builds an unbounded backlog.

The mechanism, four parts:

  Latest-wins mailbox      A single most-recent-value slot.  A newer
                           submit overwrites any unconsumed earlier one,
                           so overlapping signals collapse into one
                           freshest sample instead of queueing.

  Fixed-rate control cycle The controller runs at a steady interval and
                           always acts on the freshest available state —
                           like physiological control integrating over
                           many beats rather than re-planning each one.
                           The cycle fires every period whether or not a
                           new sample arrived (the loop keeps regulating
                           on the current state).

  Refractory interval      A minimum spacing between cycles (by analogy
                           to a neuron that cannot re-fire immediately).
                           Samples arriving within the window are coalesced
                           into the latest value, not each triggering a
                           computation.

  Backpressure / overrun   If a cycle runs longer than its period, drop
                           stale intermediate samples and resume from the
                           latest.  Never accumulate backlog: a late
                           correction on old data is worse than skipping
                           it (drop-and-keep-latest over buffering).

Optionally the cycle runs OFF the event loop (`offload=True`,
loop.run_in_executor) so a slow synchronous cycle cannot block inbound
ingestion — submit() stays responsive while process() grinds.
"""
from __future__ import annotations

import asyncio
import inspect
from typing import Any, Awaitable, Callable, Optional


class LatestWinsMailbox:
    """
    A one-slot mailbox: holds only the most recent submitted sample.

    Not a queue.  submit() overwrites; take() consumes and empties.  This
    is the structural reason overlapping signals can never pile up — there
    is physically room for exactly one pending value.

    Single-event-loop safe: submit() and take() each complete without an
    await, so they never interleave on one loop.  `dropped` counts samples
    overwritten before they were ever consumed (the coalescing rate).
    """

    def __init__(self) -> None:
        self._slot: Any = None
        self._has: bool = False
        self.submitted: int = 0
        self.dropped: int = 0

    def submit(self, sample: Any) -> None:
        self.submitted += 1
        if self._has:
            # An earlier sample was never consumed — it is superseded.
            self.dropped += 1
        self._slot = sample
        self._has = True

    def take(self) -> Optional[Any]:
        """Return the pending sample and empty the slot, or None if empty."""
        if not self._has:
            return None
        sample = self._slot
        self._slot = None
        self._has = False
        return sample

    @property
    def pending(self) -> bool:
        return self._has


class StreamingRuntime:
    """
    Drives a fixed-rate control cycle over a latest-wins mailbox.

    Parameters
    ----------
    process     : called once per cycle with the freshest sample (or None
                  if no new sample arrived).  Returns a result to emit, or
                  None to emit nothing this cycle.  May be sync; with
                  offload=True it is run in a thread executor.
    emit        : optional sink for non-None results.  May be sync or
                  return an awaitable (e.g. websocket.send_json).
    period_s    : fixed control period (the inter-cycle target spacing).
    refractory_s: hard floor on inter-cycle spacing — the loop never fires
                  two cycles closer than this even after an overrun.
    offload     : run process() off the event loop so a slow cycle cannot
                  block ingestion.

    Counters: `cycles` (process calls), `overruns` (cycles that ran longer
    than the period), plus the mailbox's submitted/dropped.
    """

    def __init__(
        self,
        process: Callable[[Optional[Any]], Any],
        emit: Optional[Callable[[Any], Any]] = None,
        *,
        period_s: float,
        refractory_s: float = 0.0,
        offload: bool = False,
    ) -> None:
        self.process = process
        self.emit = emit
        self.period_s = float(period_s)
        self.refractory_s = float(refractory_s)
        self.offload = offload

        self.mailbox = LatestWinsMailbox()
        self.cycles: int = 0
        self.overruns: int = 0

        self._running: bool = False
        self._task: Optional[asyncio.Task] = None

    # ── Ingestion (any rate, never blocks on the cycle) ──────────────

    def submit(self, sample: Any) -> None:
        """Push a sample into the mailbox.  Newer overwrites unconsumed."""
        self.mailbox.submit(sample)

    # ── Control cycle ────────────────────────────────────────────────

    async def _run(self) -> None:
        loop = asyncio.get_event_loop()
        while self._running:
            start = loop.time()

            sample = self.mailbox.take()      # freshest, or None
            if self.offload:
                result = await loop.run_in_executor(None, self.process, sample)
            else:
                result = self.process(sample)
            self.cycles += 1

            if result is not None and self.emit is not None:
                maybe = self.emit(result)
                if inspect.isawaitable(maybe):
                    await maybe

            elapsed = loop.time() - start
            wait = self.period_s - elapsed
            if elapsed > self.period_s:
                # Overrun: the cycle ate its whole budget.  Do not try to
                # "catch up" by firing back-to-back beyond the refractory
                # floor — that is the backlog we are avoiding.  Any samples
                # that arrived meanwhile already coalesced in the mailbox.
                self.overruns += 1
            if wait < self.refractory_s:
                wait = self.refractory_s
            if wait > 0:
                await asyncio.sleep(wait)
            else:
                # Yield control so ingestion / inbound handlers can run
                # even when we are saturated.
                await asyncio.sleep(0)

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> asyncio.Task:
        """Launch the control loop as a background task."""
        if self._task is not None:
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._run())
        return self._task

    async def stop(self) -> None:
        """Stop the loop and await clean cancellation."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    @property
    def running(self) -> bool:
        return self._running and self._task is not None
