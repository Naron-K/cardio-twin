"""
Tests for the respiratory lamina, and for the loader that picks it.

Two things are under test and they are worth separating.

The first is arithmetic: the relations in respiratory_lamina.py are standard
clinical equations, so they can be checked against published values rather than
against themselves. The oxyhaemoglobin inversion is pinned at three points off
the textbook curve, and the resting chain is pinned end to end.

The second is the universal machinery. This lamina exists partly to exercise
paths the circulatory lamina never takes — a segment with no outcome, a
composite no tag writes to, a tag fanning into two composites, and a tag with
polarity 0 that evaluates and deliberately corrects nothing. Those are asserted
here so a later change to the engine cannot quietly break them.
"""

import math

import pytest

from laminae import implementation_for, lamina_id_of, load_twin
from respiratory_lamina import RespiratoryLamina
from signal_source import SimulatedSource
from universal_twin import UniversalTwin

XML = "respiratory_lamina.xml"


@pytest.fixture
def twin():
    """A respiratory twin resting at its declared baselines."""
    t = load_twin(XML)
    for attr_id in t.list_attributes("SENSOR"):
        t.set_sensor(attr_id, t.attributes[attr_id].baseline)
    t.compute_all()
    return t


# ── The loader ────────────────────────────────────────────────────────

def test_loader_picks_the_implementation_by_lamina_id():
    assert lamina_id_of(XML) == "lamina_respiratory"
    assert implementation_for("lamina_respiratory") is RespiratoryLamina
    assert isinstance(load_twin(XML), RespiratoryLamina)


def test_unregistered_lamina_falls_back_to_bare_universal_twin():
    """
    An unknown lamina is a model whose arithmetic nobody wrote yet, not a
    broken file.  Falling back keeps its structure intact so the visualiser can
    still draw it — with every computed value blank, which is the honest
    picture of "declared but not implemented".
    """
    assert implementation_for("lamina_nobody_has_written") is UniversalTwin


# ── Arithmetic, against published values ──────────────────────────────

@pytest.mark.parametrize("saturation, expected", [(97, 90.5), (90, 58.1), (75, 40.2)])
def test_severinghaus_inversion_matches_the_textbook_curve(twin, saturation, expected):
    """
    Severinghaus's own inversion, checked at three points on the standard
    oxyhaemoglobin dissociation curve.  These pins caught a real error: the
    published first term is written `0.385*ln((1/S)-1)^-1`, where the exponent
    belongs to the logarithm's argument and not to the logarithm.
    """
    assert twin._calc_arterial_o2([saturation]) == pytest.approx(expected, abs=0.15)


def test_resting_chain_end_to_end(twin):
    """A healthy 70 kg adult on room air, computed from the declared baselines."""
    expected = {
        "V_E":      6.00,     # 12 breaths x 500 mL
        "V_A":      4.20,     # only 350 mL of each breath reaches an alveolus
        "V_D_frac": 0.30,
        "VCO2":   200.00,     # 250 mL/min O2 at a respiratory quotient of 0.8
        "PaCO2":   41.10,     # eucapnic
        "PAO2":    98.36,
        "PaO2":    90.48,
        "A_a":      7.88,     # normal for a young adult
        "PF_ratio": 430.87,
        "CaO2":    19.77,
        "DO2":    988.42,     # about 4x resting consumption
        "P_plat":  13.33,
        "dP":       8.33,
    }
    for attr_id, value in expected.items():
        assert twin.get(attr_id).value == pytest.approx(value, abs=0.01), attr_id


def test_every_outcome_starts_inside_its_tolerance(twin):
    """The declared baselines are a healthy state, not merely a legal one."""
    for outcomes in twin.evaluate_all_outcomes().values():
        for fb in outcomes:
            assert fb["within_tolerance"], f"{fb['outcome_id']} starts out of band"


def test_alveolar_ventilation_drives_arterial_co2(twin):
    """Halving alveolar ventilation doubles PaCO2 — the point of the equation."""
    before = twin.get("PaCO2").value
    twin.set_sensor("RR", 6.0)          # half the rate, same tidal volume
    twin.compute_all()
    assert twin.get("PaCO2").value == pytest.approx(before * 2, rel=0.01)


