"""
The health-risk lamina: risk factors that adapt, then the risk equations.

WHAT THIS FILE MEASURES

  THE CHAIN AGAINST A HAND COMPUTATION.  For the XML's "borderline" example,
  a measured resting heart rate and VO2max and one plan, every mediator at 0,
  4, 8, 12 and 1000 weeks, and both risks now and with the plan, must equal
  numbers recomputed here with math from the XML's declared baselines — never
  by calling the lamina.  A change to the arithmetic has to be argued for.

  THE INVARIANTS.  At week 0 nothing has moved; a plan equal to the habit
  moves nothing at any horizon; total cholesterol and body mass are held
  still; a lighter plan raises the risk; no factor moves further than its
  cap; and an improvement stops at its healthy limit.

  MISSING ENTRIES STAY MISSING.  An unset entry leaves the results that need
  it stale; it does not turn into a zero.

  THE GUARDS.  Each refusal is tested directly on the _calc_ method, so a
  guard that stops guarding fails here rather than in a confident-looking
  answer nobody questions.
"""

import math

import pytest

import laminae
from universal_twin import SENSOR

LAMINA_ID = "lamina_health"

DOSE_CURRENT = 21.074
DOSE_PLANNED = 45.801
RESTING_HR = 66.0
VO2MAX = 26.13
WEEKS = [0.0, 4.0, 8.0, 12.0, 1000.0]

MEDIATORS = [
    ("glucose_fasting", "glucose_fasting_at"),
    ("sbp", "sbp_at"),
    ("dbp", "dbp_at"),
    ("chol_hdl", "chol_hdl_at"),
    ("chol_total", "chol_total_at"),
    ("mass_kg", "mass_kg_at"),
    ("resting_hr", "resting_hr_at"),
    ("vo2max", "vo2max_at"),
]

GLUCOSE_AT = {
    0.0: 6.3,
    4.0: 6.1914,
    8.0: 6.1145,
    12.0: 6.0602,
    1000.0: 5.9291,
}


# ── Loading a configured twin ────────────────────────────────────────

def _new_twin():
    return laminae.load_twin(laminae.resolve_lamina(LAMINA_ID))


def _example(twin, example_id):
    for example in twin.assessment_view["examples"]:
        if example["id"] == example_id:
            return example
    raise AssertionError(f"no example {example_id!r} in the health lamina")


def _configured(example_id="borderline", *, weeks=0.0,
                dose_current=DOSE_CURRENT, dose_planned=DOSE_PLANNED,
                resting_hr=RESTING_HR, vo2max=VO2MAX,
                omit_sensor=None, overrides=None):
    """
    Load a fresh twin and fill it as the engine would not:
      - every SENSOR that declares a baseline gets that baseline;
      - the chosen example fills the form entries;
      - the links arrive through set_inter_lamina;
      - the horizon arrives through set_sensor;
      - then the whole chain is computed once.
    """
    twin = _new_twin()
    assert twin.assessment_view is not None

    for attr in twin.attributes.values():
        if attr.source == SENSOR and attr.baseline is not None:
            twin.set_sensor(attr.id, attr.baseline)

    example = _example(twin, example_id)
    for attr_id, value in example["values"].items():
        if attr_id != omit_sensor:
            twin.set_sensor(attr_id, value)
    for attr_id, value in (overrides or {}).items():
        if attr_id != omit_sensor:
            twin.set_sensor(attr_id, value)

    if dose_current is not None:
        twin.set_inter_lamina("dose_current", dose_current)
    if dose_planned is not None:
        twin.set_inter_lamina("dose_planned", dose_planned)
    if resting_hr is not None:
        twin.set_inter_lamina("resting_hr", resting_hr)
    if vo2max is not None:
        twin.set_inter_lamina("vo2max", vo2max)

    twin.set_sensor("weeks", weeks)
    twin.compute_all()
    return twin


# ── Hand computations, using only the XML's declared baselines ───────

def _coef(twin, attr_id):
    return twin.attributes[attr_id].baseline


def _clamp(value, low, high):
    return max(low, min(high, value))


def _hand_adapt(now, dose_current, dose_planned, weeks,
                per_10, cap, weeks_half, limit):
    added = dose_planned - dose_current
    settled = _clamp(per_10 * added / 10.0, -cap, cap)
    shift = settled * (1.0 - 2.0 ** (-weeks / weeks_half))
    value = now + shift
    if per_10 < 0.0 and shift < 0.0:
        value = max(value, min(now, limit))
    if per_10 > 0.0 and shift > 0.0:
        value = min(value, max(now, limit))
    return now if per_10 == 0.0 else value


