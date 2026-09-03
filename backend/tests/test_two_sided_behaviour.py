"""
Phase 4 — the behaviour the two-sided design makes possible, measured.

Phases 1-3 moved the valve onto each membrane and proved that doing so
changed no number.  This is where the arrangement earns its keep: four
things the single mid-air valve could not express at all, each one
driven on the shipped bodies and each threshold taken from a
measurement rather than chosen.

Every number in the comments below was measured on seed 11 before the
test around it was written.  Where a threshold appears, the two states
it separates are given with it, so the next person can see how much
room it has rather than having to trust it.
"""
import random

import pytest

from organism import Organism, key_gate_controller
from signal_source import SimulatedSource

SEED = 11

# ── Building variants of the shipped body ─────────────────────────────

FACE = ('<lamina id="lamina_respiratory" level="2"/>',
        '<lamina id="lamina_respiratory" level="2" face="transport_state"/>')

#: A key on the SENDING side, matched against the RECEIVER's face — the
#: sender opening because the far side is asking (C3).
DEMAND_KEY = ('</auto_gate>\n      </transmit>', '''</auto_gate>
        <key_gate id="tk_o2_demand" weight="1.0">
          <key from="lamina_respiratory:transport_state"
               metric="weighted_distance"
               match_threshold="0.95" release_below="0.90">
            <weight attribute="SpO2" ref="0.45">1.0</weight>
            <weight attribute="CaO2" ref="0.54">1.0</weight>
            <weight attribute="DO2"  ref="0.27">0.5</weight>
          </key>
        </key_gate>
      </transmit>''')

#: An AUTO gate on the RECEIVING side: the receiver's own crisis, read
#: off its own face, lifting its own absorption rate.
RECEIVE_AUTO = ('<key_gate id="rk_co" weight="1.0"', '''<auto_gate
            id="ra_transport_crisis" refractory_cycles="5">
          <pattern match_threshold="0.95" release_below="0.90">
            <weight attribute="SpO2" ref="0.45">1.0</weight>
            <weight attribute="CaO2" ref="0.24">1.0</weight>
            <weight attribute="DO2"  ref="0.22">0.5</weight>
          </pattern>
        </auto_gate>
        <key_gate id="rk_co" weight="1.0"''')


@pytest.fixture
def make_body(tmp_path):
    """The shipped body with substrings swapped, seeded and quiet."""
    from organism import DEFAULT_ORGANISM
    source = DEFAULT_ORGANISM.read_text(encoding="utf-8")
    counter = [0]

    def build(*mutations):
        text = source
        for old, new in mutations:
            assert old in text, f"organism.xml drifted: {old[:40]!r} not found"
            text = text.replace(old, new)
        counter[0] += 1
        path = tmp_path / f"body{counter[0]}.xml"
        path.write_text(text, encoding="utf-8")
        org = Organism(path)
        for twin in org.twins.values():
            twin._log = lambda *a, **k: None
        org.seed({lid: SimulatedSource(twin, seed=SEED).starting_state()
                  for lid, twin in org.twins.items()})
        return org
    return build


def run(org, circulatory=None, respiratory=None, cycles=40):
    """Hold a forcing from cycle 3 on, and return the channel's report."""
    history = []
    for cycle in range(cycles):
        updates = {}
        if circulatory and cycle >= 2:
            updates["lamina_circulatory"] = circulatory
        if respiratory and cycle >= 2:
            updates["lamina_respiratory"] = respiratory
        report = org.tick(updates or None)
        history.append(co_ref(org).value)
    return report["channels"][org.spec.channels[0].id], history


def co_ref(org):
    return org.twins["lamina_respiratory"].attributes["CO_ref"]


# ══════════════════════════════════════════════════════════════════════
# 4a — a flood stays on its own side
# ══════════════════════════════════════════════════════════════════════

