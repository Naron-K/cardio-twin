"""
Systemic vascular resistance — the number that dissolves Q vs CO.

The lamina had two paths to "flow" and they disagreed:

    CO = HR · SV / 1000            the pump branch
    Q  = (MAP − CVP) / R           the pressure branch

and R is a SINGLE-SEGMENT Poiseuille estimate, which its own description
says plainly.  So the pressure branch was never computing a systemic
flow, and the two numbers had no reason to agree.

They never did.  Measured across the shipped feed, separating what Q
computes (X') from what the feedback loop adds to it (X''):

    drive      CO     Q(X')    Q(X'')   Q reported    SVR
    HR 35     4.05     2.23     +1.91      4.14      21.80
    rest      4.75     2.23     +1.91      4.14      18.59
    HR 110    5.78     2.23     +1.91      4.14      15.27
    HR 200    9.05     2.23     +1.91      4.14       9.76

Q's own formula gives 2.23 at EVERY drive — it depends on MAP and R,
and neither responds to the pump.  The 4.14 this project quoted for a
long time was 2.23 plus a saturated +1.91 of corrective signal, because
`target_flow` asked a segmental flow to sit at a whole-body 5.5 L/min.
So the "agreement at HR 35" reported earlier was not a coincidence: the
loop manufactured it.  The real gap between the two branches is 45% to
75%, never the 14% the reported numbers suggested.

`target_flow`, its tag `Q_DEVIATION`, and the `Q_CO_match` consistency
gate were all removed on 2026-09-08 — see the tests at the end of this
file.  Q now reports 2.23, which is what it computes.  The health target
moved to `target_svr`, monitor-only.

The fix adds nothing to the input side.  Point the pressure branch at
RESISTANCE instead of flow:

    SVR = (MAP − CVP) / CO

MAP is measured (the SBP/DBP cuff sensors), CO is computed from the HR
and EDV sensors, CVP is a declared constant.  Nothing measured is
replaced by anything predicted — the arrow that mattered, and the one an
earlier draft of this change had backwards.  After it there is exactly
one flow, one pressure, and one resistance, so there is nothing left to
contradict.

What it buys, beyond removing the contradiction: SVR is a reading the
twin could not previously produce at all.  Measured on the shipped feed,
holding everything but heart rate still:

    HR 35    CO 4.05    SVR 21.80    vasoconstricted
    rest     CO 4.75    SVR 18.59    normal
    HR 110   CO 5.78    SVR 15.27    normal
    HR 200   CO 9.05    SVR  9.76    vasodilated

Low output with high resistance is compensated shock; high output with
low resistance is exercise.  The old `R` sits at 39.62 at every one of
those and never moves.
"""
import math

import pytest

from laminae import load_twin
from organism import Organism
from signal_source import SimulatedSource
from universal_twin import PRELIMINARY, SENSOR

CVP_BASELINE = 5.0


@pytest.fixture
def twin():
    return load_twin("circulatory_lamina.xml")


def _driven(hr=None, cycles=12):
    """The shipped body, held at a heart rate, run to settle."""
    org = Organism()
    org.seed({lamina_id: SimulatedSource(t, seed=7).starting_state()
              for lamina_id, t in org.twins.items()})
    for _ in range(cycles):
        org.tick({"lamina_circulatory": {"HR": hr}} if hr else None)
    return org.twins["lamina_circulatory"]


# ══════════════════════════════════════════════════════════════════════
# The declarations
# ══════════════════════════════════════════════════════════════════════

def test_cvp_is_a_declared_attribute_not_a_buried_constant(twin):
    """
    It was `CENTRAL_VENOUS_PRESSURE = 5.0` in circulatory_lamina.py — a
    number a domain expert could neither see nor change without editing
    Python.  Declaring it is the point; the value is unchanged.
    """
    cvp = twin.attributes["CVP"]
    assert cvp.source == SENSOR
    assert cvp.baseline == pytest.approx(CVP_BASELINE)
    assert (cvp.physio_min, cvp.physio_max) == (0.0, 12.0)

    import circulatory_lamina
    assert not hasattr(circulatory_lamina.CirculatoryLamina,
                       "CENTRAL_VENOUS_PRESSURE"), (
        "the constant has to be gone, or there are two places to change it"
    )


def test_svr_is_derived_not_supplied(twin):
    """
    The whole argument for this change: SVR is an OUTPUT.  Declaring it
    as a sensor would mean asking for a measurement nobody takes, and
    would let it be set to a value inconsistent with MAP and CO.
    """
    svr = twin.attributes["SVR"]
    assert svr.source == PRELIMINARY
    assert svr.computed_by == "systemic_resistance"
    assert set(svr.depends_on) == {"MAP", "CO", "CVP"}


