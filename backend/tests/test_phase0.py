"""
Phase 0 — the three things adding a second lamina found wrong.

Each was written up in docs/laminae.md as a real defect with a measured
symptom, and each one is a property of the ENGINE rather than of either
lamina, so the tests are written against the engine and use whichever
lamina exercises the path.

  0-A  Polarity belongs to the coupling, and a tag with two targets has
       two couplings.  The sign moved from <tag> to <target>, inheriting
       the tag's when absent.
  0-B  A function guards the value it returns; additive coupling means
       nobody guards the value anyone READS.  V_A displayed -2.88 L/min
       from a function that floors it at 0.05.
  0-C  A failed computation looked exactly like a healthy one, because a
       stale number and a fresh one are the same number.
"""

import pytest

from feedback_controller import FeedbackController
from laminae import load_twin, resolve_lamina
from snapshot import _simulation_snapshot
from universal_twin import Tag, TagTarget, UniversalTwin, resolve_polarity

RESP = "respiratory_lamina.xml"
CIRC = "circulatory_lamina.xml"


def _rest(twin):
    """Sit every sensor at its declared baseline and run the chain once."""
    for attr_id in twin.list_attributes("SENSOR"):
        attr = twin.attributes[attr_id]
        base = attr.baseline
        if base is None:
            base = (attr.physio_min + attr.physio_max) / 2
        twin.set_sensor(attr_id, base)
    twin.compute_all()
    return twin


@pytest.fixture
def resp():
    return _rest(load_twin(RESP))


@pytest.fixture
def circ():
    return _rest(load_twin(CIRC))


# ══════════════════════════════════════════════════════════════════════
# 0-A — polarity per target
# ══════════════════════════════════════════════════════════════════════

def test_a_target_that_declares_no_polarity_inherits_the_tags(circ):
    """
    Every XML written before <target polarity> existed must still mean
    exactly what it did.  The circulatory lamina declares none, so its
    targets have to come back carrying their tag's sign.
    """
    for tag in circ.tags.values():
        for tgt in tag.targets:
            assert tgt.polarity is None, (
                f"{tag.id} target {tgt.address} parsed a polarity it "
                f"does not declare"
            )

    fc = FeedbackController(circ)
    for tag in circ.tags.values():
        for _comp, _weight, polarity in fc._resolved_targets(tag):
            assert polarity == tag.polarity


def test_absent_polarity_is_none_and_not_the_negative_default():
    """
    The trap this field walks straight into: resolve_polarity(None)
    returns -1.0, which is the right default for a <tag> and precisely
    the wrong one for a <target>, where absent means "inherit".  Calling
    it unconditionally would silently pin every inheriting target to
    corrective — including the positive ones in the respiratory lamina.
    """
    assert resolve_polarity(None) == -1.0          # correct for a tag
    assert TagTarget(address="x").polarity is None  # and not used here


def test_a_declared_target_polarity_is_parsed(resp):
    """
    PACO2_DEVIATION is the tag that needed this: it fans into two
    composites whose couplings to PaCO2 are not the same.
    """
    targets = {t.address: t for t in resp.tags["PACO2_DEVIATION"].targets}
    assert targets["ventilation_state"].polarity == +1.0
    assert targets["gas_exchange_state"].polarity == 0.0
    # …and the tag's own sign is untouched by either.
    assert resp.tags["PACO2_DEVIATION"].polarity == +1.0


def test_the_kernel_is_handed_the_targets_sign_not_the_tags(resp):
    """
    Parsing the sign is only half of it — the kernel computes
    raw = polarity * gain * w * G * d, so the sign has to arrive in the
    params dict for that target's attributes specifically.
    """
    fc = FeedbackController(resp)
    tag = resp.tags["PACO2_DEVIATION"]

    from_ventilation = fc._build_kernel_params(
        tag, tag.outcome, "V_A", 1.0, polarity=+1.0
    )
    from_gas = fc._build_kernel_params(
        tag, tag.outcome, "PAO2", 0.4, polarity=0.0
    )
    assert from_ventilation["polarity"] == +1.0
    assert from_gas["polarity"] == 0.0

    # No polarity passed at all falls back to the tag — the shape a
    # caller with no target in hand needs.
    assert fc._build_kernel_params(tag, tag.outcome, "V_A", 1.0)["polarity"] \
        == tag.polarity