def test_a_flooding_sender_does_not_set_the_receivers_pace(make_body):
    """
    C4 and C6 together, and the reason Q3 was answered "own side only".

    At HR 200 the deviation trigger fires, so the SENDING side is in
    flood: its own weighting is bypassed and its own rate goes to 1.
    The receiver is not in flood, and its declared rate of 0.2 still
    governs what it absorbs.

    Measured: rate 0.2 on the provenance throughout, CO_ref 9.4510 after
    fourteen cycles rather than the offered 8.9952 arriving whole.

    If a sender's emergency could set the receiver's rate, the sender's
    fail-safe would be a forced write into another lamina — the disorder
    the gates exist to prevent, arriving through the door marked
    "safety".
    """
    org = make_body()
    entry, _ = run(org, circulatory={"HR": 200.0}, cycles=14)

    assert entry["transmit"][0]["flood"] is True, "the sender should flood"
    assert entry["flood"] is True
    assert co_ref(org).provenance["rate"] == pytest.approx(0.2), (
        "the receiver's own rate has to survive the sender's emergency"
    )


def test_a_gate_that_never_opens_changes_no_number(make_body):
    """
    The control for every variant below: adding a gate to a side is not
    supposed to perturb anything until that gate actually opens.  Run
    once with a receive-side auto that cannot match, and once without.
    """
    never = ('<key_gate id="rk_co" weight="1.0"', '''<auto_gate
            id="ra_never" refractory_cycles="5">
          <pattern match_threshold="0.99" release_below="0.98">
            <weight attribute="SpO2" ref="0.00">1.0</weight>
          </pattern>
        </auto_gate>
        <key_gate id="rk_co" weight="1.0"''')

    plain = make_body(FACE)
    padded = make_body(FACE, never)
    run(plain, circulatory={"HR": 200.0}, cycles=14)
    entry, _ = run(padded, circulatory={"HR": 200.0}, cycles=14)

    assert entry["receive"][0]["open"] is False
    assert co_ref(padded).value == pytest.approx(co_ref(plain).value, rel=1e-12)


# ══════════════════════════════════════════════════════════════════════
# 4b — the weight scales the deviation
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("weight,expected", [
    (1.0, 3.4013),
    (0.5, 4.2007),
    (0.25, 4.6003),
])
def test_a_partial_weight_lands_between_the_baseline_and_the_offer(
        make_body, weight, expected):
    """
    C5 / Q4, on the shipped body at HR 35 — the bradycardia the seam was
    widened to catch.

    Cardiac output settles at 3.3848 and the receiver's declared
    baseline is 5.0, so:

        weight 1.00   CO_ref 3.4013   the whole departure
        weight 0.50   CO_ref 4.2007   half of it
        weight 0.25   CO_ref 4.6003   a quarter

    The alternative reading — multiplying the VALUE — would put weight
    0.5 at 1.69 L/min, which is not a partial view of 3.38 but a
    different and false number.  Information is the departure from what
    the receiver was already assuming, so that is what a partial
    coupling takes a fraction of.
    """
    org = make_body(('<key_gate id="rk_co" weight="1.0"',
                     f'<key_gate id="rk_co" weight="{weight}"'))
    run(org, circulatory={"HR": 35.0})
    assert co_ref(org).value == pytest.approx(expected, abs=5e-4)


def test_the_weight_never_scales_the_value_itself(make_body):
    """Stated as the negative, because it is the reading being ruled out."""
    org = make_body(('<key_gate id="rk_co" weight="1.0"',
                     '<key_gate id="rk_co" weight="0.5"'))
    entry, _ = run(org, circulatory={"HR": 35.0})
    assert co_ref(org).value != pytest.approx(entry["offered"] * 0.5, abs=0.05)
    assert co_ref(org).value > entry["offered"], (
        "half the departure from 5.0 must land ABOVE the offer, not below it"
    )


