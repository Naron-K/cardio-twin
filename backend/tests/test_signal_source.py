"""
Phase 2 tests — SimulatedCardioSource + arrhythmia pipeline.

Run from the backend/ directory:
    pytest tests/

Key constants
-------------
_DEFAULT_BASELINE   : healthy resting sensor values (HR=72, CO≈4.75 L/min)
_ZERO_NOISE         : all sigmas=0 — isolates drift from noise in arrhythmia tests
magnitude=40, decay=0.15:
  tick  1 after inject: HR += 40.0 bpm  → HR ≈ 112 bpm  (CO ≈ 7.4 L/min > 6.5)
  tick 25 after inject: HR += 40×0.85^25 ≈ 0.9 bpm      (< threshold → cleared)
  tick 40 after inject: drift = 0, HR back to 72 bpm
"""

import math

import pytest

from session import Session
from signal_source import (
    SimulatedCardioSource,
    _DEFAULT_BASELINE,
    _DEFAULT_SIGMA,
    _PHYSIO_RANGES,
)

_ZERO_NOISE: dict[str, float] = {k: 0.0 for k in _DEFAULT_BASELINE}


# ── Basic interface ──────────────────────────────────────────────────

def test_next_returns_all_required_sensors():
    """next() dict contains every sensor key the Session expects."""
    source = SimulatedCardioSource(seed=42)
    assert set(source.next().keys()) == set(_DEFAULT_BASELINE.keys())


def test_next_values_within_physio_range():
    """All values from 20 consecutive ticks stay within physiological bounds."""
    source = SimulatedCardioSource(seed=0)
    for tick in range(20):
        for sensor_id, value in source.next().items():
            lo, hi = _PHYSIO_RANGES.get(sensor_id, (-math.inf, math.inf))
            assert lo <= value <= hi, (
                f"tick={tick} {sensor_id}={value:.4f} outside [{lo}, {hi}]"
            )


def test_noise_produces_variation():
    """Default noise gives different HR values on consecutive ticks."""
    source = SimulatedCardioSource()   # unseeded live RNG
    values = [source.next()["HR"] for _ in range(15)]
    assert len(set(values)) > 1, (
        "All 15 HR readings are identical — noise appears to be off"
    )


def test_seeded_source_is_reproducible():
    """Two instances with the same seed produce identical tick streams."""
    a = SimulatedCardioSource(seed=7)
    b = SimulatedCardioSource(seed=7)
    for _ in range(8):
        assert a.next() == b.next()


def test_zero_noise_source_emits_baseline():
    """With noise_sigma all-zero, next() returns exactly the baseline values."""
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE, seed=0)
    readings = source.next()
    for sensor_id, expected in _DEFAULT_BASELINE.items():
        assert readings[sensor_id] == pytest.approx(expected), (
            f"{sensor_id}: expected {expected}, got {readings[sensor_id]}"
        )


# ── Arrhythmia injection ──────────────────────────────────────────────

def test_arrhythmia_elevates_hr_on_first_tick():
    """The very next tick after inject_arrhythmia() raises HR by ~magnitude."""
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE, seed=0)
    baseline_hr = source.next()["HR"]          # pre-injection reading

    source.inject_arrhythmia(magnitude=30.0, decay=0.15)
    elevated_hr = source.next()["HR"]

    assert elevated_hr >= baseline_hr + 28.0, (
        f"Expected HR ≥ baseline+28 bpm; baseline={baseline_hr:.1f}, got={elevated_hr:.1f}"
    )


def test_arrhythmia_decays_monotonically():
    """HR decreases on every tick while drift is active (no noise)."""
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE, seed=0)
    source.inject_arrhythmia(magnitude=30.0, decay=0.15)
    readings = [source.next()["HR"] for _ in range(20)]

    for i in range(1, len(readings)):
        assert readings[i] <= readings[i - 1] + 1e-9, (
            f"HR increased at tick {i}: {readings[i-1]:.4f} → {readings[i]:.4f}"
        )


def test_arrhythmia_decays_to_baseline():
    """HR returns to baseline within 40 ticks with decay=0.15 (no noise)."""
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE, seed=0)
    baseline_hr = _DEFAULT_BASELINE["HR"]

    source.inject_arrhythmia(magnitude=40.0, decay=0.15)
    for _ in range(40):
        final_hr = source.next()["HR"]

    assert final_hr == pytest.approx(baseline_hr, abs=1.0), (
        f"HR drift persisted: final={final_hr:.2f}, baseline={baseline_hr:.1f}"
    )


def test_inject_twice_replaces_drift():
    """A second inject_arrhythmia() call before drift clears resets the magnitude."""
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE, seed=0)
    source.inject_arrhythmia(magnitude=10.0, decay=0.15)
    source.next()  # consume one tick of the first injection

    source.inject_arrhythmia(magnitude=50.0, decay=0.15)
    hr = source.next()["HR"]

    # HR should reflect the NEW magnitude (~50 bpm over baseline), not the
    # decayed remnant of the first injection (~8.5 bpm).
    assert hr >= _DEFAULT_BASELINE["HR"] + 40.0, (
        f"Second injection did not replace first: HR={hr:.1f}"
    )


# ── End-to-end pipeline ───────────────────────────────────────────────

def test_arrhythmia_pipeline_spike_then_recovery():
    """
    Full pipeline: inject arrhythmia → feedback norm rises (loop reacts)
    → norm falls after drift fades (homeostasis re-established).

    Zero noise isolates the arrhythmia signal from background variation.

    Timing (decay=0.15, magnitude=40 bpm at 100 ms/tick if wired up):
      ticks  1–8  : HR ≈ 112–86 bpm  →  CO > 6.5 L/min  →  CO_DEVIATION fires
      ticks  9–15 : HR ≈ 86–67 bpm   →  CO approaching tolerance
      ticks 16–40 : drift < threshold →  HR = 72 bpm  →  loop decays to stable
    """
    source = SimulatedCardioSource(noise_sigma=_ZERO_NOISE)
    session = Session(dict(_DEFAULT_BASELINE))

    # ── Stable phase: 15 ticks before injection ───────────────────────
    for _ in range(15):
        session.tick(source.next())
    stable_norm = session.twin.feedback_norm()

    # ── Injection phase: 8 ticks with active arrhythmia ──────────────
    source.inject_arrhythmia(magnitude=40.0, decay=0.15)
    peak_norm = stable_norm
    for _ in range(8):
        snap = session.tick(source.next())
        if snap["feedback_norm"] > peak_norm:
            peak_norm = snap["feedback_norm"]

    # ── Recovery phase: 40 ticks for drift + kernel to decay ─────────
    for _ in range(40):
        snap = session.tick(source.next())
    recovered_norm = snap["feedback_norm"]

    assert peak_norm > stable_norm, (
        f"Feedback norm should rise after arrhythmia injection: "
        f"stable={stable_norm:.4f}  peak={peak_norm:.4f}"
    )
    assert recovered_norm < peak_norm, (
        f"Feedback norm should recover after drift fades: "
        f"peak={peak_norm:.4f}  recovered={recovered_norm:.4f}"
    )


def test_pipeline_session_tick_accepts_source_output():
    """Session.tick() accepts dict from source.next() without error for 20 ticks."""
    source = SimulatedCardioSource(seed=1)
    session = Session(dict(_DEFAULT_BASELINE))
    for _ in range(20):
        snap = session.tick(source.next())
        assert "feedback_norm" in snap
        assert snap["feedback_norm"] >= 0.0
