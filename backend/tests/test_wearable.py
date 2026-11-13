"""
The fourth lamina, and the lowest one in the stack.

It is a wearable: a device that measures heart rate and activity, knows the
time and the weather, and has to say what it expects from those alone.  What
it cannot explain is reported as a residual rather than corrected away.

WHAT THIS FILE MEASURES

  THE DECLARED BASELINES.  At rest the chain must produce the numbers the
  file was written around: 1.4 kcal/min of energy, a 2.828 bpm circadian
  swing at hour 12, no heat term at the reference temperature, a 5.166 bpm
  activity drive, and a residual of -2.994 bpm between a measured 65 and a
  modelled 67.994.

  THE GUARDS.  A missing or non-finite heart rate must leave HR_measured
  stale rather than quietly computing; a negative activity rate must be
  refused by hr_drive rather than exponentiated into something complex.

  THE CLAMP.  However the drives move, HR_target never leaves [35, HR_max].

  NO CORRECTION.  The model has no tags and no gates, so a hundred jittered
  ticks must compute every attribute and fail none.
"""
import pytest
from fastapi.testclient import TestClient

from laminae import available_laminae, load_twin
from main import app
from session import Session
from signal_source import SimulatedSource
from universal_twin import PRELIMINARY, SENSOR

LAMINA_FILE = "wearable_lamina.xml"
LAMINA_ID = "lamina_wearable"

ALL_ATTRIBUTES = {
    # Activity and context
    "HR_obs", "AE_rate", "BE_rate", "step_rate", "T_app", "hour_local",
    "dt_s", "HR_level",
    # Personal coefficients
    "HR_offset", "HR_max", "k_I", "p_I", "A_circ", "phi_circ", "k_T", "T_ref",
    # Heart rate and energy
    "HR_measured", "EE_total", "VO2_est", "HR_circ", "HR_thermal",
    "HR_drive", "HR_target", "HR_model", "HR_residual",
}


@pytest.fixture
def twin():
    return load_twin(LAMINA_FILE)


@pytest.fixture
def baseline_twin():
    """
    The lamina at its declared baselines.

    A Session is seeded from the unjittered starting state of its own feed,
    then asked to compute the chain, so this is the resting operating point
    rather than one draw from the noisy stream.
    """
    twin = load_twin(LAMINA_FILE)
    session = Session(lamina=LAMINA_FILE)
    session.seed(SimulatedSource(twin).starting_state())
    session.twin.compute_all()
    return session.twin


# ══════════════════════════════════════════════════════════════════════
# The lamina loads and registers its maths
# ══════════════════════════════════════════════════════════════════════

def test_it_loads_with_its_own_maths_registered(twin):
    from wearable_lamina import WearableLamina
    assert isinstance(twin, WearableLamina)
    assert twin.lamina_id == LAMINA_ID


def test_available_laminae_lists_it_as_implemented():
    entry = {e["id"]: e for e in available_laminae()}[LAMINA_ID]
    assert entry["implemented"] is True
    assert entry["name"] == "Daily Activity"
    assert entry["level"] == 1


def test_the_declared_sources_and_coefficients_are_present(twin):
    for attr_id in ("HR_obs", "AE_rate", "BE_rate", "step_rate", "T_app",
                    "hour_local", "dt_s", "HR_level", "HR_max", "k_I",
                    "p_I", "A_circ", "phi_circ", "k_T", "T_ref"):
        assert twin.attributes[attr_id].source == SENSOR
    for attr_id in ("HR_measured", "EE_total", "VO2_est", "HR_circ",
                    "HR_thermal", "HR_drive", "HR_target", "HR_model",
                    "HR_residual"):
        assert twin.attributes[attr_id].source == PRELIMINARY


def test_nothing_writes_corrective_signal_into_this_lamina(twin):
    """No <tags> and no <gates>: this lamina monitors and corrects nothing."""
    assert twin.tags == {}
    assert twin.gates == []


# ══════════════════════════════════════════════════════════════════════
# The declared baselines
# ══════════════════════════════════════════════════════════════════════

