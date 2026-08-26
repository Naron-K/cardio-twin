"""
Choosing a lamina per request, rather than per process.

Before this, the lamina was a module global read at import: changing it meant
restarting the backend, and a browser already holding the old lamina's schema
was never told.  It kept drawing the old structure over the new lamina's
values, and the last tick before the socket died stayed on screen looking
exactly like a live one.

The fix is not a bigger warning.  It is that every snapshot now says which
lamina produced it, and both the schema and the socket take the lamina by id —
so the client can check that the structure it drew and the numbers it is
reading came from the same place.  These tests pin the three properties that
check depends on: the id round-trips, two laminae can run at once without
touching each other, and an id nobody serves is refused rather than quietly
replaced by the default.
"""

import pytest
from fastapi.testclient import TestClient

from laminae import UnknownLamina, available_laminae, resolve_lamina
from main import app
from session import Session

CIRC = "lamina_circulatory"
RESP = "lamina_respiratory"
_FAST = "/ws/feedback?tick_ms=20"


# ── The catalogue ─────────────────────────────────────────────────────

def test_available_laminae_lists_both_shipped_laminae():
    ids = {e["id"] for e in available_laminae()}
    assert {CIRC, RESP} <= ids


def test_every_listed_lamina_says_whether_its_maths_is_written():
    for entry in available_laminae():
        assert isinstance(entry["implemented"], bool)
        assert entry["name"] and entry["file"]


def test_laminae_endpoint_names_the_process_default():
    with TestClient(app) as client:
        body = client.get("/api/laminae").json()
    assert body["default"] in {e["id"] for e in body["laminae"]}


def test_resolution_is_by_id_not_by_filename():
    """The URL must not depend on where the file happens to sit on disk."""
    assert resolve_lamina(RESP).name == "respiratory_lamina.xml"
    with pytest.raises(UnknownLamina):
        resolve_lamina("respiratory_lamina.xml")


def test_omitting_the_id_falls_back_to_the_process_default():
    assert resolve_lamina(None) == resolve_lamina("")


# ── Refusing what nobody serves ───────────────────────────────────────

def test_unknown_lamina_is_a_404_naming_what_is_available():
    with TestClient(app) as client:
        res = client.get("/api/schema?lamina=lamina_nonsense")
    assert res.status_code == 404
    detail = res.json()["detail"]
    assert detail["requested"] == "lamina_nonsense"
    assert CIRC in detail["available"]


def test_unknown_lamina_closes_the_socket_instead_of_streaming_the_default():
    """
    Silently serving the default would be the original bug with extra steps:
    the client would believe it was reading the lamina it asked for.
    """
    from starlette.websockets import WebSocketDisconnect

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as caught:
            with client.websocket_connect(f"{_FAST}&lamina=lamina_nonsense") as ws:
                ws.receive_json()
    assert caught.value.code == 1008


# ── The invariant the frontend guard rests on ─────────────────────────

def test_schema_and_stream_report_the_same_lamina_id():
    """For both laminae — this is the whole contract in one assertion."""
    with TestClient(app) as client:
        for lamina_id in (CIRC, RESP):
            schema = client.get(f"/api/schema?lamina={lamina_id}").json()
            with client.websocket_connect(f"{_FAST}&lamina={lamina_id}") as ws:
                snap = ws.receive_json()
            assert schema["lamina_id"] == lamina_id
            assert snap["lamina_id"] == lamina_id


def test_session_snapshot_carries_its_own_lamina_id():
    assert Session(lamina=resolve_lamina(RESP)).tick({})["lamina_id"] == RESP


# ── Two at once ───────────────────────────────────────────────────────

def test_two_sessions_on_two_laminae_do_not_interfere():
    """
    The point of moving the lamina off the process: two tabs, two laminae, no
    restart.  Each session keeps its own twin, so a sensor written into one is
    not an attribute the other has ever heard of.
    """
    circ = Session(lamina=resolve_lamina(CIRC))
    resp = Session(lamina=resolve_lamina(RESP))

    circ_attrs = set(circ.twin.attributes)
    resp_attrs = set(resp.twin.attributes)
    assert circ_attrs != resp_attrs

    only_resp = sorted(resp_attrs - circ_attrs)
    assert only_resp, "the two laminae must differ for this test to mean anything"

    resp.tick({})
    assert circ.tick({})["lamina_id"] == CIRC
    assert all(attr_id not in circ.twin.attributes for attr_id in only_resp)


def test_two_open_sockets_stream_two_different_laminae():
    with TestClient(app) as client:
        with client.websocket_connect(f"{_FAST}&lamina={CIRC}") as a:
            with client.websocket_connect(f"{_FAST}&lamina={RESP}") as b:
                for _ in range(3):
                    assert a.receive_json()["lamina_id"] == CIRC
                    assert b.receive_json()["lamina_id"] == RESP
