"""
Phase 3 — the two gate controllers.

They answer different questions.  `threshold` asks "is this composite
doing enough to be worth passing on?"; `key` asks "does this composite
look like the state I am waiting for?".  Both are stateful, both keep
their state on the Organism rather than on the declaration, and both
must be born shut (G6).

Most of these run the controller directly on a synthetic vector rather
than through an organism.  That is deliberate: inside an organism the
sender's own feedback loop pulls the watched value away from any
boundary, so a chattering gate cannot be built there — which is a fine
property of the model and a useless property of a test meant to prove a
deadband works.
"""

import json
import random

import pytest

from organism import (
    Organism,
    OrganismError,
    key_gate_controller,
    parse_organism,
    threshold_gate_controller,
)
from signal_source import SimulatedSource
from tests.test_organism import _organism, _twins_for   # noqa: F401


THRESHOLD_PARAMS = {
    "watch": "w", "aggregate": "attr",
    "open_above": 0.75, "close_below": 0.60, "refractory_cycles": 0,
}


def drive(series, params, controller=threshold_gate_controller, key="w"):
    """Run a controller over a sequence, returning every state it produced."""
    state, out = {}, []
    for value in series:
        state = controller(state, {key: value} if not isinstance(value, dict)
                           else value, params)
        out.append(state)
    return out


# ══════════════════════════════════════════════════════════════════════
# threshold — the two-boundary state machine
# ══════════════════════════════════════════════════════════════════════

def test_a_threshold_gate_is_born_shut():
    """
    G6, at the level where it is actually decided: an empty state means
    closed, so the very first evaluation has to be a decision to open
    rather than a value inheriting an assumption.
    """
    shut = threshold_gate_controller({}, {"w": 0.70}, THRESHOLD_PARAMS)
    assert shut["open"] is False
    assert shut["open_fraction"] == 0.0
    assert shut["transitions"] == 0, "nothing happened, so nothing changed"

    # A value above open_above on the first cycle counts as a transition,
    # which is only true if the gate started closed.
    opened = threshold_gate_controller({}, {"w": 0.99}, THRESHOLD_PARAMS)
    assert opened["open"] is True
    assert opened["transitions"] == 1


def test_it_opens_above_and_shuts_below():
    states = drive([0.5, 0.8, 0.7, 0.65, 0.55, 0.7], THRESHOLD_PARAMS)
    opens = [s["open"] for s in states]
    assert opens == [False, True, True, True, False, False], opens


def test_the_deadband_holds_the_state_between_the_boundaries():
    """
    0.70 is above close_below and below open_above.  A shut gate stays
    shut there and an open gate stays open — the same input, two answers,
    which is the whole of what hysteresis means.
    """
    shut = threshold_gate_controller({"open": False}, {"w": 0.70},
                                     THRESHOLD_PARAMS)
    open_ = threshold_gate_controller({"open": True}, {"w": 0.70},
                                      THRESHOLD_PARAMS)
    assert shut["open"] is False
    assert open_["open"] is True
    assert shut["reason"] == "in deadband"


def test_the_deadband_is_what_stops_chatter():
    """
    G3, measured rather than asserted.  A signal parked on the threshold
    with the feed's own noise on it, driven through the same controller
    four ways.

    This is the evidence rule 4 rests on, and it is why the rule was
    later extended to cover the key controller too.
    """
    rng = random.Random(17)
    series = [0.75 + rng.gauss(0, 0.02) for _ in range(400)]

    def transitions(**overrides):
        params = dict(THRESHOLD_PARAMS, **overrides)
        return drive(series, params)[-1]["transitions"]

    one_boundary = transitions(close_below=0.7499)
    wide_band = transitions(close_below=0.60)

    assert one_boundary > 100, (
        f"a single boundary should chatter badly; got {one_boundary}"
    )
    assert wide_band <= 2, (
        f"a band wide enough for the noise should be quiet; got {wide_band}"
    )