def test_map_is_still_computed_from_the_cuff(twin):
    """
    The line an earlier draft crossed. MAP is measured; a model that
    predicted it from the pump would be replacing a measurement with an
    estimate, which is what D12 exists to prevent.
    """
    assert set(twin.attributes["MAP"].depends_on) == {"SBP", "DBP"}
    assert twin.attributes["SBP"].source == SENSOR
    assert twin.attributes["DBP"].source == SENSOR


def test_svr_is_computed_after_the_cardiac_output_it_divides_by(twin):
    """
    compute_all() walks functions in declared step order and the steps
    are STRINGS ("3a", "3b", "4", "5").  SVR reading a CO that has not
    been computed yet would divide by None on the first pass.
    """
    steps = {f.output: str(f.step) for f in twin.functions.values()}
    assert steps["SVR"] > steps["CO"]
    assert steps["SVR"] > steps["MAP"]


# ══════════════════════════════════════════════════════════════════════
# The arithmetic
# ══════════════════════════════════════════════════════════════════════

def test_svr_is_exactly_the_pressure_gradient_over_the_flow():
    """
    Recomputed from the three attributes rather than read off the model,
    because the model is the thing under test.
    """
    twin = _driven()
    expected = ((twin.get("MAP").value - twin.get("CVP").value)
                / twin.get("CO").value)
    assert twin.get("SVR").value == pytest.approx(expected, rel=1e-12)


def test_svr_lands_in_the_clinical_range_at_rest():
    """
    Normal systemic vascular resistance is roughly 11-18 mmHg.min/L
    (880-1440 dyn.s.cm^-5).  A derived quantity that came out an order
    of magnitude off would mean the units were wrong somewhere.
    """
    svr = _driven().get("SVR").value
    assert 10.0 < svr < 25.0, f"SVR of {svr:.2f} is not a resistance"


@pytest.mark.parametrize("hr,expected", [
    (35.0, 21.80),
    (None, 18.59),
    (110.0, 15.27),
    (200.0, 9.76),
])
def test_the_measured_readings_reproduce(hr, expected):
    """Numbers from the docstring, held to the feed at seed 7."""
    assert _driven(hr).get("SVR").value == pytest.approx(expected, abs=0.05)


def test_resistance_falls_as_output_rises():
    """
    The physiological reading, and the reason this number is worth
    having: with pressure held, a body moving more blood is a body whose
    vessels have opened.  Monotone across the whole driven range.
    """
    svrs = [_driven(hr).get("SVR").value for hr in (35.0, 72.0, 110.0, 200.0)]
    assert svrs == sorted(svrs, reverse=True), (
        f"SVR has to fall as cardiac output rises, got {svrs}")


def test_the_old_single_segment_resistance_could_not_do_this_job():
    """
    Not a test of new code — a record of why the new code exists. R is
    Poiseuille for one representative vessel, so it is blind to the pump
    and pinned near the top of its own declared range.
    """
    rs = [_driven(hr).get("R").value for hr in (35.0, 200.0)]
    assert rs[0] == pytest.approx(rs[1]), "R does not respond to the pump"
    twin = _driven()
    assert twin.get("R").value / twin.attributes["R"].physio_max > 0.95, (
        "R also sits against its own ceiling"
    )


# ══════════════════════════════════════════════════════════════════════
# Guards
# ══════════════════════════════════════════════════════════════════════

def _calc(twin, inputs):
    return twin._function_registry["systemic_resistance"](inputs)


@pytest.mark.parametrize("inputs", [
    [], [93.0], [93.0, 4.75],
])
def test_a_short_input_list_is_refused(twin, inputs):
    with pytest.raises(ValueError):
        _calc(twin, inputs)


@pytest.mark.parametrize("co", [0.0, -1.0, -0.0001])
def test_a_cardiac_output_of_zero_or_less_is_refused(twin, co):
    """
    The one that matters. Dividing by it would report an infinite or a
    NEGATIVE resistance, and a negative resistance is not a reading that
    anything downstream could interpret — it would just look like a very
    vasodilated patient.
    """
    with pytest.raises(ValueError):
        _calc(twin, [93.0, co, CVP_BASELINE])


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_inputs_are_refused(twin, bad):
    for position in range(3):
        args = [93.0, 4.75, CVP_BASELINE]
        args[position] = bad
        with pytest.raises(ValueError):
            _calc(twin, args)


def test_a_healthy_call_still_returns_a_number(twin):
    """The guards must not have closed the happy path."""
    value = _calc(twin, [93.33, 4.75, 5.0])
    assert math.isfinite(value)
    assert value == pytest.approx((93.33 - 5.0) / 4.75)


