"""
Activity dose: a metabolic equivalent and the MET-minutes worth counting.

The wearable lamina already reports total energy and oxygen consumption.
This file covers the two attributes that turn that energy into an activity
dose: MET, how many times rest the day is spending, and dose_rate, the part
of that equivalent at or above a declared floor.

WHAT THIS FILE MEASURES

  THE MATHS.  MET is 1 + AE_rate / BE_ref, checked against hand-computed
  values.  dose_rate is MET above the floor, zero below it and MET exactly
  at it.

  THE GUARDS.  A resting rate of zero or less is refused by name, as are
  None, NaN and infinity in either input, and a negative active energy rate.
  A missing MET is refused rather than treated as zero.

  THE LOADED TWIN.  With the sensors set by hand, compute_all() produces the
  same MET and dose_rate the functions do on their own.

  THE PLAN ROLE.  <plan_view> may name an optional <dose> attribute.  It
  must be a declared PRELIMINARY attribute; an unknown id or a SENSOR is
  refused, and a plan view without <dose> loads exactly as before.
"""
import pytest

from laminae import load_twin
from tests.test_plan_view_roles import VALID_PLAN_VIEW, _load, _refused

LAMINA_FILE = "wearable_lamina.xml"

DOSE_UNKNOWN = VALID_PLAN_VIEW.replace(
    "</plan_view>",
    '  <dose attribute="nope" label="Activity dose"/>\n</plan_view>',
)

DOSE_ON_SENSOR = VALID_PLAN_VIEW.replace(
    "</plan_view>",
    '  <dose attribute="energy_rate" label="Activity dose"/>\n</plan_view>',
)


@pytest.fixture
def twin():
    return load_twin(LAMINA_FILE)


def _fn(twin, name):
    return twin._function_registry[name]


# ══════════════════════════════════════════════════════════════════════
# The maths, on hand-computed inputs
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("ae_rate, be_ref, expected", [
    (7.2, 1.2, 1.0 + 7.2 / 1.2),
    (2.2, 1.2, 1.0 + 2.2 / 1.2),
    (3.6, 1.2, 1.0 + 3.6 / 1.2),
    (1.4, 1.1, 1.0 + 1.4 / 1.1),
])
def test_met_is_one_plus_activity_over_the_resting_rate(
    twin, ae_rate, be_ref, expected
):
    assert _fn(twin, "met_level")([ae_rate, be_ref]) == pytest.approx(
        expected)


def test_dose_rate_above_the_floor_is_the_met(twin):
    assert _fn(twin, "dose_rate")([6.0, 3.0]) == pytest.approx(6.0)


def test_dose_rate_below_the_floor_is_zero(twin):
    assert _fn(twin, "dose_rate")([2.5, 3.0]) == 0.0


def test_dose_rate_exactly_at_the_floor_is_the_met(twin):
    assert _fn(twin, "dose_rate")([3.0, 3.0]) == pytest.approx(3.0)


def test_dose_rate_is_either_zero_or_at_least_the_floor(twin):
    dose = _fn(twin, "dose_rate")
    for met in (0.5, 1.0, 2.9, 3.0, 3.1, 10.0, 25.0):
        for floor in (1.0, 3.0, 6.0, 10.0):
            value = dose([met, floor])
            assert value == 0.0 or value >= floor, (met, floor, value)


# ══════════════════════════════════════════════════════════════════════
# Guards
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("be_ref", [0.0, -1.2])
def test_a_non_positive_resting_rate_is_refused_by_name(twin, be_ref):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "met_level")([7.2, be_ref])
    assert "BE_ref" in str(exc.value)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_an_unusable_resting_rate_is_refused_by_name(twin, bad):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "met_level")([7.2, bad])
    assert "BE_ref" in str(exc.value)


def test_a_negative_active_energy_rate_is_refused_by_name(twin):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "met_level")([-0.1, 1.1])
    assert "AE_rate" in str(exc.value)


def test_a_missing_met_is_refused_by_name(twin):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "dose_rate")([None, 3.0])
    assert "MET" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════
# Through a loaded twin
# ══════════════════════════════════════════════════════════════════════

def test_the_loaded_twin_computes_the_hand_value():
    twin = load_twin(LAMINA_FILE)
    twin.set_sensor("AE_rate", 6.0)
    twin.set_sensor("BE_ref", 1.2)
    twin.set_sensor("MET_floor", 3.0)
    twin.compute_all()

    # MET = 1 + 6.0 / 1.2 = 6.0.
    assert twin.get("MET").value == pytest.approx(6.0)
    assert twin.get("dose_rate").value == pytest.approx(6.0)


# ══════════════════════════════════════════════════════════════════════
# The optional <dose> plan role
# ══════════════════════════════════════════════════════════════════════

def test_the_wearable_plan_view_parses_the_dose_role():
    assert load_twin(LAMINA_FILE).plan_view["dose"] == {
        "attribute": "dose_rate",
        "label": "Activity dose",
        "unit": "MET",
    }


def test_a_dose_naming_an_unknown_id_is_refused(tmp_path):
    _refused(tmp_path, DOSE_UNKNOWN, "unknown attribute 'nope'")


def test_a_dose_naming_a_sensor_is_refused(tmp_path):
    _refused(tmp_path, DOSE_ON_SENSOR,
             "dose attribute must be PRELIMINARY")


def test_a_plan_view_without_dose_still_loads(tmp_path):
    twin = _load(tmp_path, VALID_PLAN_VIEW)
    assert "dose" not in twin.plan_view
    assert twin.plan_view["intensity"]["attribute"] == "energy_rate"