def test_the_band_the_organism_actually_declares_is_quiet():
    """
    The same measurement, on the numbers that ship rather than on a pair
    chosen to demonstrate the effect.

    The shipped gate is a deviation gate, so the signal parked on its
    boundary is a CO_norm sitting `open_above` away from `reference`, and
    the noise on it is the measured sd of CO_norm on the live feed
    (0.0104).  Its deadband is 0.035, which is 3.4 of those — the first
    width where the gate stops arguing with the feed.
    """
    params = dict(parse_organism().gates[0].controller_args())
    assert params["aggregate"] == "deviation", "this test reads a deviation gate"

    rng = random.Random(11)
    parked = params["reference"] + params["open_above"]
    series = [parked + rng.gauss(0, 0.0104) for _ in range(400)]

    def transitions(**overrides):
        p = dict(params, refractory_cycles=0, **overrides)
        return drive(series, p, key="CO")[-1]["transitions"]

    # One boundary, i.e. the deadband collapsed to nothing.
    one_boundary = transitions(close_below=params["open_above"] - 0.0001)
    declared = transitions()

    assert one_boundary > 100, (
        f"collapsing the declared deadband should chatter; got {one_boundary}"
    )
    assert declared <= 2, (
        f"the band organism.xml declares should be quiet; got {declared}"
    )


def test_the_refractory_holds_the_state_through_a_fast_swing():
    """
    The deadband stops chatter from noise.  The refractory stops it from
    a genuine fast swing, and gives whatever is downstream a few cycles
    to respond before the gate changes its mind again.
    """
    params = dict(THRESHOLD_PARAMS, refractory_cycles=5)
    # Open, then immediately drop far below close_below.
    states = drive([0.9] + [0.1] * 6, params)
    opens = [s["open"] for s in states]
    assert opens[0] is True
    # Held open through the refractory despite the value collapsing…
    assert all(opens[1:6]), opens
    # …and released once it expires.
    assert opens[6] is False, opens
    assert states[-1]["transitions"] == 2


def test_a_gate_with_nothing_readable_holds_rather_than_guessing():
    """A missing reading is not evidence that the pump stopped."""
    opened = threshold_gate_controller({}, {"w": 0.9}, THRESHOLD_PARAMS)
    assert opened["open"] is True

    held = threshold_gate_controller(opened, {"w": None}, THRESHOLD_PARAMS)
    assert held["open"] is True
    assert held["reason"] == "no readable value to watch"

    shut_stays_shut = threshold_gate_controller({}, {"w": None},
                                                THRESHOLD_PARAMS)
    assert shut_stays_shut["open"] is False


@pytest.mark.parametrize("aggregate, expected_open", [
    ("attr", False),    # watches w = 0.10
    ("mean", False),    # (0.10 + 0.90) / 2 = 0.50
    ("max", True),      # 0.90
])
def test_the_aggregate_decides_what_the_thresholds_compare_against(
        aggregate, expected_open):
    params = dict(THRESHOLD_PARAMS, aggregate=aggregate)
    state = threshold_gate_controller({}, {"w": 0.10, "other": 0.90}, params)
    assert state["open"] is expected_open


def test_proportional_mode_eases_in_and_still_obeys_the_state_machine():
    """
    The sigmoid says HOW open; the deadband still says WHETHER.  A gate
    the state machine calls shut passes nothing, whatever the sigmoid
    would have made of the value.
    """
    params = dict(THRESHOLD_PARAMS, mode="proportional", steepness=8.0)

    at_threshold = threshold_gate_controller({}, {"w": 0.75}, params)
    assert at_threshold["open_fraction"] == pytest.approx(0.5, abs=1e-9)

    well_above = threshold_gate_controller({}, {"w": 1.0}, params)
    assert well_above["open_fraction"] > 0.85

    # Inside the deadband from shut: no sigmoid, because it is shut.
    in_band = threshold_gate_controller({"open": False}, {"w": 0.70}, params)
    assert in_band["open_fraction"] == 0.0


def test_binary_mode_is_the_default():
    state = threshold_gate_controller({}, {"w": 0.76}, THRESHOLD_PARAMS)
    assert state["open_fraction"] == 1.0


# ══════════════════════════════════════════════════════════════════════
# key — matching a reference point
# ══════════════════════════════════════════════════════════════════════