# ══════════════════════════════════════════════════════════════════════
# Nothing that was already there moved
# ══════════════════════════════════════════════════════════════════════

def test_flow_still_computes_the_same_number_from_a_declared_cvp():
    """
    Q now takes CVP from the declaration instead of the constant. The
    baseline is the same 5.0, so the value has to be untouched — the
    frozen 1800-value trace would catch it otherwise, and this says it
    at the one seam that changed.
    """
    twin = _driven()
    expected = ((twin.get("MAP").value - twin.get("CVP").value)
                / twin.get("R").value)
    # value_external is X' — what the formula computed.  `value` is
    # X' + X'', and Q carries a large X''; see the test below.
    assert twin.get("Q").value_external == pytest.approx(expected, rel=1e-12)
    assert twin.get("CVP").value == pytest.approx(CVP_BASELINE)


def test_svr_was_not_slipped_into_a_composite(twin):
    """
    A composite's state value is what a gate reads and what crosses to
    another lamina. Adding a new attribute to one silently changes that
    number. SVR is a readout for now; putting it on a face is a separate
    decision with its own argument.
    """
    for composite in twin.composites.values():
        assert "SVR" not in composite.attribute_ids
        assert "CVP" not in composite.attribute_ids


# ══════════════════════════════════════════════════════════════════════
# What surfaced while checking the arithmetic
# ══════════════════════════════════════════════════════════════════════

def test_the_flow_this_lamina_reports_is_now_the_flow_it_computes():
    """
    Found by asserting Q against its own formula and having it fail.

    Q computes 2.2298 L/min.  The lamina used to REPORT 4.1421, because
    `target_flow` asked Q to sit at a whole-body 5.5 +/- 1.5 L/min and
    `Q_DEVIATION` drove `flow_state` toward it — a saturated +1.91 of
    X'' at every drive, 46% of the reported number.  Every earlier
    reading of "Q = 4.14" in this project was that falsification, not
    the pressure branch's answer.

    Both were removed 2026-09-08.  Q now reports what it computes, and
    the gap against CO is the real one: 2.23 against 4.75, not the 14%
    the corrected number suggested.
    """
    twin = _driven()
    q = twin.get("Q")

    assert q.value_feedback == pytest.approx(0.0), (
        "nothing should be writing X'' onto Q any more"
    )
    assert q.value == pytest.approx(q.value_external, rel=1e-12)
    assert q.value == pytest.approx(2.2298, abs=0.01)
    assert twin.get("CO").value == pytest.approx(4.7520, abs=0.01)


def test_nothing_writes_to_flow_state_any_more_and_that_is_allowed():
    """
    `Q_DEVIATION` was the only tag targeting `flow_state`. A composite
    nothing writes to is a supported state, and an honest one here:
    nothing in this lamina knows how to correct a segmental flow.
    """
    twin = load_twin("circulatory_lamina.xml")
    assert "flow_state" in twin.composites
    targeted = {t.address for tag in twin.tags.values() for t in tag.targets}
    assert "flow_state" not in targeted


def test_the_consistency_gate_that_failed_every_cycle_is_gone():
    """
    The lamina used to declare

        <gate attribute="Q_CO_match" type="consistency">
          <tolerance>0.10</tolerance>
          <compare>Q, CO</compare>
          <flag>Q != CO: model inconsistency</flag>

    and it printed GATE FAIL on essentially every cycle.  It was right
    that something was wrong and wrong about what: Q is segmental, CO is
    systemic, and two different quantities owe each other no agreement.

    Removed with the rest.  What it was pointing at is answered rather
    than flagged — the pressure branch computes SVR now instead of a
    second opinion about flow.
    """
    twin = _driven()
    flags = [str(f) for f in twin.validate_gates()]
    assert not any("model inconsistency" in f for f in flags), (
        f"the retired consistency gate is still firing: {flags}"
    )


def test_svr_carries_the_health_target_that_flow_could_not():
    """
    `target_flow` claimed a healthy magnitude for a quantity whose own
    function description says its magnitude is unreliable.  SVR has a
    defensible band, so the outcome moved there — and stayed
    MONITOR-ONLY, because SVR is derived from MAP and CO and a loop
    writing X'' onto it would be correcting the answer, not the question.
    """
    twin = load_twin("circulatory_lamina.xml")
    outcomes = {o.id: o for seg in twin.segments.values()
                for o in seg.behavioural_outcomes}

    assert "target_flow" not in outcomes
    assert "target_svr" in outcomes
    assert outcomes["target_svr"].attribute_id == "SVR"

    watched = {tag.outcome for tag in twin.tags.values()}
    assert "target_svr" not in watched, "monitored, not corrected"
    assert "Q_DEVIATION" not in twin.tags
