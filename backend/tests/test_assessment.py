"""
The generic assessment evaluator, measured on the health-risk lamina.

WHAT THIS FILE MEASURES

  THE OPTIONS COME FROM THE VIEW.  Groups, entries, links and range are the
  lamina's own declaration, and each result's dependency walk names the real
  functions, entries and links behind it — the cardiovascular result must not
  list the glucose entry and the diabetes result must not list the HDL one.

  THE EXAMPLE, AGAINST THE FORMULAS.  The expected risks are recomputed here
  with math from the lamina's declared baselines, never by reading the
  evaluator back, so a change to the arithmetic has to be argued for.

  WHAT IS MISSING STAYS NAMED.  An omitted entry leaves only the results that
  need it stale and appears by name in ``needs``; no links leave only the
  planned values stale.  A flag whose inputs are absent is ``not_answered``.

  THE REFUSALS.  Every malformed or out-of-range entry and link is refused by
  field, so a wrong input cannot produce a confident-looking answer.
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

LINKS = {"current": 10.0, "planned": 15.0}

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


def _relative_risk(dose: float, act_max: float, act_scale: float) -> float:
    return 1.0 - act_max * (1.0 - math.exp(-dose / act_scale))


def _risk_at_ratio(risk_now: float, rr_planned: float,
                   rr_current: float) -> float:
    return 100.0 * (1.0 - (1.0 - risk_now / 100.0) **
                    (rr_planned / rr_current))


def _expected() -> dict:
    """The example's four risks, recomputed from the declared baselines."""
    twin = _twin()

    def coefficient(attribute_id: str) -> float:
        return twin.attributes[attribute_id].baseline

    age = EXAMPLE["age"]
    bmi = EXAMPLE["mass_kg"] / (EXAMPLE["height_cm"] / 100.0) ** 2

    cvd_lp = (
        coefficient("c_age") * math.log(age)
        + coefficient("c_sbp") * math.log(EXAMPLE["sbp"])
        + coefficient("c_tc") * math.log(EXAMPLE["chol_total"])
        + coefficient("c_hdl") * math.log(EXAMPLE["chol_hdl"])
        + coefficient("c_smoker") * EXAMPLE["smoker"]
        + coefficient("c_diabetes") * EXAMPLE["diabetes"]
        + coefficient("c_treated") * EXAMPLE["bp_treated"]
        + coefficient("c_male") * EXAMPLE["sex_male"]
    )
    cvd_now = 100.0 * (
        1.0 - coefficient("cvd_S0") **
        math.exp(cvd_lp - coefficient("cvd_lp_ref"))
    )

    dm_lp = (
        coefficient("d_0")
        + coefficient("d_age") * age
        + coefficient("d_bmi") * bmi
        + coefficient("d_glucose") * EXAMPLE["glucose_fasting"]
        + coefficient("d_family") * EXAMPLE["family_diabetes"]
        + coefficient("d_treated") * EXAMPLE["bp_treated"]
    )
    dm_now = 100.0 / (1.0 + math.exp(-dm_lp))

    cvd_rr_current = _relative_risk(
        LINKS["current"], coefficient("cvd_act_max"),
        coefficient("cvd_act_scale")
    )
    cvd_rr_planned = _relative_risk(
        LINKS["planned"], coefficient("cvd_act_max"),
        coefficient("cvd_act_scale")
    )
    dm_rr_current = _relative_risk(
        LINKS["current"], coefficient("dm_act_max"),
        coefficient("dm_act_scale")
    )
    dm_rr_planned = _relative_risk(
        LINKS["planned"], coefficient("dm_act_max"),
        coefficient("dm_act_scale")
    )

    return {
        "cvd_now": cvd_now,
        "cvd_plan": _risk_at_ratio(cvd_now, cvd_rr_planned,
                                   cvd_rr_current),
        "dm_now": dm_now,
        "dm_plan": _risk_at_ratio(dm_now, dm_rr_planned, dm_rr_current),
    }


# ── Options: the view is the source of truth ──────────────────────────

def test_options_match_the_declared_view():
    twin = _twin()
    view = twin.assessment_view
    options = assessment_options(LAMINA_ID)

    assert options["lamina"] == LAMINA_ID
    assert options["name"] == twin.lamina_name
    assert options["groups"] == view["groups"]
    assert options["links"] == view["links"]
    assert options["example"] == view["example"]


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
        model["id"] == "body_mass_index"
        for model in results["diabetes"]["models"]
    )
    assert results["cvd"]["links"] == ["current", "planned"]


# ── The example, against the hand-computed formulas ───────────────────

def test_the_example_computes_the_lamina_values():
    report = assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS))
    results = _results(report)
    expected = _expected()

    assert results["cvd"]["now"] == pytest.approx(
        round(expected["cvd_now"], 2), abs=1e-9)
    assert results["cvd"]["planned"] == pytest.approx(
        round(expected["cvd_plan"], 2), abs=1e-9)
    assert results["diabetes"]["now"] == pytest.approx(
        round(expected["dm_now"], 2), abs=1e-9)
    assert results["diabetes"]["planned"] == pytest.approx(
        round(expected["dm_plan"], 2), abs=1e-9)

    assert results["cvd"]["change"]["points"] < 0
    assert results["diabetes"]["change"]["points"] < 0
    assert results["cvd"]["change"]["relative_pct"] < 0

    flags = _flags(report)
    assert flags["flag_bp"]["state"] == "clear"
    assert flags["flag_dose_jump"]["state"] == "clear"
    assert flags["flag_medicine"]["state"] == "clear"

    assert report["entered"] == {"given": len(EXAMPLE), "of": len(EXAMPLE)}
    assert report["notice"] == NOTICE


