"""
Phase 1 — the schema contract for inter-lamina coupling.

Two halves, and they are separable on purpose.

`INTER_LAMINA` is a third answer to "who may write this attribute's X'".
It is not a kind of sensor: a sensor is measured, an inter-lamina value
was computed somewhere else and carried here, and collapsing the two
would make "sensor" mean "anything I did not compute" — which is the
exact distinction the coupling design rests on (G1).

`organism.xml` is the body-level declaration: which laminae, and where a
value may cross between them.  Nothing here runs a cycle.  What is under
test is that a wrong declaration fails at PARSE time, loudly, before
anything has a chance to run on it.
"""

import pytest

from feedback_controller import FeedbackController
from laminae import load_twin
from organism import (
    DEFAULT_ORGANISM,
    OrganismError,
    load_organism,
    parse_organism,
    validate_against_laminae,
)
from signal_source import SimulatedSource
from snapshot import _simulation_snapshot
from universal_twin import (
    EXTERNAL_SOURCES,
    INTER_LAMINA,
    PRELIMINARY,
    SENSOR,
    UniversalTwin,
)

RESP = "respiratory_lamina.xml"
CIRC = "circulatory_lamina.xml"


@pytest.fixture
def resp():
    """A respiratory twin resting at its declared baselines."""
    twin = load_twin(RESP)
    for attr_id in twin.list_attributes(SENSOR):
        twin.set_sensor(attr_id, twin.attributes[attr_id].baseline)
    twin.compute_all()
    return twin


# ══════════════════════════════════════════════════════════════════════
# 1a — the INTER_LAMINA source
# ══════════════════════════════════════════════════════════════════════

def test_co_ref_is_the_declared_seam(resp):
    """
    The attribute whose description has said "this is the seam" since the
    respiratory lamina was written now says it in its source too.
    """
    assert resp.attributes["CO_ref"].source == INTER_LAMINA
    assert "CO_ref" not in resp.list_attributes(SENSOR)
    assert "CO_ref" not in resp.list_attributes(PRELIMINARY)
    assert "CO_ref" in resp.list_attributes(INTER_LAMINA)


def test_an_uncoupled_seam_rests_at_its_declared_baseline(resp):
    """
    G9.  Nothing is coupled to CO_ref yet, and nothing else will seed it —
    so without this the whole chain below the seam would go dark the
    moment the attribute stopped being a sensor, and a lamina running
    standalone would visibly regress for a change meant to leave it
    exactly where it was.
    """
    co = resp.attributes["CO_ref"]
    assert co.value == co.baseline == 5.0
    assert co.provenance is None
    # …and the chain below it computes rather than going stale.
    assert resp.attributes["DO2"].value == pytest.approx(988.42, abs=0.5)
    assert "CO_ref" not in resp.failed_attributes
    assert "DO2" not in resp.failed_attributes


def test_the_snapshot_says_the_seam_is_uncoupled(resp):
    """
    A placeholder baseline and a live coupled value are the same number.
    The same failure mode as a stale computed value looking live, one
    layer up, and it gets the same answer: the payload says which.
    """
    snap = _simulation_snapshot(resp)
    assert "CO_ref" not in snap["sensors"], "an inbound value is not a reading"
    entry = snap["inbound"]["CO_ref"]
    assert entry["value"] == 5.0
    assert entry["provenance"] == {
        "state": "uncoupled",
        "detail": "baseline (uncoupled)",
    }


def test_set_sensor_refuses_the_seam_and_points_at_the_right_door(resp):
    with pytest.raises(ValueError, match="INTER_LAMINA"):
        resp.set_sensor("CO_ref", 6.0)


def test_set_inter_lamina_refuses_everything_else(resp):
    """Symmetric with set_sensor: one door each, and neither opens the other."""
    with pytest.raises(ValueError, match="SENSOR"):
        resp.set_inter_lamina("RR", 12.0)
    with pytest.raises(ValueError, match="PRELIMINARY"):
        resp.set_inter_lamina("DO2", 900.0)
    with pytest.raises(KeyError):
        resp.set_inter_lamina("NOT_AN_ATTRIBUTE", 1.0)