def test_rapid_shallow_breathing_raises_minute_but_lowers_alveolar_ventilation(twin):
    """
    The clinical reason both V_E and V_A exist.  A patient breathing fast and
    shallow moves more air and ventilates less.
    """
    v_e_before, v_a_before = twin.get("V_E").value, twin.get("V_A").value
    twin.set_sensor("RR", 30.0)
    twin.set_sensor("V_T", 250.0)
    twin.compute_all()
    assert twin.get("V_E").value > v_e_before
    assert twin.get("V_A").value < v_a_before


def test_hypoventilation_drops_both_tensions_and_leaves_the_gradient_normal(twin):
    """
    The A-a gradient's whole diagnostic value: it separates a failing lung from
    a failing respiratory drive.

    Both inputs move, because both are measured.  Someone hypoventilating has a
    low respiratory rate *and* a falling saturation; feeding one without the
    other describes no patient.  PAO2 falls through the CO2 term of the
    alveolar gas equation, PaO2 falls with the oximeter, and the gradient
    between them stays where it was — which is the finding that says the lung
    is fine and the drive is not.
    """
    gradient_before = twin.get("A_a").value
    twin.set_sensor("RR", 8.0)
    twin.set_sensor("SpO2", 92.0)
    twin.compute_all()
    assert twin.get("PAO2").value < 90
    assert twin.get("PaO2").value < 70
    assert twin.get("A_a").value == pytest.approx(gradient_before, abs=6)


def test_failing_gas_exchange_widens_the_gradient(twin):
    """The other half of the discrimination: saturation falls, ventilation does not."""
    gradient_before = twin.get("A_a").value
    twin.set_sensor("SpO2", 90.0)
    twin.compute_all()
    assert twin.get("PAO2").value == pytest.approx(98.36, abs=0.01)   # unchanged
    assert twin.get("A_a").value > gradient_before + 20


def test_crossed_over_tensions_clamp_rather_than_going_negative(twin):
    """
    PAO2 and PaO2 are two independent estimates — one from the gas equation,
    one from an oximeter inversion — and nothing in the model forces them to
    agree.  Drive the rate down without touching saturation and the arithmetic
    puts arterial oxygen above alveolar oxygen, which is not physiology but
    mutually inconsistent inputs.  The gradient clamps at zero rather than
    reporting a negative number that would read as a measurement.
    """
    twin.set_sensor("RR", 7.0)          # SpO2 deliberately left at 97%
    twin.compute_all()
    assert twin.get("PAO2").value < twin.get("PaO2").value
    assert twin.get("A_a").value == 0.0


def test_altitude_lowers_alveolar_oxygen_at_unchanged_fio2(twin):
    """3000 m is a lower barometric pressure, not a lower oxygen fraction."""
    pao2_before = twin.get("PAO2").value
    twin.set_sensor("P_atm", 525.0)
    twin.compute_all()
    assert twin.get("PAO2").value < pao2_before
    assert twin.get("FiO2").value == pytest.approx(0.21)


def test_anaemia_starves_delivery_at_a_perfect_saturation(twin):
    """Content is dominated by haemoglobin, which is why SpO2 alone misleads."""
    twin.set_sensor("Hb", 7.0)
    twin.set_sensor("SpO2", 100.0)
    twin.compute_all()
    assert twin.get("DO2").value < 600
    assert twin.get("SpO2").value == pytest.approx(100.0)


def test_tidal_volume_at_dead_space_does_not_divide_by_zero(twin):
    """
    No effective ventilation is a real clinical state that steady-state algebra
    cannot express, so V_A is floored rather than allowed to reach zero.
    """
    twin.set_sensor("V_T", 150.0)      # exactly the dead space
    twin.compute_all()
    assert twin.get("V_A").value > 0
    assert math.isfinite(twin.get("PaCO2").value)


# ── Machinery the circulatory lamina never exercises ──────────────────

def test_a_segment_may_declare_no_outcome(twin):
    """Mechanics is tracked and gated without being given a target."""
    mechanics = twin.segments["seg_mechanics"]
    assert mechanics.behavioural_outcomes == []
    assert {g.attribute for g in twin.gates} >= {"P_plat", "dP"}


def test_a_composite_may_have_no_tag_writing_to_it(twin):
    """mechanics_state is a grouping, not a feedback address."""
    written_to = {t.address for tag in twin.tags.values() for t in tag.targets}
    assert "mechanics_state" in twin.composites
    assert "mechanics_state" not in written_to


