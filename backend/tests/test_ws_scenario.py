"""
Scenarios over /ws/feedback, and the presets GET /api/sources offers.

Every preset is written into tmp_path; these tests never read the real
presets directory.  The wearable lamina is the worked example because it has
both an observed measurement (`HR_obs`) and personal coefficients, which are
the two cases a scenario has to get right.

Run from the backend/ directory:
    pytest tests/test_ws_scenario.py -q
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import scenario_presets
from main import app

SCENARIO = (
    "/ws/feedback?lamina=lamina_wearable&source=scenario"
    "&preset=walk&tick_ms=20"
)
SCENARIO_BASE = (
    "/ws/feedback?lamina=lamina_wearable&source=scenario&tick_ms=20"
)
SIMULATED = "/ws/feedback?tick_ms=20"


def _write_preset(
    directory: Path,
    stem: str,
    values: dict,
    *,
    lamina: str = "lamina_wearable",
    label: str,
    subject: str = "s9",
    order: int,
    description: str = "",
) -> Path:
    path = Path(directory) / f"{stem}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)

    metadata = [
        f"    <name>{label}</name>",
        f"    <lamina>{lamina}</lamina>",
        f"    <subject>{subject}</subject>",
        f"    <order>{order}</order>",
    ]
    if description:
        metadata.append(f"    <description>{description}</description>")

    sensors = [
        f"    <{attr_id}>{value}</{attr_id}>"
        for attr_id, value in values.items()
    ]
    path.write_text(
        "<patient>\n"
        "  <metadata>\n"
        + "\n".join(metadata)
        + "\n  </metadata>\n"
        "  <sensor_data>\n"
        + "\n".join(sensors)
        + "\n  </sensor_data>\n"
        "</patient>\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def presets(tmp_path, monkeypatch):
    _write_preset(
        tmp_path / "wearable",
        "walk",
        {"AE_rate": 3.22, "step_rate": 106, "hour_local": 17.1},
        label="Walk",
        order=1,
        description="Walking home",
    )
    _write_preset(
        tmp_path / "wearable",
        "rest_awake",
        {"AE_rate": 0.31, "step_rate": 0, "hour_local": 17.7},
        label="Rest (awake)",
        order=2,
    )
    monkeypatch.setattr(scenario_presets, "PRESET_DIR", tmp_path)
    return tmp_path


def _receive_notice(ws, limit: int = 200) -> dict:
    """Return the first notice frame, skipping snapshots; fail after `limit`."""
    for _ in range(limit):
        frame = ws.receive_json()
        if frame.get("type") == "notice":
            return frame
    raise AssertionError(f"No notice frame within {limit} frames")


def _receive_snapshot(ws, *, preset=None, limit: int = 200) -> dict:
    """Return a snapshot, optionally waiting for a named scenario preset."""
    for _ in range(limit):
        frame = ws.receive_json()
        if frame.get("type") == "notice":
            continue
        if preset is None or frame["source"].get("preset") == preset:
            return frame
    raise AssertionError(f"No matching snapshot within {limit} frames")


# ── The scenario stream ──────────────────────────────────────────────

def test_a_scenario_stream_names_its_kind_and_omits_the_measurement(presets):
    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            snapshot = ws.receive_json()

    assert snapshot["source"]["kind"] == "scenario"
    assert snapshot["source"]["preset"] == "walk"
    assert snapshot["source"]["coefficients"] == "declared defaults"
    assert snapshot["computed"]["HR_measured"]["stale"] is True
    assert snapshot["sensors"]["HR_obs"]["value"] is None


def test_set_preset_moves_the_scenario_and_the_target(presets):
    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            walk = _receive_snapshot(ws)
            ws.send_json({"type": "set_preset", "preset": "rest_awake"})
            rest = _receive_snapshot(ws, preset="rest_awake")

    assert walk["source"]["preset"] == "walk"
    assert rest["source"]["preset"] == "rest_awake"
    assert rest["source"]["label"] == "Rest (awake)"
    assert (
        rest["computed"]["HR_target"]["value"]
        < walk["computed"]["HR_target"]["value"]
    )


def test_set_preset_outside_a_scenario_is_refused():
    with TestClient(app) as client:
        with client.websocket_connect(SIMULATED) as ws:
            ws.send_json({"type": "set_preset", "preset": "walk"})
            notice = _receive_notice(ws)

    assert notice["code"] == "not_scenario"


def test_an_unknown_preset_lists_the_available_names(presets):
    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            ws.send_json({"type": "set_preset", "preset": "nope"})
            notice = _receive_notice(ws)

    assert notice["code"] == "unknown_preset"
    assert "walk" in notice["message"]
    assert "rest_awake" in notice["message"]


def test_set_sensor_on_an_observed_measurement_is_refused(presets):
    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            ws.send_json({"type": "set_sensor", "id": "HR_obs", "value": 90})
            notice = _receive_notice(ws)

    assert notice["code"] == "observed_input"
    assert notice["id"] == "HR_obs"
    assert notice["message"] == (
        "HR_obs is a measurement, and a scenario has none."
    )


def test_set_sensor_on_an_input_reaches_a_later_snapshot(presets):
    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            _receive_snapshot(ws)
            ws.send_json({"type": "set_sensor", "id": "AE_rate", "value": 5.0})
            for _ in range(200):
                frame = ws.receive_json()
                if frame.get("type") == "notice":
                    continue
                if frame["sensors"]["AE_rate"]["value"] == pytest.approx(5.0):
                    break
            else:
                raise AssertionError("AE_rate = 5.0 never reached a snapshot")

    assert frame["sensors"]["AE_rate"]["value"] == pytest.approx(5.0)


# ── Bad requests close before streaming ──────────────────────────────

@pytest.mark.parametrize(
    "url, fragment",
    [
        (SCENARIO_BASE, "A scenario needs a preset"),
        (SCENARIO_BASE + "&preset=nope", "nope"),
        (SCENARIO_BASE + "&preset=Walk", "Invalid preset name"),
    ],
)
def test_unservable_scenario_requests_close_1008(presets, url, fragment):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(url) as ws:
                ws.receive_json()

    assert caught.value.code == 1008
    assert fragment in caught.value.reason


# ── GET /api/sources ─────────────────────────────────────────────────

def test_sources_offers_scenario_and_both_presets(presets):
    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_wearable").json()

    assert "simulated" in body["modes"]
    assert "replay" in body["modes"]
    assert "scenario" in body["modes"]
    assert [preset["name"] for preset in body["presets"]] == [
        "walk", "rest_awake"
    ]
    assert body["presets"][0]["label"] == "Walk"
    assert body["presets"][0]["subject"] == "s9"


def test_sources_does_not_offer_scenario_to_a_lamina_without_presets(presets):
    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_circulatory").json()

    assert body["modes"] == ["simulated"]
    assert body["presets"] == []


# ── A fitted subject ─────────────────────────────────────────────────

def test_a_fitted_subject_supplies_the_scenario_coefficients(
    presets, tmp_path, monkeypatch
):
    params_dir = tmp_path / "bundles" / "s9"
    params_dir.mkdir(parents=True)
    (params_dir / "params.json").write_text(
        json.dumps({"schema_version": 1, "coefficients": {"k_I": 20.0}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path / "bundles"))

    with TestClient(app) as client:
        with client.websocket_connect(SCENARIO) as ws:
            snapshot = ws.receive_json()

    assert snapshot["source"]["coefficients"] == "fitted"
    assert snapshot["sensors"]["k_I"]["value"] == pytest.approx(20.0)
