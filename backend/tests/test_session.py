"""
Phase 1 tests — Session (stateful twin + feedback loop).

Run from the backend/ directory:
    pytest tests/

Sensor arithmetic used in fixtures
-----------------------------------
NORMAL_SENSORS
  CO   = 72 * (0.55 * 120) / 1000  = 4.75 L/min  (target 5.0 ± 1.5  ✓)
  SV   = 0.55 * 120                 = 66 mL        (target 70 ± 15    ✓)
  MAP  = (1/3)*120 + (2/3)*80       = 93.3 mmHg    (target 85 ± 15    ✓)
  λ    = sqrt(1600 / 400)           = 2.0 mm       (target 2.0 ± 0.5  ✓)

ABNORMAL_SENSORS (HR=160, EDV=180)
  CO   = 160 * (0.55 * 180) / 1000 = 15.84 L/min  (target 5.0 ± 1.5  ✗)
  → CO_DEVIATION tag guaranteed to fire; kernel state guaranteed to grow.
"""

import pytest
from session import Session

# ── Sensor fixtures ──────────────────────────────────────────────────

NORMAL_SENSORS: dict[str, float] = {
    "SBP": 120.0,
    "DBP":  80.0,
    "HR":   72.0,
    "EDV": 120.0,
    "r":    0.50,
    "eta":  3.5,
    "L":   40.0,
    "r_m": 1600.0,   # lambda = sqrt(1600/400) = 2.0 mm  (on target)
    "r_i":  200.0,
    "r_e":  200.0,
}

ABNORMAL_SENSORS: dict[str, float] = {
    **NORMAL_SENSORS,
    "HR":  160.0,   # high HR → CO far above target → guaranteed tag fire
    "EDV": 180.0,
}


# ── Snapshot shape ───────────────────────────────────────────────────

def test_tick_returns_expected_keys():
    """tick() result contains all required top-level keys."""
    session = Session(NORMAL_SENSORS)
    snap = session.tick(NORMAL_SENSORS)
    for key in ("sensors", "computed", "vectors", "outcomes",
                "feedback_norm", "cycle_report"):
        assert key in snap, f"Missing key in tick() snapshot: '{key}'"


def test_tick_sensor_value_propagates():
    """After a tick with updated HR, value_external reflects the new reading."""
    session = Session(NORMAL_SENSORS)
    updated = {**NORMAL_SENSORS, "HR": 140.0}
    snap = session.tick(updated)
    assert snap["sensors"]["HR"]["value_external"] == pytest.approx(140.0)


# ── Feedback loop activation ─────────────────────────────────────────

def test_abnormal_sensors_trigger_tags():
    """CO far above target → at least one tag emits on the first tick."""
    session = Session(ABNORMAL_SENSORS)
    snap = session.tick(ABNORMAL_SENSORS)
    assert len(snap["cycle_report"]["tags_emitted"]) > 0, (
        "Expected at least one tag to fire with CO ≈ 15.8 L/min "
        "(target 5.0 ± 1.5)"
    )


def test_kernel_state_accumulates_after_tick():
    """_kernel_state is empty before the first tick and non-empty after."""
    session = Session(ABNORMAL_SENSORS)
    assert len(session.controller._kernel_state) == 0

    session.tick(ABNORMAL_SENSORS)

    assert len(session.controller._kernel_state) > 0


def test_kernel_state_persists_across_ticks():
    """_kernel_state is NOT wiped between tick() calls."""
    session = Session(ABNORMAL_SENSORS)
    session.tick(ABNORMAL_SENSORS)
    keys_after_tick1 = set(session.controller._kernel_state.keys())

    session.tick(ABNORMAL_SENSORS)

    # Keys from tick 1 survive into tick 2 (decay, not wipe).
    assert keys_after_tick1.issubset(session.controller._kernel_state.keys())


# ── Reset ────────────────────────────────────────────────────────────

def test_reset_clears_kernel_state_and_cycle():
    """reset() empties _kernel_state and restarts the cycle counter."""
    session = Session(ABNORMAL_SENSORS)
    for _ in range(5):
        session.tick(ABNORMAL_SENSORS)
    assert len(session.controller._kernel_state) > 0
    assert session.controller.cycle == 5

    session.reset()

    assert len(session.controller._kernel_state) == 0
    assert session.controller.cycle == 0


def test_reset_zeros_value_feedback():
    """After reset(), every attribute's value_feedback is exactly 0."""
    session = Session(ABNORMAL_SENSORS)
    for _ in range(5):
        session.tick(ABNORMAL_SENSORS)

    session.reset()

    for attr_id, attr in session.twin.attributes.items():
        assert attr.value_feedback == pytest.approx(0.0), (
            f"{attr_id}.value_feedback = {attr.value_feedback} after reset()"
        )


# ── Settling behaviour ────────────────────────────────────────────────

def test_feedback_norm_stabilises_with_fixed_inputs():
    """
    Running 60 ticks with fixed abnormal inputs should stabilise the
    feedback norm — bounded correction, not runaway divergence.

    Note: with HR=160/EDV=180 the loop cannot fully reach target CO
    (a_max caps the correction), so the norm settles at a nonzero
    plateau rather than zero.  We verify the plateau is stable
    (spread over the final 20 ticks < 2.0).
    """
    session = Session(ABNORMAL_SENSORS)
    norms: list[float] = []
    for _ in range(60):
        snap = session.tick(ABNORMAL_SENSORS)
        norms.append(snap["feedback_norm"])

    late = norms[40:]
    spread = max(late) - min(late)
    assert spread < 2.0, (
        f"Feedback norm did not stabilise. "
        f"Spread over ticks 40-60: {spread:.4f}  "
        f"(values: {[round(n, 3) for n in late]})"
    )
