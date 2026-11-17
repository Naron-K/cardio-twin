"""
The health-risk lamina: entered figures and an activity dose to risk.

WHAT THIS FILE MEASURES

  THE EXAMPLE.  With every sensor at its declared baseline, the XML's
  invented example values and a current dose of 10 MET-h/week rising to a
  planned 15, the chain must produce the numbers its formulas define.  The
  expected values are recomputed here with math — never by calling the
  lamina — so a change to the arithmetic has to be argued for.

  THE TWO RISKS MOVE THE RIGHT WAY.  A plan below the current dose raises
  the risk; a plan equal to the current dose leaves it unchanged.

  MISSING ENTRIES STAY MISSING.  An unset entry leaves the risk that needs
  it stale; it does not turn into a zero.  A missing planned dose leaves the
  plan risks stale while the now risks still compute.

  THE GUARDS.  Each refusal is tested directly on the _calc_ method, so a
  guard that stops guarding fails here rather than in a confident-looking
  answer nobody questions.
"""

import math

import pytest

from health_lamina import HealthLamina
from laminae import load_twin, resolve_lamina
from universal_twin import SENSOR

LAMINA_ID = "lamina_health"

EXAMPLE = {
    "age": 52.0,
    "sex_male": 0.0,
    "height_cm": 168.0,
    "mass_kg": 74.0,
    "sbp": 134.0,
    "dbp": 84.0,
    "chol_total": 5.6,
    "chol_hdl": 1.3,
    "glucose_fasting": 5.4,
    "smoker": 0.0,
    "diabetes": 0.0,
    "bp_treated": 0.0,
    "family_diabetes": 1.0,
    "hr_medicine": 0.0,
}

DOSE_CURRENT = 10.0
DOSE_PLANNED = 15.0


def _new_twin() -> HealthLamina:
    twin = load_twin(resolve_lamina(LAMINA_ID))
    assert isinstance(twin, HealthLamina)
    return twin


def _seed_declared_baselines(twin: HealthLamina) -> None:
    """Put every SENSOR that declares a baseline on it, as the XML asks."""
    for attr in twin.attributes.values():
        if attr.source == SENSOR and attr.baseline is not None:
            twin.set_sensor(attr.id, attr.baseline)


def _seed_example(twin: HealthLamina, omit: str | None = None) -> None:
    for attr_id, value in EXAMPLE.items():
        if attr_id != omit:
            twin.set_sensor(attr_id, value)


def _configured(planned: float = DOSE_PLANNED,
                current: float = DOSE_CURRENT) -> HealthLamina:
    twin = _new_twin()
    _seed_declared_baselines(twin)
    _seed_example(twin)
    twin.set_inter_lamina("dose_current", current)
    twin.set_inter_lamina("dose_planned", planned)
    return twin


def _coef(twin: HealthLamina, attr_id: str) -> float:
    return twin.attributes[attr_id].baseline


def _relative_risk(dose: float, act_max: float, act_scale: float) -> float:
    return 1.0 - act_max * (1.0 - math.exp(-dose / act_scale))


def _risk_at_ratio(risk_now: float, rr_planned: float,
                   rr_current: float) -> float:
    return 100.0 * (1.0 - (1.0 - risk_now / 100.0) **
                    (rr_planned / rr_current))


# ── The example, against the formulas ────────────────────────────────

