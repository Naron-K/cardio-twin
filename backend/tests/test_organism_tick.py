"""
Phase 2 — the container, and the one thing only it can own: the ORDER.

Each lamina already knows how to compute itself and how to run its own
feedback loop.  Neither can decide WHEN a value crosses to the other,
because that question does not exist until there is more than one.  So
these tests are mostly about sequence, and about two properties that
sequence has to preserve:

  - an organism whose gates never open behaves exactly like the laminae
    standing apart (G6, and Phase 5's acceptance criterion 2 — worth
    being able to check before the gates can open, not after);
  - a body that diverges shuts its gates and leaves the laminae running,
    because a lamina's internal loop is its own business and the thing
    that went wrong is the coupling.

The gate controllers arrive in Phase 3 and the transfer engine in Phase
4.  Where a test needs a gate that opens, it registers a stub controller
through the public registry — which is how a container with no
controllers of its own is supposed to be exercised.
"""

import pytest

from laminae import load_twin
from organism import DEFAULT_MAX_TOTAL_NORM, Organism
from session import OrganismSession, Session
from signal_source import SimulatedSource
from snapshot import _simulation_snapshot


def always_open(state, source_vec, params):
    """A stub gate controller: wide open, every cycle."""
    return {"open_fraction": 1.0, "stub": True}


def never_open(state, source_vec, params):
    return {"open_fraction": 0.0}


@pytest.fixture
def body():
    """An organism seeded from each lamina's own declared baselines."""
    org = Organism()
    org.seed({
        lamina_id: SimulatedSource(twin, seed=7).starting_state()
        for lamina_id, twin in org.twins.items()
    })
    return org


# ══════════════════════════════════════════════════════════════════════
# The container
# ══════════════════════════════════════════════════════════════════════

def test_an_organism_holds_one_controller_per_lamina(body):
    assert set(body.twins) == {"lamina_circulatory", "lamina_respiratory"}
    assert set(body.controllers) == set(body.twins)
    for lamina_id, controller in body.controllers.items():
        assert controller.twin is body.twins[lamina_id]


def test_gate_state_lives_on_the_container_not_the_declaration(body):
    """
    Same placement as FeedbackController._kernel_state, and for the same
    reason: a declaration that is also a mutable state bag cannot be
    reloaded, compared or serialised without dragging the run with it.
    """
    gate = body.gates[0]
    assert gate.id in body._gate_state
    for field in vars(gate):
        assert "state" not in field, f"gate declaration grew a state field: {field}"


def test_a_gate_with_no_controller_registered_stays_shut(body):
    """
    Not an error — the declared resting state (G6).  A gate whose
    controller has not been written yet is a valve nobody connected, and
    a valve nobody connected is shut.  That has to keep holding now that
    the registry ships with controllers in it, because the case it
    covers is a gate naming one that has not arrived.
    """
    body._gate_controller_registry.pop("threshold")

    report = body.tick()
    entry = report["gates"]["pg_co_to_resp"]
    assert entry["open_fraction"] == 0.0
    assert entry["transmitted"] is None
    assert "no 'threshold' controller registered" in entry["state"]["reason"]


def test_the_two_v1_controllers_ship_registered(body):
    """
    Same pattern as UniversalTwin registering its default kernels in
    __init__: a container that has to be configured before it works is a
    container that will sometimes be used unconfigured.
    """
    assert set(body._gate_controller_registry) == {"threshold", "key"}
    assert set(body._gate_controller_registry) >= {
        gate.controller for gate in body.gates
    }


# ══════════════════════════════════════════════════════════════════════
# The tick order
# ══════════════════════════════════════════════════════════════════════

def test_the_tick_runs_sensors_compute_gates_then_feedback(body):
    """
    The order, recorded by instrumenting each stage rather than by
    reading the source.  This is the assertion the whole class exists
    for: everything else in the design has an opinion about it, and only
    one place decides.
    """
    trace: list = []

    for lamina_id, twin in body.twins.items():
        original = twin.compute_all
        twin.compute_all = (lambda o=original, l=lamina_id:
                            (trace.append(f"compute:{l}"), o())[1])
    for lamina_id, controller in body.controllers.items():
        original = controller.step
        controller.step = (lambda o=original, l=lamina_id:
                           (trace.append(f"feedback:{l}"), o())[1])
    original_pass = body._gate_pass
    body._gate_pass = lambda w: (trace.append("gates"), original_pass(w))[1]

    body.tick()

    computes = [i for i, e in enumerate(trace) if e.startswith("compute:")]
    feedbacks = [i for i, e in enumerate(trace) if e.startswith("feedback:")]
    gates = trace.index("gates")

    # Every lamina computes before the gate pass…
    assert max(computes[:len(body.twins)]) < gates, trace
    # …and the gate pass finishes before any feedback step starts.
    assert gates < min(feedbacks), trace