def test_a_coupled_value_arrives_with_its_provenance(resp):
    before = resp.attributes["DO2"].value
    resp.set_inter_lamina(
        "CO_ref", 6.5,
        provenance={"gate": "pg_co_to_resp", "from": "lamina_circulatory"},
    )
    resp.compute_all()

    assert resp.attributes["CO_ref"].value == 6.5
    assert resp.attributes["DO2"].value > before, "the chain should follow it"

    entry = _simulation_snapshot(resp)["inbound"]["CO_ref"]
    assert entry["provenance"]["state"] == "coupled"
    assert entry["provenance"]["gate"] == "pg_co_to_resp"
    assert entry["provenance"]["from"] == "lamina_circulatory"


def test_the_synthetic_feed_does_not_invent_the_seam(resp):
    """
    A simulated feed emits readings.  An inter-lamina value is not a
    reading, and jittering one would be inventing a measurement error for
    a number that is not a measurement.  The filter is already right —
    SimulatedSource reads list_attributes("SENSOR") — and this pins it.
    """
    source = SimulatedSource(resp, seed=1)
    assert "CO_ref" not in source.next()
    assert "CO_ref" not in source.starting_state()
    assert "CO_ref" not in source.describe()


def test_the_feedback_loop_leaves_an_inbound_value_alone(resp):
    """
    G1 / D12.  An inter-lamina value is another lamina's ground truth, and
    this lamina's internal loop has no more standing to correct it than it
    has to correct a thermometer.

    The situation has to be BUILT: no composite in either shipped lamina
    holds an INTER_LAMINA attribute today, so `transport_state` is given
    CO_ref here rather than in the XML.  Adding it there would be a change
    to the model — new distribution weights, a different fan-out for
    DO2_DEVIATION — and this is a test of the engine, not a proposal about
    physiology.  The rule guards nothing in the laminae as they ship, and
    it has to be correct before the first gate makes it matter.
    """
    transport = resp.composites["transport_state"]
    assert "CO_ref" not in transport.attribute_ids, (
        "a lamina now ships an inbound attribute inside a composite — this "
        "test should stop constructing the case and use the real one"
    )
    transport.attribute_ids = [*transport.attribute_ids, "CO_ref"]

    resp.set_sensor("Hb", 8.0)          # anaemia — DO2 falls well below target
    resp.compute_all()

    fc = FeedbackController(resp)
    for _ in range(15):
        fc.step()

    assert resp.attributes["CO_ref"].value_feedback == 0.0, \
        "the loop wrote X'' onto another lamina's value"
    assert resp.attributes["CO_ref"].value == 5.0, "and so left it where it was"
    assert resp.attributes["CaO2"].value_feedback != 0.0, \
        "the tag should still drive the attributes it may drive"


def test_nothing_but_a_computed_attribute_ever_receives_x_pp(resp):
    """
    The invariant behind the previous test, checked over every attribute
    of a disturbed lamina rather than the one the case was built around.

    The old rule was "skip SENSOR", which lets everything else through, so
    a source added later is writable by default and the failure is silent.
    Asking for PRELIMINARY inverts the default: a new source is read-only
    until somebody decides otherwise.
    """
    resp.set_sensor("Hb", 8.0)
    resp.set_sensor("RR", 7.0)
    resp.compute_all()

    fc = FeedbackController(resp)
    touched: set = set()
    for _ in range(15):
        report = fc.step()
        touched |= {a for a, d in report["deltas_per_attr"].items() if d}

    assert touched, "the loop should have done something to disturb"
    for attr_id in touched:
        assert resp.attributes[attr_id].source == PRELIMINARY, (
            f"the loop wrote X'' onto {attr_id}, declared "
            f"{resp.attributes[attr_id].source}"
        )


def test_an_unknown_source_does_not_parse(tmp_path):
    """
    An unrecognised source used to fall through as "not PRELIMINARY",
    which is now the branch an inter-lamina attribute takes — so a typo
    would quietly become an input nobody feeds, resting on whatever it
    was declared with.
    """
    src = tmp_path / "typo.xml"
    src.write_text(_MINIMAL_LAMINA.replace(
        "<source>SENSOR</source>", "<source>SENSER</source>"
    ), encoding="utf-8")

    with pytest.raises(ValueError, match="Legal sources"):
        UniversalTwin(str(src))


def test_external_sources_are_the_two_that_arrive_from_outside():
    assert EXTERNAL_SOURCES == {SENSOR, INTER_LAMINA}
    assert PRELIMINARY not in EXTERNAL_SOURCES


# ══════════════════════════════════════════════════════════════════════
# 1b — organism.xml parses into something usable
# ══════════════════════════════════════════════════════════════════════