KEY_PARAMS = {
    "key_weights": {"a": (1.0, 0.50), "b": (1.0, 0.80)},
    "metric": "weighted_distance",
    "match_threshold": 0.90,
    "release_below": 0.85,
}


def test_an_exact_match_scores_one():
    state = key_gate_controller({}, {"a": 0.50, "b": 0.80}, KEY_PARAMS)
    assert state["distance"] == pytest.approx(0.0)
    assert state["match"] == pytest.approx(1.0)
    assert state["open"] is True


def test_matching_is_within_tolerance_not_exact():
    """
    G2.  Real data is noisy, so an exact match on a float never happens,
    and a key that can never fire is not a gate.
    """
    near = key_gate_controller({}, {"a": 0.53, "b": 0.83}, KEY_PARAMS)
    assert near["distance"] == pytest.approx(0.03, abs=1e-9)
    assert near["open"] is True

    far = key_gate_controller({}, {"a": 0.90, "b": 0.20}, KEY_PARAMS)
    assert far["open"] is False


def test_weights_say_which_coordinate_matters():
    heavy_on_a = dict(KEY_PARAMS,
                      key_weights={"a": (9.0, 0.50), "b": (1.0, 0.80)})
    # Same total error, put on different coordinates.
    a_wrong = key_gate_controller({}, {"a": 0.60, "b": 0.80}, heavy_on_a)
    b_wrong = key_gate_controller({}, {"a": 0.50, "b": 0.90}, heavy_on_a)
    assert a_wrong["distance"] > b_wrong["distance"]


def test_cosine_matches_on_direction_rather_than_magnitude():
    params = dict(KEY_PARAMS, metric="cosine")
    scaled = key_gate_controller({}, {"a": 0.25, "b": 0.40}, params)
    exact = key_gate_controller({}, {"a": 0.50, "b": 0.80}, params)
    # Half the magnitude, same direction — cosine cannot tell them apart.
    assert scaled["distance"] == pytest.approx(exact["distance"], abs=1e-9)
    assert scaled["open"] is True


def test_a_key_gate_is_born_shut_and_keeps_its_band():
    """
    Hysteresis here exists because measuring said so: a key with one
    threshold, sitting just above it, flipped 148 times in 400 cycles.
    """
    assert key_gate_controller({}, {"a": 0.90, "b": 0.20}, KEY_PARAMS)["open"] \
        is False

    # b is 0.24 off its reference, so the mean weighted error is 0.12 and
    # the match is 0.88 — inside the band, above release_below and below
    # match_threshold. Same input, two answers, which is what a band is.
    mid = {"a": 0.50, "b": 1.04}
    from_shut = key_gate_controller({"open": False}, mid, KEY_PARAMS)
    from_open = key_gate_controller({"open": True}, mid, KEY_PARAMS)

    assert from_shut["match"] == pytest.approx(0.88, abs=1e-9)
    assert KEY_PARAMS["release_below"] < from_shut["match"] \
        < KEY_PARAMS["match_threshold"]
    assert from_shut["open"] is False
    assert from_open["open"] is True
    assert from_shut["transitions"] == 0 and from_open["transitions"] == 0


def test_the_key_band_stops_the_chatter_it_was_measured_against():
    """
    `a` sits exactly on its reference and `b` wobbles 0.20 away from
    its own, so the mean weighted error hovers at 0.10 — a match of
    0.90, straddling the threshold rather than sitting safely to one
    side of it.  Getting that wrong is easy: put the noise where the
    error is one-sided and the match never crosses, and the test proves
    nothing while passing.
    """
    rng = random.Random(23)
    series = [{"a": 0.50, "b": 1.00 + rng.gauss(0, 0.02)} for _ in range(400)]

    one_boundary = drive(series, dict(KEY_PARAMS, release_below=0.8999),
                         controller=key_gate_controller)[-1]
    banded = drive(series, KEY_PARAMS, controller=key_gate_controller)[-1]

    assert 0.88 < banded["match"] < 0.94, (
        f"the series must straddle the threshold to test anything; "
        f"match sat at {banded['match']:.4f}"
    )
    assert one_boundary["transitions"] > 50, one_boundary["transitions"]
    assert banded["transitions"] <= 4, banded["transitions"]


