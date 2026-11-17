"""
The generic assessment evaluator, measured on the health-risk lamina.

WHAT THIS FILE MEASURES

  THE OPTIONS COME FROM THE VIEW.  Groups, entries, links, examples, measured
  links, horizons and mediators are the lamina's own declaration, and each
  result's dependency walk names the real functions, entries and links behind
  it — the cardiovascular result must not list the glucose entry and the
  diabetes result must not list the HDL one.

  THE BORDERLINE EXAMPLE, AGAINST THE FORMULAS.  The expected risks and the
  adapted factors are recomputed here with math from the lamina's declared
  baselines, never by reading the evaluator back, so a change to the
  arithmetic has to be argued for.

  THE HORIZONS.  At week 0 every series equals the value now; the settled
  value is a separate run at the settled horizon; ``planned`` is the last
  horizon's value; the mediators report their own movement and what they
  still need.

  WHAT IS MISSING STAYS NAMED.  An omitted entry or recording leaves only the
  results that need it stale and appears by name in ``needs``; no links leave
  only the planned values stale.  A flag whose inputs are absent is
  ``not_answered``.

  THE REFUSALS.  Every malformed or out-of-range entry, link and measured
  value is refused by field, so a wrong input cannot produce a
  confident-looking answer.
"""

import math

import pytest

from assessment import (
    EntryRefused,
    NoAssessmentView,
    assess,
    assessment_options,
)
from laminae import load_twin, resolve_lamina

LAMINA_ID = "lamina_health"

EXAMPLE = {
    "age": 52.0,
    "sex_male": 1.0,
    "height_cm": 175.0,
    "mass_kg": 89.0,
    "sbp": 134.0,
    "dbp": 86.0,
    "chol_total": 5.8,
    "chol_hdl": 1.1,
    "glucose_fasting": 6.3,
    "smoker": 0.0,
    "diabetes": 0.0,
    "bp_treated": 0.0,
    "family_diabetes": 1.0,
    "hr_medicine": 0.0,
}

LINKS = {"current": 21.074, "planned": 45.801}
MEASURED = {"resting_hr": 66.0, "vo2max": 26.13}

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

NOTICE = (
    "Placeholder models: the figures below are not validated and are not "
    "medical advice."
)


def _twin():
    return load_twin(resolve_lamina(LAMINA_ID))


def _entries(**changes) -> dict:
    entries = dict(EXAMPLE)
    for attribute_id, value in changes.items():
        if value is None:
            entries.pop(attribute_id, None)
        else:
            entries[attribute_id] = value
    return entries


def _results(report: dict) -> dict:
    return {result["id"]: result for result in report["results"]}


def _flags(report: dict) -> dict:
    return {flag["attribute"]: flag for flag in report["flags"]}


def _mediators(report: dict) -> dict:
    return {mediator["now"]: mediator for mediator in report["mediators"]}


def _coef(twin, attribute_id: str) -> float:
    return twin.attributes[attribute_id].baseline


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _hand_adapt(now, added, weeks, per_10, cap, weeks_half, limit):
    settled = _clamp(per_10 * added / 10.0, -cap, cap)
    shift = settled * (1.0 - 2.0 ** (-weeks / weeks_half))
    value = now + shift
    if per_10 < 0.0 and shift < 0.0:
        value = max(value, min(now, limit))
    if per_10 > 0.0 and shift > 0.0:
        value = min(value, max(now, limit))
    return now if per_10 == 0.0 else value


def _now_factors() -> dict:
    factors = dict(EXAMPLE)
    factors.update(MEASURED)
    return factors


def _hand_mediators(twin, factors, weeks):
    added = LINKS["planned"] - LINKS["current"]
    return {
        now_id: _hand_adapt(
            factors[now_id], added, weeks,
            _coef(twin, f"{now_id}_per_10"),
            _coef(twin, f"{now_id}_cap"),
            _coef(twin, f"{now_id}_weeks_half"),
            _coef(twin, f"{now_id}_limit"),
        )
        for now_id, _at_id in MEDIATORS
    }


def _hand_risk(twin, factors) -> tuple[float, float]:
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


def _hand_at(twin, weeks: float) -> tuple[float, float]:
    factors = _now_factors()
    factors.update(_hand_mediators(twin, factors, weeks))
    return _hand_risk(twin, factors)


# ── Options: the view is the source of truth ──────────────────────────

def test_options_match_the_declared_view():
    twin = _twin()
    view = twin.assessment_view
    options = assessment_options(LAMINA_ID)

    assert options["lamina"] == LAMINA_ID
    assert options["name"] == twin.lamina_name
    assert options["groups"] == view["groups"]
    assert options["links"] == view["links"]
    assert options["examples"] == view["examples"]
    assert options["example"] == view["example"]
    assert options["measured"] == view["measured"]
    assert options["horizons"] == view["horizons"]