def test_the_example_matches_the_hand_computed_formulas():
    twin = _configured()
    twin.compute_all()

    c = lambda attr_id: _coef(twin, attr_id)
    age, mass, height = (EXAMPLE["age"], EXAMPLE["mass_kg"],
                         EXAMPLE["height_cm"])

    expected_bmi = mass / (height / 100.0) ** 2
    expected_cvd_lp = (
        c("c_age") * math.log(age)
        + c("c_sbp") * math.log(EXAMPLE["sbp"])
        + c("c_tc") * math.log(EXAMPLE["chol_total"])
        + c("c_hdl") * math.log(EXAMPLE["chol_hdl"])
        + c("c_smoker") * EXAMPLE["smoker"]
        + c("c_diabetes") * EXAMPLE["diabetes"]
        + c("c_treated") * EXAMPLE["bp_treated"]
        + c("c_male") * EXAMPLE["sex_male"]
    )
    expected_cvd_risk = 100.0 * (
        1.0 - c("cvd_S0") ** math.exp(expected_cvd_lp - c("cvd_lp_ref"))
    )
    expected_dm_lp = (
        c("d_0")
        + c("d_age") * age
        + c("d_bmi") * expected_bmi
        + c("d_glucose") * EXAMPLE["glucose_fasting"]
        + c("d_family") * EXAMPLE["family_diabetes"]
        + c("d_treated") * EXAMPLE["bp_treated"]
    )
    expected_dm_risk = 100.0 / (1.0 + math.exp(-expected_dm_lp))

    expected_cvd_rr_current = _relative_risk(
        DOSE_CURRENT, c("cvd_act_max"), c("cvd_act_scale"))
    expected_cvd_rr_planned = _relative_risk(
        DOSE_PLANNED, c("cvd_act_max"), c("cvd_act_scale"))
    expected_dm_rr_current = _relative_risk(
        DOSE_CURRENT, c("dm_act_max"), c("dm_act_scale"))
    expected_dm_rr_planned = _relative_risk(
        DOSE_PLANNED, c("dm_act_max"), c("dm_act_scale"))

    expected_cvd_plan = _risk_at_ratio(
        expected_cvd_risk, expected_cvd_rr_planned,
        expected_cvd_rr_current)
    expected_dm_plan = _risk_at_ratio(
        expected_dm_risk, expected_dm_rr_planned, expected_dm_rr_current)

    values = {attr_id: twin.attributes[attr_id].value
              for attr_id in (
                  "BMI", "cvd_lp", "cvd_risk_now", "dm_lp", "dm_risk_now",
                  "cvd_rr_current", "cvd_rr_planned", "dm_rr_current",
                  "dm_rr_planned", "cvd_risk_plan", "dm_risk_plan",
                  "flag_bp", "flag_dose_jump", "flag_medicine",
              )}

    assert values["BMI"] == pytest.approx(expected_bmi, rel=1e-12)
    assert values["cvd_lp"] == pytest.approx(expected_cvd_lp, rel=1e-12)
    assert values["cvd_risk_now"] == pytest.approx(
        expected_cvd_risk, rel=1e-12)
    assert values["dm_lp"] == pytest.approx(expected_dm_lp, rel=1e-12)
    assert values["dm_risk_now"] == pytest.approx(
        expected_dm_risk, rel=1e-12)

    assert values["cvd_rr_current"] == pytest.approx(
        expected_cvd_rr_current, rel=1e-12)
    assert values["cvd_rr_planned"] == pytest.approx(
        expected_cvd_rr_planned, rel=1e-12)
    assert values["dm_rr_current"] == pytest.approx(
        expected_dm_rr_current, rel=1e-12)
    assert values["dm_rr_planned"] == pytest.approx(
        expected_dm_rr_planned, rel=1e-12)

    assert values["cvd_risk_plan"] == pytest.approx(
        expected_cvd_plan, rel=1e-12)
    assert values["dm_risk_plan"] == pytest.approx(
        expected_dm_plan, rel=1e-12)

    assert values["flag_bp"] == 0.0
    assert values["flag_dose_jump"] == 0.0
    assert values["flag_medicine"] == 0.0

    # The example itself: both plan risks are lower than the risks now.
    assert values["cvd_risk_plan"] < values["cvd_risk_now"]
    assert values["dm_risk_plan"] < values["dm_risk_now"]
    assert 0.0 < values["cvd_risk_now"] < 100.0
    assert 0.0 < values["dm_risk_now"] < 100.0


# ── Direction of the plan ────────────────────────────────────────────