def test_two_targets_of_one_tag_can_pull_in_opposite_directions(resp):
    """
    The property the whole change exists for.  One tag, one outcome, two
    composites — and the X'' that lands in each has the sign that
    composite declared, not one sign for both.
    """
    resp.set_sensor("RR", 7.0)          # hypoventilation: PaCO2 well above target
    resp.set_sensor("V_T", 300.0)
    resp.compute_all()

    for tgt in resp.tags["PACO2_DEVIATION"].targets:
        if tgt.address == "gas_exchange_state":
            tgt.polarity = -1.0          # opposite to ventilation_state's +1.0

    fc = FeedbackController(resp)
    for _ in range(5):
        fc.step()

    # PaO2 is the witness on the gas side rather than PAO2, and the reason
    # is 0-B: hypoventilation drives the gas equation's PAO2 below its
    # declared floor on X' alone, and an attribute already under its floor
    # cannot be pushed further down by feedback.  The sign would be right
    # and the applied value zero, which tests the clamp rather than the
    # polarity.  PaO2 sits inside its range throughout.
    ventilation = resp.attributes["V_A"].value_feedback
    gas = resp.attributes["PaO2"].value_feedback
    assert ventilation > 0, "positive target should push its composite up"
    assert gas < 0, "negative target should push its composite down"


def test_a_monitor_only_target_leaves_its_composite_alone(resp):
    """
    Polarity 0 on ONE target: the tag still corrects through its other
    target, and touches nothing in this one.  Measured, this is exactly
    what gas_exchange_state is worth to PaCO2 — the sign there changes
    PaO2 and A-a and leaves PaCO2 identical to the last decimal, because
    PaCO2 = 0.863 * VCO2 / V_A reads neither.
    """
    resp.set_sensor("RR", 7.0)
    resp.set_sensor("V_T", 300.0)
    resp.compute_all()

    fc = FeedbackController(resp)
    for _ in range(5):
        fc.step()

    # ventilation_state acted…
    assert resp.attributes["V_A"].value_feedback > 0
    # …gas_exchange_state did not.
    for attr_id in ("PAO2", "PaO2", "A_a"):
        assert resp.attributes[attr_id].value_feedback == 0.0
    # and no kernel state accumulated for the skipped target either.
    assert not any(
        key for key in fc._kernel_state
        if key[0] == "PACO2_DEVIATION" and key[1] in ("PAO2", "PaO2", "A_a")
    )


def test_an_acting_target_on_a_monitor_only_tag_is_refused(tmp_path):
    """
    A tag with polarity 0 short-circuits before any target is read, so a
    sign declared underneath it would sit in the XML looking effective
    and do nothing.  That is the kind of quiet disagreement between
    declaration and behaviour this project keeps paying for, so it is a
    parse error.
    """
    src = (tmp_path / "monitor.xml")
    src.write_text(_MINIMAL_LAMINA.replace(
        '<target address="c_one" weight="1.0" />',
        '<target address="c_one" weight="1.0" polarity="positive" />',
    ).replace('polarity="negative"', 'polarity="0"'), encoding="utf-8")

    with pytest.raises(ValueError, match="monitor-only"):
        UniversalTwin(str(src))


def test_a_monitor_only_target_under_a_monitor_only_tag_is_fine(tmp_path):
    """Agreeing with the tag is not a contradiction."""
    src = (tmp_path / "agree.xml")
    src.write_text(_MINIMAL_LAMINA.replace(
        '<target address="c_one" weight="1.0" />',
        '<target address="c_one" weight="1.0" polarity="0" />',
    ).replace('polarity="negative"', 'polarity="0"'), encoding="utf-8")

    twin = UniversalTwin(str(src))
    assert twin.tags["t_one"].targets[0].polarity == 0.0


# ══════════════════════════════════════════════════════════════════════
# 0-B — the guard lives on the value anyone reads
# ══════════════════════════════════════════════════════════════════════

def test_an_external_value_outside_its_range_still_shows(circ):
    """
    The half of this that must NOT change.  A pathological reading is a
    reading: MAP 120 against a declared max of 110 stays 120 on the
    screen.  Hiding it is the soft_range bug fixed on 2026-06-23 and not
    one to relearn.
    """
    attr = circ.attributes["MAP"]
    attr.set_value(120.0)
    assert attr.physio_max < 120.0
    assert attr.value == 120.0

    # And with no feedback asked for, nothing moves it.
    attr.apply_feedback(0.0)
    assert attr.value == 120.0


def test_feedback_cannot_push_a_value_through_its_floor(resp):
    """
    The measured symptom: _calc_alveolar_ventilation floors V_A at
    0.05 L/min, the loop added X'' afterwards, and the screen showed
    -2.88 L/min.
    """
    v_a = resp.attributes["V_A"]
    v_a.set_value(1.05)
    v_a.apply_feedback(-5.886)          # the delta the runaway actually asked for

    assert v_a.value == pytest.approx(v_a.physio_min)
    assert v_a.value_feedback == pytest.approx(v_a.physio_min - 1.05)


