"""
Tests for /ws/feedback command validation and notice frames.

An invalid control command is a thing the person at the dashboard sent, so
it deserves an answer rather than silence or a closed socket.  These tests
cover the validator on a real twin and the frames the socket emits when a
command is refused.

Run from the backend/ directory:
    pytest tests/test_ws_notices.py -q
"""

import pytest
from fastapi.testclient import TestClient

from main import _build_feedback_twin, app, validate_sensor_command
from universal_twin import SENSOR

_FAST = "/ws/feedback?tick_ms=20"


@pytest.fixture(scope="module")
def twin():
    """A real twin, built the same way the feedback HTTP endpoints build one."""
    return _build_feedback_twin({}, {})


def _receive_notice(ws, limit: int = 50) -> dict:
    """Return the first notice frame, skipping snapshots; fail after `limit`."""
    for _ in range(limit):
        frame = ws.receive_json()
        if frame.get("type") == "notice":
            return frame
    raise AssertionError(f"No notice frame within {limit} frames")


# ── validate_sensor_command ──────────────────────────────────────────

def test_unknown_input_for_unknown_id(twin):
    value, notice = validate_sensor_command(twin, "XYZ", 100)
    assert value is None
    assert notice["type"] == "notice"
    assert notice["level"] == "warning"
    assert notice["code"] == "unknown_input"
    assert notice["id"] == "XYZ"
    assert "XYZ" in notice["message"]


def test_unknown_input_for_computed_attribute(twin):
    """MAP is computed by the model, so it is not a slot a sensor may write."""
    value, notice = validate_sensor_command(twin, "MAP", 90)
    assert value is None
    assert notice["code"] == "unknown_input"
    assert notice["id"] == "MAP"


def test_unknown_input_for_empty_and_missing_id(twin):
    for sensor_id in (None, ""):
        value, notice = validate_sensor_command(twin, sensor_id, 90)
        assert value is None
        assert notice["code"] == "unknown_input"


def test_invalid_value_for_non_numeric(twin):
    value, notice = validate_sensor_command(twin, "HR", "abc")
    assert value is None
    assert notice["code"] == "invalid_value"
    assert notice["id"] == "HR"
    assert "abc" in notice["message"]


def test_invalid_value_for_none_bool_and_containers(twin):
    for raw in (None, True, False, [1, 2], {"value": 1}):
        value, notice = validate_sensor_command(twin, "HR", raw)
        assert value is None
        assert notice["code"] == "invalid_value", raw


def test_invalid_value_for_nan_and_inf(twin):
    for raw in (float("nan"), float("inf"), float("-inf")):
        value, notice = validate_sensor_command(twin, "HR", raw)
        assert value is None
        assert notice["code"] == "invalid_value", raw


def test_out_of_range_below_and_above(twin):
    attr = twin.attributes["HR"]
    for raw in (attr.physio_min - 1, attr.physio_max + 1):
        value, notice = validate_sensor_command(twin, "HR", raw)
        assert value is None
        assert notice["code"] == "out_of_range"
        assert notice["id"] == "HR"
        assert attr.unit in notice["message"]
        assert f"{attr.physio_min:g}" in notice["message"]
        assert f"{attr.physio_max:g}" in notice["message"]


def test_happy_path_hr_at_baseline(twin):
    baseline = twin.attributes["HR"].baseline
    value, notice = validate_sensor_command(twin, "HR", baseline)
    assert notice is None
    assert isinstance(value, float)
    assert value == pytest.approx(baseline)


def test_boundaries_are_inclusive_for_every_sensor(twin):
    """physio_min and physio_max themselves are valid commands."""
    for attr_id, attr in twin.attributes.items():
        if attr.source != SENSOR:
            continue
        for boundary in (attr.physio_min, attr.physio_max):
            value, notice = validate_sensor_command(twin, attr_id, boundary)
            assert notice is None, (attr_id, boundary, notice)
            assert value == pytest.approx(boundary)


def test_validator_never_raises(twin):
    """Every shape that can come off a wire gets an answer, not an exception."""
    sensor_ids = [
        None, "", "abc", float("nan"), float("inf"), True, [1], {"a": 1},
        "XYZ", "MAP", "HR",
    ]
    raw_values = [
        None, "", "abc", float("nan"), float("inf"), True, [1], {"a": 1},
        39, 201, 72,
    ]
    for sensor_id in sensor_ids:
        for raw in raw_values:
            value, notice = validate_sensor_command(twin, sensor_id, raw)
            assert (value is None) == (notice is not None), (sensor_id, raw)


# ── WebSocket notices ────────────────────────────────────────────────

def test_ws_set_sensor_out_of_range_sends_notice():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_json({"type": "set_sensor", "id": "HR", "value": 9999})
            notice = _receive_notice(ws)

    assert notice["code"] == "out_of_range"
    assert notice["id"] == "HR"


def test_ws_set_sensor_non_numeric_sends_notice():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_json({"type": "set_sensor", "id": "HR", "value": "abc"})
            notice = _receive_notice(ws)

    assert notice["code"] == "invalid_value"
    assert notice["id"] == "HR"


def test_ws_set_sensor_computed_attribute_sends_notice():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_json({"type": "set_sensor", "id": "MAP", "value": 90})
            notice = _receive_notice(ws)

    assert notice["code"] == "unknown_input"
    assert notice["id"] == "MAP"


def test_ws_bad_json_notice_and_socket_survives():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_text("not json")
            notice = _receive_notice(ws)
            assert notice["code"] == "bad_message"
            assert notice["id"] is None

            # The socket must still be streaming after the bad frame.
            for _ in range(50):
                frame = ws.receive_json()
                if "sensors" in frame:
                    break
            else:
                raise AssertionError("Socket stopped delivering snapshots")


def test_ws_keepalive_gets_no_notice():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_json({"type": "keepalive"})
            for _ in range(5):
                assert ws.receive_json().get("type") != "notice"


def test_ws_valid_set_sensor_gets_no_notice():
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            ws.send_json({"type": "set_sensor", "id": "HR", "value": 100})
            for _ in range(10):
                assert ws.receive_json().get("type") != "notice"
