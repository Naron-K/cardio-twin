"""
The backward pass — what a lamina learns from the far side of a seam.

The forward direction has been settled since the gate channels landed: a
composite absorbs its attributes into ONE state value, and that value
crosses when both membranes open.  This is the other half of the same
sentence.  The number crossed, the receiving lamina's outcome came out
wrong, and the only question left is whether the sender should have sent
a different one.

    delta = polarity * lambda_gate * E

E is the receiver's outcome error normalised into tolerances; lambda is
the openness the FORWARD pass actually used this cycle.  That is the
whole mechanism, and what it does NOT do is the point:

  NO TRANSPOSED MATRIX, NO CHAIN RULE.  The error is one scalar, the
  gate is one scalar, and their product is one scalar the sending
  composite learns on.  A body of ten laminae routes error exactly the
  way a body of two does, and nothing in organism.py changes shape.

  ERROR IS PAYLOAD, AND PAYLOAD OBEYS GATES.  A shut gate returns
  nothing; a half-open gate returns half.  The return path can never be
  wider than the path the value took, which is what keeps the backward
  direction inside the architecture instead of beside it.

  IT STOPS.  Inside the tolerance the receiver declared there is no
  news, so nothing is sent back.  Same dead-zone as the local loop, and
  literally the same function computing it.

The bodies here are built from two purpose-written laminae of plain
sensors, because the shipped seam cannot carry a return path at all —
its face composite holds one attribute, and a one-attribute composite's
state IS that attribute whatever its weight.  That is tested too.
"""
import pytest

import organism as organism_module
from organism import Organism, OrganismError
from universal_twin import UniversalTwin

# ══════════════════════════════════════════════════════════════════════
# Two laminae, built for this and nothing else
# ══════════════════════════════════════════════════════════════════════

# The sender.  Three sensors, one face, and a wide-tolerance outcome of
# its own so the LOCAL learning loop never fires and every weight
# movement in these tests is one the channel caused.
_UP = """<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_up" name="Up" level="1">
  <attributes>
    <attribute id="a"><name>A</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline></attribute>
    <attribute id="b"><name>B</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline></attribute>
    <attribute id="c"><name>C</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline></attribute>
  </attributes>
  <composites>
    <composite id="face_up">
      <name>Face Up</name>
      <attributes>a, b, c</attributes>
      <absorption_vector {learning}>
        <weight attribute="a">0.3333333333333333</weight>
        <weight attribute="b">0.3333333333333333</weight>
        <weight attribute="c">0.3333333333333334</weight>
      </absorption_vector>
    </composite>
    <composite id="solo_up">
      <name>Solo Up</name>
      <attributes>a</attributes>
      <absorption_vector learns_from="target_a" learning_rate="0.1"
                         clamp_min="0.0" clamp_max="1.0">
        <weight attribute="a">1.0</weight>
      </absorption_vector>
    </composite>
  </composites>
  <segments>
    <segment id="seg_up" name="Up">
      <attributes>a, b, c</attributes>
      <composites>face_up, solo_up</composites>
      <behavioural_outcomes>
        <outcome id="target_a" attribute="a" target="5" tolerance="1000"
                 name="Target A" unit="u"/>
      </behavioural_outcomes>
    </segment>
  </segments>
</lamina>
"""

_LEARNS = ('learns_from="target_a" learning_rate="{rate}" '
           'clamp_min="0.0" clamp_max="1.0"')

# The receiver.  One place for somebody else's number to attach, and one
# outcome on it — so the error travelling back is exactly the error the
# crossing caused.
_DOWN = """<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_down" name="Down" level="2">
  <attributes>
    <attribute id="inbound"><name>Inbound</name><unit>u</unit>
      <source>INTER_LAMINA</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline></attribute>
  </attributes>
  <composites>
    <composite id="face_down">
      <name>Face Down</name>
      <attributes>inbound</attributes>
      <absorption_vector>
        <weight attribute="inbound">1.0</weight>
      </absorption_vector>
    </composite>
  </composites>
  <segments>
    <segment id="seg_down" name="Down">
      <attributes>inbound</attributes>
      <composites>face_down</composites>
      <behavioural_outcomes>
        <outcome id="target_inbound" attribute="inbound"
                 target="{target}" tolerance="{tol}"
                 name="Target Inbound" unit="u"/>
      </behavioural_outcomes>
    </segment>
  </segments>
  {tags}
</lamina>
"""

