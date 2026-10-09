"""
The absorption vector as a DYNAMIC weight matrix — the loop that was
described for a year and never ran.

Until now `absorption_vector` was parsed from XML and never touched
again: `auto_adjust_weights` existed, nothing called it, and D17 froze
it on the grounds that the learning loop and the gate kernel would
couple through the two vectors.  They do not — D2 split them for exactly
this, the kernel reads `distribution_vector` and learning writes
`absorption_vector` — so what this file tests is the loop finally
running, and the two properties that make running it safe:

  IT STOPS.  Inside the tolerance the domain expert declared, there is
  nothing to correct, and the weights stay where they were put.  Without
  that dead-zone the loop grinds against its own clamps forever while
  the model is already fine — measured, and the reason the dead-zone is
  in the code.

  IT IS BOUNDED.  Every declaration carries a clamp, refused at parse
  if absent, because this loop now sits inside another one: absorption
  moves the composite's state value, the state value opens a gate, the
  gate moves CO_ref, CO_ref moves DO2, and DO2 is the outcome that moves
  absorption.

Numbers here are measured on the shipped bodies at seed 11, not chosen.
"""
import math

import numpy as np
import pytest

from organism import Organism
from signal_source import SimulatedSource
from universal_twin import Composite, UniversalTwin

SEED = 11


# ══════════════════════════════════════════════════════════════════════
# The declaration
# ══════════════════════════════════════════════════════════════════════

def _lamina(tmp_path, absorption_attrs: str) -> str:
    """A one-composite lamina whose absorption block the test controls."""
    path = tmp_path / "lamina_learn.xml"
    path.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_learn" name="Learn" level="0">
  <attributes>
    <attribute id="a">
      <name>A</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline>
    </attribute>
    <attribute id="b">
      <name>B</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline>
    </attribute>
  </attributes>
  <composites>
    <composite id="pair">
      <name>Pair</name>
      <attributes>a, b</attributes>
      <absorption_vector {absorption_attrs}>
        <weight attribute="a">0.5</weight>
        <weight attribute="b">0.5</weight>
      </absorption_vector>
    </composite>
  </composites>
