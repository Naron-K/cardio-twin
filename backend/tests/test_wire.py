"""
Phase 6 — the wire: what a screen can find out about a body.

Two things, and the split between them is the same one the single-lamina
world already has.  `/api/organism` answers "what is this body made of",
once, and every number in it is declared.  The `gates` section of the
snapshot answers "what is it doing", every tick, and every number in it
is live.  A reader that confuses the two draws a valve with no state or a
state with no valve.

The seam's provenance appears in two places on one payload — beside the
receiving lamina's inputs under `inbound`, and on the gate entry — and
these tests pin them to the same object, because two places computing the
same claim is how they come to disagree.
"""

import pytest
from fastapi.testclient import TestClient

from main import app
from organism import Organism
from session import OrganismSession
from signal_source import SimulatedSource


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def body():
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=11).starting_state()
              for lamina_id, twin in org.twins.items()})
    return org


# ══════════════════════════════════════════════════════════════════════
# GET /api/organism — the declaration
# ══════════════════════════════════════════════════════════════════════

def test_the_body_endpoint_describes_the_shipped_organism(client):
    payload = client.get("/api/organism").json()
    assert payload["organism_id"] == "bdt_default"
    assert [lamina["id"] for lamina in payload["laminae"]] == [
        "lamina_circulatory", "lamina_respiratory"]
    assert [c["id"] for c in payload["channels"]] == ["ch_co_to_resp"]
    assert payload["levels"] == {
        "lamina_circulatory": 1, "lamina_respiratory": 2}


def test_each_lamina_says_which_of_its_inputs_come_from_outside(client):
    laminae = {l["id"]: l for l in client.get("/api/organism").json()["laminae"]}

    assert laminae["lamina_respiratory"]["inbound"] == ["CO_ref"]
    assert "CO_ref" not in laminae["lamina_respiratory"]["sensors"], (
        "an inter-lamina input is not a sensor, and the wire has to keep "
        "saying so (G1)"
    )
    assert laminae["lamina_circulatory"]["inbound"] == [], (
        "circulation receives nothing; it only sends"
    )
    assert "pump_state" in laminae["lamina_circulatory"]["composites"]


def test_a_channel_arrives_resolved_rather_than_as_raw_xml(client):
    channel = client.get("/api/organism").json()["channels"][0]

    assert channel["from_lamina"] == "lamina_circulatory"
    assert channel["from_member"] == "output_state"
    assert channel["to_lamina"] == "lamina_respiratory"
    assert channel["to_member"] == "CO_ref"
    assert channel["carry"] == "state"
    assert channel["direction"] == "up", (
        "a diagram lays the stack out vertically and should not have to "
        "recompute which way the wire climbs"
    )


def test_both_ends_of_a_channel_arrive_with_their_own_gates(client):
    """
    The half the one-valve wire could not express. A reader has to be
    able to draw two valves on one edge, and to tell which kind each is
    — an auto gate and a key gate look different because they ARE
    different, and someone who cannot tell them apart cannot tell a
    protection layer from a policy.
    """
    channel = client.get("/api/organism").json()["channels"][0]

    sender = channel["transmit"][0]
    assert sender["kind"] == "auto"
    assert sender["side"] == "transmit"
    assert sender["trigger"] == "threshold"
    assert sender["starts_closed"] is True, "rule 1, as a value not a promise"
    params = sender["params"]
    assert params["aggregate"] == "deviation"
    assert params["close_below"] < params["open_above"], "rule 4, on the wire"
    assert params["reference"] == pytest.approx(0.30)

    receiver = channel["receive"][0]
    assert receiver["kind"] == "key"
    assert receiver["side"] == "receive"
    assert receiver["metric"] == "identity"
    assert receiver["on_close"] == "hold"
    assert 0.0 < receiver["rate"] <= 1.0, (
        "how fast to absorb belongs to the receiver, and the wire says so"
    )


def test_an_organism_that_does_not_exist_is_refused_by_name(client):
    response = client.get("/api/organism", params={"organism": "nope.xml"})
    assert response.status_code == 404
    assert response.json()["detail"]["requested"] == "nope.xml"


def test_an_organism_that_breaks_a_rule_is_refused_here_not_at_first_tick(
        client, tmp_path):
    """
    The endpoint loads the laminae rather than merely listing them, so a
    gate naming a composite nobody declares fails on the request that
    asked about the body — not later, on a socket somebody has already
    opened and is watching.
    """
    from tests.test_organism import _organism

    path = _organism(tmp_path, 'from="lamina_circulatory:output_state"',
                     'from="lamina_circulatory:not_a_composite"')
    response = client.get("/api/organism", params={"organism": str(path)})
    assert response.status_code == 400
    assert "not_a_composite" in response.json()["detail"]["error"]


# ══════════════════════════════════════════════════════════════════════
# snapshot["channels"] — the live state
# ══════════════════════════════════════════════════════════════════════

def test_a_shut_gate_reports_itself_shut_with_nothing_to_show_for_it(body):
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 72.0}})

    channel = body.snapshot()["channels"][0]
    assert channel["transmit"][0]["open"] is False
    assert channel["transmit"][0]["open_fraction"] == 0.0
    assert channel["last_value"] is None
    assert channel["provenance"] == {}
    assert channel["offered"] is None, "a shut sender has offered nothing"
    # The declaration is still there, because a shut valve is still a valve.
    assert channel["from"] == "lamina_circulatory:output_state"
    assert channel["to"] == "lamina_respiratory:CO_ref"
    assert channel["transmit"][0]["trigger"] == "threshold"


