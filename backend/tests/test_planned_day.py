"""
A planned day run through the lamina and answered in the /api/day shape.

The acceptance test is the one section 4.7 names: a plan copied from a
recorded day's sessions reproduces that day's session energy.  The default
plan must run end to end through POST /api/day/plan, every guard must refuse
by field, and the recorded /api/day must be untouched by the refactor.
"""
import copy
import json

import pytest
from fastapi.testclient import TestClient

import day_summary as ds
from bundles import load_bundle, load_params, subject_labels
from laminae import load_twin, resolve_lamina
from main import app
from plan_options import kind_groups, load_templates, plan_options
from planned_day import build_planned_bundle, summarise_bundle

LAMINA = "lamina_wearable"
SUBJECT = "subject_demo"
DATE = "2025-04-03"


@pytest.fixture(scope="module")
def options() -> dict:
    plan_options.cache_clear()
    return plan_options(LAMINA, SUBJECT)


@pytest.fixture(scope="module")
def templates() -> dict:
    data = load_templates(SUBJECT)
    assert data is not None
    return data


@pytest.fixture(scope="module")
def groups() -> dict:
    return kind_groups(load_twin(resolve_lamina(LAMINA)))


def _base_plan(options: dict) -> dict:
    return copy.deepcopy(dict(options["default_plan"], subject=SUBJECT))


