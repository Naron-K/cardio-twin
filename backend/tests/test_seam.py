"""
Phase 5 — the first live seam: circulation's CO into respiration's CO_ref.

Everything before this phase built machinery and proved it in isolation:
a schema that refuses a badly declared gate, a container with one tick
order, two controllers, a transfer engine.  None of that says the seam
DOES anything.  These are the acceptance criteria, and they are about the
joined body rather than about any part of it.

  1. Coupling has an effect.  Break the pump and oxygen delivery on the
     other side moves, through the gate, within a bounded number of
     cycles — and the receiving lamina's own outcome notices.
  2. Shut is identical.  A body whose gate never opens produces exactly
     what the two laminae produce standing apart.  Not approximately.
  3. No tug-of-war.  Both feedback loops running with the gate open, and
     the body-level norm settles instead of winding up.
  4. No regression.  The single-lamina world is untouched.

Criterion 1 is the one that changed the model.  As the plan wrote it, it
was "drop EDV, watch CO fall, watch DO2 follow", and neither half of that
survived measurement:

  - EDV is not a lever on settled CO.  The circulatory loop's declared
    outcome is target_co = 5.0 +/- 1.5, so it spends its correction
    budget undoing exactly the perturbation the test was applying.
    Measured, EDV forced to 60 for 40 cycles: CO settles at 5.97, ABOVE
    where it started.  HR is the honest lever, because a forced sensor
    the loop cannot write back to moves the settled point.

  - The gate could not have opened for a falling CO anyway.  It watched
    raw normalised CO against a single high boundary, so it opened for a
    racing heart and stayed shut for a failing one.  That is fixed in
    organism.xml; test_gate_controllers.py is where the fix is measured,
    and here it is only used.
"""

import pytest

from feedback_controller import FeedbackController
from laminae import load_twin, resolve_lamina
from organism import DEFAULT_MAX_TOTAL_NORM, Organism
from session import OrganismSession
from signal_source import SimulatedSource
from snapshot import _simulation_snapshot

# The gate's declared refractory is 5 cycles, so "responds promptly" has
# to allow at least that plus what the EWMA needs to walk the receiver
# off its baseline.  Measured, the seam moves DO2 on the cycle the gate
# opens; this bound is loose enough not to be a trip-wire for unrelated
# changes and tight enough to fail if the seam goes dead.
RESPONSE_BUDGET = 12


@pytest.fixture
def body():
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=11).starting_state()
              for lamina_id, twin in org.twins.items()})
    return org


def _do2_outcome(twin):
    for outcomes in twin.evaluate_all_outcomes().values():
        for fb in outcomes:
            if fb["outcome_id"] == "target_do2":
                return fb
    raise AssertionError("lamina_respiratory no longer declares target_do2")


# ══════════════════════════════════════════════════════════════════════
# 1 — the coupling has an effect
# ══════════════════════════════════════════════════════════════════════

def test_a_failing_pump_reaches_oxygen_delivery_through_the_gate(body):
    """
    The criterion, in the direction that matters.

    Bradycardia at HR 35 settles the circulation at about 3.3 L/min.  On
    a body with no seam, respiration goes on computing DO2 from its own
    uncoupled baseline of 5.0 and reports normal delivery for a pump
    doing two thirds of it.  With the seam, the number crosses and the
    far side's oxygen delivery follows it down.
    """
    resp = body.twins["lamina_respiratory"]
    circ = body.twins["lamina_circulatory"]

    for _ in range(4):
        body.tick()
    rested_do2 = resp.attributes["DO2"].value
    assert resp.attributes["CO_ref"].value == pytest.approx(5.0, abs=0.01), (
        "the seam should still be resting on its declared baseline"
    )

    opened_on = None
    for cycle in range(RESPONSE_BUDGET):
        report = body.tick({"lamina_circulatory": {"HR": 35.0}})
        if opened_on is None and report["gates"]["pg_co_to_resp"]["open_fraction"] > 0:
            opened_on = cycle

    assert opened_on is not None, "the gate never opened for a failing pump"

    assert circ.attributes["CO"].value < 4.5, (
        "the pump really is failing — it is still on its way down at this "
        "point, and settles near 3.3 if the forcing is held"
    )
    assert resp.attributes["CO_ref"].value < 5.0, (
        "the seam should have carried the shortfall, not the baseline"
    )
    assert resp.attributes["DO2"].value < rested_do2, (
        f"oxygen delivery should follow the pump down; "
        f"{rested_do2:.1f} -> {resp.attributes['DO2'].value:.1f}"
    )

    provenance = resp.attributes["CO_ref"].provenance
    assert provenance["state"] == "coupled"
    assert provenance["gate"] == "pg_co_to_resp"
    assert provenance["from"] == "lamina_circulatory"