def test_the_shipped_organism_loads_and_passes_every_rule():
    spec, twins = load_organism()
    assert spec.id == "bdt_default"
    assert spec.lamina_ids == ["lamina_circulatory", "lamina_respiratory"]
    assert set(twins) == set(spec.lamina_ids)

    assert spec.levels == {"lamina_circulatory": 1, "lamina_respiratory": 2}

    channel = spec.channels[0]
    assert channel.id == "ch_co_to_resp"
    assert (channel.source.lamina, channel.source.member) == \
        ("lamina_circulatory", "output_state")
    assert (channel.dest.lamina, channel.dest.member) == \
        ("lamina_respiratory", "CO_ref")
    assert channel.carry == "state"
    # The sender decides whether to offer; the receiver decides whether
    # to take, and holds the terms it absorbs on.
    assert channel.transmit[0].id == "ta_pump_deviation"
    assert channel.transmit[0].trigger_kind == "threshold"
    assert channel.receive[0].id == "rk_co"
    assert channel.receive[0].rate == 0.2
    assert channel.receive[0].on_close == "hold"


def test_the_two_halves_of_the_seam_agree():
    """
    organism.xml says CO_ref is where lamina_circulatory's CO attaches;
    respiratory_lamina.xml says CO_ref is INTER_LAMINA.  Neither file can
    state the coupling alone, and this is the assertion that they are
    talking about the same thing.
    """
    spec, twins = load_organism()
    channel = spec.channels[0]
    dest = twins[channel.dest.lamina].attributes[channel.dest.member]
    assert dest.source == INTER_LAMINA
    source_comp = twins[channel.source.lamina].composites[channel.source.member]
    # No attribute name is asserted, because there is no longer one to
    # assert: what crosses is the composite's own state value. What the
    # two files have to agree about is that the source composite has
    # something to summarise and the destination has room to land it.
    assert source_comp.attribute_ids
    assert dest.physio_max > dest.physio_min


def test_channels_are_indexable_by_which_lamina_they_touch():
    spec = parse_organism()
    assert [c.id for c in spec.channels_into("lamina_respiratory")] == \
        ["ch_co_to_resp"]
    assert [c.id for c in spec.channels_out_of("lamina_circulatory")] == \
        ["ch_co_to_resp"]
    assert spec.channels_into("lamina_circulatory") == []


def test_gates_are_indexable_by_the_lamina_whose_membrane_they_sit_on():
    """
    A gate belongs to the lamina it is ON — the transmit side of a
    channel leaving it, the receive side of one arriving at it.  That is
    the ownership the two-sided design exists to make explicit, and the
    two faces rule 8 counts separately.
    """
    spec = parse_organism()
    assert [g.id for g in spec.gates_on("lamina_circulatory")] == \
        ["ta_pump_deviation"]
    assert [g.id for g in spec.gates_on("lamina_respiratory")] == ["rk_co"]


# ══════════════════════════════════════════════════════════════════════
# 1c — the five rules, each one refused at parse time
# ══════════════════════════════════════════════════════════════════════

def _organism(tmp_path, old: str, new: str):
    """
    The shipped organism with one substring swapped, written to a temp file.

    Every rule test below breaks the REAL declaration in one specific way,
    rather than building a fixture organism from scratch.  A fixture drifts
    away from the file that ships and then tests a document nobody reads;
    this cannot, and the assertion below fails loudly if the text it edits
    ever moves.
    """
    text = DEFAULT_ORGANISM.read_text(encoding="utf-8")
    assert old in text, f"organism.xml drifted: {old!r} not found"
    path = tmp_path / "organism.xml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def _twins_for(spec):
    """One twin per lamina the spec lists, by id."""
    return {
        lid: load_twin(f"{lid.replace('lamina_', '')}_lamina.xml")
        for lid in spec.lamina_ids
    }


#: The one line of the shipped gate the learnable tests hang things off.
_EXTRACT = '<extract mode="state"/>'


def test_rule_1_a_gate_cannot_be_declared_open():
    """
    G6.  Closed is the stable state — a pressure-cooker valve is shut and
    opens on condition.  The enforcement is that there is no attribute to
    write: `starts_closed` is a property with no setter and no XML behind
    it, so "born open" is not a thing anyone can express.
    """
    spec = parse_organism()
    gates = [g for c in spec.channels for g in (*c.transmit, *c.receive)]
    assert gates
    for gate in gates:
        assert not hasattr(gate, "initial_open")
        assert not hasattr(gate, "starts_open")