def test_the_gate_reads_the_senders_value_after_its_chain_has_run(body):
    """
    After compute, not before.  A gate reading the sender ahead of its
    chain would carry last cycle's number while claiming to carry this
    one's — the same "stale value looking live" the snapshot's `stale`
    flag exists to stop, one layer up.

    Compared against the sender's value AT THE MOMENT the gate pass runs,
    not against its value after the tick: step 4 moves it again, which is
    the next test's business.
    """
    body.register_gate_controller("threshold", always_open)
    circ = body.twins["lamina_circulatory"]

    seen: dict = {}
    original = body._gate_pass
    body._gate_pass = lambda w: (
        seen.__setitem__("co", circ.attributes["CO"].value), original(w))[1]

    report = body.tick({"lamina_circulatory": {"HR": 100.0}})
    assert report["gates"]["pg_co_to_resp"]["reading"] == pytest.approx(
        seen["co"], rel=1e-12
    )
    # HR 100 with the declared EDV gives CO = 100 * 66 / 1000 — this cycle's
    # number, not the 72 bpm one the twin was seeded with.
    assert seen["co"] == pytest.approx(6.6, rel=1e-6)


def test_the_receiver_uses_a_crossing_on_the_same_tick(body):
    """
    The consequence that the obvious reasoning gets backwards.

    Step 2 has already run when the gate writes, so it looks as though
    the receiver must wait a tick.  It does not: step 4 is
    FeedbackController.step(), whose last act is another compute_all(),
    so the receiving chain re-derives from the crossed value within the
    same tick.

    This matters beyond bookkeeping.  There is no implicit one-cycle
    delay to lean on — `time_delay=0` really is zero — so the EWMA rate
    is the whole of the anti-oscillation defence when Phase 4 lands it.
    """
    body.register_gate_controller("threshold", always_open)
    resp = body.twins["lamina_respiratory"]

    do2_before = resp.attributes["DO2"].value
    report = body.tick()

    crossed = report["gates"]["pg_co_to_resp"]["transmitted"]
    assert crossed is not None
    assert resp.attributes["CO_ref"].value == pytest.approx(crossed)
    assert crossed != pytest.approx(5.0), "the seam's uncoupled baseline"

    # Same tick, not the next one.
    assert resp.attributes["DO2"].value != pytest.approx(do2_before, rel=1e-6)
    # And it is the crossed value the chain used: DO2 = CaO2 * CO_ref * 10.
    cao2 = resp.attributes["CaO2"].value
    assert resp.attributes["DO2"].value == pytest.approx(cao2 * crossed * 10,
                                                         rel=1e-6)


def test_the_value_that_crosses_carries_the_senders_previous_correction(body):
    """
    The other half of the ordering, and the price of running the gate
    before the loops rather than after: the gate reads between step 2 and
    step 4, so what crosses is this cycle's X' plus LAST cycle's X''.

    The alternative — reading after step 4 — hands the receiver a number
    the sender's own loop has already reacted to.
    """
    body.register_gate_controller("threshold", always_open)
    circ = body.twins["lamina_circulatory"]

    seen: list = []
    original = body._gate_pass
    body._gate_pass = lambda w: (
        seen.append(circ.attributes["CO"].value_feedback), original(w))[1]

    body.tick()
    x_pp_after_first = circ.attributes["CO"].value_feedback
    body.tick()

    assert seen[1] == pytest.approx(x_pp_after_first), (
        "the second gate pass should see the X'' the first tick's feedback "
        "step left behind, not one the current tick has produced"
    )


def test_a_crossing_arrives_as_x_prime_with_its_provenance(body):
    """G1: an inter-lamina value is an input, not a correction."""
    body.register_gate_controller("threshold", always_open)
    body.tick()

    co_ref = body.twins["lamina_respiratory"].attributes["CO_ref"]
    assert co_ref.value_feedback == 0.0, "a crossing must not land in X''"
    assert co_ref.value_external is not None
    assert co_ref.provenance["gate"] == "pg_co_to_resp"
    assert co_ref.provenance["from"] == "lamina_circulatory"

    entry = _simulation_snapshot(body.twins["lamina_respiratory"])["inbound"]
    assert entry["CO_ref"]["provenance"]["state"] == "coupled"


