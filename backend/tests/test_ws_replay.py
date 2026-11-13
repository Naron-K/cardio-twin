"""
Tests for replaying a recorded day over /ws/feedback, and GET /api/sources.

The demo day is sped up to 60000 data seconds per wall second (one minute per
millisecond) so a 1440-minute recording can be checked end to end without
sleeping through a day.  `signal_source.REPLAY_SPEEDS` is read at call time by
both the endpoint and ReplaySource, so the test can add that speed without a
code change.

Run from the backend/ directory:
    pytest tests/test_ws_replay.py -q
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
import signal_source
from main import app

FAST_SPEEDS = (60, 120, 600, 60000)
DEMO = (
    "/ws/feedback?lamina=lamina_wearable&source=replay"
    "&subject=demo&date=2025-06-01&speed=60000"
)
# A slower replay leaves room to interleave control messages before the day
# finishes.  600 is in the patched set.
SLOW = (
    "/ws/feedback?lamina=lamina_wearable&source=replay"
    "&subject=demo&date=2025-06-01&speed=600"
)
SIMULATED = "/ws/feedback?tick_ms=20"


@pytest.fixture
def fast_speeds(monkeypatch):
    monkeypatch.setattr(signal_source, "REPLAY_SPEEDS", FAST_SPEEDS)


def _receive_notice(ws, limit: int = 200) -> dict:
    """Return the first notice frame, skipping snapshots; fail after `limit`."""
    for _ in range(limit):
        frame = ws.receive_json()
        if frame.get("type") == "notice":
            return frame
    raise AssertionError(f"No notice frame within {limit} frames")


def _collect(ws, count: int) -> list[dict]:
    return [ws.receive_json() for _ in range(count)]


# ── The recorded day arrives whole ───────────────────────────────────

def test_demo_day_arrives_as_1440_minutes_then_ends(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(DEMO) as ws:
            frames = _collect(ws, 1440)
            notice = ws.receive_json()

    assert len(frames) == 1440
    positions = [frame["source"]["position_s"] for frame in frames]
    assert positions == list(range(0, 1440 * 60, 60))
    assert all(frame["source"]["kind"] == "replay" for frame in frames)
    assert all(frame["source"]["synthetic"] is True for frame in frames)
    assert frames[0]["source"]["data_time"] == "2025-06-01T00:00:00+00:00"
    assert notice == {
        "type": "notice",
        "level": "info",
        "code": "replay_end",
        "id": None,
        "message": "The recorded day has finished. Reset to play it again.",
    }


def test_emit_every_does_not_thin_a_replay(fast_speeds, monkeypatch):
    monkeypatch.setattr(main, "STREAM_EMIT_EVERY", 5)

    with TestClient(app) as client:
        with client.websocket_connect(DEMO) as ws:
            frames = _collect(ws, 1440)
            notice = ws.receive_json()

    assert len(frames) == 1440
    assert frames[-1]["source"]["position_s"] == 1439 * 60
    assert notice["code"] == "replay_end"


# ── Bad requests close before streaming ──────────────────────────────

@pytest.mark.parametrize(
    "url, fragment",
    [
        (
            "/ws/feedback?lamina=lamina_wearable&source=replay"
            "&subject=nobody&date=2025-06-01&speed=60000",
            "nobody",
        ),
        (
            "/ws/feedback?lamina=lamina_wearable&source=replay"
            "&subject=demo&date=2025-06-02&speed=60000",
            "2025-06-02",
        ),
        (
            "/ws/feedback?lamina=lamina_wearable&source=replay"
            "&subject=demo&date=2025-06-01&speed=3600",
            "3600",
        ),
        (
            "/ws/feedback?lamina=lamina_wearable&source=scenario",
            "scenario mode is not built yet",
        ),
        (
            "/ws/feedback?lamina=lamina_wearable&source=bogus",
            "bogus",
        ),
        (
            "/ws/feedback?lamina=lamina_circulatory&source=replay"
            "&subject=demo&date=2025-06-01&speed=60000",
            "replay_field",
        ),
    ],
)
def test_unservable_requests_close_1008(fast_speeds, url, fragment):
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(url) as ws:
                ws.receive_json()

    assert caught.value.code == 1008
    assert fragment in caught.value.reason


# ── Control messages during a replay ─────────────────────────────────

def test_set_sensor_on_a_recorded_field_is_refused(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(SLOW) as ws:
            ws.send_json({"type": "set_sensor", "id": "HR_obs", "value": 90})
            notice = _receive_notice(ws)

    assert notice["code"] == "measured_input"
    assert notice["id"] == "HR_obs"
    assert notice["message"] == (
        "HR_obs comes from the recorded day during a replay, "
        "so it cannot be set."
    )


def test_set_sensor_on_a_coefficient_is_applied(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(SLOW) as ws:
            ws.send_json({"type": "set_sensor", "id": "k_I", "value": 20})
            for _ in range(100):
                frame = ws.receive_json()
                if frame.get("type") == "notice":
                    continue
                if frame["sensors"]["k_I"]["value"] == pytest.approx(20):
                    break
            else:
                raise AssertionError("k_I = 20 never reached a snapshot")

    assert frame["sensors"]["k_I"]["value"] == pytest.approx(20)


def test_set_speed_outside_a_replay_is_refused():
    with TestClient(app) as client:
        with client.websocket_connect(SIMULATED) as ws:
            ws.send_json({"type": "set_speed", "speed": 600})
            notice = _receive_notice(ws)

    assert notice["code"] == "not_replaying"


def test_a_stray_speed_does_not_refuse_a_simulated_stream():
    # Speed means nothing without a replay, so it must not be the reason a
    # simulated stream is turned away.
    with TestClient(app) as client:
        with client.websocket_connect(SIMULATED + "&speed=7") as ws:
            snap = ws.receive_json()

    assert snap["source"]["kind"] == "simulated"


def test_set_speed_not_in_the_offered_set_is_refused(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(SLOW) as ws:
            ws.send_json({"type": "set_speed", "speed": 7})
            notice = _receive_notice(ws)

    assert notice["code"] == "bad_speed"
    for speed in FAST_SPEEDS:
        assert str(speed) in notice["message"]


def test_reset_after_the_end_plays_the_day_again(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(DEMO) as ws:
            frames = _collect(ws, 1440)
            notice = ws.receive_json()
            assert notice["code"] == "replay_end"

            ws.send_json({"type": "reset"})
            first = ws.receive_json()

    assert frames[-1]["source"]["position_s"] == 1439 * 60
    assert first["source"]["kind"] == "replay"
    assert first["source"]["position_s"] == 0


# ── GET /api/sources ─────────────────────────────────────────────────

def test_sources_lists_the_demo_day_for_the_wearable():
    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_wearable").json()

    assert body["lamina"] == "lamina_wearable"
    assert body["modes"] == ["simulated", "replay"]
    assert body["replay"]["subjects"]["demo"] == ["2025-06-01"]
    assert body["replay"]["speeds"] == [60, 120, 600]
    assert body["replay"]["default_speed"] == 60
    assert body["presets"] == []


def test_sources_does_not_offer_replay_to_a_lamina_without_replay_fields():
    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_circulatory").json()

    assert body["lamina"] == "lamina_circulatory"
    assert body["modes"] == ["simulated"]
    assert body["replay"] is None


def test_sources_refuses_an_unknown_lamina_like_the_schema_does():
    with TestClient(app) as client:
        schema = client.get("/api/schema?lamina=lamina_nonsense")
        sources = client.get("/api/sources?lamina=lamina_nonsense")

    assert sources.status_code == schema.status_code


def test_sources_lists_a_subject_added_by_the_bundle_directory(
    tmp_path, monkeypatch
):
    demo_path = (
        Path(__file__).resolve().parents[1]
        / "bundles" / "demo" / "2025-06-01.json"
    )
    bundle = json.loads(demo_path.read_text(encoding="utf-8"))
    bundle["subject"] = "s9"
    bundle["date"] = "2025-01-02"

    subject_dir = tmp_path / "s9"
    subject_dir.mkdir()
    (subject_dir / "2025-01-02.json").write_text(
        json.dumps(bundle), encoding="utf-8"
    )
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))

    with TestClient(app) as client:
        body = client.get("/api/sources?lamina=lamina_wearable").json()

    assert body["replay"]["subjects"]["s9"] == ["2025-01-02"]
