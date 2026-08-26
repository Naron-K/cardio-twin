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
    assert [gate["id"] for gate in payload["gates"]] == ["pg_co_to_resp"]


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


def test_a_gate_arrives_resolved_rather_than_as_raw_xml(client):
    gate = client.get("/api/organism").json()["gates"][0]

    assert gate["from_lamina"] == "lamina_circulatory"
    assert gate["from_member"] == "pump_state"
    assert gate["to_lamina"] == "lamina_respiratory"
    assert gate["to_member"] == "CO_ref"
    assert gate["extract"] == "CO"
    assert gate["starts_closed"] is True, "rule 1, as a value not a promise"

    params = gate["controller_params"]
    assert params["aggregate"] == "deviation"
    assert params["close_below"] < params["open_above"], "rule 4, on the wire"
    assert params["reference"] == pytest.approx(0.30)

    transfer = gate["transfer"]
    assert transfer["mode"] == "proportional"
    assert transfer["on_close"] == "hold"
    assert 0.0 < transfer["rate"] <= 1.0


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

    path = _organism(tmp_path, 'from="lamina_circulatory:pump_state"',
                     'from="lamina_circulatory:not_a_composite"')
    response = client.get("/api/organism", params={"organism": str(path)})
    assert response.status_code == 400
    assert "not_a_composite" in response.json()["detail"]["error"]


# ══════════════════════════════════════════════════════════════════════
# snapshot["gates"] — the live state
# ══════════════════════════════════════════════════════════════════════

def test_a_shut_gate_reports_itself_shut_with_nothing_to_show_for_it(body):
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 72.0}})

    gate = body.snapshot()["gates"][0]
    assert gate["open"] is False
    assert gate["open_fraction"] == 0.0
    assert gate["last_value"] is None
    assert gate["provenance"] == {}
    # The declaration is still there, because a shut valve is still a valve.
    assert gate["from"] == "lamina_circulatory:pump_state"
    assert gate["to"] == "lamina_respiratory:CO_ref"
    assert gate["controller"] == "threshold"


def test_an_open_gate_carries_its_state_and_the_value_that_crossed(body):
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 200.0}})

    gate = body.snapshot()["gates"][0]
    assert gate["open"] is True
    assert gate["open_fraction"] == 1.0
    assert gate["last_value"] > 5.0
    assert gate["watch_value"] > gate_open_above()
    assert gate["provenance"]["state"] == "coupled"
    assert gate["provenance"]["gate"] == "pg_co_to_resp"
    assert gate["provenance"]["age"] == 0


def gate_open_above() -> float:
    from organism import parse_organism
    return parse_organism().gates[0].controller_args()["open_above"]


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

    from_gate = snapshot["gates"][0]["provenance"]
    from_lamina = snapshot["laminae"]["lamina_respiratory"]["inbound"]["CO_ref"]

    assert from_lamina["provenance"] == {"state": "coupled", **from_gate}
    assert from_lamina["value"] == pytest.approx(snapshot["gates"][0]["last_value"])


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
    shut = body.snapshot()["gates"][0]
    assert shut["open"] is False
    crossed, age = shut["last_value"], shut["provenance"]["age"]

    for _ in range(5):
        body.tick({"lamina_circulatory": {"HR": 72.0}})

    gate = body.snapshot()["gates"][0]
    assert gate["last_value"] == pytest.approx(crossed), "hold keeps the value"
    assert gate["provenance"]["state"] == "held"
    assert gate["provenance"]["age"] == age + 5, "and it ages every cycle"
    assert gate["provenance"]["open_fraction"] == 0.0


def test_the_gate_says_why_rather_than_only_whether(body):
    """
    A valve that reports a boolean and nothing else makes the reader
    guess between "the value is inside the deadband" and "the breaker
    fired", which are not the same news.
    """
    for _ in range(10):
        body.tick({"lamina_circulatory": {"HR": 72.0}})
    assert "deadband" in body.snapshot()["gates"][0]["reason"]

    body.gates_locked = True
    body.tick({"lamina_circulatory": {"HR": 200.0}})
    assert body.snapshot()["gates"][0]["reason"] == "organism breaker"


# ══════════════════════════════════════════════════════════════════════
# and the same thing over the socket the page actually uses
# ══════════════════════════════════════════════════════════════════════

def test_the_organism_socket_carries_the_gates_section(client):
    with client.websocket_connect("/ws/organism?tick_ms=20") as ws:
        snapshot = ws.receive_json()

    assert isinstance(snapshot["gates"], list)
    gate = snapshot["gates"][0]
    for key in ("id", "from", "to", "controller", "open", "open_fraction",
                "last_value", "provenance", "reason"):
        assert key in gate, f"the socket dropped '{key}' from the gate entry"


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

    gate = snapshot["gates"][0]
    assert gate["from_lamina"] in snapshot["laminae"]
    assert gate["to_lamina"] in snapshot["laminae"]
    assert gate["open"] is True
    assert snapshot["organism_report"]["gates"][gate["id"]]["open_fraction"] == (
        gate["open_fraction"]), "the tick report and the snapshot must agree"
