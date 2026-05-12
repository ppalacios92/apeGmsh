"""Dispatcher Phase 2 perf + correctness gates.

Covers the new ``subscribe()`` / ``Lane`` surface added in Phase 2:

* RENDER lane fires synchronously, every event, no coalesce.
* UI lane defers via injected ``defer_fn``; coalesce collapses N
  same-key events to one call with the last payload.
* ``session_batch`` queues UI fires (coalesced) during suppression
  and drains them on exit.
* Storm bench: 1000 STEP_CHANGED with coalesce=True invokes the
  handler at most once per flush.

The bench is marked ``@pytest.mark.bench`` so it stays opt-in
(``pytest -m bench``); correctness tests run by default.
"""
from __future__ import annotations

import time
from typing import Any, Callable

import pytest

from apeGmsh.viewers.diagrams._dispatch import (
    DIAGRAM_ATTACHED,
    Dispatcher,
    GEOMETRIES_CHANGED,
    Lane,
    STEP_CHANGED,
)


# ---------------------------------------------------------------------
# Fixture — a Dispatcher wired to no-op pumps + a manual defer queue.
# ---------------------------------------------------------------------

class _Recorder:
    """Records UI flushes posted via defer_fn so tests can drain manually."""
    def __init__(self) -> None:
        self.pending: list[Callable[[], None]] = []

    def __call__(self, fn: Callable[[], None]) -> None:
        self.pending.append(fn)

    def drain(self) -> int:
        n = len(self.pending)
        queue, self.pending = self.pending, []
        for fn in queue:
            fn()
        return n


@pytest.fixture
def dispatcher_and_defer():
    """Headless dispatcher with no-op pumps + recorded defer_fn."""
    defer = _Recorder()
    calls: dict[str, int] = {"step": 0, "deform": 0, "gate": 0, "restack": 0, "render": 0}

    def _pump_step(_layer):  calls["step"]    += 1
    def _pump_deform(_layer): calls["deform"]  += 1
    def _pump_gate():        calls["gate"]    += 1
    def _pump_restack():     calls["restack"] += 1
    def _render():           calls["render"]  += 1

    d = Dispatcher(
        director=object(),
        pump_step=_pump_step,
        pump_deform=_pump_deform,
        pump_gate=_pump_gate,
        pump_restack=_pump_restack,
        render=_render,
        defer_fn=defer,
    )
    return d, defer, calls


# ---------------------------------------------------------------------
# Correctness — lanes
# ---------------------------------------------------------------------

def test_render_lane_fires_synchronously(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[tuple[str, Any]] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append((k, p)),
        lane=Lane.RENDER,
    )
    d.fire(STEP_CHANGED, payload=7)
    assert received == [(STEP_CHANGED, 7)]
    # Nothing posted to the UI queue.
    assert defer.pending == []


def test_render_lane_fires_every_event_no_coalesce(dispatcher_and_defer):
    d, _, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.RENDER,
    )
    for i in range(50):
        d.fire(STEP_CHANGED, payload=i)
    assert received == list(range(50))


def test_ui_lane_defers_until_flush(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.UI, coalesce=False,
    )
    d.fire(STEP_CHANGED, payload="a")
    # Handler not called yet — queued, but defer_fn hasn't been drained.
    assert received == []
    # One singleShot scheduled.
    assert len(defer.pending) == 1
    defer.drain()
    assert received == ["a"]


def test_ui_lane_coalesce_last_wins(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.UI, coalesce=True,
    )
    for i in range(1000):
        d.fire(STEP_CHANGED, payload=i)
    # Only one flush scheduled regardless of how many fires we issued.
    assert len(defer.pending) == 1
    defer.drain()
    assert received == [999]


def test_ui_lane_coalesce_keyed_by_payload(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.UI, coalesce=True, key_fn=lambda p: p["group"],
    )
    d.fire(STEP_CHANGED, payload={"group": "A", "n": 1})
    d.fire(STEP_CHANGED, payload={"group": "B", "n": 2})
    d.fire(STEP_CHANGED, payload={"group": "A", "n": 3})
    d.fire(STEP_CHANGED, payload={"group": "B", "n": 4})
    defer.drain()
    # Two groups → two distinct flush entries, each carrying last value.
    assert received == [{"group": "A", "n": 3}, {"group": "B", "n": 4}]


