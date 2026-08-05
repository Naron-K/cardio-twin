"""
Phase 2 tests — SimulatedCardioSource.

Run from the backend/ directory:
    pytest tests/

Key constants
-------------
_DEFAULT_BASELINE   : healthy resting sensor values (HR=72, CO≈4.75 L/min)
_ZERO_NOISE         : all sigmas=0 — emits the baseline exactly (no noise)
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


# ── End-to-end pipeline ───────────────────────────────────────────────

def test_pipeline_session_tick_accepts_source_output():
    """Session.tick() accepts dict from source.next() without error for 20 ticks."""
    source = SimulatedCardioSource(seed=1)
    session = Session(dict(_DEFAULT_BASELINE))
    for _ in range(20):
        snap = session.tick(source.next())
        assert "feedback_norm" in snap
        assert snap["feedback_norm"] >= 0.0