# ══════════════════════════════════════════════════════════════════════
# 4c — a sender that opens because the receiver is asking
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("label,spo2,should_open", [
    ("rest",              None,  False),   # match 0.7219
    ("mild hypoxaemia",   92.0,  False),   # match 0.7963
    ("moderate",          85.0,  False),   # match 0.8975  <- closest shut
    ("severe",            78.0,  True),    # match 0.9974
])
def test_the_sender_opens_on_the_receivers_need(
        make_body, label, spo2, should_open):
    """
    The behaviour the one-valve design could not have, because it had
    nowhere to put a condition belonging to the sender but ABOUT the
    receiver.

    Cardiac output is unremarkable in every row here — the deviation
    trigger stays shut throughout — so nothing in the circulatory
    lamina's own state would open this seam.  What opens it is the
    respiratory lamina's face, matched against the shape of severe
    hypoxaemia, presented at the channel as demand.

    match_threshold 0.95 sits between 0.8975 and 0.9974: 0.052 clear of
    the nearest state that must stay shut and 0.047 of the nearest that
    must open.
    """
    org = make_body(FACE, DEMAND_KEY)
    entry, _ = run(org, respiratory={"SpO2": spo2} if spo2 else None)

    auto, demand = entry["transmit"][0], entry["transmit"][1]
    assert auto["open"] is False, (
        "the pump is fine in every one of these; if its own trigger fires "
        "the test is measuring the wrong thing"
    )
    assert demand["open"] is should_open, (
        f"{label}: match {demand['state']['match']:.4f} against 0.95"
    )
    assert (entry["state"] == "crossing") is should_open


def test_the_loop_the_demand_key_closes_still_settles(make_body):
    """
    4c creates a cycle across two laminae: respiration presents need,
    circulation opens, cardiac output crosses, oxygen delivery moves, and
    the need changes.  That is an algebraic loop, now visible in the
    declaration rather than hidden in the code.

    Two defences hold it: the tick order is one-directional, and the
    receiver absorbs through an EWMA rather than jumping.  Measured over
    80 cycles at SpO2 78, the last twenty are identical to five decimal
    places — it settles rather than ringing.
    """
    org = make_body(FACE, DEMAND_KEY)
    _, history = run(org, respiratory={"SpO2": 78.0}, cycles=80)
    tail = history[-20:]
    assert max(tail) - min(tail) < 1e-5, (
        f"the loop is still moving after 80 cycles: span {max(tail)-min(tail)}"
    )


# ══════════════════════════════════════════════════════════════════════
# 4d — a receiver whose own crisis lifts its own rate
# ══════════════════════════════════════════════════════════════════════

def test_the_receivers_own_crisis_lifts_its_own_absorption_rate(make_body):
    """
    The mirror of 4a.  A flood binds only its own side — which cuts both
    ways: the receiver cannot be flooded BY the sender, and it can flood
    itself.

    Driven at HR 200 with SpO2 78, the respiratory lamina's own face
    matches the crisis it was keyed on, its auto gate fires, and its
    absorption rate goes from the declared 0.2 to 1.0 for as long as the
    gate holds.
    """
    org = make_body(FACE, RECEIVE_AUTO)
    rates = []
    for cycle in range(20):
        updates = {"lamina_circulatory": {"HR": 200.0},
                   "lamina_respiratory": {"SpO2": 78.0}} if cycle >= 2 else None
        report = org.tick(updates)
        entry = report["channels"][org.spec.channels[0].id]
        rates.append((entry["receive"][0]["open"],
                      (co_ref(org).provenance or {}).get("rate")))

    fired = [rate for opened, rate in rates if opened]
    assert fired, "the receiving crisis trigger never fired"
    assert all(rate == pytest.approx(1.0) for rate in fired), (
        "while the receiver's own auto gate is open its rate is 1"
    )
    calm = [rate for opened, rate in rates if not opened and rate is not None]
    assert all(rate == pytest.approx(0.2) for rate in calm), (
        "and its declared rate governs the rest of the time"
    )