def _post(plan, lamina: str = LAMINA):
    """Post a plan, keeping NaN on the wire as the non-standard literal it is."""
    client = TestClient(app)
    return client.post(
        "/api/day/plan",
        params={"lamina": lamina},
        content=json.dumps(plan, allow_nan=True).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


def test_a_plan_copied_from_a_recorded_day_reproduces_its_energy(
    options, templates, groups
):
    """Section 4.7's acceptance test: session energy is the recorded energy."""
    bundle = load_bundle(SUBJECT, DATE)
    params = load_params(SUBJECT)
    day = ds.day_summary(LAMINA, SUBJECT, DATE)

    offered = {kind["id"] for kind in options["kinds"]}
    intensity_id = options["roles"]["intensity"]["attribute"]

    compared = 0
    for recorded in day["sessions"]:
        minutes = range(recorded["start"], recorded["end"])
        all_worn = all(
            bundle["samples"][minute]["ae_kcal_min"] is not None
            for minute in minutes
        )
        if (
            recorded["minutes"] < 5
            or not all_worn
            or recorded["group"] not in offered
        ):
            continue

        intensity = sum(
            bundle["samples"][minute]["ae_kcal_min"] for minute in minutes
        ) / recorded["minutes"]
        count = sum(
            bundle["samples"][minute]["steps_min"] or 0
            for minute in minutes
        )
        plan = {
            "subject": SUBJECT,
            "awake": [0, 1440],
            "ambient": options["day"]["ambient"]["default"],
            "level": options["day"]["level"]["default"],
            "count_outside": 0,
            "sessions": [{
                "kind": recorded["group"],
                "start": recorded["start"],
                "minutes": recorded["minutes"],
                "intensity": intensity,
                "count": count,
            }],
        }

        planned_bundle = build_planned_bundle(plan, templates, groups)
        result = summarise_bundle(
            LAMINA, planned_bundle, params, options["subject_label"],
            planned=True,
        )
        planned = result["sessions"][0]
        assert planned["start"] == recorded["start"]
        assert planned["rate_totals"][intensity_id] == pytest.approx(
            recorded["rate_totals"][intensity_id], abs=1e-6
        )
        compared += 1

    assert compared >= 1


def test_the_default_plan_runs_through_the_endpoint(options):
    plan = _base_plan(options)
    response = _post(plan)
    assert response.status_code == 200
    body = response.json()

    assert body["planned"] is True
    assert body["summary"] is None
    assert all(value is None for value in body["pair"]["measured"])

    start, end = plan["awake"]
    modelled = body["pair"]["modelled"]
    for minute, value in enumerate(modelled):
        if start <= minute < end:
            assert value is not None
        else:
            assert value is None

    labels = {kind["id"]: kind["label"] for kind in options["kinds"]}
    sessions = sorted(body["sessions"], key=lambda item: item["start"])
    plan_sessions = sorted(plan["sessions"], key=lambda item: item["start"])
    assert len(sessions) == len(plan_sessions) == 2
    for session, spec in zip(sessions, plan_sessions):
        assert session["label"] == labels[spec["kind"]]
        assert session["group_label"] == labels[spec["kind"]]
        assert session["group"] == spec["kind"]
        assert session["target_set"] == spec["target"]
        assert session["peak_modelled"] >= session["mean_modelled"]

    steps_key = options["roles"]["count"]["attribute"]
    steps_kpi = {kpi["key"]: kpi for kpi in body["kpis"]}[steps_key]
    expected_steps = plan["count_outside"] + sum(
        spec["count"] for spec in plan["sessions"]
    )
    assert steps_kpi["value"] == pytest.approx(expected_steps, abs=1)


def _seven_sessions(plan: dict) -> None:
    plan["sessions"].extend([
        {"kind": "walk", "start": 500 + 60 * i, "minutes": 20,
         "intensity": 3.0, "count": 100}
        for i in range(5)
    ])


def _reversed_awake(plan: dict) -> None:
    plan["awake"] = [500, 400]


def _unknown_key(plan: dict) -> None:
    plan["banana"] = 1


@pytest.mark.parametrize(
    "mutate,field",
    [
        (lambda plan: plan["sessions"][0].__setitem__("kind", "nope"),
         "sessions[0].kind"),
        (lambda plan: plan["sessions"][0].__setitem__(
            "start", plan["awake"][0] - 5), "sessions[0].start"),
        (lambda plan: plan["sessions"][1].__setitem__(
            "start", plan["sessions"][0]["start"] + 1), "sessions[1].start"),
        (_seven_sessions, "sessions"),
        (lambda plan: plan["sessions"][0].__setitem__("minutes", 4),
         "sessions[0].minutes"),
        (lambda plan: plan["sessions"][0].__setitem__("minutes", 181),
         "sessions[0].minutes"),
        (lambda plan: plan["sessions"][0].__setitem__("intensity", -1.0),
         "sessions[0].intensity"),
        (lambda plan: plan["sessions"][0].__setitem__("count", -1),
         "sessions[0].count"),
        (lambda plan: plan["sessions"][0].__setitem__(
            "intensity", float("nan")), "sessions[0].intensity"),
        (_reversed_awake, "awake"),
        (_unknown_key, "banana"),
    ],
)
def test_a_refused_plan_names_the_field(options, mutate, field):
    plan = _base_plan(options)
    mutate(plan)
    response = _post(plan)
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == field


def test_a_body_that_is_not_an_object_is_422():
    client = TestClient(app)
    response = client.post(
        "/api/day/plan", params={"lamina": LAMINA}, json=[1, 2, 3]
    )
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "plan"


def test_a_lamina_without_a_plan_view_is_400(options):
    response = _post(_base_plan(options), lamina="lamina_circulatory")
    assert response.status_code == 400
    assert response.json()["detail"]["lamina"] == "lamina_circulatory"


def test_an_unknown_subject_is_404(options):
    plan = _base_plan(options)
    plan["subject"] = "nobody_here"
    response = _post(plan)
    assert response.status_code == 404
    assert response.json()["detail"]["subject"] == "nobody_here"


def test_a_subject_without_templates_is_404(options):
    plan = _base_plan(options)
    plan["subject"] = "demo"
    response = _post(plan)
    assert response.status_code == 404
    assert response.json()["detail"]["subject"] == "demo"


def test_a_recorded_day_is_still_the_same_summary():
    expected = summarise_bundle(
        LAMINA,
        load_bundle(SUBJECT, DATE),
        load_params(SUBJECT),
        subject_labels().get(SUBJECT, SUBJECT),
    )
    client = TestClient(app)
    response = client.get(
        "/api/day",
        params={"lamina": LAMINA, "subject": SUBJECT, "date": DATE},
    )
    assert response.status_code == 200
    assert response.json() == expected


def test_the_default_targets_are_what_the_model_reaches(options):
    """
    The default plan's targets are read at each kind's typical level, so a
    session settles near the target it was given (within the 1 h grain of
    the settle table's clock, about 1 bpm here).
    """
    plan = dict(options["default_plan"], subject=SUBJECT)
    response = TestClient(app).post(
        "/api/day/plan", params={"lamina": LAMINA}, json=plan
    )
    assert response.status_code == 200
    for session in response.json()["sessions"]:
        assert abs(session["target_set"] - session["mean_modelled"]) < 1.5


@pytest.mark.parametrize("field, value", [
    ("level", True), ("level", 999), ("ambient", float("nan")), ("ambient", -50),
])
def test_a_refused_level_or_temperature_names_its_field(options, field, value):
    plan = dict(options["default_plan"], subject=SUBJECT)
    plan[field] = value
    response = TestClient(app).post(
        "/api/day/plan", params={"lamina": LAMINA}, content=json.dumps(plan),
        headers={"content-type": "application/json"},
    ) if value != value else TestClient(app).post(
        "/api/day/plan", params={"lamina": LAMINA}, json=plan
    )
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == field


@pytest.mark.parametrize("missing", ["subject", "level", "ambient"])
def test_a_missing_required_field_is_named(options, missing):
    plan = dict(options["default_plan"], subject=SUBJECT)
    del plan[missing]
    response = TestClient(app).post(
        "/api/day/plan", params={"lamina": LAMINA}, json=plan
    )
    assert response.status_code == 422
    assert response.json()["detail"]["field"] == missing