def test_options_range_is_read_from_the_endpoint_baselines():
    twin = _twin()
    options = assessment_options(LAMINA_ID)

    assert options["range"]["low"] == twin.attributes[
        "dose_guideline_low"].baseline
    assert options["range"]["high"] == twin.attributes[
        "dose_guideline_high"].baseline
    assert options["range"]["unit"] == twin.attributes[
        "dose_guideline_low"].unit


def test_every_result_is_a_placeholder_with_a_real_model_chain():
    twin = _twin()
    options = assessment_options(LAMINA_ID)

    assert options["notice"] == NOTICE
    assert options["results"]
    for result in options["results"]:
        assert result["status"] == "placeholder"
        assert result["models"]
        for model in result["models"]:
            assert model["id"] in twin.functions


def test_the_dependency_walk_separates_the_two_results():
    options = assessment_options(LAMINA_ID)
    results = {result["id"]: result for result in options["results"]}

    assert "glucose_fasting" not in results["cvd"]["entries"]
    assert "chol_hdl" not in results["diabetes"]["entries"]
    assert "glucose_fasting" in results["diabetes"]["entries"]
    assert "chol_hdl" in results["cvd"]["entries"]
    # Body mass index is a computed input of the diabetes chain, so its
    # function belongs to that chain even though no result names it.
    assert any(
        model["id"] == "body_mass_index_now"
        for model in results["diabetes"]["models"]
    )
    assert results["cvd"]["links"] == ["current", "planned"]


def test_the_options_mediators_carry_their_chain_and_source():
    twin = _twin()
    options = assessment_options(LAMINA_ID)
    by_now = {mediator["now"]: mediator for mediator in options["mediators"]}

    assert len(options["mediators"]) == len(MEDIATORS)
    for mediator in options["mediators"]:
        assert mediator["status"] == "placeholder"
        assert mediator["models"]
        for model in mediator["models"]:
            assert model["id"] in twin.functions
    assert by_now["resting_hr"]["source"] == "measured"
    assert by_now["resting_hr"]["key"] == "resting_hr"
    assert by_now["vo2max"]["source"] == "measured"
    assert by_now["glucose_fasting"]["source"] == "entered"
    assert by_now["chol_total"]["still"]
    assert by_now["mass_kg"]["still"]


# ── The borderline example, against the hand-computed formulas ────────

def test_the_borderline_example_matches_the_hand_computed_chain():
    twin = _twin()
    report = assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS), dict(MEASURED))
    results = _results(report)

    expected_now_cvd, expected_now_dm = _hand_risk(twin, _now_factors())
    assert results["cvd"]["now"] == pytest.approx(
        round(expected_now_cvd, 2), abs=1e-9)
    assert results["diabetes"]["now"] == pytest.approx(
        round(expected_now_dm, 2), abs=1e-9)
    assert results["cvd"]["now"] == 14.3
    assert results["diabetes"]["now"] == 19.33

    for index, weeks in enumerate([0.0, 4.0, 8.0, 12.0]):
        expected_cvd, expected_dm = _hand_at(twin, weeks)
        assert results["cvd"]["series"][index] == {
            "weeks": weeks, "value": round(expected_cvd, 2),
        }
        assert results["diabetes"]["series"][index] == {
            "weeks": weeks, "value": round(expected_dm, 2),
        }

    expected_settled_cvd, expected_settled_dm = _hand_at(twin, 1000.0)
    assert results["cvd"]["settled"] == pytest.approx(
        round(expected_settled_cvd, 2), abs=1e-9)
    assert results["diabetes"]["settled"] == pytest.approx(
        round(expected_settled_dm, 2), abs=1e-9)
    assert results["cvd"]["settled"] == 10.74
    assert results["diabetes"]["settled"] == 14.65

    assert results["cvd"]["planned"] == results["cvd"]["series"][-1]["value"]
    assert results["diabetes"]["planned"] == (
        results["diabetes"]["series"][-1]["value"]
    )
    assert results["cvd"]["change"]["points"] < 0
    assert results["diabetes"]["change"]["points"] < 0

    mediators = _mediators(report)
    assert [point["value"] for point in
            mediators["glucose_fasting"]["series"]] == [
        6.3, 6.19, 6.11, 6.06,
    ]
    assert mediators["glucose_fasting"]["settled"] == 5.93

    assert report["horizons"] == twin.assessment_view["horizons"]
    flags = _flags(report)
    assert flags["flag_bp"]["state"] == "clear"
    assert flags["flag_dose_jump"]["state"] == "raised"
    assert flags["flag_medicine"]["state"] == "clear"

    assert report["entered"] == {"given": len(EXAMPLE), "of": len(EXAMPLE)}
    assert report["notice"] == NOTICE