# ── Missing entries and missing links ─────────────────────────────────

def test_a_missing_entry_names_only_the_result_that_needs_it():
    report = assess(LAMINA_ID, _entries(chol_hdl=None), dict(LINKS))
    results = _results(report)

    assert results["cvd"]["now"] is None
    assert [need["attribute"] for need in results["cvd"]["needs"]["now"]] == [
        "chol_hdl"
    ]
    assert results["diabetes"]["now"] is not None
    assert results["diabetes"]["needs"]["now"] == []


def test_no_links_leave_the_planned_values_stale():
    report = assess(LAMINA_ID, dict(EXAMPLE))
    results = _results(report)

    for result in results.values():
        assert result["now"] is not None
        assert result["planned"] is None
        assert result["change"] is None
        assert {need.get("link") for need in result["needs"]["planned"]
                if "link" in need} == {"current", "planned"}


def test_a_not_applicable_result_is_hidden_but_the_other_computes():
    view = _twin().assessment_view
    text = next(
        result["not_applicable_text"]
        for result in view["results"]
        if result["id"] == "diabetes"
    )
    report = assess(LAMINA_ID, _entries(diabetes=1.0), dict(LINKS))
    results = _results(report)

    assert results["diabetes"]["not_applicable"] == text
    assert results["diabetes"]["now"] is None
    assert results["diabetes"]["planned"] is None
    assert results["diabetes"]["needs"] == {"now": [], "planned": []}
    assert results["cvd"]["now"] is not None
    assert results["cvd"]["planned"] is not None


# ── Flags ─────────────────────────────────────────────────────────────

def test_high_pressure_raises_the_blood_pressure_flag():
    report = assess(LAMINA_ID, _entries(sbp=170.0), dict(LINKS))
    flags = _flags(report)

    assert flags["flag_bp"]["state"] == "raised"
    assert flags["flag_dose_jump"]["state"] == "clear"


def test_a_large_jump_raises_the_jump_flag():
    report = assess(
        LAMINA_ID, dict(EXAMPLE), {"current": 10.0, "planned": 30.0}
    )
    flags = _flags(report)

    assert flags["flag_dose_jump"]["state"] == "raised"
    assert flags["flag_bp"]["state"] == "clear"


def test_an_unanswered_entry_leaves_the_flag_not_answered():
    report = assess(LAMINA_ID, _entries(sbp=None), dict(LINKS))
    flag = _flags(report)["flag_bp"]

    assert flag["state"] == "not_answered"
    assert [need["attribute"] for need in flag["needs"]] == ["sbp"]


# ── Refusals ──────────────────────────────────────────────────────────

def _refused(field: str, entries, links=None) -> None:
    with pytest.raises(EntryRefused) as refused:
        assess(LAMINA_ID, entries, links)
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
    _refused("links", dict(EXAMPLE), ["current"])


def test_an_unknown_link_role_is_refused():
    _refused("links.tomorrow", dict(EXAMPLE), {"tomorrow": 5.0})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "10"])
def test_a_non_number_link_is_refused(value):
    _refused("links.current", dict(EXAMPLE), {"current": value})


def test_a_negative_link_is_refused():
    _refused("links.current", dict(EXAMPLE), {"current": -1.0})


def test_a_link_outside_the_attribute_range_is_refused():
    _refused("links.current", dict(EXAMPLE), {"current": 1000.0})


# ── Privacy ──────────────────────────────────────────────────────────

def test_nothing_entered_is_printed(capsys):
    assess(LAMINA_ID, _entries(sbp=133.7), dict(LINKS))
    captured = capsys.readouterr()

    assert "133.7" not in captured.out
    assert "133.7" not in captured.err


# ── A lamina without the view ────────────────────────────────────────

def test_a_lamina_without_the_view_is_refused():
    with pytest.raises(NoAssessmentView) as refused:
        assessment_options("lamina_wearable")
    assert refused.value.lamina_id == "lamina_wearable"

    with pytest.raises(NoAssessmentView) as refused:
        assess("lamina_wearable", {})


# ── Invariant ────────────────────────────────────────────────────────

def test_needs_now_is_empty_exactly_when_now_is_answered():
    reports = [
        assess(LAMINA_ID, dict(EXAMPLE), dict(LINKS)),
        assess(LAMINA_ID, _entries(chol_hdl=None), dict(LINKS)),
        assess(LAMINA_ID, _entries(age=None), dict(LINKS)),
        assess(LAMINA_ID, dict(EXAMPLE)),
        assess(LAMINA_ID, _entries(diabetes=1.0), dict(LINKS)),
    ]
    for report in reports:
        for result in report["results"]:
            answered = (
                result["now"] is not None
                or result["not_applicable"] is not None
                or result["reason"] is not None
            )
            assert (len(result["needs"]["now"]) == 0) == answered
