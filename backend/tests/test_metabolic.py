"""
The third lamina, and the first place the backward pass runs for real.

The return path has been buildable since the gate channels landed and
unusable on the shipped body, for a reason that is arithmetic rather than
oversight: circulation's face `output_state` holds ONE attribute, a
composite's state value is the weighted mean of its attributes, so with
one attribute the state IS that attribute whatever its weight and every
learning step is exactly zero.  Rule 14 refuses that.

Respiration's `transport_state` was already eligible before this lamina
existed — four attributes AND a learning rule its own file declares.  All
it lacked was somebody above it to send to.

WHAT THIS FILE MEASURES

  THE ELBOW.  Oxygen consumption is supply-INDEPENDENT above a critical
  supply and supply-DEPENDENT below it.  Without that, delivery could
  fall to zero while the tissue still reported itself comfortable.

  THE LOOP, END TO END.  Driven at VO2_demand 1000 on the three-lamina
  body, lactate starts at 6.40 and the error travels back down the
  channel it arrived on:

      cyc   supply     VO2  deficit  lactate      E   w(transport_state)
        0   0.5333   639.9    360.1    6.401  4.401  [.25, .25, .25, .25]
       40   0.7746   929.5     70.5    2.057  0.057  [.245, .425, .28, .05]
      240   0.7776   933.1     66.9    2.003  0.003  [.238, .436, .276, .05]

  Weight moves onto SpO2, the highest-sitting attribute, and DO2 falls to
  its clamp floor — the only direction that raises the face's state
  value.  It stops at the tolerance edge, not at the target, which is the
  dead-zone doing its job.  sum(A) stays 1.000000000 throughout: the
  invariant that keeps the state value equal to the inner product AᵀX.

  THE DEFAULT BODY DOES NOT MOVE.  organism.xml stays at two laminae and
  keeps its frozen 1800-value baseline.  This is a SECOND body file;
  available_organisms() globs organism*.xml, so adding one is dropping a
  file in rather than editing the one everything else is measured
  against.
"""
import math

import pytest

from laminae import available_laminae, load_twin
from organism import Organism, available_organisms
from signal_source import SimulatedSource
from universal_twin import INTER_LAMINA, PRELIMINARY, SENSOR

BODY = "organism_metabolic.xml"
RESTING = {"VO2_demand": 250.0, "VO2_capacity": 1200.0,
           "lactate_base": 1.0, "lactate_k": 0.015}


@pytest.fixture
def twin():
    return load_twin("metabolic_lamina.xml")


def _standalone(supply=0.6663, **overrides):
    """The lamina on its own, with a supply index pushed in by hand."""
    t = load_twin("metabolic_lamina.xml")
    for attr, value in {**RESTING, **overrides}.items():
        t.set_sensor(attr, value)
    t.set_inter_lamina("supply_index", supply)
    t.compute_all()
    return t


def _body(cycles=0, demand=None):
    org = Organism(BODY)
    org.seed({lamina_id: SimulatedSource(t, seed=7).starting_state()
              for lamina_id, t in org.twins.items()})
    updates = {"lamina_metabolic": {"VO2_demand": demand}} if demand else None
    for _ in range(cycles):
        org.tick(updates)
    return org


def _weights(org):
    comp = org.twins["lamina_respiratory"].composites["transport_state"]
    return [float(w) for w in comp.absorption_vector]


# ══════════════════════════════════════════════════════════════════════
# The lamina stands on its own
# ══════════════════════════════════════════════════════════════════════

def test_it_loads_with_its_own_maths_registered(twin):
    from metabolic_lamina import MetabolicLamina
    assert isinstance(twin, MetabolicLamina)
    assert twin.lamina_id == "lamina_metabolic"
    assert {"lamina_circulatory", "lamina_respiratory", "lamina_metabolic"} <= {
        entry["id"] for entry in available_laminae()}


def test_what_arrives_is_declared_as_an_index_not_a_delivery(twin):
    """
    The naming decision this lamina exists to get right.  A four-attribute
    face blends its attributes into one number, so the wire carries an
    INDEX.  Measured: respiration's face sits at 0.6663 while its own DO2
    reads 988 mL/min — mapped onto DO2's range that index would arrive as
    1715.8, overstated by 74%, in an attribute labelled "oxygen delivery".
    """
    supply = twin.attributes["supply_index"]
    assert supply.source == INTER_LAMINA
    assert (supply.physio_min, supply.physio_max) == (0.0, 1.0)
    assert "not oxygen delivery" in supply.description.lower() \
        or "NOT oxygen delivery" in supply.description


def test_the_coefficients_are_declared_rather_than_buried(twin):
    """The lesson CVP taught: a constant in Python is one nobody can see."""
    for attr_id in ("lactate_base", "lactate_k", "VO2_capacity"):
        assert twin.attributes[attr_id].source == SENSOR
    import metabolic_lamina
    src = open(metabolic_lamina.__file__, encoding="utf-8").read()
    assert "= 0.015" not in src, "lactate_k must not be hard-coded"