def _now_factors(example):
    factors = dict(example["values"])
    factors["resting_hr"] = RESTING_HR
    factors["vo2max"] = VO2MAX
    return factors


def _hand_mediators(twin, factors, weeks, dose_current, dose_planned):
    return {
        now_id: _hand_adapt(
            factors[now_id], dose_current, dose_planned, weeks,
            _coef(twin, f"{now_id}_per_10"),
            _coef(twin, f"{now_id}_cap"),
            _coef(twin, f"{now_id}_weeks_half"),
            _coef(twin, f"{now_id}_limit"),
        )
        for now_id, _at_id in MEDIATORS
    }


def _hand_risk(twin, factors):
    age = factors["age"]
    bmi = factors["mass_kg"] / (factors["height_cm"] / 100.0) ** 2

    cvd_lp = (
        _coef(twin, "c_age") * math.log(age)
        + _coef(twin, "c_sbp") * math.log(factors["sbp"])
        + _coef(twin, "c_tc") * math.log(factors["chol_total"])
        + _coef(twin, "c_hdl") * math.log(factors["chol_hdl"])
        + _coef(twin, "c_smoker") * factors["smoker"]
        + _coef(twin, "c_diabetes") * factors["diabetes"]
        + _coef(twin, "c_treated") * factors["bp_treated"]
        + _coef(twin, "c_male") * factors["sex_male"]
        + _coef(twin, "c_vo2") * factors["vo2max"]
        + _coef(twin, "c_rhr") * factors["resting_hr"]
    )
    cvd_risk = 100.0 * (
        1.0 - _coef(twin, "cvd_S0") ** math.exp(
            cvd_lp - _coef(twin, "cvd_lp_ref"))
    )

    dm_lp = (
        _coef(twin, "d_0")
        + _coef(twin, "d_age") * age
        + _coef(twin, "d_bmi") * bmi
        + _coef(twin, "d_glucose") * factors["glucose_fasting"]
        + _coef(twin, "d_family") * factors["family_diabetes"]
        + _coef(twin, "d_treated") * factors["bp_treated"]
        + _coef(twin, "d_vo2") * factors["vo2max"]
    )
    dm_risk = 100.0 / (1.0 + math.exp(-dm_lp))
    return cvd_risk, dm_risk


# ── The borderline example, against the hand computation ─────────────

def test_the_borderline_example_matches_the_hand_computed_chain():
    reference = _configured(weeks=0.0)
    example = _example(reference, "borderline")
    factors = _now_factors(example)

    expected_cvd_now, expected_dm_now = _hand_risk(reference, factors)
    assert expected_cvd_now == pytest.approx(14.30, abs=0.005)
    assert expected_dm_now == pytest.approx(19.33, abs=0.005)

    for weeks in WEEKS:
        twin = _configured(weeks=weeks)

        assert twin.attributes["cvd_risk_now"].value == pytest.approx(
            expected_cvd_now, rel=1e-12)
        assert twin.attributes["dm_risk_now"].value == pytest.approx(
            expected_dm_now, rel=1e-12)

        mediators = _hand_mediators(
            twin, factors, weeks, DOSE_CURRENT, DOSE_PLANNED)
        for now_id, at_id in MEDIATORS:
            assert twin.attributes[at_id].value == pytest.approx(
                mediators[now_id], abs=1e-9)

        at_factors = dict(factors)
        at_factors.update(mediators)
        expected_cvd_at, expected_dm_at = _hand_risk(twin, at_factors)
        assert twin.attributes["cvd_risk_at"].value == pytest.approx(
            expected_cvd_at, rel=1e-12)
        assert twin.attributes["dm_risk_at"].value == pytest.approx(
            expected_dm_at, rel=1e-12)

        assert twin.attributes["glucose_fasting_at"].value == pytest.approx(
            GLUCOSE_AT[weeks], abs=1e-4)

        if weeks == 1000.0:
            assert expected_cvd_at == pytest.approx(10.74, abs=0.005)
            assert expected_dm_at == pytest.approx(14.65, abs=0.005)


# ── Invariants ───────────────────────────────────────────────────────