def test_rule_2_the_source_must_be_a_composite(tmp_path):
    path = _organism(tmp_path,
                     'from="lamina_circulatory:output_state"',
                     'from="lamina_circulatory:CO"')
    spec = parse_organism(path)
    twins = _twins_for(spec)
    with pytest.raises(OrganismError, match="not a composite"):
        validate_against_laminae(spec, twins)


def test_rule_2_names_the_composite_when_you_named_an_attribute(tmp_path):
    """A wrong declaration should say what the right one looks like."""
    path = _organism(tmp_path,
                     'from="lamina_circulatory:output_state"',
                     'from="lamina_circulatory:CO"')
    spec = parse_organism(path)
    twins = _twins_for(spec)
    with pytest.raises(OrganismError, match="<extract>"):
        validate_against_laminae(spec, twins)


@pytest.mark.parametrize("target, expected_source", [
    ("lamina_respiratory:RR", "SENSOR"),
    ("lamina_respiratory:DO2", "PRELIMINARY"),
])
def test_rule_3_the_destination_must_be_declared_inter_lamina(
        tmp_path, target, expected_source):
    """
    Writing another lamina's SENSOR forges a measurement; writing its
    PRELIMINARY overwrites something it computes for itself.
    """
    path = _organism(tmp_path,
                     'to="lamina_respiratory:CO_ref"',
                     f'to="{target}"')
    spec = parse_organism(path)
    twins = _twins_for(spec)
    with pytest.raises(OrganismError, match=expected_source):
        validate_against_laminae(spec, twins)


def test_rule_4_one_threshold_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     'close_below="0.09"',
                     '')
    with pytest.raises(OrganismError, match="open_above and close_below"):
        parse_organism(path)


def test_rule_4_the_band_must_be_the_right_way_round(tmp_path):
    path = _organism(tmp_path,
                     'close_below="0.09"',
                     'close_below="0.20"')
    with pytest.raises(OrganismError, match="not below open_above"):
        parse_organism(path)


#: The receiving gate's key — the anchor the learnable tests hang off.
#: A <learnable> belongs INSIDE a gate in v2, because the parameter it
#: names (a weight, a threshold) is the gate's and not the channel's.
_KEY = '<key metric="identity"/>'


def _with_learnable(tmp_path, declaration: str):
    """The shipped receive gate, plus one <learnable> however spelled."""
    return _organism(tmp_path, _KEY, f"{_KEY}\n          {declaration}")


def test_rule_5_a_learnable_without_a_clamp_does_not_parse(tmp_path):
    path = _with_learnable(tmp_path, '<learnable name="match_threshold" />')
    with pytest.raises(OrganismError, match="clamp"):
        parse_organism(path)


def test_rule_5_half_a_clamp_is_not_a_clamp(tmp_path):
    path = _with_learnable(
        tmp_path, '<learnable name="match_threshold" min="0.5" />')
    with pytest.raises(OrganismError, match="declares no max"):
        parse_organism(path)


def test_rule_5_a_clamped_learnable_parses(tmp_path):
    path = _with_learnable(
        tmp_path,
        '<learnable name="match_threshold" min="0.5" max="0.99" initial="0.9" />')
    gate = parse_organism(path).channels[0].receive[0]
    assert len(gate.learnables) == 1
    assert (gate.learnables[0].min, gate.learnables[0].max) == (0.5, 0.99)
    assert gate.learnables[0].initial == 0.9


def test_rule_5_a_learnable_cannot_start_outside_its_own_clamp(tmp_path):
    path = _with_learnable(
        tmp_path,
        '<learnable name="match_threshold" min="0.5" max="0.9" initial="2.0" />')
    with pytest.raises(OrganismError, match="outside its own clamp"):
        parse_organism(path)


# ── The vocabulary checks that stop a silent no-op ────────────────────

def test_an_unknown_trigger_does_not_parse(tmp_path):
    """
    An unrecognised element inside a gate is refused rather than
    ignored. Ignoring it leaves a gate whose declared condition nobody
    evaluates — which runs, and quietly means something other than what
    the file says.
    """
    path = _organism(tmp_path, '<threshold ', '<telepathy ')
    with pytest.raises(OrganismError, match="telepathy"):
        parse_organism(path)


def test_a_channel_from_a_lamina_to_itself_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     'to="lamina_respiratory:CO_ref"',
                     'to="lamina_circulatory:CO_ref"')
    with pytest.raises(OrganismError, match="to itself"):
        parse_organism(path)


