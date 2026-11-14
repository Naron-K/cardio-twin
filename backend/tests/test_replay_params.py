"""
Fitted params.json beside a subject's bundles.

A replay runs on the lamina's declared defaults until a subject brings its
own coefficients.  This file covers the reader, the tolerance override, and
the WebSocket path that puts both together without starting a replay on a
file that cannot be trusted.
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import signal_source
from bundles import BUNDLE_DIR, load_params
from laminae import LAMINA_DIR, load_twin
from main import app

FAST_SPEEDS = (60, 120, 600, 60000)
WEARABLE = LAMINA_DIR / "wearable_lamina.xml"
DEMO_FILE = BUNDLE_DIR / "demo" / "2025-06-01.json"
REPLAY = (
    "/ws/feedback?lamina=lamina_wearable&source=replay"
    "&subject=s9&date=2025-01-02&speed=60000"
)
PARAMS = {
    "schema_version": 1,
    "coefficients": {"k_I": 20.0, "HR_offset": -5.0},
    "outcome_tolerance": {"target_residual": 23.0},
}


@pytest.fixture
def fast_speeds(monkeypatch):
    monkeypatch.setattr(signal_source, "REPLAY_SPEEDS", FAST_SPEEDS)


def _write_subject(tmp_path, monkeypatch, params=None) -> Path:
    bundle = json.loads(DEMO_FILE.read_text(encoding="utf-8"))
    bundle["subject"] = "s9"
    bundle["date"] = "2025-01-02"

    subject_dir = tmp_path / "s9"
    subject_dir.mkdir()
    (subject_dir / "2025-01-02.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    if params is not None:
        (subject_dir / "params.json").write_text(
            json.dumps(params), encoding="utf-8"
        )
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    return subject_dir


def _outcome(twin, outcome_id):
    for segment in twin.segments.values():
        for outcome in segment.behavioural_outcomes:
            if outcome.id == outcome_id:
                return outcome
    raise AssertionError(f"{outcome_id} is not on this lamina")


# ── load_params ───────────────────────────────────────────────────────

def test_load_params_returns_none_for_the_demo():
    assert load_params("demo") is None


def test_load_params_round_trips_a_fitted_file(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, PARAMS)
    assert load_params("s9") == PARAMS


@pytest.mark.parametrize(
    "mutate, fragment",
    [
        (
            lambda p: p["coefficients"].__setitem__("k_I", float("nan")),
            "k_I",
        ),
        (lambda p: p.__setitem__("schema_version", 2), "schema_version"),
        (
            lambda p: p["outcome_tolerance"].__setitem__(
                "target_residual", 0
            ),
            "target_residual",
        ),
        (
            lambda p: p["outcome_tolerance"].__setitem__(
                "target_residual", "x"
            ),
            "target_residual",
        ),
    ],
    ids=["nan-coefficient", "schema-version-2", "tolerance-zero",
         "tolerance-string"],
)
def test_a_malformed_params_file_names_the_file_and_key(
    tmp_path, monkeypatch, mutate, fragment
):
    params = {
        "schema_version": 1,
        "coefficients": {"k_I": 20.0},
        "outcome_tolerance": {"target_residual": 23.0},
    }
    mutate(params)
    _write_subject(tmp_path, monkeypatch, params)

    with pytest.raises(ValueError) as exc:
        load_params("s9")
    message = str(exc.value)
    assert "params.json" in message
    assert fragment in message


# ── set_outcome_tolerance ────────────────────────────────────────────

def test_set_outcome_tolerance_changes_the_twin():
    twin = load_twin(WEARABLE)
    twin.set_outcome_tolerance("target_residual", 23.0)
    assert _outcome(twin, "target_residual").tolerance == pytest.approx(23.0)


def test_set_outcome_tolerance_refuses_an_unknown_id():
    twin = load_twin(WEARABLE)
    with pytest.raises(KeyError) as exc:
        twin.set_outcome_tolerance("no_such_outcome", 23.0)
    assert "target_residual" in str(exc.value)


def test_set_outcome_tolerance_refuses_a_non_positive_band():
    twin = load_twin(WEARABLE)
    with pytest.raises(ValueError):
        twin.set_outcome_tolerance("target_residual", -1)


# ── The WebSocket replay ─────────────────────────────────────────────

def test_a_replay_uses_fitted_coefficients_and_tolerance(
    fast_speeds, tmp_path, monkeypatch
):
    _write_subject(tmp_path, monkeypatch, PARAMS)

    with TestClient(app) as client:
        with client.websocket_connect(REPLAY) as ws:
            first = ws.receive_json()

    assert first["sensors"]["k_I"]["value"] == pytest.approx(20.0)
    assert first["sensors"]["HR_offset"]["value"] == pytest.approx(-5.0)
    assert first["before_after"]["target_residual"]["tolerance"] == (
        pytest.approx(23.0)
    )
    assert first["source"]["coefficients"] == "fitted"
    assert "fitted" in first["source"]["detail"]


def test_a_replay_without_params_reports_declared_defaults(
    fast_speeds, tmp_path, monkeypatch
):
    _write_subject(tmp_path, monkeypatch)

    with TestClient(app) as client:
        with client.websocket_connect(REPLAY) as ws:
            first = ws.receive_json()

    assert first["source"]["coefficients"] == "declared defaults"
    assert "fitted" not in first["source"]["detail"]


def test_a_params_file_without_a_tolerance_still_replays(
    fast_speeds, tmp_path, monkeypatch
):
    # outcome_tolerance is optional: leaving it out must keep the declared
    # band, not refuse the replay with the missing key as its reason.
    _write_subject(
        tmp_path, monkeypatch, {"schema_version": 1, "coefficients": {"k_I": 20.0}}
    )

    with TestClient(app) as client:
        with client.websocket_connect(REPLAY) as ws:
            first = ws.receive_json()

    assert first["sensors"]["k_I"]["value"] == pytest.approx(20.0)
    assert first["before_after"]["target_residual"]["tolerance"] == pytest.approx(10.0)
    assert first["source"]["coefficients"] == "fitted"


@pytest.mark.parametrize(
    "params",
    [
        {"schema_version": 1, "coefficients": {"nope": 1.0}},
        {
            "schema_version": 1,
            "coefficients": {"k_I": 20.0},
            "outcome_tolerance": {"nope": 1.0},
        },
    ],
    ids=["unknown-coefficient", "unknown-outcome"],
)
def test_an_unknown_id_closes_1008(
    fast_speeds, tmp_path, monkeypatch, params
):
    _write_subject(tmp_path, monkeypatch, params)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(REPLAY) as ws:
                ws.receive_json()

    assert caught.value.code == 1008
    assert "nope" in caught.value.reason


# ── GET /api/sources ─────────────────────────────────────────────────

def test_sources_reports_which_subjects_are_fitted(tmp_path, monkeypatch):
    _write_subject(tmp_path, monkeypatch, PARAMS)

    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_wearable").json()

    # Subjects committed to the repository are offered too; only the two this
    # test controls are pinned.
    fitted = body["replay"]["fitted"]
    assert fitted["demo"] is False
    assert fitted["s9"] is True