def test_the_refractory_holds_a_crisis_trigger_through_its_own_effect(
        make_body):
    """
    The defect this phase found.

    A pattern keyed on a composite that the crossing itself moves will
    open, change the very coordinates it matched on, and shut again next
    cycle.  Measured before the fix: four transitions in eight cycles,
    the gate arguing with its own effect.

    The deadband cannot help — this is a genuine fast swing, not noise —
    which is exactly what the refractory is for, and it was accepted on
    the declaration while nothing read it.  With it honoured the same run
    makes two transitions: one opening, one release.
    """
    org = make_body(FACE, RECEIVE_AUTO)
    for cycle in range(20):
        org.tick({"lamina_circulatory": {"HR": 200.0},
                  "lamina_respiratory": {"SpO2": 78.0}} if cycle >= 2 else None)

    transitions = org._gate_state["ra_transport_crisis"]["transitions"]
    assert transitions <= 2, (
        f"the crisis trigger flipped {transitions} times chasing its own "
        f"effect; the refractory should hold it"
    )


# ══════════════════════════════════════════════════════════════════════
# 4e — every new trigger is quiet on its own boundary
# ══════════════════════════════════════════════════════════════════════

def test_the_band_the_new_triggers_declare_does_not_chatter():
    """
    The measurement rule 4 rests on, repeated for the shape-matching
    triggers 4c and 4d introduce.

    A vector parked exactly on match 0.95 with the feed's own noise on it
    (sd 0.01), 400 cycles:

        one boundary (0.9499)   118 transitions
        band 0.01    (0.94)      68
        band 0.03    (0.92)       1
        band 0.05    (0.90)       1

    0.05 is the band both new triggers declare, and it is the second
    width at which the gate stops arguing with the feed.
    """
    weights = {"SpO2": (1.0, 0.45), "CaO2": (1.0, 0.54), "DO2": (0.5, 0.27)}
    # Weighted distance 0.05 — match exactly 0.95 — with the whole
    # offset placed on one coordinate.
    parked = {"SpO2": 0.45 + 0.125, "CaO2": 0.54, "DO2": 0.27}

    def transitions(release_below):
        state, rng = {}, random.Random(SEED)
        params = {"key_weights": weights, "metric": "weighted_distance",
                  "match_threshold": 0.95, "release_below": release_below,
                  "refractory_cycles": 0}
        for _ in range(400):
            reading = {k: v + rng.gauss(0, 0.01) for k, v in parked.items()}
            state = key_gate_controller(state, reading, params)
        return state["transitions"]

    assert transitions(0.9499) > 100, "one boundary should chatter badly"
    assert transitions(0.90) <= 2, "the declared band should be quiet"


# ══════════════════════════════════════════════════════════════════════
# 4f — the drift telemetry survived being refiled
# ══════════════════════════════════════════════════════════════════════

def test_the_pattern_trigger_still_reports_its_drift():
    """
    G7: measure the drift before correcting the drift.

    organism_key.xml's trigger was a `controller="key"` and is now an
    auto gate with a pattern.  That was a refiling, not a change of
    behaviour, and the telemetry that makes the v3 adaptation question
    answerable with data has to have come along.
    """
    org = Organism("organism_key.xml")
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lid: SimulatedSource(twin, seed=SEED).starting_state()
              for lid, twin in org.twins.items()})
    for cycle in range(40):
        report = org.tick({"lamina_circulatory": {"HR": 150.0, "EDV": 55.0}}
                          if cycle >= 2 else None)

    state = report["channels"]["ch_failing_pump"]["transmit"][0]["state"]
    for field in ("distance", "distance_ewma", "distance_first",
                  "distance_min", "distance_max", "evaluations", "drift"):
        assert field in state, f"the pattern trigger stopped reporting '{field}'"
    assert state["evaluations"] == 40
    assert state["distance_min"] <= state["distance"] <= state["distance_max"]