def test_an_endpoint_without_a_lamina_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     'from="lamina_circulatory:output_state"',
                     'from="pump_state"')
    with pytest.raises(OrganismError, match="<lamina_id>"):
        parse_organism(path)


def test_a_gate_naming_an_unlisted_lamina_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     'to="lamina_respiratory:CO_ref"',
                     'to="lamina_renal:CO_ref"')
    with pytest.raises(OrganismError, match="does not list"):
        parse_organism(path)


def test_an_absorption_rate_outside_zero_to_one_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     'rate="0.2"',
                     'rate="1.8"')
    with pytest.raises(OrganismError, match=r"outside \[0,1\]"):
        parse_organism(path)


def test_a_channel_may_not_pick_an_attribute_out_of_the_composite(tmp_path):
    """
    The payload rule, refused at parse rather than quietly reinterpreted.

    A body written against the old schema names the attribute it wants on
    the wire. Reading that as "carry the composite instead" would run and
    mean something other than it says, so it is an error, and the message
    says what to write in its place.
    """
    with pytest.raises(OrganismError, match="no longer carries an attribute"):
        parse_organism(_organism(tmp_path, _EXTRACT,
                                 '<extract attribute="CO"/>'))


# A lamina small enough to read at a glance, for the source-parsing tests.
_MINIMAL_LAMINA = """<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_minimal" name="Minimal" level="0">
  <attributes>
    <attribute id="a_one">
      <name>One</name>
      <unit>u</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min>
      <physio_max>10</physio_max>
      <baseline>5</baseline>
    </attribute>
  </attributes>
</lamina>
"""


# ══════════════════════════════════════════════════════════════════════
# Rule 6 — one seam, one gate
# ══════════════════════════════════════════════════════════════════════

def test_rule_6_two_gates_cannot_feed_one_attribute(tmp_path):
    """
    Measured before it was written, which is why the rule exists.

    Two gates declared onto the same attribute both parsed, both reported
    a `transmitted` value as though they had carried it, and the one
    declared LAST silently won: gate one reported sending 6.64 while the
    attribute held 7.95 from gate two. Every reader downstream — the tick
    report and the body diagram included — then attributes a number to a
    gate that did not put it there.
    """
    text = DEFAULT_ORGANISM.read_text(encoding="utf-8")
    start = text.index("<channel id=")
    end = text.index("</channel>") + len("</channel>")
    one = text[start:end]
    two = (one.replace('id="ch_co_to_resp"', 'id="ch_rival"')
              .replace('id="ta_pump_deviation"', 'id="ta_rival"')
              .replace('id="rk_co"', 'id="rk_rival"'))

    path = tmp_path / "two_channels.xml"
    path.write_text(text.replace(one, one + "\n" + two), encoding="utf-8")

    with pytest.raises(OrganismError, match="already feeds"):
        parse_organism(path)


def test_rule_6_leaves_two_gates_out_of_one_lamina_alone(tmp_path):
    """
    The rule is about the DESTINATION, not the source.

    One lamina sending to several places is ordinary — that is what a
    composite feeding two downstream systems looks like. It is only the
    receiving end that cannot be shared, because that is the end where
    two writers overwrite each other.
    """
    text = DEFAULT_ORGANISM.read_text(encoding="utf-8")
    start = text.index("<channel id=")
    end = text.index("</channel>") + len("</channel>")
    one = text[start:end]
    # Same source composite (rule 9 requires it), a destination that
    # exists but is not INTER_LAMINA — so if it gets past rule 6 it
    # fails on rule 3 instead, which is the proof it got past.
    two = (one.replace('id="ch_co_to_resp"', 'id="ch_elsewhere"')
              .replace('id="ta_pump_deviation"', 'id="ta_elsewhere"')
              .replace('id="rk_co"', 'id="rk_elsewhere"')
              .replace('to="lamina_respiratory:CO_ref"',
                       'to="lamina_respiratory:PaO2"'))

    path = tmp_path / "two_destinations.xml"
    path.write_text(text.replace(one, one + "\n" + two), encoding="utf-8")

    spec = parse_organism(path)          # rule 6 does not object
    assert [c.id for c in spec.channels] == ["ch_co_to_resp", "ch_elsewhere"]
    with pytest.raises(OrganismError, match="INTER_LAMINA"):
        validate_against_laminae(spec, _twins_for(spec))
