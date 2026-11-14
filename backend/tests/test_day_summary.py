"""
The day summary and GET /api/day on the committed demo day.

Everything here runs on the synthetic demo bundle: no real person's data.
The lamina declares the roles, so the module names no attribute id of its
own — that is asserted directly against its source text.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import day_summary as ds
from bundles import BUNDLE_DIR
from main import app

SUBJECT = "demo"
DATE = "2025-06-01"
LAMINA = "lamina_wearable"
DEMO_FILE = BUNDLE_DIR / "demo" / f"{DATE}.json"


@pytest.fixture(scope="module")
def bundle() -> dict:
    return json.loads(DEMO_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def day() -> dict:
    ds.day_summary.cache_clear()
    return ds.day_summary(LAMINA, SUBJECT, DATE)


def test_sessions_are_the_three_runs_with_their_groups(day):
    got = [
        (s["start"], s["end"], s["label"], s["group"])
        for s in day["sessions"]
    ]
    assert got == [
        (480, 510, "Walking", "walk"),
        (735, 755, "Walking", "walk"),
        (1050, 1095, "Traditional strength training", "strength"),
    ]
    for session in day["sessions"]:
        assert session["minutes"] == session["end"] - session["start"]
    assert all(
        s["verdict"] == "as_expected" for s in day["sessions"]
    )


def test_there_are_no_gaps_on_the_demo_day(day):
    assert day["gaps"] == []


def test_the_active_energy_total_is_the_bundle_sum(day, bundle):
    kpis = {k["key"]: k for k in day["kpis"]}
    expected = sum(
        row["ae_kcal_min"] for row in bundle["samples"]
        if row["ae_kcal_min"] is not None
    )
    assert expected == pytest.approx(661.0)
    assert kpis["AE_rate"]["value"] == pytest.approx(661.0, abs=1e-6)


def test_the_watch_was_worn_for_the_whole_day(day):
    kpis = {k["key"]: k for k in day["kpis"]}
    assert kpis["worn"]["value"] == pytest.approx(24.0)
    assert kpis["worn"]["unit"] == "h"


def test_the_measured_series_is_the_bundle_heart_rate(day, bundle):
    measured = day["pair"]["measured"]
    assert len(measured) == len(bundle["samples"])
    for value, row in zip(measured, bundle["samples"]):
        if row["hr"] is None:
            assert value is None
        else:
            assert value == pytest.approx(row["hr"])


def test_the_day_has_the_usual_error_computed_from_this_day(day):
    assert day["model"]["sd_source"] == "this day"
    assert day["model"]["fitted"] is False
    assert day["model"]["applies_to"] is None


def test_the_summary_says_every_session_was_as_expected(day):
    assert "every session was as expected" in day["summary"].lower()


def test_api_day_returns_the_same_summary(day):
    client = TestClient(app)
    response = client.get(
        "/api/day",
        params={"lamina": LAMINA, "subject": SUBJECT, "date": DATE},
    )
    assert response.status_code == 200
    assert response.json() == day


def test_api_day_unknown_date_is_404():
    client = TestClient(app)
    response = client.get(
        "/api/day",
        params={"lamina": LAMINA, "subject": SUBJECT, "date": "2024-01-01"},
    )
    assert response.status_code == 404


def test_api_day_bad_date_is_400():
    client = TestClient(app)
    response = client.get(
        "/api/day",
        params={"lamina": LAMINA, "subject": SUBJECT, "date": "2025-13-01"},
    )
    assert response.status_code == 400


def test_api_day_lamina_without_roles_is_400():
    client = TestClient(app)
    response = client.get(
        "/api/day",
        params={
            "lamina": "lamina_circulatory",
            "subject": SUBJECT,
            "date": DATE,
        },
    )
    assert response.status_code == 400
    assert "day_view" in response.json()["detail"]["error"]


def test_the_module_names_no_attribute_of_the_wearable_lamina():
    source = Path(ds.__file__).read_text(encoding="utf-8")
    for token in ("HR_", "AE_rate", "step_rate", "is_walk"):
        assert token not in source


def test_a_second_call_is_served_from_the_cache(monkeypatch):
    constructions = []
    real_session = ds.Session

    class CountingSession(real_session):
        def __init__(self, *args, **kwargs):
            constructions.append(1)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(ds, "Session", CountingSession)
    ds.day_summary.cache_clear()

    first = ds.day_summary(LAMINA, SUBJECT, DATE)
    assert len(constructions) == 1

    second = ds.day_summary(LAMINA, SUBJECT, DATE)
    assert len(constructions) == 1
    assert second == first