def test_the_mediators_report_movement_and_their_source():
    report = assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS), dict(MEASURED))
    mediators = _mediators(report)

    assert mediators["chol_total"]["moves"] is False
    assert mediators["mass_kg"]["moves"] is False
    assert mediators["chol_total"]["still"]
    assert mediators["mass_kg"]["still"]
    assert mediators["resting_hr"]["source"] == "measured"
    assert mediators["resting_hr"]["key"] == "resting_hr"
    assert mediators["vo2max"]["source"] == "measured"
    assert mediators["resting_hr"]["moves"] is True
    assert mediators["vo2max"]["moves"] is True
    assert mediators["glucose_fasting"]["value_now"] == 6.3
    assert mediators["glucose_fasting"]["series"][0]["value"] == 6.3


# ── Missing entries, links and recordings ─────────────────────────────

def test_a_missing_entry_names_only_the_result_that_needs_it():
    report = assess(
        LAMINA_ID, _entries(chol_hdl=None), dict(LINKS), dict(MEASURED)
    )
    results = _results(report)

    assert results["cvd"]["now"] is None
    assert results["cvd"]["series"][0]["value"] is None
    assert [need["attribute"] for need in results["cvd"]["needs"]["now"]] == [
        "chol_hdl"
    ]
    assert results["diabetes"]["now"] is not None
    assert results["diabetes"]["needs"]["now"] == []


def test_no_links_leave_the_planned_values_stale():
    report = assess(LAMINA_ID, dict(EXAMPLE), measured=dict(MEASURED))
    results = _results(report)

    for result in results.values():
        assert result["now"] is not None
        assert result["planned"] is None
        assert result["change"] is None
        assert [point["value"] for point in result["series"]] == [None] * 4
        assert result["settled"] is None
        assert {need.get("link") for need in result["needs"]["planned"]
                if "link" in need} == {"current", "planned"}


def test_without_measured_the_risks_are_stale_and_name_what_they_need():
    report = assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS))
    results = _results(report)

    for result in results.values():
        assert result["now"] is None
        assert result["planned"] is None
        assert [point["value"] for point in result["series"]] == [None] * 4
        assert result["settled"] is None

    cvd_measured = {
        need.get("measured")
        for side in ("now", "planned")
        for need in results["cvd"]["needs"][side]
        if "measured" in need
    }
    assert cvd_measured == {"resting_hr", "vo2max"}
    diabetes_measured = {
        need.get("measured")
        for side in ("now", "planned")
        for need in results["diabetes"]["needs"][side]
        if "measured" in need
    }
    assert diabetes_measured == {"vo2max"}
    for need in results["cvd"]["needs"]["now"]:
        if need.get("measured") == "resting_hr":
            assert need["label"] == (
                "Resting heart rate, from your recordings"
            )


def test_a_not_applicable_result_is_hidden_but_the_other_computes():
    view = _twin().assessment_view
    text = next(
        result["not_applicable_text"]
        for result in view["results"]
        if result["id"] == "diabetes"
    )
    report = assess(
        LAMINA_ID, _entries(diabetes=1.0), dict(LINKS), dict(MEASURED)
    )
    results = _results(report)

    assert results["diabetes"]["not_applicable"] == text
    assert results["diabetes"]["now"] is None
    assert results["diabetes"]["planned"] is None
    assert results["diabetes"]["series"] == [
        {"weeks": 0.0, "value": None},
        {"weeks": 4.0, "value": None},
        {"weeks": 8.0, "value": None},
        {"weeks": 12.0, "value": None},
    ]
    assert results["diabetes"]["settled"] is None
    assert results["diabetes"]["needs"] == {"now": [], "planned": []}
    assert results["cvd"]["now"] is not None
    assert results["cvd"]["planned"] is not None


# ── Flags ─────────────────────────────────────────────────────────────

def test_high_pressure_raises_the_blood_pressure_flag():
    report = assess(
        LAMINA_ID, _entries(sbp=170.0), dict(LINKS), dict(MEASURED)
    )
    flags = _flags(report)

    assert flags["flag_bp"]["state"] == "raised"
    assert flags["flag_medicine"]["state"] == "clear"


def test_a_large_jump_raises_the_jump_flag():
    report = assess(
        LAMINA_ID, dict(EXAMPLE), {"current": 10.0, "planned": 30.0},
        dict(MEASURED),
    )
    flags = _flags(report)

    assert flags["flag_dose_jump"]["state"] == "raised"
    assert flags["flag_bp"]["state"] == "clear"


def test_an_unanswered_entry_leaves_the_flag_not_answered():
    report = assess(
        LAMINA_ID, _entries(sbp=None), dict(LINKS), dict(MEASURED)
    )
    flag = _flags(report)["flag_bp"]

    assert flag["state"] == "not_answered"
    assert [need["attribute"] for need in flag["needs"]] == ["sbp"]