def test_a_plan_below_the_current_dose_raises_the_risk():
    twin = _configured(planned=5.0)
    twin.compute_all()

    assert (twin.attributes["cvd_risk_plan"].value
            > twin.attributes["cvd_risk_now"].value)
    assert (twin.attributes["dm_risk_plan"].value
            > twin.attributes["dm_risk_now"].value)


def test_a_plan_equal_to_the_current_dose_leaves_the_risk_unchanged():
    twin = _configured(planned=DOSE_CURRENT)
    twin.compute_all()

    assert twin.attributes["cvd_risk_plan"].value == pytest.approx(
        twin.attributes["cvd_risk_now"].value, abs=1e-9)
    assert twin.attributes["dm_risk_plan"].value == pytest.approx(
        twin.attributes["dm_risk_now"].value, abs=1e-9)


# ── Missing entries and missing links ────────────────────────────────

def test_an_unset_entry_makes_only_the_risk_that_needs_it_stale():
    twin = _new_twin()
    _seed_declared_baselines(twin)
    _seed_example(twin, omit="chol_hdl")
    twin.set_inter_lamina("dose_current", DOSE_CURRENT)
    twin.set_inter_lamina("dose_planned", DOSE_PLANNED)
    twin.compute_all()

    assert twin.attributes["cvd_lp"].value is None
    assert twin.attributes["cvd_risk_now"].value is None
    assert twin.attributes["cvd_risk_plan"].value is None

    assert twin.attributes["dm_lp"].value is not None
    assert twin.attributes["dm_risk_now"].value is not None


def test_an_unset_planned_dose_leaves_only_the_plan_risks_stale():
    twin = _new_twin()
    _seed_declared_baselines(twin)
    _seed_example(twin)
    twin.set_inter_lamina("dose_current", DOSE_CURRENT)
    twin.compute_all()

    assert twin.attributes["cvd_rr_planned"].value is None
    assert twin.attributes["dm_rr_planned"].value is None
    assert twin.attributes["cvd_risk_plan"].value is None
    assert twin.attributes["dm_risk_plan"].value is None

    assert twin.attributes["cvd_risk_now"].value is not None
    assert twin.attributes["dm_risk_now"].value is not None


# ── Guards, tested directly on the _calc_ methods ────────────────────

CVD = [52.0, 134.0, 5.6, 1.3, 0.0, 0.0, 0.0, 0.0,
       2.5, 2.5, 1.1, -0.8, 0.6, 0.6, 0.3, 0.5]
DM = [52.0, 26.2188, 5.4, 1.0, 0.0, -10.0, 0.03, 0.09, 0.6, 0.5, 0.4]
ACTIVITY = [10.0, 0.30, 12.0]
RATIO = [7.0, 0.75, 0.83]
BP = [134.0, 84.0, 160.0, 100.0]
JUMP = [15.0, 10.0, 1.5]


def _at(args: list, index: int, value: float) -> list:
    changed = list(args)
    changed[index] = value
    return changed