def test_the_receiving_lamina_notices_a_shortfall_it_could_not_see_before(body):
    """
    The point of the seam, rather than the mechanics of it.

    An uncoupled respiratory lamina cannot report a delivery deficit
    caused by the heart, because nothing in it knows what the heart is
    doing: DO2 comes off a baseline of 5.0 that is right by declaration.
    Coupled, the deficit becomes visible to the lamina's OWN outcome,
    which is what makes the crossing worth having — not that a number
    moved, but that a judgement changed.
    """
    resp = body.twins["lamina_respiratory"]

    for _ in range(4):
        body.tick()
    rested = _do2_outcome(resp)
    assert rested["within_tolerance"], "at rest, delivery is fine"

    for _ in range(30):
        body.tick({"lamina_circulatory": {"HR": 30.0}})

    coupled = _do2_outcome(resp)
    assert coupled["actual"] < rested["actual"], (
        f"delivery should read lower than at rest; "
        f"{rested['actual']:.1f} -> {coupled['actual']:.1f}"
    )
    assert coupled["deviation"] < -100.0, (
        f"and the shortfall should be big enough for the lamina to argue "
        f"with; got a deviation of {coupled['deviation']:.1f} mL/min"
    )


def test_an_unremarkable_pump_is_not_worth_crossing_for(body):
    """
    The other half of criterion 1, and the reason a gate is a valve
    rather than a wire.

    A circulation sitting inside the band the receiver's own tolerance
    allows has nothing to tell it: the seam stays on its declared
    baseline and claims no provenance, because it has carried nothing.
    """
    resp = body.twins["lamina_respiratory"]
    for _ in range(20):
        report = body.tick({"lamina_circulatory": {"HR": 72.0}})
        assert report["gates"]["pg_co_to_resp"]["open_fraction"] == 0.0

    assert resp.attributes["CO_ref"].value == pytest.approx(5.0, abs=0.01)
    assert not resp.attributes["CO_ref"].provenance, (
        "a gate that never carried anything has no provenance to claim"
    )


# ══════════════════════════════════════════════════════════════════════
# 2 — shut is identical, not merely similar
# ══════════════════════════════════════════════════════════════════════

def test_a_body_whose_gate_never_opens_equals_two_standalone_laminae():
    """
    G6 as an equality, on the SHIPPED gate rather than on a stub that
    refuses to open.

    Phase 2 could only check this with no controller registered, which
    proves that a gate nobody wired carries nothing.  Now that the gate
    can open, the stronger statement is available: driven at rest, where
    the declared deadband keeps it shut, the body and the two separate
    laminae agree to the last decimal.
    """
    def as_a_body():
        org = Organism()
        for twin in org.twins.values():
            twin._log = lambda *a, **k: None
        org.seed({lid: SimulatedSource(t, seed=3).starting_state()
                  for lid, t in org.twins.items()})
        for _ in range(25):
            report = org.tick({"lamina_circulatory": {"HR": 72.0}})
            assert report["gates"]["pg_co_to_resp"]["open_fraction"] == 0.0, (
                "this comparison only means anything while the gate is shut"
            )
        return {lid: _simulation_snapshot(t) for lid, t in org.twins.items()}

    def standing_apart():
        out = {}
        for lamina_id in ("lamina_circulatory", "lamina_respiratory"):
            twin = load_twin(resolve_lamina(lamina_id))
            twin._log = lambda *a, **k: None
            for attr_id, value in SimulatedSource(twin, seed=3).starting_state().items():
                twin.set_sensor(attr_id, value)
            twin.compute_all()
            controller = FeedbackController(twin)
            for _ in range(25):
                if lamina_id == "lamina_circulatory":
                    twin.set_sensor("HR", 72.0)
                twin.compute_all()
                controller.step()
            out[lamina_id] = _simulation_snapshot(twin)
        return out

    coupled, apart = as_a_body(), standing_apart()
    assert set(coupled) == set(apart)
    for lamina_id in coupled:
        for section in ("sensors", "computed", "vectors", "outcomes"):
            assert coupled[lamina_id][section] == apart[lamina_id][section], (
                f"{lamina_id}.{section} differs with the gate shut"
            )
        assert coupled[lamina_id]["feedback_norm"] == (
            apart[lamina_id]["feedback_norm"])