def test_nothing_writes_corrective_signal_into_this_lamina(twin):
    """
    No <tags>, and that is a decision.  Lactate is high because supply is
    short, and nothing this lamina owns can make more supply.  A tag here
    would grind against its own clamps while the cause sat one level down.
    """
    assert twin.tags == {}


# ══════════════════════════════════════════════════════════════════════
# The elbow
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("demand,expected_vo2,expected_lactate", [
    (250.0, 250.0, 1.000),      # supply-independent: takes what it asks
    (600.0, 600.0, 1.000),      # still under the ceiling
    (1000.0, 799.6, 4.007),     # supply-dependent: capped, deficit, lactate
    (1200.0, 799.6, 7.007),     # deeper into the deficit
])
def test_consumption_is_capped_by_supply_only_past_the_elbow(
        demand, expected_vo2, expected_lactate):
    t = _standalone(VO2_demand=demand)
    assert t.get("VO2").value == pytest.approx(expected_vo2, abs=0.1)
    assert t.get("lactate").value == pytest.approx(expected_lactate, abs=0.01)


def test_below_the_elbow_there_is_no_deficit_and_no_lactate():
    t = _standalone()
    assert t.get("O2_deficit").value == pytest.approx(0.0)
    assert t.get("lactate").value == pytest.approx(1.0)
    assert t.failed_attributes == {}


def test_utilisation_reaches_one_at_the_elbow_and_says_it_is_not_o2er(twin):
    """
    It is VO2 over the CEILING, so it hits exactly 1.0 when consumption
    becomes supply-limited.  A true extraction ratio is VO2 over oxygen
    DELIVERED, and this lamina never receives a delivery — only an index.
    Naming it O2ER would put a familiar clinical label on a different
    quantity, which is the mistake `Q` carries in the circulatory lamina.
    """
    assert "O2ER" not in twin.attributes
    assert twin.attributes["O2_utilisation"].source == PRELIMINARY
    assert _standalone(VO2_demand=1000.0).get("O2_utilisation").value \
        == pytest.approx(1.0)
    assert _standalone().get("O2_utilisation").value == pytest.approx(0.3127,
                                                                     abs=1e-3)


# ══════════════════════════════════════════════════════════════════════
# Guards
# ══════════════════════════════════════════════════════════════════════

def _fn(twin, name):
    return twin._function_registry[name]


@pytest.mark.parametrize("name,args", [
    ("o2_consumption", [250.0, 0.5]),
    ("supply_utilisation", [250.0]),
    ("oxygen_deficit", []),
    ("lactate_production", [1.0, 0.015]),
])
def test_a_short_input_list_is_refused(twin, name, args):
    with pytest.raises(ValueError) as exc:
        _fn(twin, name)(args)
    assert "inputs" in str(exc.value)


@pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
def test_unusable_inputs_are_refused(twin, bad):
    with pytest.raises(ValueError):
        _fn(twin, "o2_consumption")([bad, 0.5, 1200.0])
    with pytest.raises(ValueError):
        _fn(twin, "lactate_production")([1.0, 0.015, bad])


def test_no_supply_on_offer_is_refused_rather_than_divided_by(twin):
    """
    A utilisation fraction of infinity is not a measurement, and reporting
    it would send a confident number to an outcome.
    """
    for index, capacity in ((0.0, 1200.0), (-0.1, 1200.0), (0.5, 0.0)):
        with pytest.raises(ValueError):
            _fn(twin, "supply_utilisation")([250.0, index, capacity])


def test_a_negative_demand_is_refused(twin):
    with pytest.raises(ValueError) as exc:
        _fn(twin, "o2_consumption")([-10.0, 0.5, 1200.0])
    assert "backwards" in str(exc.value)


def test_a_negative_lactate_yield_is_refused(twin):
    """It would make lactate FALL as the deficit grows — the whole
    relationship inverted, and a shocked tissue reported as improving."""
    with pytest.raises(ValueError) as exc:
        _fn(twin, "lactate_production")([1.0, -0.015, 200.0])
    assert "negative" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════
# The three-lamina body
# ══════════════════════════════════════════════════════════════════════

def test_the_body_is_a_second_file_not_a_change_to_the_default():
    ids = {o["id"]: o for o in available_organisms()}
    assert ids["bdt_default"]["default"] is True
    assert ids["bdt_metabolic"]["default"] is False
    assert ids["bdt_metabolic"]["channels"] == 2


def test_the_default_body_still_has_two_laminae_and_no_return_path():
    """The guardrail: a new mechanism arrives without moving a shipped
    number.  organism.xml keeps its frozen baseline."""
    org = Organism()
    assert set(org.twins) == {"lamina_circulatory", "lamina_respiratory"}
    assert all(channel.backprop is None for channel in org.channels)


def test_the_three_lamina_body_loads_and_passes_every_rule():
    org = _body()
    assert org.spec.lamina_ids == ["lamina_circulatory", "lamina_respiratory",
                                   "lamina_metabolic"]
    assert org.spec.levels["lamina_metabolic"] == 3
    assert [c.id for c in org.channels] == ["ch_co_to_resp",
                                            "ch_supply_to_tissue"]