# ══════════════════════════════════════════════════════════════════════
# Closed gates change nothing
# ══════════════════════════════════════════════════════════════════════

def test_an_organism_with_shut_gates_matches_two_standalone_laminae():
    """
    Phase 5's acceptance criterion 2, checkable now because a gate with
    no controller cannot open.  If this ever fails, the container is
    doing something to the laminae beyond ordering them.
    """
    org = Organism()
    seeds = {
        lamina_id: SimulatedSource(twin, seed=3).starting_state()
        for lamina_id, twin in org.twins.items()
    }
    org.seed(seeds)
    for _ in range(20):
        org.tick()

    for lamina_id, twin in org.twins.items():
        alone = Session(sensor_data=seeds[lamina_id],
                        lamina=twin.xml_path)
        for _ in range(20):
            alone.tick({})

        together = _simulation_snapshot(twin)
        apart = _simulation_snapshot(alone.twin)
        for section in ("sensors", "inbound", "computed"):
            assert together[section].keys() == apart[section].keys()
            for attr_id in together[section]:
                assert together[section][attr_id]["value"] == pytest.approx(
                    apart[section][attr_id]["value"], rel=1e-9
                ), f"{lamina_id}.{attr_id} differs inside an organism"


def test_a_registered_controller_that_says_shut_transmits_nothing(body):
    """The other way of being closed: a controller that ran and said no."""
    body.register_gate_controller("threshold", never_open)
    report = body.tick()
    assert report["gates"]["pg_co_to_resp"]["open_fraction"] == 0.0
    assert report["gates"]["pg_co_to_resp"]["transmitted"] is None
    assert body.twins["lamina_respiratory"].attributes["CO_ref"].value == 5.0


def test_an_out_of_range_open_fraction_is_clamped_and_reported(body):
    body.register_gate_controller(
        "threshold", lambda s, v, p: {"open_fraction": 4.0})
    report = body.tick()
    assert report["gates"]["pg_co_to_resp"]["open_fraction"] == 1.0
    assert any("outside [0,1]" in w for w in report["warnings"])


# ══════════════════════════════════════════════════════════════════════
# The body-level breaker
# ══════════════════════════════════════════════════════════════════════

def test_the_body_breaker_shuts_the_gates_and_leaves_the_laminae_running(body):
    """
    Two laminae can each sit under their own limit while feeding each
    other through an open gate, and no per-lamina breaker can see that.
    What the body breaker does about it is shut the gates — a lamina's
    internal loop is its own business, and the coupling is what went
    wrong.
    """
    body.register_gate_controller("threshold", always_open)
    body.max_total_norm = 0.0          # anything at all trips it

    report = body.tick()
    assert report["gates_locked"] is True
    assert any("ORGANISM BREAKER" in w for w in report["warnings"])

    # Gates stay shut…
    after = body.tick()
    assert after["gates"]["pg_co_to_resp"]["open_fraction"] == 0.0
    assert after["gates"]["pg_co_to_resp"]["transmitted"] is None
    # …and both laminae are still cycling.
    for lamina_id, cycle_report in after["cycle_reports"].items():
        assert cycle_report["cycle"] == after["cycle"], lamina_id


def test_the_breaker_stays_tripped_until_reset(body):
    body.register_gate_controller("threshold", always_open)
    body.max_total_norm = 0.0
    body.tick()
    assert body.gates_locked

    body.max_total_norm = DEFAULT_MAX_TOTAL_NORM
    body.tick()
    assert body.gates_locked, "a tripped breaker must not un-trip itself"

    body.reset()
    assert not body.gates_locked
    assert body.cycle == 0
    assert body._gate_state == {gate.id: {} for gate in body.gates}


def test_a_settled_body_does_not_trip_anything(body):
    body.register_gate_controller("threshold", always_open)
    for _ in range(30):
        report = body.tick()
        assert not report["gates_locked"], report["warnings"]
    assert report["total_feedback_norm"] < DEFAULT_MAX_TOTAL_NORM


# ══════════════════════════════════════════════════════════════════════
# OrganismSession stands beside Session
# ══════════════════════════════════════════════════════════════════════