def test_at_week_zero_every_at_equals_its_now_value():
    twin = _configured(weeks=0.0)

    for now_id, at_id in MEDIATORS:
        assert twin.attributes[at_id].value == pytest.approx(
            twin.attributes[now_id].value, abs=1e-9)

    assert twin.attributes["cvd_risk_at"].value == pytest.approx(
        twin.attributes["cvd_risk_now"].value, abs=1e-9)
    assert twin.attributes["dm_risk_at"].value == pytest.approx(
        twin.attributes["dm_risk_now"].value, abs=1e-9)


@pytest.mark.parametrize("weeks", WEEKS)
def test_a_plan_equal_to_the_habit_changes_nothing(weeks):
    twin = _configured(weeks=weeks, dose_planned=DOSE_CURRENT)

    for now_id, at_id in MEDIATORS:
        assert twin.attributes[at_id].value == pytest.approx(
            twin.attributes[now_id].value, abs=1e-9)

    assert twin.attributes["cvd_risk_at"].value == pytest.approx(
        twin.attributes["cvd_risk_now"].value, abs=1e-9)
    assert twin.attributes["dm_risk_at"].value == pytest.approx(
        twin.attributes["dm_risk_now"].value, abs=1e-9)


@pytest.mark.parametrize("weeks", WEEKS)
def test_total_cholesterol_and_body_mass_do_not_move(weeks):
    twin = _configured(weeks=weeks)

    for now_id in ("chol_total", "mass_kg"):
        assert twin.attributes[f"{now_id}_at"].value == pytest.approx(
            twin.attributes[now_id].value, abs=1e-12)


def test_a_lighter_plan_raises_the_risk():
    twin = _configured(weeks=1000.0, dose_planned=6.629)

    assert (twin.attributes["cvd_risk_at"].value
            > twin.attributes["cvd_risk_now"].value)
    assert (twin.attributes["dm_risk_at"].value
            > twin.attributes["dm_risk_now"].value)


@pytest.mark.parametrize("weeks", WEEKS)
def test_a_mediator_never_moves_further_than_its_cap(weeks):
    twin = _configured(weeks=weeks)

    for now_id, at_id in MEDIATORS:
        now = twin.attributes[now_id].value
        at = twin.attributes[at_id].value
        cap = _coef(twin, f"{now_id}_cap")
        assert abs(at - now) <= cap + 1e-12


def test_an_improvement_stops_at_the_healthy_limit():
    twin = _configured(weeks=1000.0,
                       overrides={"glucose_fasting": 4.6})

    assert twin.attributes["glucose_fasting_at"].value >= 4.5
    assert twin.attributes["glucose_fasting_at"].value == pytest.approx(
        4.5, abs=1e-9)


def test_a_value_already_below_the_limit_is_not_moved_down():
    twin = _configured(weeks=1000.0,
                       overrides={"glucose_fasting": 4.2})

    assert twin.attributes["glucose_fasting_at"].value == pytest.approx(
        4.2, abs=1e-12)


# ── Every example is plausible and responds to the plan ──────────────

@pytest.mark.parametrize("example_id", ["low", "borderline", "high_cv"])
def test_each_example_is_in_range_and_responds_to_the_plan(example_id):
    twin = _configured(example_id, weeks=0.0)
    assert 1.0 <= twin.attributes["cvd_risk_now"].value <= 60.0
    assert 1.0 <= twin.attributes["dm_risk_now"].value <= 60.0

    lighter = _configured(example_id, weeks=1000.0, dose_planned=6.629)
    heavier = _configured(example_id, weeks=1000.0, dose_planned=DOSE_PLANNED)

    assert (lighter.attributes["cvd_risk_at"].value
            - heavier.attributes["cvd_risk_at"].value >= 0.1)
    assert (lighter.attributes["dm_risk_at"].value
            - heavier.attributes["dm_risk_at"].value >= 0.1)


# ── Missing entries and missing links ────────────────────────────────

def test_without_resting_hr_only_the_cvd_results_are_stale():
    twin = _configured(resting_hr=None)

    for attr_id in ("cvd_lp_now", "cvd_risk_now",
                    "cvd_lp_at", "cvd_risk_at"):
        assert twin.attributes[attr_id].value is None

    for attr_id in ("dm_lp_now", "dm_risk_now",
                    "dm_lp_at", "dm_risk_at"):
        assert twin.attributes[attr_id].value is not None