def test_ui_lane_no_coalesce_preserves_all_events(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.UI, coalesce=False,
    )
    for i in range(5):
        d.fire(STEP_CHANGED, payload=i)
    defer.drain()
    assert received == [0, 1, 2, 3, 4]


def test_unsubscribe(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    unsub = d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.RENDER,
    )
    d.fire(STEP_CHANGED, payload=1)
    unsub()
    d.fire(STEP_CHANGED, payload=2)
    assert received == [1]


def test_multi_kind_subscribe(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[str] = []
    d.subscribe(
        [STEP_CHANGED, GEOMETRIES_CHANGED],
        lambda k, p: received.append(k),
        lane=Lane.RENDER,
    )
    d.fire(STEP_CHANGED)
    d.fire(GEOMETRIES_CHANGED)
    assert received == [STEP_CHANGED, GEOMETRIES_CHANGED]


# ---------------------------------------------------------------------
# Correctness — session_batch cooperation
# ---------------------------------------------------------------------

def test_session_batch_drains_ui_queue_on_exit(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.UI, coalesce=True,
    )
    with d.session_batch():
        for i in range(100):
            d.fire(STEP_CHANGED, payload=i)
        # Inside the batch — UI handler is NOT called yet, no flush
        # has been scheduled (the batch owns flushing on exit).
        assert received == []
        assert defer.pending == []
    # On exit, last-wins value got dispatched.
    assert received == [99]


def test_session_batch_render_lane_suppressed_during_block(dispatcher_and_defer):
    d, _, _ = dispatcher_and_defer
    received: list[Any] = []
    d.subscribe(
        STEP_CHANGED, lambda k, p: received.append(p),
        lane=Lane.RENDER,
    )
    with d.session_batch():
        d.fire(STEP_CHANGED, payload=1)
        # RENDER lane fires only inside the non-suppressed path; during
        # a batch the early-return suppresses it.
        assert received == []


# ---------------------------------------------------------------------
# Bench gate — 1000 fires with coalesce must collapse to one handler
# invocation per flush (this is the storm-mitigation contract).
# ---------------------------------------------------------------------

@pytest.mark.bench
def test_coalesce_storm_1000_fires_one_invocation(dispatcher_and_defer):
    d, defer, _ = dispatcher_and_defer
    n_invocations = [0]

    def _handler(kind, payload):
        n_invocations[0] += 1

    d.subscribe(
        STEP_CHANGED, _handler, lane=Lane.UI, coalesce=True,
    )

    n = 1000
    t0 = time.perf_counter()
    for i in range(n):
        d.fire(STEP_CHANGED, payload=i)
    fire_ms = (time.perf_counter() - t0) * 1000.0
    print(f"\n{n} fires + coalesce queued in {fire_ms:.2f} ms")

    n_flushes = defer.drain()
    print(f"flushes drained: {n_flushes}, handler invocations: {n_invocations[0]}")

    # Core invariant — the storm collapsed to a single handler call.
    assert n_invocations[0] <= n_flushes
    assert n_invocations[0] == 1
    # Speed gate — queueing 1000 events shouldn't cost more than 50 ms
    # on any sane machine; this catches accidental O(N^2) regressions.
    assert fire_ms < 50.0, f"fire loop took {fire_ms:.2f} ms (>50 ms gate)"


@pytest.mark.bench
def test_render_lane_storm_1000_invocations_under_50ms(dispatcher_and_defer):
    """RENDER lane has NO coalesce — every fire invokes the handler.

    This bench locks in the speed of the synchronous path: 1000
    invocations of a no-op handler should still complete in <50 ms on
    a development machine. Catches regressions in fire() overhead.
    """
    d, _, _ = dispatcher_and_defer
    n_invocations = [0]

    def _handler(kind, payload):
        n_invocations[0] += 1

    d.subscribe(STEP_CHANGED, _handler, lane=Lane.RENDER)

    n = 1000
    t0 = time.perf_counter()
    for i in range(n):
        d.fire(STEP_CHANGED, payload=i)
    elapsed = (time.perf_counter() - t0) * 1000.0
    print(f"\nRENDER lane: {n} fires + invocations in {elapsed:.2f} ms")

    assert n_invocations[0] == n
    assert elapsed < 50.0, f"RENDER storm took {elapsed:.2f} ms (>50 ms gate)"
