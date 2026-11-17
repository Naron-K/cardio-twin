"""
POST /api/assessment — entered figures read against a planned week.

The reported dose comes from the plan's own day and the subject's recorded
week; the assessment is the health lamina's own view.  These tests pin the
endpoint's success shape, the no-plan case, the refusals by field, and the
privacy rule: no entered value and no entry id may reach the server log.
"""
import copy

import pytest
from fastapi.testclient import TestClient

from assessment import assessment_options
from main import app
from plan_options import plan_options

ASSESS_LAMINA = "lamina_health"
ACTIVITY_LAMINA = "lamina_wearable"
SUBJECT = "subject_demo"


@pytest.fixture(scope="module")
def options() -> dict:
    plan_options.cache_clear()
    return plan_options(ACTIVITY_LAMINA, SUBJECT)


@pytest.fixture(scope="module")
def example() -> dict:
    return dict(assessment_options(ASSESS_LAMINA)["example"]["values"])


def _plan(options: dict) -> dict:
    return copy.deepcopy(dict(options["default_plan"], subject=SUBJECT))


def _post(body, *, lamina=ASSESS_LAMINA, activity=ACTIVITY_LAMINA):
    client = TestClient(app)
    return client.post(
        "/api/assessment",
        params={"lamina": lamina, "activity_lamina": activity},
        json=body,
    )


def _body(options: dict, example: dict, **changes) -> dict:
    body = {
        "subject": SUBJECT,
        "entries": dict(example),
        "plan": _plan(options),
        "days_per_week": 5,
    }
    body.update(changes)
    return body


def test_options_without_a_lamina_pick_the_health_lamina():
    response = TestClient(app).get("/api/assessment/options")

    assert response.status_code == 200
    assert response.json()["lamina"] == ASSESS_LAMINA
    assert response.json()["results"]


def test_options_for_a_lamina_without_the_view_is_400():
    response = TestClient(app).get(
        "/api/assessment/options", params={"lamina": ACTIVITY_LAMINA}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["lamina"] == ACTIVITY_LAMINA


def test_the_example_with_the_default_plan_reports_now_and_planned(
    options, example
):
    response = _post(_body(options, example))

    assert response.status_code == 200
    body = response.json()
    assert body["subject"] == SUBJECT
    assert body["subject_label"] == "Subject demo"
    assert body["dose"]["planned"]["value"] > 0
    assert body["dose"]["planned"]["days_per_week"] == 5
    assert set(body["day"]) >= {"pair", "sessions", "kpis", "dose"}
    assert body["day"]["planned"] is True

    results = body["assessment"]["results"]
    assert {result["id"] for result in results} == {"cvd", "diabetes"}
    for result in results:
        assert result["now"] is not None
        assert result["planned"] is not None
        assert result["change"] is not None


def test_without_a_plan_only_the_recorded_week_is_offered(options, example):
    response = _post(_body(options, example, plan=None))

    assert response.status_code == 200
    body = response.json()
    assert body["day"] is None
    assert body["dose"]["planned"] is None
    for result in body["assessment"]["results"]:
        assert result["planned"] is None
        assert any(
            need.get("link") == "planned" for need in result["needs"]["planned"]
        )


def test_a_missing_entry_is_named_in_needs(options, example):
    entries = dict(example)
    del entries["chol_hdl"]
    response = _post(_body(options, example, entries=entries))

    assert response.status_code == 200
    named = {
        need.get("attribute")
        for result in response.json()["assessment"]["results"]
        for side in ("now", "planned")
        for need in result["needs"][side]
    }
    assert "chol_hdl" in named


def test_an_entry_outside_its_range_names_the_field(options, example):
    entries = dict(example, sbp=933.7)
    response = _post(_body(options, example, entries=entries))

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "entries.sbp"


def test_an_unknown_top_level_key_is_refused(options, example):
    response = _post(_body(options, example, banana=1))

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "banana"


def test_an_unknown_subject_is_404(options, example):
    response = _post(_body(options, example, subject="nobody_here", plan=None))

    assert response.status_code == 404
    assert response.json()["detail"]["subject"] == "nobody_here"


def test_a_plan_for_another_subject_is_refused(options, example):
    plan = dict(_plan(options), subject="demo")
    response = _post(_body(options, example, plan=plan))

    assert response.status_code == 422
    assert response.json()["detail"]["field"] == "plan.subject"


def test_nothing_entered_is_printed(options, example, capsys):
    valid = dict(example, sbp=133.7)
    refused = dict(example, sbp=933.7)

    _post(_body(options, example, entries=valid))
    _post(_body(options, example, entries=refused))

    captured = capsys.readouterr()
    for text in ("133.7", "933.7", "sbp"):
        assert text not in captured.out
        assert text not in captured.err


def test_the_planned_parts_add_up(options, example):
    response = _post(_body(options, example))

    assert response.status_code == 200
    planned = response.json()["dose"]["planned"]
    assert (
        planned["from_sessions"] + planned["from_everyday"]
        == pytest.approx(planned["value"], abs=1e-6)
    )
