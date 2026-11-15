"""
Recorded days with nothing to draw.

A day on which the lamina's observed attribute never has a reading cannot be
set against the model, so /api/sources names it for the picker to leave out
and /api/day answers it with a plain 404 rather than a 400 fault.
"""
import json

import pytest
from fastapi.testclient import TestClient

import bundles
import day_summary as ds
from main import app

LAMINA = "lamina_wearable"


def _write_subject(tmp_path, monkeypatch, *, blank_hr: bool):
    demo = json.loads(
        (bundles.BUNDLE_DIR / "demo" / "2025-06-01.json").read_text(encoding="utf-8")
    )
    demo["subject"] = "s7"
    if blank_hr:
        for row in demo["samples"]:
            row["hr"] = None
            row["hr_n"] = 0
    folder = tmp_path / "s7"
    folder.mkdir()
    (folder / "2025-06-01.json").write_text(json.dumps(demo), encoding="utf-8")
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    ds.day_summary.cache_clear()


def test_a_day_without_an_observed_reading_is_named(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, blank_hr=True)
    empty = ds.days_without_readings(LAMINA)
    assert empty.get("s7") == ["2025-06-01"]
    assert "demo" not in empty


def test_a_day_with_readings_is_not_named(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, blank_hr=False)
    assert "s7" not in ds.days_without_readings(LAMINA)


def test_sources_carry_the_empty_days(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, blank_hr=True)
    with TestClient(app) as client:
        replay = client.get(f"/api/sources?lamina={LAMINA}").json()["replay"]
    assert replay["no_readings"]["s7"] == ["2025-06-01"]
    # The day is still listed: the field says what to leave out, it does
    # not change what exists.
    assert "2025-06-01" in replay["subjects"]["s7"]


def test_a_lamina_without_a_day_view_names_no_empty_days():
    with TestClient(app) as client:
        replay = client.get("/api/sources?lamina=lamina_circulatory").json()["replay"]
    assert replay is None or replay["no_readings"] == {}


def test_the_day_endpoint_answers_an_empty_day_with_404(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, blank_hr=True)
    with TestClient(app) as client:
        response = client.get(
            "/api/day", params={"lamina": LAMINA, "subject": "s7", "date": "2025-06-01"}
        )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["no_readings"] is True
    assert detail["error"].startswith("No readings on 2025-06-01")


def test_empty_day_raises_its_own_error(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, blank_hr=True)
    with pytest.raises(ds.NoReadings):
        ds.day_summary(LAMINA, "s7", "2025-06-01")


def test_subject_demo_has_exactly_its_eleven_days_without_heart_rate(monkeypatch):
    monkeypatch.delenv("CARDIOTWIN_BUNDLE_DIR", raising=False)
    empty = ds.days_without_readings(LAMINA).get("subject_demo", [])
    assert len(empty) == 11
    assert "2025-01-02" in empty and "2025-04-03" not in empty