# ══════════════════════════════════════════════════════════════════════
# 3 — no tug-of-war
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("hr,label", [(200.0, "racing"), (35.0, "failing")])
def test_two_loops_pulling_through_an_open_gate_still_settle(body, hr, label):
    """
    Criterion 3.  Both laminae run their own feedback loop and the gate is
    open, so each one's correction reaches the other's inputs.  The
    failure this rules out is the two of them winding each other up.

    Measured over 60 cycles with the gate open throughout: the body-level
    norm peaks early and then flattens — at HR 200, from a peak of 0.046
    to a last-ten maximum of 0.010, with the last ten cycles varying by
    4e-5.  The breaker never fires, which is the other half of the
    statement: it settles because it settles, not because something shut
    the gates.
    """
    norms, opens = [], []
    for _ in range(60):
        report = body.tick({"lamina_circulatory": {"HR": hr}})
        norms.append(report["total_feedback_norm"])
        opens.append(report["gates"]["pg_co_to_resp"]["open_fraction"])

    assert min(opens[-10:]) > 0.0, f"the {label} gate should be open at the end"
    assert not body.gates_locked, "the body breaker fired instead of settling"

    # "Settles" is the swing contracting, not the level falling.  The two
    # directions get there differently and both are settled: racing peaks
    # at 0.046 and decays, failing climbs slowly to 0.0026 and flattens,
    # so an assertion that the late peak is under the early one would
    # only hold for one of them and would be measuring the shape of the
    # transient rather than convergence.
    def spread(lo, hi):
        window = norms[lo:hi]
        return max(window) - min(window)

    assert spread(-10, None) < 0.001, (
        f"the tail is still swinging by {spread(-10, None):.5f}"
    )
    assert spread(-10, None) < spread(20, 40), (
        f"the swing is not contracting: {spread(20, 40):.5f} mid, "
        f"{spread(-10, None):.5f} at the end"
    )
    assert max(norms) < DEFAULT_MAX_TOTAL_NORM / 10.0, (
        f"peak norm {max(norms):.5f} is close enough to the breaker at "
        f"{DEFAULT_MAX_TOTAL_NORM} that 'it never fired' proves little"
    )


def test_the_seam_holds_up_over_a_live_feed_with_both_loops_running():
    """
    The same property with the noise on.

    The `body` fixture drives the twins directly; this one goes through
    OrganismSession, which is what the socket uses — each lamina gets its
    own synthetic feed, so every sensor jitters every cycle rather than
    being pinned.  A seam that settles only on clean inputs would settle
    only in tests.
    """
    session = OrganismSession(seed=5)
    for twin in session.organism.twins.values():
        twin._log = lambda *a, **k: None

    opened, norms = 0, []
    for _ in range(80):
        sample = session.sample()
        sample["lamina_circulatory"]["HR"] = 190.0
        report = session.tick(sample)["organism_report"]
        norms.append(report["total_feedback_norm"])
        opened += report["gates"]["pg_co_to_resp"]["open_fraction"] > 0

    assert opened > 40, f"the gate should spend most of this open; got {opened}"
    assert not session.organism.gates_locked
    assert max(norms[-15:]) <= max(norms[5:25]), "winding up on a noisy feed"


# ══════════════════════════════════════════════════════════════════════
# 4 — no regression: the single-lamina world knows about none of this
# ══════════════════════════════════════════════════════════════════════

def test_a_lamina_loaded_on_its_own_never_touches_the_organism():
    """
    Criterion 4 is mostly the rest of the suite staying green, which a
    test cannot assert about itself.  What it CAN assert is the property
    the rest of the suite rests on: a lamina loaded on its own has no
    gate, no organism, and a seam sitting on its declared baseline,
    whatever organism.xml happens to say.
    """
    twin = load_twin(resolve_lamina("lamina_respiratory"))
    twin._log = lambda *a, **k: None
    for attr_id, value in SimulatedSource(twin, seed=3).starting_state().items():
        twin.set_sensor(attr_id, value)
    twin.compute_all()

    snapshot = _simulation_snapshot(twin)
    assert snapshot["inbound"]["CO_ref"]["value"] == pytest.approx(5.0)
    assert snapshot["inbound"]["CO_ref"]["provenance"]["state"] == "uncoupled"
    assert "gates" not in snapshot
    assert twin.attributes["DO2"].value is not None, (
        "and the chain below the seam still runs (G9)"
    )