# A feedback loop on the RECEIVING lamina, so `inbound` moves between
# the gate pass and the back pass.  Only the ordering test needs it.
_DOWN_TAGS = """
  <tags>
    <tag id="INBOUND_DEVIATION" outcome="target_inbound"
         deviation_type="absolute" emitter="binary"
         gate_kernel="sigmoid_leaky_tanh" polarity="negative">
      <targets><target address="face_down" weight="1.0"/></targets>
      <params gain="0.6" decay="0.10" threshold_k="4.0"
              saturation="0.3" epsilon_ratio="0.001"/>
    </tag>
  </tags>
"""

_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<organism id="bdt_backprop" version="2.0">
  <name>Backprop test body</name>
  <laminae>
    <lamina id="lamina_up" level="1"/>
    <lamina id="lamina_down" level="2"/>
  </laminae>
  <channels>
    <channel id="ch_back" from="lamina_up:{source}"
             to="lamina_down:inbound" time_delay="0">
      <extract mode="state"/>
      <transmit>
        <auto_gate id="tx_b" refractory_cycles="0">
          <threshold aggregate="state" open_above="0.01" close_below="0.005"/>
        </auto_gate>
      </transmit>
      <receive>
        <key_gate id="rx_b" weight="{rx_weight}" rate="1.0"
                  on_close="hold" confidence="1.0">
          <key metric="identity"/>
        </key_gate>
      </receive>
      {backprop}
    </channel>
  </channels>
