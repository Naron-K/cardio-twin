"""
Phase 3 tests — WebSocket transport (/ws/feedback).

Run from the backend/ directory:
    pytest tests/

Uses FastAPI's synchronous TestClient which runs the ASGI app in a
background thread with its own event loop.  The ticker task runs inside
that loop; receive_json() blocks the test until the ticker fires.

All tests use tick_ms=20 (50 Hz) to keep wall-clock time short while
still exercising the real async timing path.

Naming convention for the 'reset cycle' test
---------------------------------------------
After session.reset() the cycle counter goes to 0.  The NEXT step()
call increments it to 1.  There may be one in-flight tick from before
the reset message was processed, so we collect a short burst and check
that the minimum cycle seen is 1 — i.e. the reset definitely happened.
"""

import pytest
from fastapi.testclient import TestClient

from main import app

_FAST = "/ws/feedback?tick_ms=20"


# ── Snapshot structure ───────────────────────────────────────────────

def test_ws_snapshot_has_required_keys():
    """First snapshot contains all top-level keys the frontend expects."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            snap = ws.receive_json()

    for key in ("sensors", "computed", "vectors", "outcomes",
                "feedback_norm", "cycle_report"):
        assert key in snap, f"Missing key in snapshot: '{key}'"


def test_ws_cycle_report_has_expected_fields():
    """cycle_report sub-dict contains all fields emitted by FeedbackController."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            snap = ws.receive_json()

    cr = snap["cycle_report"]
    for field in ("cycle", "tags_emitted", "deltas_per_attr",
                  "feedback_norm", "diverged", "snapped"):
        assert field in cr, f"Missing cycle_report field: '{field}'"


def test_ws_cycle_counter_increments():
    """Cycle number increases by 1 on every tick."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            cycles = [ws.receive_json()["cycle_report"]["cycle"] for _ in range(5)]

    for i in range(1, len(cycles)):
        assert cycles[i] == cycles[i - 1] + 1, (
            f"Cycle jumped unexpectedly: {cycles}"
        )


def test_ws_sensors_present_in_snapshot():
    """All 10 sensor attrs (HR, SBP, DBP, …) appear in the sensors dict."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            snap = ws.receive_json()

    expected = {"SBP", "DBP", "HR", "EDV", "r", "eta", "L", "r_m", "r_i", "r_e"}
    assert expected.issubset(snap["sensors"].keys())


# ── Control messages ─────────────────────────────────────────────────

def test_ws_inject_arrhythmia_raises_feedback_norm():
    """
    inject_arrhythmia raises feedback_norm above the stable baseline.

    magnitude=50 → HR ≈ 122 bpm → CO ≈ 8 L/min (above 6.5 tolerance) →
    CO_DEVIATION fires → feedback_norm > 0.
    """
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            # Drain 5 baseline ticks
            norms_before = [ws.receive_json()["feedback_norm"] for _ in range(5)]
            avg_before = sum(norms_before) / len(norms_before)

            ws.send_json({"type": "inject_arrhythmia",
                          "magnitude": 50.0, "decay": 0.15})

            # Collect 8 ticks — at least one should show loop response
            norms_after = [ws.receive_json()["feedback_norm"] for _ in range(8)]
            peak_after = max(norms_after)

    assert peak_after > avg_before, (
        f"Feedback norm should rise after arrhythmia: "
        f"avg_before={avg_before:.4f}  peak_after={peak_after:.4f}"
    )


def test_ws_set_sensor_changes_hr():
    """
    set_sensor with id=HR updates source baseline: subsequent snapshots
    show the new HR value_external.
    """
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.receive_json()  # drain one tick before sending control

            ws.send_json({"type": "set_sensor", "id": "HR", "value": 150.0})

            hr_values = [
                ws.receive_json()["sensors"]["HR"]["value_external"]
                for _ in range(5)
            ]

    # With noise sigma=1 bpm, any reading from the new baseline should be > 140.
    assert max(hr_values) > 140.0, (
        f"Expected HR near 150 after set_sensor, got max={max(hr_values):.2f}"
    )