def test_feedback_can_only_pull_back_from_an_out_of_range_reading(circ):
    """
    The band is the declared range WIDENED to contain X'.  With X'
    already above the range, the loop may pull toward it and may not
    push further out — which is what "the feedback never makes a value
    unphysical" means when the value arrived unphysical.
    """
    attr = circ.attributes["MAP"]
    attr.set_value(120.0)               # above the declared max

    attr.apply_feedback(+10.0)
    assert attr.value_feedback == 0.0, "must not be driven further out"
    assert attr.value == 120.0

    attr.apply_feedback(-8.0)
    assert attr.value_feedback == -8.0, "pulling back toward the range is allowed"
    assert attr.value == 112.0


def test_a_value_with_no_external_anchor_is_not_clamped(circ):
    """
    X' None means the attribute was never set or never computed.  There
    is no anchor to build a band around, and inventing one would make
    the clamp a different rule than the one documented.
    """
    attr = circ.attributes["Q"]
    attr.value_external = None
    attr.apply_feedback(999.0)
    assert attr.value_feedback == 999.0


def test_a_runaway_loop_never_produces_a_negative_ventilation(resp):
    """
    End to end, on the exact failure docs/laminae.md recorded: the sign
    on the ventilation target flipped, which drove V_A down, which
    raised PaCO2, which drove V_A down further.

    The runaway is NOT prevented here — a wrong sign is still a wrong
    sign, and PaCO2 still climbs.  What is prevented is the screen
    showing a negative alveolar ventilation while it happens.
    """
    resp.set_sensor("RR", 7.0)
    resp.set_sensor("V_T", 300.0)
    resp.compute_all()
    for tgt in resp.tags["PACO2_DEVIATION"].targets:
        if tgt.address == "ventilation_state":
            tgt.polarity = -1.0          # the bug, put back

    fc = FeedbackController(resp)
    for _ in range(6):
        fc.step()

    assert resp.attributes["PaCO2"].value > 100, "the runaway should still run away"

    for attr_id, attr in resp.attributes.items():
        if attr.value is None or attr.value_feedback == 0.0:
            continue
        lo = min(attr.physio_min, attr.value_external)
        hi = max(attr.physio_max, attr.value_external)
        assert lo - 1e-9 <= attr.value <= hi + 1e-9, (
            f"feedback drove {attr_id} to {attr.value}, outside "
            f"[{lo}, {hi}]"
        )


def test_the_controller_says_when_it_clamped(resp):
    """
    A clamp means the loop wanted to drive an attribute somewhere the
    model says it cannot go — usually a sign problem rather than a
    strong correction, and worth more than silence.
    """
    resp.set_sensor("RR", 7.0)
    resp.set_sensor("V_T", 300.0)
    resp.compute_all()
    for tgt in resp.tags["PACO2_DEVIATION"].targets:
        if tgt.address == "ventilation_state":
            tgt.polarity = -1.0

    fc = FeedbackController(resp)
    clamped = []
    for _ in range(6):
        clamped += [w for w in fc.step()["warnings"] if "clamped" in w]

    assert clamped, "the runaway clamps V_A; the report should say so"
    assert any("V_A" in w for w in clamped)


def test_a_settled_loop_clamps_nothing(resp):
    """The guard must be invisible when the loop behaves."""
    fc = FeedbackController(resp)
    for _ in range(10):
        assert not [w for w in fc.step()["warnings"] if "clamped" in w]


def test_an_attribute_pinned_by_the_clamp_does_not_charge_up(resp):
    """
    A clamp that holds forever is the case the dead-zone snap cannot see:
    its condition excludes a value_feedback already at 0.0, so the kernel
    would keep integrating behind a value that never moves and dump the
    lot the moment X' came back into range.

    A shunt does exactly that.  FiO2 0.9 against SpO2 85% puts the A-a
    gradient at ~540 mmHg on a declared max of 80, and PF_DEVIATION keeps
    asking to widen it further, which the clamp refuses every cycle.
    """
    resp.set_sensor("FiO2", 0.9)
    resp.set_sensor("SpO2", 85.0)
    resp.compute_all()
    assert resp.attributes["A_a"].value > resp.attributes["A_a"].physio_max

    fc = FeedbackController(resp)
    for _ in range(30):
        report = fc.step()

    assert any("clamped on A_a" in w for w in report["warnings"]), \
        "the loop should still be asking, and still be refused"
    assert resp.attributes["A_a"].value_feedback == 0.0
    assert fc._kernel_state.get(("PF_DEVIATION", "A_a"), {}).get("x_pp", 0.0) == 0.0
    assert "A_a" in report["snapped"]


# ══════════════════════════════════════════════════════════════════════
# 0-C — a failed computation is marked as one
# ══════════════════════════════════════════════════════════════════════

def test_a_healthy_pass_marks_nothing(circ):
    assert circ.failed_attributes == {}