def test_the_return_path_is_declared_with_the_inverted_sign():
    """
    polarity MULTIPLIES the deviation, so the default -1 is right when
    raising the source RAISES the far outcome.  Here more oxygen supply
    means LESS lactate, so the sign flips.  Getting this backwards does
    not fail loudly — it diverges quietly.
    """
    channel = [c for c in _body().channels if c.backprop][0]
    assert channel.id == "ch_supply_to_tissue"
    assert channel.backprop.outcome == "target_lactate"
    assert channel.backprop.polarity == 1.0


# ══════════════════════════════════════════════════════════════════════
# The loop, end to end
# ══════════════════════════════════════════════════════════════════════

def test_a_tissue_in_deficit_teaches_the_lamina_below_it():
    org = _body(cycles=1, demand=1000.0)
    entry = org.tick({"lamina_metabolic": {"VO2_demand": 1000.0}})["backprop"]
    report = entry["ch_supply_to_tissue"]
    assert report["state"] == "learned"
    assert report["error"] > 0.0
    assert report["delta"] == pytest.approx(
        1.0 * report["lambda"] * report["error"], abs=1e-5)
    assert _weights(org) != [0.25, 0.25, 0.25, 0.25]


def test_the_far_sides_lactate_falls_because_the_near_side_reweighed():
    """
    The headline, and the only claim that matters: does the receiving
    lamina's outcome actually get better?
    """
    org = _body(cycles=1, demand=1000.0)
    met = org.twins["lamina_metabolic"]
    first = met.get("lactate").value
    for _ in range(240):
        org.tick({"lamina_metabolic": {"VO2_demand": 1000.0}})
    last = met.get("lactate").value

    assert first == pytest.approx(6.401, abs=0.05)
    assert last == pytest.approx(2.003, abs=0.05)
    assert last < first
    assert met.get("supply_index").value > 0.77
    assert met.get("VO2").value > 930.0


def test_the_weight_moves_onto_the_attribute_that_raises_the_face():
    """
    SpO2 sits highest of the four, DO2 lowest.  Raising the face's state
    value means weighting the high one and starving the low one — and the
    low one lands on its declared clamp floor rather than going negative.
    """
    org = _body(cycles=240, demand=1000.0)
    comp = org.twins["lamina_respiratory"].composites["transport_state"]
    weights = dict(zip(comp.attribute_ids, _weights(org)))

    assert weights["SpO2"] > 0.40, "the highest attribute should gain most"
    assert weights["DO2"] == pytest.approx(0.05, abs=1e-9), "clamp floor"
    assert all(0.05 <= w <= 1.0 for w in weights.values())


def test_the_sum_of_the_weights_never_moves():
    """
    The invariant the forward pass rests on: a composite's state value is
    the inner product AᵀX only while sum(A) is what the file declared.
    """
    org = _body(cycles=1, demand=1000.0)
    for _ in range(120):
        org.tick({"lamina_metabolic": {"VO2_demand": 1000.0}})
        assert sum(_weights(org)) == pytest.approx(1.0, abs=1e-9)


def test_learning_stops_at_the_tolerance_edge_not_at_the_target():
    """
    The dead-zone is why this loop is safe to leave running inside the
    forward one.  It converges to the edge of the band the receiver
    declared acceptable and then does almost nothing.
    """
    org = _body(cycles=240, demand=1000.0)
    report = org.tick({"lamina_metabolic":
                       {"VO2_demand": 1000.0}})["backprop"]["ch_supply_to_tissue"]
    assert abs(report["error"]) < 0.01
    lactate = org.twins["lamina_metabolic"].get("lactate").value
    assert 2.0 <= lactate < 2.02, (
        f"expected the band edge (2.0), settled at {lactate}")


def test_a_tissue_inside_its_band_sends_nothing_back():
    """At rest the supply is ample, so there is no news to send."""
    org = _body(cycles=30)
    report = org.tick()["backprop"]["ch_supply_to_tissue"]
    assert org.twins["lamina_metabolic"].get("lactate").value \
        == pytest.approx(1.0, abs=0.01)
    assert report["state"] == "in tolerance"
    assert report["error"] == 0.0
    assert _weights(org) == pytest.approx([0.25, 0.25, 0.25, 0.25], abs=1e-9)


def test_every_value_stays_inside_the_range_its_file_declares():
    """
    However far the weights move, the face's state value stays in [0,1] —
    the space the channel carries and the receiver maps from.
    """
    org = _body(cycles=1, demand=1200.0)
    resp = org.twins["lamina_respiratory"]
    for _ in range(120):
        org.tick({"lamina_metabolic": {"VO2_demand": 1200.0}})
        state = resp.get_composite_state("transport_state")
        assert 0.0 <= state <= 1.0
        assert math.isfinite(org.twins["lamina_metabolic"].get("lactate").value)