def test_a_key_with_no_readable_coordinate_stays_shut():
    state = key_gate_controller({}, {"a": None, "b": None}, KEY_PARAMS)
    assert state["open_fraction"] == 0.0
    assert "no key coordinate is readable" in state["reason"]


def test_drift_telemetry_accumulates_from_the_first_evaluation():
    """
    G7.  A static key drifts, and the tempting fix is to make it
    adaptive — a v2 decision that should be made on evidence.  So the
    controller records what a drifting key would look like from cycle
    one, rather than a slow loop being built first and asked afterwards.
    """
    walk = [{"a": 0.50 + i * 0.001, "b": 0.80} for i in range(200)]
    states = drive(walk, KEY_PARAMS, controller=key_gate_controller)

    first, last = states[0], states[-1]
    assert last["evaluations"] == 200
    assert first["drift"] == pytest.approx(0.0, abs=1e-9)
    assert last["drift"] > 0.05, "a steadily worsening match should show drift"
    assert last["distance_min"] <= last["distance_ewma"] <= last["distance_max"]
    assert last["distance_first"] == pytest.approx(first["distance"])


def test_a_stable_key_reports_no_drift():
    """The other half: telemetry that always says 'drifting' says nothing."""
    rng = random.Random(5)
    steady = [{"a": 0.50 + rng.gauss(0, 0.01), "b": 0.80} for _ in range(200)]
    last = drive(steady, KEY_PARAMS, controller=key_gate_controller)[-1]
    assert abs(last["drift"]) < 0.02, last["drift"]


# ══════════════════════════════════════════════════════════════════════
# Both, in the registry
# ══════════════════════════════════════════════════════════════════════

def test_both_controllers_return_state_the_snapshot_can_carry():
    """
    A gate whose reasoning cannot be inspected is a gate nobody can
    debug, and the state travels on the snapshot to make that possible.
    """
    threshold_state = threshold_gate_controller({}, {"w": 0.9},
                                                THRESHOLD_PARAMS)
    key_state = key_gate_controller({}, {"a": 0.5, "b": 0.8}, KEY_PARAMS)
    for state in (threshold_state, key_state):
        assert json.loads(json.dumps(state)) == state
        assert 0.0 <= state["open_fraction"] <= 1.0


def test_the_shipped_gate_opens_on_departure_in_either_direction():
    """
    End to end on the real declaration, and on the property that makes it
    two-sided.

    A resting circulation should not open it — a respiratory model on its
    own declared baseline of 5 L/min is uninformed rather than wrong, and
    an uninformed model that is stable beats a coupled one that
    oscillates.  But the first version of this gate watched the raw
    normalised CO against a single high boundary, so it opened for a
    racing heart and stayed shut for a failing one: measured at HR 35,
    cardiac output settled at 3.39 L/min and the seam never opened, which
    left respiration computing oxygen delivery from 5.0 while the pump
    delivered two thirds of that.  aggregate="deviation" makes both
    directions the same number.

    The settled values these HRs produce, measured — the circulatory loop
    pulls them well away from the raw HR·SV/1000, so they are taken from
    what the model settles at rather than from arithmetic:

        HR  72   CO 4.75   deviation 0.025   shut
        HR  90   CO 5.94   deviation 0.094   shut (inside the deadband)
        HR 110   CO 6.36   deviation 0.136   OPEN (high)
        HR 200   CO 9.93   deviation 0.493   OPEN (high)
        HR  35   CO 3.30   deviation 0.170   OPEN (low)
    """
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=11).starting_state()
              for lamina_id, twin in org.twins.items()})

    def settle(hr):
        for _ in range(8):
            report = org.tick({"lamina_circulatory": {"HR": float(hr)}})
        return report["gates"]["pg_co_to_resp"]

    assert settle(72)["open_fraction"] == 0.0, "resting"
    assert settle(90)["open_fraction"] == 0.0, "working, still in the deadband"

    hard = settle(200)
    assert hard["open_fraction"] == 1.0
    assert hard["state"]["watch_value"] > 0.125
    assert org.twins["lamina_respiratory"].attributes["CO_ref"].value \
        == pytest.approx(hard["transmitted"])
    assert hard["transmitted"] > 5.0, "above the seam's uncoupled baseline"

    settle(72)
    failing = settle(35)
    assert failing["open_fraction"] == 1.0, (
        "a pump at 3.3 L/min is the most remarkable thing this seam can "
        "see; a gate that stays shut for it is watching half its subject"
    )
    assert failing["state"]["watch_value"] > 0.125
    assert org.twins["lamina_respiratory"].attributes["CO_ref"].value == (
        pytest.approx(failing["transmitted"]))
    assert failing["transmitted"] < 5.0, "below the seam's uncoupled baseline"