def test_without_dose_planned_every_at_is_stale_and_every_now_computes():
    twin = _configured(dose_planned=None)

    at_ids = [at_id for _now_id, at_id in MEDIATORS] + [
        "BMI_at", "cvd_lp_at", "cvd_risk_at", "dm_lp_at", "dm_risk_at",
    ]
    for attr_id in at_ids:
        assert twin.attributes[attr_id].value is None

    for attr_id in ("BMI_now", "cvd_lp_now", "cvd_risk_now",
                    "dm_lp_now", "dm_risk_now"):
        assert twin.attributes[attr_id].value is not None


def test_without_chol_hdl_the_cvd_risk_now_is_stale():
    twin = _configured(omit_sensor="chol_hdl")

    assert twin.attributes["cvd_lp_now"].value is None
    assert twin.attributes["cvd_risk_now"].value is None
    assert twin.attributes["dm_risk_now"].value is not None


# ── Guards, tested directly on the _calc_ methods ────────────────────

CVD = [
    52.0, 134.0, 5.8, 1.1, 0.0, 0.0, 0.0, 1.0, 26.13, 66.0,
    2.5, 2.5, 1.1, -0.8, 0.6, 0.6, 0.3, 0.5, -0.03, 0.01,
]
DM = [
    52.0, 29.0612, 6.3, 1.0, 0.0, 26.13,
    -9.1, 0.03, 0.09, 0.6, 0.5, 0.4, -0.03,
]
ADAPT = [6.3, 21.074, 45.801, 8.0, -0.15, 0.6, 8.0, 4.5]
BMI = [89.0, 175.0]
CVD_RISK = [24.356, 0.95, 23.255]
DM_RISK = [-1.428]


def _at(args, index, value):
    changed = list(args)
    changed[index] = value
    return changed


def test_the_guard_input_lists_match_the_xml_input_order():
    twin = _new_twin()
    assert twin.functions["cvd_score_now"].inputs == [
        "age", "sbp", "chol_total", "chol_hdl", "smoker", "diabetes",
        "bp_treated", "sex_male", "vo2max", "resting_hr", "c_age", "c_sbp",
        "c_tc", "c_hdl", "c_smoker", "c_diabetes", "c_treated", "c_male",
        "c_vo2", "c_rhr",
    ]
    assert twin.functions["dm_score_now"].inputs == [
        "age", "BMI_now", "glucose_fasting", "family_diabetes", "bp_treated",
        "vo2max", "d_0", "d_age", "d_bmi", "d_glucose", "d_family",
        "d_treated", "d_vo2",
    ]
    assert twin.functions["adapt_glucose_fasting"].inputs == [
        "glucose_fasting", "dose_current", "dose_planned", "weeks",
        "glucose_fasting_per_10", "glucose_fasting_cap",
        "glucose_fasting_weeks_half", "glucose_fasting_limit",
    ]