def test_a_raising_function_records_the_attribute(circ):
    """
    _calc_resistance rejects a radius of zero, so R keeps last cycle's
    value and reads as live.  Nothing downstream could tell before.
    """
    healthy_r = circ.attributes["R"].value
    circ.set_sensor("r", 0.0)
    circ.compute_all()

    assert "R" in circ.failed_attributes
    assert "radius" in circ.failed_attributes["R"].lower()
    # The stale value is still there — that is the point of flagging it.
    assert circ.attributes["R"].value == healthy_r


def test_the_snapshot_carries_the_flag(circ):
    circ.set_sensor("r", 0.0)
    circ.compute_all()

    snap = _simulation_snapshot(circ)
    assert snap["computed"]["R"]["stale"] is True
    assert snap["computed"]["R"]["error"]
    # Its neighbours are not swept up with it.
    assert snap["computed"]["MAP"]["stale"] is False
    assert snap["computed"]["MAP"]["error"] is None


def test_an_attribute_that_recovers_stops_being_stale(circ):
    circ.set_sensor("r", 0.0)
    circ.compute_all()
    assert "R" in circ.failed_attributes

    circ.set_sensor("r", 0.15)
    circ.compute_all()
    assert circ.failed_attributes == {}
    assert _simulation_snapshot(circ)["computed"]["R"]["stale"] is False


def test_a_lamina_with_no_implementation_marks_every_computed_attribute():
    """
    Bare UniversalTwin registers no functions at all, which is the
    deliberate "declared but not implemented" fallback.  Every computed
    attribute is unset, and now says so per attribute rather than only
    in the log.
    """
    twin = UniversalTwin(str(_xml_path(CIRC)))
    _rest_sensors_only(twin)
    twin.compute_all()

    computed = twin.list_attributes("PRELIMINARY")
    assert set(twin.failed_attributes) == set(computed)
    assert all("No function registered" in reason
               for reason in twin.failed_attributes.values())

    snap = _simulation_snapshot(twin)
    assert all(snap["computed"][a]["stale"] for a in computed)


# ── fixtures' plumbing ────────────────────────────────────────────────

def _xml_path(name: str) -> str:
    from pathlib import Path
    import laminae
    return str(Path(laminae.__file__).parent / name)


def _rest_sensors_only(twin):
    for attr_id in twin.list_attributes("SENSOR"):
        attr = twin.attributes[attr_id]
        base = attr.baseline
        if base is None:
            base = (attr.physio_min + attr.physio_max) / 2
        twin.set_sensor(attr_id, base)


# A lamina small enough to be read at a glance, used by the parse-error
# tests.  Anything they assert has to be about the <target> element, so
# everything else here is the minimum that parses.
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
  <composites>
    <composite id="c_one">
      <name>Composite One</name>
      <attributes>a_one</attributes>
    </composite>
  </composites>
  <segments>
    <segment id="s_one" name="Segment One">
      <attributes>a_one</attributes>
      <composites>c_one</composites>
      <functions></functions>
      <behavioural_outcomes>
        <outcome id="o_one" attribute="a_one" target="5" tolerance="1"
                 name="Outcome One" unit="u" />
      </behavioural_outcomes>
    </segment>
  </segments>
  <tags>
    <tag id="t_one" outcome="o_one" polarity="negative">
      <targets>
        <target address="c_one" weight="1.0" />
      </targets>
    </tag>
  </tags>
</lamina>
"""


# ══════════════════════════════════════════════════════════════════════
# A log line is never worth more than the run it describes
# ══════════════════════════════════════════════════════════════════════

def test_a_console_that_cannot_spell_a_character_does_not_kill_the_run(capsys):
    """
    Found by running the thing, not by reading it.

    Windows opens stdout as cp1252. This codebase writes prose, and the
    per-target monitor-only message added in 0-A contains U+2192. print()
    raised UnicodeEncodeError inside _log, which killed the streaming
    runtime's control task and left the socket open and silent: five
    frames, then a stream that looked settled and was dead.

    The echo is a side effect. The model keeps going.
    """
    import io as _io
    import sys as _sys

    twin = load_twin(resolve_lamina("lamina_respiratory"))

    class Cp1252Stdout(_io.TextIOBase):
        encoding = "cp1252"

        def write(self, text):
            text.encode("cp1252")     # raises on anything cp1252 lacks
            return len(text)

    original = _sys.stdout
    _sys.stdout = Cp1252Stdout()
    try:
        twin._log("FB: tag X → composite Y monitor-only — not applied.")
    finally:
        _sys.stdout = original

    # And the in-memory log, which is what the snapshot reads, keeps the
    # real text rather than the console's approximation of it.
    assert any("→" in line for line in twin.get_log())