def test_the_single_lamina_session_is_untouched():
    """
    Coupling two laminae should not make running one of them go through
    machinery it does not need.
    """
    session = Session()
    assert not hasattr(session, "organism")
    snapshot = session.tick({})
    assert "laminae" not in snapshot
    assert "cycle_report" in snapshot


def test_an_organism_session_gives_every_lamina_its_own_feed():
    session = OrganismSession(seed=5)
    sample = session.sample()
    assert set(sample) == set(session.organism.twins)
    # …and no feed invents a reading for the seam.
    assert "CO_ref" not in sample["lamina_respiratory"]


def test_an_organism_session_snapshot_nests_the_familiar_shape():
    session = OrganismSession(seed=5)
    snapshot = session.tick(session.sample())

    assert set(snapshot["laminae"]) == set(session.organism.twins)
    for lamina_snapshot in snapshot["laminae"].values():
        # Exactly the keys a single-lamina session sends.
        for key in ("sensors", "inbound", "computed", "outcomes",
                    "cycle_report", "before_after", "warnings"):
            assert key in lamina_snapshot
    assert snapshot["organism_report"]["cycle"] == 1
    assert [g["id"] for g in snapshot["gates"]] == ["pg_co_to_resp"]


def test_setting_a_sensor_on_one_lamina_leaves_the_other_alone():
    session = OrganismSession(seed=5)
    resp_before = session.organism.twins["lamina_respiratory"].attributes["RR"].value

    session.set_sensor("lamina_circulatory", "HR", 130.0)
    assert session.organism.twins["lamina_circulatory"].attributes["HR"].value == 130.0
    assert session.organism.twins["lamina_respiratory"].attributes["RR"].value \
        == resp_before

    # Commanding the seam is refused rather than silently applied.
    session.set_sensor("lamina_respiratory", "CO_ref", 9.0)
    assert session.organism.twins["lamina_respiratory"].attributes["CO_ref"].value \
        == 5.0


# ══════════════════════════════════════════════════════════════════════
# The socket
# ══════════════════════════════════════════════════════════════════════

_FAST_ORGANISM = "/ws/organism?tick_ms=20"


def test_the_organism_socket_streams_a_body():
    """
    A separate endpoint from /ws/feedback rather than a query parameter
    on it, because the two payloads are different shapes and a client
    should not discover that from the reply.  See the note in the module
    docstring of main.py's handler.
    """
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        with client.websocket_connect(_FAST_ORGANISM) as ws:
            snap = ws.receive_json()

    assert snap["organism_id"] == "bdt_default"
    assert set(snap["laminae"]) == {"lamina_circulatory", "lamina_respiratory"}
    assert snap["organism_report"]["cycle"] >= 1
    assert "pg_co_to_resp" in snap["organism_report"]["gates"]
    # Each lamina still ships the shape a one-lamina socket sends.
    for lamina_snapshot in snap["laminae"].values():
        for key in ("sensors", "computed", "outcomes", "feedback_norm",
                    "cycle_report"):
            assert key in lamina_snapshot


def test_the_organism_socket_says_its_feed_is_generated():
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        with client.websocket_connect(_FAST_ORGANISM) as ws:
            snap = ws.receive_json()

    assert snap["source"]["kind"] == "simulated"
    for lamina_id in snap["laminae"]:
        assert lamina_id in snap["source"]["detail"]


def test_setting_a_sensor_over_the_socket_needs_a_lamina():
    """
    On a body "set HR" is ambiguous, and guessing which lamina meant it
    is the kind of thing that looks like it works.
    """
    from fastapi.testclient import TestClient
    from main import app

    with TestClient(app) as client:
        with client.websocket_connect(_FAST_ORGANISM) as ws:
            for _ in range(3):
                ws.receive_json()
            # No lamina named — dropped rather than applied to a guess.
            ws.send_json({"type": "set_sensor", "id": "HR", "value": 150.0})
            for _ in range(4):
                snap = ws.receive_json()
            assert snap["laminae"]["lamina_circulatory"]["sensors"]["HR"]["value"] \
                < 100.0

            ws.send_json({"type": "set_sensor", "lamina": "lamina_circulatory",
                          "id": "HR", "value": 150.0})
            seen = [ws.receive_json()["laminae"]["lamina_circulatory"]
                    ["sensors"]["HR"]["value"] for _ in range(6)]
    assert max(seen) > 140.0, seen


def test_an_unparseable_organism_is_refused_before_streaming():
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from main import app

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                    "/ws/organism?organism=no_such_organism.xml") as ws:
                ws.receive_json()