</organism>
"""


def _write_body(tmp_path, monkeypatch, backprop, source, target, tol,
                learning, rx_weight, tags):
    up = tmp_path / "up_lamina.xml"
    up.write_text(_UP.format(learning=learning), encoding="utf-8")
    down = tmp_path / "down_lamina.xml"
    down.write_text(_DOWN.format(target=target, tol=tol, tags=tags),
                    encoding="utf-8")
    body = tmp_path / "organism.xml"
    body.write_text(_BODY.format(source=source, backprop=backprop,
                                 rx_weight=rx_weight),
                    encoding="utf-8")
    files = {"lamina_up": up, "lamina_down": down}
    # Redirected rather than the files being dropped into the package
    # directory, because a test that writes a lamina next to the shipped
    # ones changes what every OTHER test can see.
    monkeypatch.setattr(organism_module, "resolve_lamina",
                        lambda lid: files[lid])
    monkeypatch.setattr(organism_module, "load_twin",
                        lambda path: UniversalTwin(str(path)))
    return body


@pytest.fixture
def make_body(tmp_path, monkeypatch):
    """An organism built from the two laminae above."""
    def build(backprop='<backprop from="target_inbound"/>',
              source="face_up", target=5.0, tol=0.5, rate=0.1,
              open_fraction=None, learning=None, rx_weight=1.0,
              tags=""):
        path = _write_body(
            tmp_path, monkeypatch, backprop, source, target, tol,
            _LEARNS.format(rate=rate) if learning is None else learning,
            rx_weight, tags)
        org = Organism(path)
        if open_fraction is not None:
            org.register_gate_controller(
                "threshold",
                lambda state, reading, params: {"open_fraction": open_fraction},
            )
        org.seed({"lamina_up": {"a": 2.0, "b": 5.0, "c": 8.0}})
        return org
    return build


def _weights(org):
    return [float(w) for w in
            org.twins["lamina_up"].composites["face_up"].absorption_vector]


# ══════════════════════════════════════════════════════════════════════
# The declaration
# ══════════════════════════════════════════════════════════════════════

def test_a_channel_without_a_backprop_is_one_way(make_body):
    """Absent means absent: the sender never hears anything back."""
    org = make_body(backprop="")
    assert org.channels[0].backprop is None
    assert org.tick()["backprop"] == {}


def test_a_backprop_is_read_whole(make_body):
    org = make_body(backprop='<backprop from="target_inbound" polarity="1"/>')
    bp = org.channels[0].backprop
    assert bp.outcome == "target_inbound"
    assert bp.polarity == 1.0


def test_polarity_defaults_to_corrective(make_body):
    """
    -1 is the default here for the same reason it is the default on a
    tag: it MULTIPLIES the deviation, so it is the sign that turns "the
    far outcome is BELOW target" into "send more", which is the coupling
    almost every seam has.
    """
    assert make_body().channels[0].backprop.polarity == -1.0


def test_a_return_path_with_nothing_to_carry_is_refused(make_body):
    with pytest.raises(OrganismError) as exc:
        make_body(backprop="<backprop/>")
    assert "has to name the outcome" in str(exc.value)


def test_a_return_path_may_not_name_an_attribute(make_body):
    """
    Rule 13 holds in both directions. A return path that could name an
    attribute would let the far side reach past the face into the
    machinery behind it — the exact coupling the face exists to stop.
    """
    with pytest.raises(OrganismError) as exc:
        make_body(backprop='<backprop from="target_inbound" attribute="a"/>')
    assert "rule 13" in str(exc.value)


def test_an_unreadable_polarity_fails_loudly(make_body):
    with pytest.raises(OrganismError) as exc:
        make_body(
            backprop='<backprop from="target_inbound" polarity="sideways"/>')
    assert "polarity" in str(exc.value)


def test_an_outcome_the_far_side_never_declared_is_refused(make_body):
    with pytest.raises(OrganismError) as exc:
        make_body(backprop='<backprop from="target_nothing"/>')
    assert "declares no such outcome" in str(exc.value)
    assert "target_inbound" in str(exc.value)


def test_teaching_weights_that_may_not_move_is_refused(make_body):
    """
    Rule 5 reaches the return path: anything that may learn declares its
    clamp first. A wire into weights that are pinned is a wire to
    nowhere, and it looks exactly like one that works.
    """
    with pytest.raises(OrganismError) as exc:
        make_body(learning="")
    assert "declares no learning rule" in str(exc.value)


def test_a_one_attribute_face_cannot_be_taught_and_says_so(make_body):
    """
    The case the SHIPPED body is in, and the reason it carries no
    <backprop> yet.  A composite's state value is the weighted mean of
    its attributes, so with one attribute the state is that attribute
    whatever its weight: every learning step is exactly zero.  Refusing
    beats a return path that runs forever and moves nothing.
    """
    with pytest.raises(OrganismError) as exc:
        make_body(source="solo_up")
    assert "one attribute" in str(exc.value)
    assert "nothing for a learning step to reweigh" in str(exc.value)


def test_the_shipped_face_is_the_one_attribute_case():
    """The claim above, checked against the body that actually ships."""
    org = Organism()
    face = org.twins["lamina_circulatory"].composites["output_state"]
    assert face.attribute_ids == ["CO"]
    assert all(ch.backprop is None for ch in org.channels)


# ══════════════════════════════════════════════════════════════════════
# delta = polarity * lambda * E
# ══════════════════════════════════════════════════════════════════════

def test_an_error_inside_the_receivers_tolerance_sends_nothing_back(make_body):
    """
    The dead-zone, and it is the same one the local loop uses because it
    is the same function.  Inside the band the receiver declared
    acceptable there is no news to send.
    """
    org = make_body(target=5.0, tol=9.0)
    before = _weights(org)
    entry = org.tick()["backprop"]["ch_back"]
    assert entry["state"] == "in tolerance"
    assert entry["error"] == 0.0
    assert _weights(org) == before


def test_a_shut_gate_returns_no_error(make_body):
    """
    Error is payload and payload obeys gates. Nothing the sender did
    reached this outcome, so the sender has nothing to answer for.
    """
    org = make_body(target=1.0, tol=0.1, open_fraction=0.0)
    before = _weights(org)
    entry = org.tick()["backprop"]["ch_back"]
    assert entry["state"] == "shut"
    assert entry["lambda"] == 0.0
    assert _weights(org) == before


def test_the_step_is_exactly_polarity_times_lambda_times_error(make_body):
    """
    Recomputed here from the three declared numbers rather than read off
    the report, because the report is the thing under test.
    """
    org = make_body(target=1.0, tol=0.5)
    entry = org.tick()["backprop"]["ch_back"]
    assert entry["state"] == "learned"

    actual = org.twins["lamina_down"].get("inbound").value
    deviation = actual - 1.0
    assert deviation > 0.5, "the fixture is meant to land out of band"
    expected_error = (abs(deviation) - 0.5) / 0.5
    assert entry["error"] == pytest.approx(expected_error, abs=1e-5)
    assert entry["delta"] == pytest.approx(
        -1.0 * entry["lambda"] * entry["error"], abs=1e-5)


def test_a_half_open_gate_returns_half_the_error(make_body):
    """
    The return path is never wider than the path the value took, and
    "never wider" is arithmetic here rather than a promise: lambda is
    the number the forward pass actually used, and it MULTIPLIES the
    error rather than merely being reported beside it.

    The second assertion is the one that matters.  Without it a version
    that computed delta = polarity * error and only reported lambda
    passes every other test in this file, because everywhere else the
    gate happens to be wide open — measured, by making exactly that
    change and watching 21 tests stay green.
    """
    full = make_body(target=1.0, tol=0.5, open_fraction=1.0)
    half = make_body(target=1.0, tol=0.5, open_fraction=0.5)
    e_full = full.tick()["backprop"]["ch_back"]
    e_half = half.tick()["backprop"]["ch_back"]
    assert e_full["lambda"] == pytest.approx(1.0)
    assert e_half["lambda"] == pytest.approx(0.5)

    assert e_full["delta"] == pytest.approx(-1.0 * e_full["error"], abs=1e-5)
    assert e_half["delta"] == pytest.approx(-0.5 * e_half["error"], abs=1e-5)
    assert abs(e_half["delta"]) < abs(e_half["error"]), (
        "a half-open gate has to shrink the step, not just report a "
        "fraction beside it"
    )


def test_a_partial_receive_weight_narrows_the_return_path_too(make_body):
    """
    lambda is both gates AND both weights:

        lambda = (tx_open * rx_open) * tx_weight * rx_weight

    Both halves belong in it because both decided how much of the
    sender's number actually reached the outcome that is now sending an
    error back.  A receptor taking half the deviation is half as
    entitled to blame the sender for what it did with it.
    """
    org = make_body(target=1.0, tol=0.5, open_fraction=0.5, rx_weight=0.5)
    entry = org.tick()["backprop"]["ch_back"]
    assert org.channels[0].receive[0].weight == 0.5
    # tx_open 0.5 * rx_open 1.0 * tx_weight 1.0 * rx_weight 0.5
    assert entry["lambda"] == pytest.approx(0.25, abs=1e-9)
    assert entry["delta"] == pytest.approx(-0.25 * entry["error"], abs=1e-6)


def test_the_body_breaker_shuts_the_return_path_too(make_body):
    """
    A body whose coupling has run away stops teaching across it. The
    laminae keep running on their own — same rule as the forward pass.
    """
    org = make_body(target=1.0, tol=0.5)
    org.gates_locked = True
    before = _weights(org)
    entry = org.tick()["backprop"]["ch_back"]
    assert entry["state"] == "breaker"
    assert _weights(org) == before


# ══════════════════════════════════════════════════════════════════════
# What it does over time
# ══════════════════════════════════════════════════════════════════════

def test_an_out_of_band_receiver_moves_the_senders_weights(make_body):
    org = make_body(target=1.0, tol=0.5)
    before = _weights(org)
    entry = org.tick()["backprop"]["ch_back"]
    assert entry["state"] == "learned"
    assert _weights(org) != before
    assert entry["weights"] == pytest.approx(_weights(org))


def test_the_sender_reweighs_toward_what_the_receiver_asked_for(make_body):
    """
    The loop, end to end and in the only terms that matter: does the far
    side's error get SMALLER?

    a=2, b=5, c=8 on a 0-10 range, so the face starts at 0.5 and the
    receiver is handed 5.0 against a target of 1.0.  It is far too high,
    the error comes back, and the sender has exactly one way to answer:
    shift weight onto the attribute sitting lowest.
    """
    org = make_body(target=1.0, tol=0.5, rate=0.2)
    first = org.tick()["backprop"]["ch_back"]["error"]
    for _ in range(60):
        org.tick()
    last = org.tick()["backprop"]["ch_back"]["error"]

    assert last < first, "the receiver's error has to shrink"
    a, b, c = _weights(org)
    assert a > c, ("weight has to move onto the LOW attribute — that is "
                   "the only way this composite can lower its state")
    assert org.twins["lamina_down"].get("inbound").value < 5.0


def test_learning_stops_when_the_receiver_comes_back_into_band(make_body):
    """
    It converges and then it stops, which is the property that makes it
    safe to run inside the forward loop it is coupled to.
    """
    org = make_body(target=3.0, tol=0.4, rate=0.3)
    states = [org.tick()["backprop"]["ch_back"]["state"] for _ in range(120)]
    assert "learned" in states
    assert states[-1] == "in tolerance", (
        f"expected the loop to settle, ended {states[-8:]}")


def test_the_weights_stay_inside_the_declared_band(make_body):
    """
    The clamp is the whole reason this loop is allowed to run inside
    another one, and the return path does not get an exemption.
    """
    org = make_body(target=0.0, tol=0.01, rate=5.0)
    for _ in range(80):
        org.tick()
    assert all(0.0 <= w <= 1.0 for w in _weights(org))


def test_the_sum_of_the_weights_survives_the_return_path(make_body):
    """
    The invariant the whole forward pass rests on: a composite's state
    value is the inner product A.X only while sum(A) is what the file
    declared.  A backward pass that quietly changed it would make the
    two disagree about which way the composite is moving.
    """
    org = make_body(target=1.0, tol=0.5, rate=0.3)
    for _ in range(40):
        org.tick()
    assert sum(_weights(org)) == pytest.approx(1.0, abs=1e-9)


def test_the_face_still_summarises_itself_inside_the_wire_range(make_body):
    """
    Whatever the return path does to the weights, the state value stays
    in [0,1] — the space the channel carries and the receiver maps from.
    """
    org = make_body(target=0.0, tol=0.01, rate=5.0)
    for _ in range(80):
        org.tick()
        state = org.twins["lamina_up"].get_composite_state("face_up")
        assert 0.0 <= state <= 1.0


def test_the_back_pass_runs_after_every_lamina_has_stepped(make_body):
    """
    Why the back pass is step 5 and not a tail on step 3.

    An outcome is not evaluated until its lamina's own feedback cycle
    has run, so a back pass folded into the gate pass would carry the
    error from BEFORE the receiver corrected itself — the sender told
    off for a mistake already fixed, once per cycle, forever.  The
    order is asserted rather than described because moving the call two
    lines earlier breaks nothing else in this file.

    Worth recording while it is in view: on THIS body the receiver
    could not correct itself anyway.  `inbound` is INTER_LAMINA, and a
    lamina's own loop is forbidden from writing X'' onto one (G1/D12) —
    it is somebody else's ground truth, and this lamina has no more
    standing to correct it than to correct a thermometer.  So an
    outcome measured on an arriving value is precisely the outcome its
    receiver CANNOT fix alone, which is the case the return path exists
    for.  A receiver with its own machinery downstream of `inbound`
    would correct that machinery first, and step 5 is what makes the
    sender hear the remainder rather than the whole.
    """
    org = make_body(target=1.0, tol=0.5)
    order: list = []

    for lamina_id, controller in org.controllers.items():
        original = controller.step

        def stepped(_original=original, _id=lamina_id):
            order.append(f"step:{_id}")
            return _original()

        controller.step = stepped

    original_back = org._back_pass

    def back(warnings, _original=original_back):
        order.append("back_pass")
        return _original(warnings)

    org._back_pass = back
    org.tick()

    assert order[-1] == "back_pass", (
        f"the back pass has to run after every lamina has stepped, got {order}"
    )
    assert order.count("step:lamina_up") == 1
    assert order.count("step:lamina_down") == 1