GUARD_CASES = [
    # logarithm arguments
    ("_calc_cvd_score", _at(CVD, 0, 0.0), "age=0.0"),
    ("_calc_cvd_score", _at(CVD, 1, 0.0), "sbp=0.0"),
    ("_calc_cvd_score", _at(CVD, 2, -1.0), "chol_total=-1.0"),
    ("_calc_cvd_score", _at(CVD, 3, 0.0), "chol_hdl=0.0"),
    # height and mass
    ("_calc_body_mass_index", [74.0, 0.0], "height_cm=0.0"),
    ("_calc_body_mass_index", [74.0, -168.0], "height_cm=-168.0"),
    ("_calc_body_mass_index", [0.0, 168.0], "mass_kg=0.0"),
    # yes/no answers
    ("_calc_cvd_score", _at(CVD, 4, 0.5), "smoker=0.5"),
    ("_calc_cvd_score", _at(CVD, 5, 2.0), "diabetes=2.0"),
    ("_calc_cvd_score", _at(CVD, 6, -1.0), "bp_treated=-1.0"),
    ("_calc_cvd_score", _at(CVD, 7, 0.5), "sex_male=0.5"),
    ("_calc_dm_score", _at(DM, 3, 0.5), "family_diabetes=0.5"),
    ("_calc_dm_score", _at(DM, 4, 2.0), "bp_treated=2.0"),
    ("_calc_flag_medicine", [0.5], "hr_medicine=0.5"),
    # cvd_S0 strictly between 0 and 1
    ("_calc_cvd_risk_now", [23.8, 0.0, 23.455], "cvd_S0=0.0"),
    ("_calc_cvd_risk_now", [23.8, 1.0, 23.455], "cvd_S0=1.0"),
    # the activity curve
    ("_calc_activity_relative_risk", [10.0, 0.30, 0.0],
     "act_scale=0.0"),
    ("_calc_activity_relative_risk", [10.0, 1.0, 12.0],
     "act_max=1.0"),
    ("_calc_activity_relative_risk", [10.0, -0.1, 12.0],
     "act_max=-0.1"),
    ("_calc_activity_relative_risk", [-1.0, 0.30, 12.0], "dose=-1.0"),
    # risk and relative-risk inputs
    ("_calc_risk_at_ratio", [-1.0, 0.75, 0.83], "risk_now=-1.0"),
    ("_calc_risk_at_ratio", [101.0, 0.75, 0.83], "risk_now=101.0"),
    ("_calc_risk_at_ratio", [7.0, 0.0, 0.83], "rr_planned=0.0"),
    ("_calc_risk_at_ratio", [7.0, 0.75, 0.0], "rr_current=0.0"),
    # flags
    ("_calc_flag_dose_jump", [15.0, 10.0, 0.5],
     "dose_jump_ratio=0.5"),
    ("_calc_flag_dose_jump", [-1.0, 10.0, 1.5],
     "dose_planned=-1.0"),
    ("_calc_flag_dose_jump", [15.0, -1.0, 1.5],
     "dose_current=-1.0"),
    ("_calc_flag_bp", [134.0, 84.0, 0.0, 100.0], "sbp_flag=0.0"),
    ("_calc_flag_bp", [134.0, 84.0, 160.0, 0.0], "dbp_flag=0.0"),
]


@pytest.mark.parametrize("method_name, args, named", GUARD_CASES)
def test_each_guard_raises_value_error_naming_the_input(
        method_name, args, named):
    twin = _new_twin()
    with pytest.raises(ValueError, match=named):
        getattr(twin, method_name)(args)


def test_a_short_input_list_is_refused():
    twin = _new_twin()
    with pytest.raises(ValueError, match="expected 2 inputs"):
        twin._calc_body_mass_index([74.0])


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"),
                                 float("-inf")])
def test_missing_and_non_finite_inputs_are_refused_by_name(bad):
    twin = _new_twin()
    with pytest.raises(ValueError, match="age"):
        twin._calc_cvd_score(_at(CVD, 0, bad))


# ── Invariants ───────────────────────────────────────────────────────

def test_relative_risk_is_non_increasing_in_dose_and_stays_in_the_unit_interval():
    twin = _new_twin()
    doses = [0.0, 1.0, 5.0, 10.0, 20.0, 50.0, 300.0]
    risks = [twin._calc_activity_relative_risk([dose, 0.30, 12.0])
             for dose in doses]

    assert all(0.0 < risk <= 1.0 for risk in risks)
    assert all(earlier >= later for earlier, later in zip(risks, risks[1:]))


def test_computed_risks_stay_within_zero_and_one_hundred():
    for planned in (0.0, 5.0, 10.0, 15.0, 50.0, 300.0):
        twin = _configured(planned=planned)
        twin.compute_all()
        for attr_id in ("cvd_risk_now", "dm_risk_now",
                        "cvd_risk_plan", "dm_risk_plan"):
            value = twin.attributes[attr_id].value
            assert 0.0 <= value <= 100.0