def test_an_open_gate_carries_its_state_and_the_value_that_crossed(body):
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 200.0}})

    channel = body.snapshot()["channels"][0]
    sender = channel["transmit"][0]
    assert sender["open"] is True
    assert sender["open_fraction"] == 1.0
    assert sender["state"]["watch_value"] > gate_open_above()
    assert channel["last_value"] > 5.0
    assert channel["provenance"]["state"] == "coupled"
    assert channel["provenance"]["channel"] == "ch_co_to_resp"
    assert channel["provenance"]["age"] == 0


def gate_open_above() -> float:
    from organism import parse_organism
    return parse_organism().channels[0].transmit[0].trigger["open_above"]


def test_the_gate_and_the_receiving_lamina_agree_about_the_crossing(body):
    """
    One claim, one source.

    The gate entry's provenance is read off the receiving attribute, so
    the seam drawn on a body diagram and the value shown beside the far
    side's inputs cannot disagree about how old the number is.
    """
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 200.0}})
    snapshot = body.snapshot()

    from_channel = snapshot["channels"][0]["provenance"]
    from_lamina = snapshot["laminae"]["lamina_respiratory"]["inbound"]["CO_ref"]

    assert from_lamina["provenance"] == {"state": "coupled", **from_channel}
    assert from_lamina["value"] == pytest.approx(
        snapshot["channels"][0]["last_value"])


def test_a_held_value_shows_as_held_on_the_gate_too(body):
    """
    Phase 3 fixed the receiving attribute claiming a shut gate's leftovers
    were current.  The gate entry has to tell the same story, or a
    diagram draws a shut valve beside a number labelled live.
    """
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 200.0}})

    # Back to rest.  The gate does not shut the instant the pump does —
    # the deadband and the refractory both have a say, and it goes on
    # carrying the falling value until they let go.  What is held is
    # therefore the LAST value that crossed, not the peak one, so the
    # baseline for this comparison is read at the moment it shuts.
    for _ in range(25):
        body.tick({"lamina_circulatory": {"HR": 72.0}})
    shut = body.snapshot()["channels"][0]
    assert shut["transmit"][0]["open"] is False
    crossed, age = shut["last_value"], shut["provenance"]["age"]

    for _ in range(5):
        body.tick({"lamina_circulatory": {"HR": 72.0}})

    channel = body.snapshot()["channels"][0]
    assert channel["last_value"] == pytest.approx(crossed), "hold keeps the value"
    assert channel["provenance"]["state"] == "held"
    assert channel["provenance"]["age"] == age + 5, "and it ages every cycle"
    assert channel["provenance"]["open_fraction"] == 0.0


def test_the_gate_says_why_rather_than_only_whether(body):
    """
    A valve that reports a boolean and nothing else makes the reader
    guess between "the value is inside the deadband" and "the breaker
    fired", which are not the same news.
    """
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 72.0}})
    assert "deadband" in body.snapshot()["channels"][0]["transmit"][0]["reason"]

    body.gates_locked = True
    body.tick({"lamina_circulatory": {"HR": 200.0}})
    channel = body.snapshot()["channels"][0]
    for side in ("transmit", "receive"):
        assert channel[side][0]["reason"] == "organism breaker", (
            f"the breaker fired and the {side} gate did not say so"
        )


# ══════════════════════════════════════════════════════════════════════
# and the same thing over the socket the page actually uses
# ══════════════════════════════════════════════════════════════════════

def test_the_organism_socket_carries_the_channels_section(client):
    with client.websocket_connect("/ws/organism?tick_ms=20") as ws:
        snapshot = ws.receive_json()

    assert isinstance(snapshot["channels"], list)
    channel = snapshot["channels"][0]
    for key in ("id", "from", "to", "transmit", "receive", "offered",
                "last_value", "provenance"):
        assert key in channel, f"the socket dropped '{key}' from the channel"
    for side in ("transmit", "receive"):
        for key in ("id", "kind", "side", "open", "open_fraction", "reason"):
            assert key in channel[side][0], (
                f"the socket dropped '{key}' from a {side} gate"
            )


def test_a_session_snapshot_holds_both_halves_at_once():
    """
    The declaration-side keys and the live keys arrive on one object, so
    a page can draw the seam without a second request mid-render.
    """
    session = OrganismSession(seed=5)
    for twin in session.organism.twins.values():
        twin._log = lambda *a, **k: None
    for _ in range(12):
        sample = session.sample()
        sample["lamina_circulatory"]["HR"] = 200.0
        snapshot = session.tick(sample)

    channel = snapshot["channels"][0]
    assert channel["from_lamina"] in snapshot["laminae"]
    assert channel["to_lamina"] in snapshot["laminae"]
    assert channel["transmit"][0]["open"] is True
    reported = snapshot["organism_report"]["channels"][channel["id"]]
    assert reported["transmit"][0]["open_fraction"] == (
        channel["transmit"][0]["open_fraction"]), (
        "the tick report and the snapshot must agree")