GUARD_CASES = [
    # logarithm arguments
    ("_calc_cvd_score", _at(CVD, 0, 0.0), "age=0.0"),
    ("_calc_cvd_score", _at(CVD, 1, 0.0), "sbp=0.0"),
    ("_calc_cvd_score", _at(CVD, 2, -1.0), "chol_total=-1.0"),
    ("_calc_cvd_score", _at(CVD, 3, 0.0), "chol_hdl=0.0"),
    # height and mass
    ("_calc_body_mass_index", [89.0, 0.0], "height_cm=0.0"),
    ("_calc_body_mass_index", [89.0, -175.0], "height_cm=-175.0"),
    ("_calc_body_mass_index", [0.0, 175.0], "mass_kg=0.0"),
    # yes/no answers
    ("_calc_cvd_score", _at(CVD, 4, 0.5), "smoker=0.5"),
    ("_calc_cvd_score", _at(CVD, 5, 2.0), "diabetes=2.0"),
    ("_calc_cvd_score", _at(CVD, 6, -1.0), "bp_treated=-1.0"),
    ("_calc_cvd_score", _at(CVD, 7, 0.5), "sex_male=0.5"),
    ("_calc_dm_score", _at(DM, 3, 0.5), "family_diabetes=0.5"),
    ("_calc_dm_score", _at(DM, 4, 2.0), "bp_treated=2.0"),
    ("_calc_flag_medicine", [0.5], "hr_medicine=0.5"),
    # cvd_S0 strictly between 0 and 1
    ("_calc_cvd_risk", [24.356, 0.0, 23.255], "cvd_S0=0.0"),
    ("_calc_cvd_risk", [24.356, 1.0, 23.255], "cvd_S0=1.0"),
    # fitness
    ("_calc_cvd_score", _at(CVD, 8, 0.0), "vo2max=0.0"),
    ("_calc_cvd_score", _at(CVD, 9, 0.0), "resting_hr=0.0"),
    ("_calc_dm_score", _at(DM, 5, 0.0), "vo2max=0.0"),
    # adaptation time, cap and doses
    ("_calc_adapt", _at(ADAPT, 3, -1.0), "weeks=-1.0"),
    ("_calc_adapt", _at(ADAPT, 6, 0.0), "weeks_half=0.0"),
    ("_calc_adapt", _at(ADAPT, 5, -0.1), "cap=-0.1"),
    ("_calc_adapt", _at(ADAPT, 2, -1.0), "dose_planned=-1.0"),
    ("_calc_adapt", _at(ADAPT, 1, -1.0), "dose_current=-1.0"),
    # flags
    ("_calc_flag_dose_jump", [45.801, 21.074, 0.5],
     "dose_jump_ratio=0.5"),
    ("_calc_flag_dose_jump", [-1.0, 21.074, 1.5],
     "dose_planned=-1.0"),
    ("_calc_flag_dose_jump", [45.801, -1.0, 1.5],
     "dose_current=-1.0"),
    ("_calc_flag_bp", [134.0, 86.0, 0.0, 100.0], "sbp_flag=0.0"),
    ("_calc_flag_bp", [134.0, 86.0, 160.0, 0.0], "dbp_flag=0.0"),
]


@pytest.mark.parametrize("method_name, args, named", GUARD_CASES)
def test_each_guard_raises_value_error_naming_the_input(
        method_name, args, named):
    twin = _new_twin()
    with pytest.raises(ValueError, match=named):
        getattr(twin, method_name)(args)


GUARD_INPUTS = [
    ("_calc_adapt", ADAPT, [
        "now", "dose_current", "dose_planned", "weeks", "per_10", "cap",
        "weeks_half", "limit",
    ]),
    ("_calc_body_mass_index", BMI, ["mass_kg", "height_cm"]),
    ("_calc_cvd_score", CVD, [
        "age", "sbp", "chol_total", "chol_hdl", "smoker", "diabetes",
        "bp_treated", "sex_male", "vo2max", "resting_hr", "c_age", "c_sbp",
        "c_tc", "c_hdl", "c_smoker", "c_diabetes", "c_treated", "c_male",
        "c_vo2", "c_rhr",
    ]),
    ("_calc_cvd_risk", CVD_RISK, ["cvd_lp", "cvd_S0", "cvd_lp_ref"]),
    ("_calc_dm_score", DM, [
        "age", "BMI", "glucose_fasting", "family_diabetes", "bp_treated",
        "vo2max", "d_0", "d_age", "d_bmi", "d_glucose", "d_family",
        "d_treated", "d_vo2",
    ]),
    ("_calc_dm_risk", DM_RISK, ["dm_lp"]),
]


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf"),
                                 float("-inf")])
@pytest.mark.parametrize("method_name, args, names", GUARD_INPUTS)
def test_every_input_refuses_missing_and_non_finite(
        method_name, args, names, bad):
    twin = _new_twin()
    for index, name in enumerate(names):
        with pytest.raises(ValueError, match=name):
            getattr(twin, method_name)(_at(args, index, bad))


def test_a_risk_outside_zero_to_one_hundred_raises_instead_of_clipping():
    twin = _new_twin()
    with pytest.raises(ValueError, match="overflows"):
        twin._calc_cvd_risk([1e9, 0.95, 23.255])
    with pytest.raises(ValueError, match="overflows"):
        twin._calc_dm_risk([-1e9])


def test_risk_percent_refuses_a_value_outside_the_range():
    from health_lamina import _risk_percent

    with pytest.raises(ValueError, match="outside"):
        _risk_percent("risk", 100.5)
    with pytest.raises(ValueError, match="outside"):
        _risk_percent("risk", -0.5)


def test_a_short_input_list_is_refused():
    twin = _new_twin()
    with pytest.raises(ValueError, match="expected 2 inputs"):
        twin._calc_body_mass_index([89.0])