def test_a_tag_may_fan_into_two_composites(twin):
    """A CO2 disturbance is answered by ventilation and, in part, gas exchange."""
    targets = {t.address: t.weight for t in twin.tags["PACO2_DEVIATION"].targets}
    assert targets == {"ventilation_state": 1.0, "gas_exchange_state": 0.4}


def test_monitor_only_tag_has_zero_polarity(twin):
    """
    A widened A-a gradient means the lung is failing to transfer oxygen, and no
    adjustment inside this model repairs a lung.  Declaring the outcome and
    refusing to act on it is the honest encoding, and polarity 0 is how the
    engine spells it.
    """
    assert twin.tags["AA_MONITOR"].polarity == 0.0


def test_monitor_only_tag_emits_no_correction(twin):
    """
    Polarity 0 must evaluate and log without writing X'' anywhere.

    Isolated by removing every other tag, because gas_exchange_state is also
    written to by PF_DEVIATION and a delta appearing there proves nothing on
    its own.  With AA_MONITOR alone, any non-zero correction is its.
    """
    from feedback_controller import FeedbackController

    twin.tags = {"AA_MONITOR": twin.tags["AA_MONITOR"]}
    twin.set_sensor("SpO2", 88.0)      # widens the gradient well past tolerance
    twin.compute_all()

    report = FeedbackController(twin).step()

    assert "AA_MONITOR" in report["tags_emitted"], "the tag should still evaluate"
    assert all(delta == 0.0 for delta in report["deltas_per_attr"].values())
    assert report["feedback_norm"] == pytest.approx(0.0)


def test_inverse_coupling_needs_positive_polarity_to_converge(twin):
    """
    The finding this lamina exists to have caught, pinned so it cannot come back.

    The gate kernel computes raw = polarity * gain * w * G * d, so a tag marked
    "negative" pushes every attribute in its target composites *down* when its
    outcome sits above target.  That corrects an outcome that rises with the
    composite and amplifies one that falls with it.  PaCO2 = 0.863 * VCO2 / V_A
    is the second kind: with polarity negative, hypoventilation drove V_A down,
    which raised PaCO2, which drove V_A down further — measured at PaCO2 = 1928
    mmHg and a negative alveolar ventilation within two cycles.

    Every relation in the circulatory lamina is positive, so nothing there ever
    exercised this. The assertion is on convergence, not on the sign, so it
    still holds if the engine's convention is ever changed to a saner one.
    """
    from feedback_controller import FeedbackController

    twin.set_sensor("RR", 9.0)         # hypoventilation: PaCO2 rises past target
    twin.compute_all()
    disturbed = twin.get("PaCO2").value
    assert disturbed > 45, "the disturbance should push the outcome out of band"

    controller = FeedbackController(twin)
    for _ in range(40):
        controller.step()

    settled = twin.get("PaCO2").value
    assert twin.get("V_A").value > 0, "alveolar ventilation must not go negative"
    assert abs(settled - 40) < abs(disturbed - 40), "the loop must close the gap"

    outcome = next(
        fb
        for outcomes in twin.evaluate_all_outcomes().values()
        for fb in outcomes
        if fb["outcome_id"] == "target_paco2"
    )
    assert outcome["within_tolerance"]


def test_a_failed_computation_reaches_the_snapshot_warnings(twin):
    """
    When a function raises, the twin logs and moves on — the attribute keeps
    last cycle's value and looks live.  It is still stale, but the snapshot now
    carries the line so the screen can say something went wrong rather than
    nothing at all.
    """
    from snapshot import _simulation_snapshot

    twin.attributes["V_A"].value_feedback = -10.0   # drive V_A negative
    twin.attributes["V_A"].normalise()
    twin.compute_all()

    warnings = _simulation_snapshot(twin)["warnings"]
    assert any("ERROR computing PaCO2" in line for line in warnings)


# ── The synthetic feed, on a lamina it was not written for ────────────

def test_feed_is_built_from_this_lamina_not_from_a_table(twin):
    source = SimulatedSource(twin, seed=3)
    reading = source.next()
    assert set(reading) == set(twin.list_attributes("SENSOR"))
    assert "HR" not in reading          # a circulatory sensor, correctly absent
    assert source.describe().endswith("all with a declared baseline")