def test_the_declared_baselines_produce_these_exact_values(baseline_twin):
    expected = {
        "EE_total":    1.4,
        "VO2_est":     288.066,
        "HR_circ":     2.828,
        "HR_thermal":  0.0,
        "HR_drive":    5.166,
        "HR_target":   67.994,
        "HR_model":    67.994,
        "HR_residual": -2.994,
    }
    for attr_id, value in expected.items():
        assert baseline_twin.get(attr_id).value == pytest.approx(
            value, abs=1e-3), attr_id

    assert baseline_twin.failed_attributes == {}


def test_the_measured_heart_rate_is_carried_unchanged(baseline_twin):
    assert baseline_twin.get("HR_measured").value == pytest.approx(65.0)


# ══════════════════════════════════════════════════════════════════════
# Guards
# ══════════════════════════════════════════════════════════════════════

def _fn(twin, name):
    return twin._function_registry[name]


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_a_bad_heart_rate_reading_marks_the_attribute_stale(bad):
    t = load_twin(LAMINA_FILE)
    t.set_sensor("HR_obs", bad)
    t.compute_all()
    assert "HR_measured" in t.failed_attributes


def test_a_negative_activity_rate_is_refused_by_hr_drive(twin):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "hr_drive")([12.0, -1.0, 0.7])
    assert "AE_rate" in str(exc.value)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_every_registered_function_refuses_an_unusable_input(twin, bad):
    """
    None, NaN and infinity are not measurements.  Each callable is handed a
    list with its first input replaced, and must raise rather than return a
    number that looks like an answer.
    """
    orders = {
        "measured_hr":   [65.0],
        "energy_total":  [0.3, 1.1],
        "vo2_estimate":  [1.4],
        "hr_circadian":  [4.0, 15.0, 12.0],
        "hr_thermal":    [0.11, 20.0, 20.0],
        "hr_drive":      [12.0, 0.3, 0.7],
        "hr_target":     [60.0, 0.0, 2.828, 0.0, 5.166, 185.0],
        "hr_model":      [67.994, 60.0, 30.0, 90.0, None],
        "hr_residual":   [65.0, 67.994],
    }
    for name, args in orders.items():
        poisoned = [bad] + args[1:]
        with pytest.raises(ValueError):
            _fn(twin, name)(poisoned)


# ══════════════════════════════════════════════════════════════════════
# The clamp
# ══════════════════════════════════════════════════════════════════════

def test_hr_target_always_lies_between_35_and_hr_max(twin):
    circ = _fn(twin, "hr_circadian")
    thermal = _fn(twin, "hr_thermal")
    drive = _fn(twin, "hr_drive")
    target = _fn(twin, "hr_target")
    hr_max = 185.0

    for ae_rate in (0.0, 1.0, 5.0, 12.5, 25.0):
        for t_app in (-10.0, 0.0, 20.0, 35.0, 50.0):
            for hour_local in (0.0, 6.0, 12.0, 18.0, 24.0):
                hr_circ = circ([4.0, 15.0, hour_local])
                hr_thermal = thermal([0.11, t_app, 20.0])
                hr_drive = drive([12.0, ae_rate, 0.7])
                value = target([60.0, 0.0, hr_circ, hr_thermal, hr_drive, hr_max])
                assert 35.0 <= value <= hr_max, (ae_rate, t_app, hour_local)


# ══════════════════════════════════════════════════════════════════════
# The schema the frontend reads
# ══════════════════════════════════════════════════════════════════════

def test_schema_lists_every_attribute():
    with TestClient(app) as client:
        res = client.get(f"/api/schema?lamina={LAMINA_ID}")
    assert res.status_code == 200
    body = res.json()
    assert body["lamina_id"] == LAMINA_ID
    assert ALL_ATTRIBUTES <= set(body["attributes"])


# ══════════════════════════════════════════════════════════════════════
# A hundred ticks
# ══════════════════════════════════════════════════════════════════════

def test_a_hundred_jittered_ticks_leave_nothing_failed():
    twin = load_twin(LAMINA_FILE)
    session = Session(lamina=LAMINA_FILE)
    source = SimulatedSource(twin, seed=1)
    for _ in range(100):
        session.tick(source.next())
    assert session.twin.failed_attributes == {}