</lamina>
""", encoding="utf-8")
    return str(path)


GOOD = ('learns_from="target_a" learning_rate="0.02" '
        'clamp_min="0.05" clamp_max="1.0"')


def test_a_composite_without_a_learning_block_does_not_learn(tmp_path):
    """
    The default, and it stays the default: a weight moves only where
    somebody wrote down that it may.
    """
    twin = UniversalTwin(_lamina(tmp_path, ""))
    twin._log = lambda *a, **k: None
    assert twin.composites["pair"].absorption_learning is None


def test_a_full_declaration_is_read_whole(tmp_path):
    twin = UniversalTwin(_lamina(tmp_path, GOOD))
    twin._log = lambda *a, **k: None
    assert twin.composites["pair"].absorption_learning == {
        "outcome": "target_a", "rate": 0.02, "min": 0.05, "max": 1.0,
    }


@pytest.mark.parametrize("attrs, expected", [
    # A rate with no clamp is the case the rule exists for: a weight
    # that may move without a bound, inside a closed loop.
    ('learns_from="target_a" learning_rate="0.02"', "clamp_max"),
    ('learning_rate="0.02" clamp_min="0.05" clamp_max="1.0"', "learns_from"),
    ('learns_from="target_a" clamp_min="0.05" clamp_max="1.0"',
     "learning_rate"),
])
def test_a_partial_declaration_is_refused_and_names_what_is_missing(
        tmp_path, attrs, expected):
    with pytest.raises(ValueError, match=expected):
        UniversalTwin(_lamina(tmp_path, attrs))


@pytest.mark.parametrize("attrs, expected", [
    (GOOD.replace('learning_rate="0.02"', 'learning_rate="0"'),
     "reports learning and does none"),
    (GOOD.replace('learning_rate="0.02"', 'learning_rate="-0.1"'),
     "reports learning and does none"),
    (GOOD.replace('clamp_min="0.05"', 'clamp_min="1.5"'), "have width"),
    (GOOD.replace('clamp_min="0.05"', 'clamp_min="-0.2"'), "negative"),
    (GOOD.replace('learning_rate="0.02"', 'learning_rate="fast"'),
     "non-numeric"),
])
def test_an_unusable_learning_parameter_fails_loudly(tmp_path, attrs,
                                                     expected):
    """
    Each of these would otherwise produce a loop that runs and means
    something other than it says: a rate of zero that reports learning,
    a clamp with no width that pins the weights while claiming they
    move, a negative floor that flips an attribute's contribution.
    """
    with pytest.raises(ValueError, match=expected):
        UniversalTwin(_lamina(tmp_path, attrs))


# ══════════════════════════════════════════════════════════════════════
# The step itself
# ══════════════════════════════════════════════════════════════════════

def _composite(weights, rule=None):
    comp = Composite(id="c", name="C", attribute_ids=["a", "b"])
    comp.update_weights(weights)
    comp.absorption_learning = rule or {"outcome": "o", "rate": 0.1,
                                        "min": 0.05, "max": 1.0}
    return comp


def test_the_step_follows_the_gradient_of_the_state_value():
    """
    Δwᵢ = rate · deviation · (vᵢ − v̄), the gradient ∂s/∂wᵢ = (vᵢ − s)/Σw
    projected onto the surface where Σw does not move.  A positive error raises the
    weight of whatever sits ABOVE the composite's current state and
    lowers the weight of whatever sits below it — the two directions
    that actually move the summary.
    """
    comp = _composite([0.5, 0.5])
    state_before = comp.state_value([0.2, 0.8])

    comp.adapt_absorption([0.2, 0.8], deviation=1.0)

    assert comp.absorption_vector[0] < 0.5, "the low coordinate should lose"
    assert comp.absorption_vector[1] > 0.5, "the high coordinate should gain"
    assert comp.state_value([0.2, 0.8]) > state_before, (
        "a positive error has to move the state value up"
    )


def test_an_attribute_sitting_on_the_state_value_keeps_its_weight():
    """
    It carries no information about which way to move, so it earns no
    change — the gradient term (vᵢ − s) is exactly zero.
    """
    comp = _composite([0.5, 0.5])
    comp.adapt_absorption([0.4, 0.4], deviation=1.0)
    assert comp.absorption_vector == pytest.approx([0.5, 0.5])


def test_a_negative_error_moves_the_state_the_other_way():
    comp = _composite([0.5, 0.5])
    before = comp.state_value([0.2, 0.8])
    comp.adapt_absorption([0.2, 0.8], deviation=-1.0)
    assert comp.state_value([0.2, 0.8]) < before


def test_the_weights_never_leave_the_declared_band():
    """
    The clamp is the whole reason this loop is allowed to run inside
    another one, so it is tested against a deviation far larger than
    anything the model produces.
    """
    comp = _composite([0.5, 0.5], rule={"outcome": "o", "rate": 5.0,
                                        "min": 0.05, "max": 1.0})
    for _ in range(50):
        comp.adapt_absorption([0.0, 1.0], deviation=100.0)
    assert all(0.05 <= float(w) <= 1.0 for w in comp.absorption_vector)

    for _ in range(50):
        comp.adapt_absorption([0.0, 1.0], deviation=-100.0)
    assert all(0.05 <= float(w) <= 1.0 for w in comp.absorption_vector)


def test_the_state_value_stays_in_range_however_the_weights_move():
    """
    The invariant the whole seam rests on: whatever learning does to the
    weights, a state value built from normalised coordinates is itself a
    normalised coordinate, and a wire carrying it can be mapped back
    into any receiver's units.
    """
    comp = _composite([0.5, 0.5], rule={"outcome": "o", "rate": 1.0,
                                        "min": 0.05, "max": 1.0})
    rng = np.random.default_rng(SEED)
    for _ in range(200):
        values = list(rng.random(2))
        comp.adapt_absorption(values, deviation=float(rng.normal(0, 3)))
        assert 0.0 <= comp.state_value(values) <= 1.0


@pytest.mark.parametrize("values, deviation, expected", [
    ([0.5, 0.5], float("nan"), "non-finite deviation"),
    ([0.5, 0.5], math.inf, "non-finite deviation"),
    ([0.5], 1.0, "was handed 1 values"),
    ([0.5, 0.5, 0.5], 1.0, "was handed 3 values"),
    ([0.5, float("nan")], 1.0, "NaN or infinite attribute values"),
])
def test_a_step_it_cannot_take_is_refused_rather_than_taken_badly(
        values, deviation, expected):
    comp = _composite([0.5, 0.5])
    with pytest.raises(ValueError, match=expected):
        comp.adapt_absorption(values, deviation)


def test_a_composite_that_declared_no_rule_refuses_to_learn():
    comp = Composite(id="c", name="C", attribute_ids=["a", "b"])
    comp.update_weights([0.5, 0.5])
    with pytest.raises(ValueError, match="declares no learning rule"):
        comp.adapt_absorption([0.4, 0.6], 1.0)


def test_a_rule_without_a_vector_to_learn_on_refuses():
    comp = Composite(id="c", name="C", attribute_ids=["a", "b"])
    comp.absorption_learning = {"outcome": "o", "rate": 0.1,
                                "min": 0.0, "max": 1.0}
    with pytest.raises(ValueError, match="no absorption vector"):
        comp.adapt_absorption([0.4, 0.6], 1.0)


# ══════════════════════════════════════════════════════════════════════
# In the body — the measured behaviour
# ══════════════════════════════════════════════════════════════════════

def _body():
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lid: SimulatedSource(twin, seed=SEED).starting_state()
              for lid, twin in org.twins.items()})
    return org


def _weights(org):
    comp = org.twins["lamina_respiratory"].composites["transport_state"]
    return [round(float(w), 6) for w in comp.absorption_vector]


def _drive(org, hr, cycles):
    for cycle in range(cycles):
        org.tick({"lamina_circulatory": {"HR": hr}} if cycle >= 2 else None)


def test_the_only_composite_that_learns_is_the_one_that_said_so():
    """
    The guardrail: a universal mechanism has to be used by at least one
    real lamina, and by only the ones that asked.
    """
    org = _body()
    learning = [cid for twin in org.twins.values()
                for cid, comp in twin.composites.items()
                if comp.absorption_learning is not None]
    assert learning == ["transport_state"]


def test_weights_do_not_move_while_the_outcome_is_inside_its_tolerance():
    """
    Measured: held at HR 110 oxygen delivery settles around 1080 against
    a target of 1000 ± 250, comfortably inside the band.  There is
    nothing to correct, so nothing is corrected.

    Before the dead-zone existed this same run walked the weights from
    equal quarters to SpO2 0.497 with DO2 pinned on its floor, and they
    were still moving at cycle 200 — a loop with nothing to converge on,
    grinding against its own clamps.
    """
    org = _body()
    previous = _weights(org)
    moved: list = []
    for cycle in range(160):
        org.tick({"lamina_circulatory": {"HR": 110.0}} if cycle >= 2 else None)
        current = _weights(org)
        if current != previous:
            moved.append((cycle,
                          max(abs(a - b) for a, b in zip(current, previous))))
        previous = current

    do2 = org.twins["lamina_respiratory"].attributes["DO2"].value
    assert 750.0 < do2 < 1250.0, (
        f"this test needs the outcome INSIDE its band to mean anything; "
        f"DO2 sat at {do2}"
    )
    # Measured: exactly one cycle of 160 moves anything, by 2.8e-05, when
    # oxygen delivery clips the edge of its band on the way to settling.
    # Asserted as a bound rather than as silence, because claiming
    # silence and getting one 2.8e-05 step would be a test that has to be
    # loosened later rather than one that says what happens.
    assert len(moved) <= 1, f"weights moved on cycles {[c for c, _ in moved]}"
    assert all(step < 1e-4 for _, step in moved), moved
    assert not [c for c, _ in moved if c >= 60], (
        "the loop is still acting long after the outcome settled inside "
        "its band"
    )


def test_weights_move_and_then_settle_when_the_outcome_leaves_its_band():
    """
    Held at HR 200 the crossing drives oxygen delivery to about 2100 —
    far outside the band — and the loop responds, then stops.

    Measured: the weights are identical at cycles 50, 150 and 299, and
    oxygen delivery comes back from 2118 to about 1210.  Both halves
    matter.  A loop that never moved would be inert; one that never
    stopped would be the failure the dead-zone was added for.
    """
    org = _body()
    before = _weights(org)
    _drive(org, 200.0, 50)
    at_50 = _weights(org)
    assert at_50 != before, "the loop did not respond to a real excursion"

    _drive(org, 200.0, 100)
    assert _weights(org) == at_50, (
        "the weights were still moving 100 cycles after the excursion was "
        "answered — this loop has to converge, not grind"
    )

    do2 = org.twins["lamina_respiratory"].attributes["DO2"].value
    assert do2 < 1400.0, (
        f"oxygen delivery should have come back down from ~2100; it is {do2}"
    )


def test_the_cycle_report_says_which_weights_moved():
    """
    A loop nobody can see is a loop nobody can debug, and this one now
    sits inside the seam's own feedback path.
    """
    org = _body()
    for cycle in range(12):
        report = org.tick({"lamina_circulatory": {"HR": 200.0}}
                          if cycle >= 2 else None)

    absorption = report["cycle_reports"]["lamina_respiratory"]["absorption"]
    assert "transport_state" in absorption
    assert len(absorption["transport_state"]) == 4

    resting = org.tick(None)["cycle_reports"]["lamina_circulatory"]
    assert resting["absorption"] == {}, (
        "a lamina where nothing learns should report nothing learning"
    )


# ══════════════════════════════════════════════════════════════════════
# AᵀX — the invariant the forward pass rests on
# ══════════════════════════════════════════════════════════════════════
#
# The architecture says a composite's state is the inner product of its
# attributes and its absorption vector, C = AᵀX.  What the code computes
# is the weighted MEAN, AᵀX / ΣA — and it has to, because the channel
# carries a [0,1] quantity and the receiver maps it onto its own range:
# a raw inner product over four attributes at weight 1 reaches 4.0, and
# CO_ref would land at 42 L/min on a declared maximum of 12.
#
# The two are the SAME NUMBER exactly while ΣA = 1, which every
# absorption vector in both shipped laminae declares.  So the invariant
# worth defending is not "renormalise to 1" but "Σ stays what the file
# said", and these are the tests that hold it.

def _three(weights, rate=0.1):
    comp = Composite(id="t", name="T", attribute_ids=["a", "b", "c"])
    comp.update_weights(weights)
    comp.absorption_learning = {"outcome": "o", "rate": rate,
                                "min": 0.0, "max": 1.0}
    return comp


def test_a_learning_step_does_not_move_the_sum_of_the_weights():
    """
    Measured before the step was projected, on exactly this probe: the
    sum walked 1.000 → 0.928 → 0.873 → 0.847 over four steps.
    """
    comp = _three([0.7, 0.2, 0.1])
    values = [0.9, 0.5, 0.1]
    for _ in range(4):
        comp.adapt_absorption(values, deviation=1.0)
        assert float(np.sum(comp.absorption_vector)) == pytest.approx(
            1.0, abs=1e-12)


def test_the_state_value_stays_the_inner_product_while_the_weights_learn():
    """
    The property the whole forward pass is built on, checked step by
    step rather than at the end — because the failure it guards against
    is not a drift, it is a DISAGREEMENT ABOUT DIRECTION.

    Measured on this probe before the fix: after three steps AᵀX had
    fallen to 0.7168 while the state value had risen to 0.8464.  One
    number said the composite was going down and the other said up, and
    that number is the whole of what crosses a channel.
    """
    comp = _three([0.7, 0.2, 0.1])
    values = [0.9, 0.5, 0.1]
    for _ in range(6):
        inner = float(np.dot(comp.absorption_vector, values))
        assert comp.state_value(values) == pytest.approx(inner, abs=1e-12)
        comp.adapt_absorption(values, deviation=1.0)


def test_a_sum_the_expert_chose_is_the_sum_that_is_kept():
    """
    Not renormalised to 1 — preserved at whatever was declared.  A
    domain expert who writes weights summing to 2 has said something,
    and a loop that quietly rescaled them would be overruling it.
    """
    comp = _three([0.8, 0.7, 0.5])
    assert float(np.sum(comp.absorption_vector)) == pytest.approx(2.0)
    for _ in range(10):
        comp.adapt_absorption([0.9, 0.5, 0.1], deviation=1.0)
    assert float(np.sum(comp.absorption_vector)) == pytest.approx(2.0, abs=1e-12)


def test_the_sum_survives_a_clamp_biting():
    """
    A clipped weight takes the sum with it unless the residual is handed
    to the weights that still have room.  Driven hard enough that the
    floor binds on the first step.
    """
    comp = _three([0.5, 0.3, 0.2], rate=2.0)
    comp.adapt_absorption([1.0, 0.5, 0.0], deviation=1.0)
    assert min(comp.absorption_vector) == pytest.approx(0.0), (
        "the fixture is meant to drive a weight onto its floor")
    assert float(np.sum(comp.absorption_vector)) == pytest.approx(1.0, abs=1e-12)


def test_a_fully_pinned_composite_keeps_its_clamp_and_loses_the_sum():
    """
    The one case where the sum cannot be held, and the clamp wins.

    A weight that may move has to say how far, and that promise outranks
    the sum — so a residual with nowhere to go is left unplaced rather
    than pushed past an edge.  It is visible: the caller gets the vector
    and can add it up.
    """
    comp = Composite(id="p", name="P", attribute_ids=["a", "b"])
    comp.update_weights([0.5, 0.5])
    comp.absorption_learning = {"outcome": "o", "rate": 10.0,
                                "min": 0.4, "max": 0.45}
    weights = comp.adapt_absorption([1.0, 0.0], deviation=1.0)
    assert all(0.4 <= w <= 0.45 for w in weights), "the clamp is not negotiable"
    assert sum(weights) < 1.0, "and the sum is what gives way"
