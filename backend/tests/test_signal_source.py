"""
Phase 2 tests — SimulatedSource.

Run from the backend/ directory:
    pytest tests/

The feed used to carry its own tables of ranges, baselines and noise for the
ten circulatory sensors.  It now reads all three off whichever lamina it is
handed, so these tests assert against the lamina rather than against a constant
this file imports — which is the property worth protecting.
"""

import pytest

from laminae import load_twin
from session import Session
from signal_source import SimulatedSource

_LAMINA = "circulatory_lamina.xml"


@pytest.fixture
def twin():
    return load_twin(_LAMINA)


def _zero_noise(twin) -> dict[str, float]:
    return {attr_id: 0.0 for attr_id in twin.list_attributes("SENSOR")}


# ── Basic interface ──────────────────────────────────────────────────

def test_next_returns_every_declared_sensor(twin):
    """next() emits one reading per SENSOR attribute the lamina declares."""
    source = SimulatedSource(twin, seed=42)
    assert set(source.next().keys()) == set(twin.list_attributes("SENSOR"))


def test_next_values_within_declared_range(twin):
    """20 consecutive ticks stay inside each attribute's declared range."""
    source = SimulatedSource(twin, seed=0)
    for tick in range(20):
        for sensor_id, value in source.next().items():
            attr = twin.attributes[sensor_id]
            assert attr.physio_min <= value <= attr.physio_max, (
                f"tick={tick} {sensor_id}={value:.4f} outside "
                f"[{attr.physio_min}, {attr.physio_max}]"
            )


def test_noise_produces_variation(twin):
    """Default noise gives different readings on consecutive ticks."""
    source = SimulatedSource(twin)   # unseeded live RNG
    values = [source.next()["HR"] for _ in range(15)]
    assert len(set(values)) > 1, (
        "All 15 HR readings are identical — noise appears to be off"
    )


def test_seeded_source_is_reproducible(twin):
    """Two instances with the same seed produce identical tick streams."""
    a = SimulatedSource(twin, seed=7)
    b = SimulatedSource(load_twin(_LAMINA), seed=7)
    for _ in range(8):
        assert a.next() == b.next()


def test_zero_noise_source_emits_the_declared_baseline(twin):
    """With noise off, next() returns exactly what the XML declares."""
    source = SimulatedSource(twin, noise_sigma=_zero_noise(twin), seed=0)
    readings = source.next()
    for sensor_id in twin.list_attributes("SENSOR"):
        expected = twin.attributes[sensor_id].baseline
        assert expected is not None, f"{sensor_id} declares no <baseline>"
        assert readings[sensor_id] == pytest.approx(expected)


def test_baseline_override_beats_the_declaration(twin):
    """An explicit baseline wins over the one in the XML."""
    source = SimulatedSource(
        twin, baseline={"HR": 95.0}, noise_sigma=_zero_noise(twin), seed=0
    )
    assert source.next()["HR"] == pytest.approx(95.0)


def test_undeclared_baseline_falls_back_to_midpoint_and_says_so(twin):
    """A lamina that declares no baseline still runs, and reports that it did."""
    twin.attributes["HR"].baseline = None
    source = SimulatedSource(twin, noise_sigma=_zero_noise(twin), seed=0)
    attr = twin.attributes["HR"]
    assert source.next()["HR"] == pytest.approx((attr.physio_min + attr.physio_max) / 2)
    assert "HR" in source.describe()


# ── End-to-end pipeline ───────────────────────────────────────────────

def test_pipeline_session_tick_accepts_source_output():
    """Session.tick() accepts dict from source.next() without error for 20 ticks."""
    session = Session()
    source = SimulatedSource(session.twin, seed=1)
    session.seed(source.starting_state())
    for _ in range(20):
        snap = session.tick(source.next())
        assert "feedback_norm" in snap
        assert snap["feedback_norm"] >= 0.0


def test_seed_skips_attributes_this_lamina_does_not_declare():
    """A baseline addressed to another lamina is survived, not raised on."""
    session = Session()
    session.seed({"HR": 80.0, "not_an_attribute_here": 1.0})
    assert session.twin.attributes["HR"].value == pytest.approx(80.0)