def test_ws_reset_restarts_cycle():
    """
    After sending reset, the cycle counter restarts from 1.

    We advance to cycle ≥ 10, send reset, then collect 4 ticks and
    verify that at least one has cycle == 1 (the post-reset tick).
    """
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            # Advance well past cycle 1
            for _ in range(10):
                ws.receive_json()
            cycle_high = ws.receive_json()["cycle_report"]["cycle"]
            assert cycle_high >= 10, f"Expected cycle ≥ 10, got {cycle_high}"

            ws.send_json({"type": "reset"})

            # Within 4 ticks the reset must have taken effect.
            post_cycles = [
                ws.receive_json()["cycle_report"]["cycle"] for _ in range(4)
            ]

    assert min(post_cycles) == 1, (
        f"Expected cycle=1 after reset; got cycles={post_cycles}"
    )


def test_ws_pause_and_resume():
    """
    pause stops the ticker; resume restarts it.

    We send pause, confirm no message arrives for ~200 ms, then resume
    and confirm messages flow again.  Because TestClient's receive_json()
    is blocking, we use a short timeout via threading.
    """
    import queue
    import threading

    received: list[dict] = []
    timed_out = threading.Event()

    def _drain(ws, n: int, timeout: float) -> None:
        q: queue.Queue = queue.Queue()

        def _recv():
            for _ in range(n):
                try:
                    q.put(ws.receive_json())
                except Exception:
                    break

        t = threading.Thread(target=_recv, daemon=True)
        t.start()
        t.join(timeout)
        while not q.empty():
            received.append(q.get_nowait())
        if t.is_alive():
            timed_out.set()

    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            # Let a few ticks through first
            for _ in range(3):
                ws.receive_json()

            # Pause
            ws.send_json({"type": "pause"})

            # Try to receive 2 messages with 200ms timeout — should time out
            _drain(ws, 2, timeout=0.25)
            paused_ok = timed_out.is_set()

            # Resume
            ws.send_json({"type": "resume"})

            # Now messages should flow again
            resumed_snaps = [ws.receive_json() for _ in range(3)]

    assert paused_ok, "Expected no messages during pause but received some"
    assert len(resumed_snaps) == 3, "Expected messages after resume"


# ── Session isolation ────────────────────────────────────────────────

def test_ws_two_connections_are_independent():
    """
    Two concurrent connections have isolated Sessions: reset on ws1
    does not affect ws2's cycle counter.
    """
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws1:
            with client.websocket_connect(_FAST) as ws2:
                # Let both advance past cycle 5
                for _ in range(6):
                    ws1.receive_json()
                    ws2.receive_json()

                snap2_before = ws2.receive_json()
                cycle2_before = snap2_before["cycle_report"]["cycle"]

                # Reset ws1 only
                ws1.send_json({"type": "reset"})

                # Collect post-reset ticks from both
                post_ws1 = [ws1.receive_json()["cycle_report"]["cycle"]
                            for _ in range(4)]
                post_ws2 = [ws2.receive_json()["cycle_report"]["cycle"]
                            for _ in range(4)]

    # ws1 should have restarted from 1
    assert min(post_ws1) == 1, (
        f"ws1 cycle should have reset to 1, got {post_ws1}"
    )
    # ws2 should keep incrementing from where it was — never saw cycle 1 again
    assert min(post_ws2) > cycle2_before, (
        f"ws2 cycle should keep growing: before={cycle2_before}, after={post_ws2}"
    )


# ── Clean disconnect ──────────────────────────────────────────────────

def test_ws_disconnect_does_not_hang():
    """Exiting the websocket_connect context closes cleanly (no hang)."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.receive_json()   # at least one tick before disconnect
        # Context manager exit → CLOSE frame → ticker cancelled.
        # If this test completes, disconnect is clean.