# ── Refusals ──────────────────────────────────────────────────────────

def _refused(field: str, entries, links=None, measured=None) -> None:
    with pytest.raises(EntryRefused) as refused:
        assess(LAMINA_ID, entries, links, measured)
    assert refused.value.field == field


def test_entries_must_be_an_object():
    _refused("entries", [("age", 52.0)])


def test_an_unknown_entry_is_refused_by_id():
    _refused("entries.house_number", {"house_number": 1.0})


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), float("-inf"), True, "52",
])
def test_a_non_number_entry_is_refused(value):
    _refused("entries.age", _entries(age=value))


def test_an_entry_outside_its_range_is_refused():
    _refused("entries.age", _entries(age=5.0))


def test_a_yesno_entry_must_be_zero_or_one():
    _refused("entries.smoker", _entries(smoker=0.5))


def test_a_choice_entry_must_be_a_declared_option():
    _refused("entries.sex_male", _entries(sex_male=0.5))


def test_links_must_be_an_object():
    _refused("links", dict(EXAMPLE), ["current"], dict(MEASURED))


def test_an_unknown_link_role_is_refused():
    _refused(
        "links.tomorrow", dict(EXAMPLE), {"tomorrow": 5.0}, dict(MEASURED)
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "10"])
def test_a_non_number_link_is_refused(value):
    _refused(
        "links.current", dict(EXAMPLE), {"current": value}, dict(MEASURED)
    )


def test_a_negative_link_is_refused():
    _refused(
        "links.current", dict(EXAMPLE), {"current": -1.0}, dict(MEASURED)
    )


def test_a_link_outside_the_attribute_range_is_refused():
    _refused(
        "links.current", dict(EXAMPLE), {"current": 1000.0}, dict(MEASURED)
    )


def test_measured_must_be_an_object():
    _refused("measured", dict(EXAMPLE), dict(LINKS), ["resting_hr"])


@pytest.mark.parametrize("value", [
    float("nan"), float("inf"), float("-inf"), True, "66",
])
def test_a_non_number_measured_value_is_refused(value):
    _refused(
        "measured.resting_hr", dict(EXAMPLE), dict(LINKS),
        {"resting_hr": value},
    )


def test_a_measured_value_outside_its_range_is_refused():
    _refused(
        "measured.vo2max", dict(EXAMPLE), dict(LINKS),
        {"vo2max": 200.0},
    )


def test_an_unknown_measured_key_is_ignored():
    report = assess(
        LAMINA_ID, dict(EXAMPLE), dict(LINKS),
        dict(MEASURED, weight_kg=89.0),
    )
    assert _results(report)["cvd"]["now"] is not None


# ── Privacy ──────────────────────────────────────────────────────────

def test_nothing_entered_or_measured_is_printed(capsys):
    assess(
        LAMINA_ID, _entries(sbp=133.7), dict(LINKS),
        {"resting_hr": 61.37, "vo2max": 26.13},
    )
    captured = capsys.readouterr()

    for text in ("133.7", "61.37"):
        assert text not in captured.out
        assert text not in captured.err


# ── A lamina without the view ────────────────────────────────────────

def test_a_lamina_without_the_view_is_refused():
    with pytest.raises(NoAssessmentView) as refused:
        assessment_options("lamina_wearable")
    assert refused.value.lamina_id == "lamina_wearable"

    with pytest.raises(NoAssessmentView) as refused:
        assess("lamina_wearable", {})


# ── Invariants ───────────────────────────────────────────────────────

def test_every_series_starts_at_the_value_now():
    report = assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS), dict(MEASURED))

    for result in report["results"]:
        assert result["series"][0]["value"] == pytest.approx(
            result["now"], abs=1e-9)
    for mediator in report["mediators"]:
        assert mediator["series"][0]["value"] == pytest.approx(
            mediator["value_now"], abs=1e-9)


def test_needs_now_is_empty_exactly_when_now_is_answered():
    reports = [
        assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS), dict(MEASURED)),
        assess(
            LAMINA_ID, _entries(chol_hdl=None), dict(LINKS), dict(MEASURED)
        ),
        assess(LAMINA_ID, _entries(age=None), dict(LINKS), dict(MEASURED)),
        assess(LAMINA_ID, dict(EXAMPLE), measured=dict(MEASURED)),
        assess(
            LAMINA_ID, _entries(diabetes=1.0), dict(LINKS), dict(MEASURED)
        ),
    ]
    for report in reports:
        for result in report["results"]:
            answered = (
                result["now"] is not None
                or result["not_applicable"] is not None
                or result["reason"] is not None
            )
            assert (len(result["needs"]["now"]) == 0) == answered