def test_a_key_gate_without_a_release_band_does_not_parse(tmp_path):
    """Rule 4, now covering the controller the measurement said needs it."""
    path = _organism(
        tmp_path,
        '<controller_params watch="CO" aggregate="deviation" reference="0.30"\n'
        '                         open_above="0.125" close_below="0.09"\n'
        '                         refractory_cycles="5" />',
        '<key metric="weighted_distance" match_threshold="0.9">\n'
        '        <weight attribute="CO" ref="0.65">1.0</weight>\n'
        '      </key>',
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'controller="threshold"', 'controller="key"'),
        encoding="utf-8")
    with pytest.raises(OrganismError, match="release_below"):
        parse_organism(path)


def test_a_key_gate_with_a_release_band_parses(tmp_path):
    path = _organism(
        tmp_path,
        '<controller_params watch="CO" aggregate="deviation" reference="0.30"\n'
        '                         open_above="0.125" close_below="0.09"\n'
        '                         refractory_cycles="5" />',
        '<key metric="weighted_distance" match_threshold="0.9"\n'
        '           release_below="0.85">\n'
        '        <weight attribute="CO" ref="0.65">1.0</weight>\n'
        '      </key>',
    )
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'controller="threshold"', 'controller="key"'),
        encoding="utf-8")
    gate = parse_organism(path).gates[0]
    assert gate.controller == "key"
    assert gate.key_weights == {"CO": (1.0, 0.65)}
    assert gate.controller_args()["release_below"] == 0.85


def test_a_value_left_behind_by_a_shut_gate_reports_its_age():
    """
    Until a gate could open, nothing could go stale.  The moment one can,
    a gate that opens and then shuts leaves the receiver holding the last
    value that crossed — and saying nothing about it would report a live
    reading from a shut gate.  Measured before the fix: CO_ref sat at
    8.73 claiming to be current while the circulation had returned to
    4.84.
    """
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=11).starting_state()
              for lamina_id, twin in org.twins.items()})

    def settle(hr, cycles=8):
        for _ in range(cycles):
            org.tick({"lamina_circulatory": {"HR": float(hr)}})

    co_ref = org.twins["lamina_respiratory"].attributes["CO_ref"]

    settle(200)
    assert co_ref.provenance["state"] == "coupled"
    assert co_ref.provenance["age"] == 0

    # Back to rest.  Long enough for the deadband and the refractory to
    # let go — the age is read from the gate rather than assumed equal to
    # the number of cycles, because the cycle the gate actually shuts on
    # is the controller's business and this test is about what happens
    # after it does.
    settle(72, cycles=20)
    assert co_ref.provenance["state"] == "held"
    assert co_ref.provenance["open_fraction"] == 0.0
    held_value = co_ref.value
    held_age = co_ref.provenance["age"]
    assert held_age > 0

    settle(72, cycles=5)
    assert co_ref.value == pytest.approx(held_value), "hold keeps the value"
    assert co_ref.provenance["state"] == "held"
    assert co_ref.provenance["age"] == held_age + 5, "and it ages every cycle"
    # And the number it is holding really has gone stale.
    assert org.twins["lamina_circulatory"].attributes["CO"].value < held_value


def test_an_uncoupled_seam_has_nothing_to_age():
    """A gate that never opened leaves the baseline reading as a baseline."""
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=11).starting_state()
              for lamina_id, twin in org.twins.items()})
    for _ in range(10):
        org.tick()

    assert org.twins["lamina_respiratory"].attributes["CO_ref"].provenance is None
