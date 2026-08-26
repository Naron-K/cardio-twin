"""
Phase 4 — the transfer engine.

Three stages between a gate deciding it is open and a number landing in
the receiving lamina, each one a defence against a different failure:

  delay     a ring buffer `time_delay` cycles long.  Phase 2 measured
            that there is no implicit lag to lean on, so a delay exists
            only if it is declared.
  EWMA      the low-pass filter G4 names as the main line against two
            feedback loops pulling on each other through an open gate.
  on_close  what the receiver is left holding once the gate shuts, and
            whether it is told.

The gate is driven with a stub controller in most of these.  Driving it
through the real threshold controller would make every test also a test
of when the pump works hard, and a failure would not say which half
broke.
"""

import pytest

from organism import Organism, OrganismError, parse_organism
from signal_source import SimulatedSource
from snapshot import _simulation_snapshot
from tests.test_organism import _organism   # noqa: F401


def always_open(state, source_vec, params):
    return {"open_fraction": 1.0}


def half_open(state, source_vec, params):
    return {"open_fraction": 0.5}


def shut(state, source_vec, params):
    return {"open_fraction": 0.0}


def body(rate=0.2, delay=0, on_close="hold", mode="proportional",
         band=None, controller=always_open, seed=11):
    """An organism whose one gate is driven by a stub controller."""
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lamina_id: SimulatedSource(twin, seed=seed).starting_state()
              for lamina_id, twin in org.twins.items()})
    gate = org.gates[0]
    gate.transfer.rate = rate
    gate.transfer.time_delay = delay
    gate.transfer.on_close = on_close
    gate.transfer.mode = mode
    if band:
        gate.transfer.band_min, gate.transfer.band_max = band
    org.register_gate_controller("threshold", controller)
    return org, gate


def co_ref(org):
    return org.twins["lamina_respiratory"].attributes["CO_ref"]


def run(org, cycles, hr=200.0):
    for _ in range(cycles):
        report = org.tick({"lamina_circulatory": {"HR": hr}})
    return report


# ══════════════════════════════════════════════════════════════════════
# The delay line
# ══════════════════════════════════════════════════════════════════════

def test_no_declared_delay_means_no_delay():
    """
    Phase 2 measured that the receiver re-derives within the same tick,
    so there is no implicit lag hiding here: time_delay=0 has to be
    genuinely zero, and the first cycle has to deliver.
    """
    org, gate = body(rate=1.0, delay=0)
    report = org.tick({"lamina_circulatory": {"HR": 200.0}})
    entry = report["gates"][gate.id]
    assert entry["transmitted"] == pytest.approx(entry["reading"])


@pytest.mark.parametrize("delay", [1, 2, 3])
def test_a_declared_delay_shifts_the_stream_by_exactly_that_many_cycles(delay):
    """
    Not "roughly later" — the same sequence, moved.  Anything else means
    the line is dropping or duplicating values, which a delay that also
    filters would hide.
    """
    undelayed, gate_a = body(rate=1.0, delay=0)
    delayed, gate_b = body(rate=1.0, delay=delay)

    straight = [run(undelayed, 1)["gates"][gate_a.id]["transmitted"]
                for _ in range(8)]
    shifted = [run(delayed, 1)["gates"][gate_b.id]["transmitted"]
               for _ in range(8)]

    assert shifted[:delay] == [None] * delay, (
        "a line still filling has nothing to deliver, and should say so "
        "rather than invent something"
    )
    for i, value in enumerate(shifted[delay:]):
        assert value == pytest.approx(straight[i]), (straight, shifted)


def test_the_delay_buffer_survives_the_controller_writing_its_own_state():
    """
    The bug this split was made for.  A gate controller's contract is
    that its return value IS its whole new state, so the container
    replaces that dict each cycle — which wiped the delay buffer when
    both lived in one place.  Measured: a gate declaring time_delay=1
    delivered nothing, ever, because the line was emptied between being
    filled and being read.
    """
    org, gate = body(rate=1.0, delay=2,
                     controller=lambda s, v, p: {"open_fraction": 1.0,
                                                 "noisy": True})
    for _ in range(5):
        org.tick({"lamina_circulatory": {"HR": 200.0}})

    gate_state = org._gate_state[gate.id]
    assert set(gate_state) == {"controller", "transfer"}
    assert gate_state["controller"] == {"open_fraction": 1.0, "noisy": True}
    assert len(gate_state["transfer"]["buffer"]) == 2, "the line kept its fill"


# ══════════════════════════════════════════════════════════════════════
# The low-pass filter
# ══════════════════════════════════════════════════════════════════════

def test_the_receiver_walks_out_of_its_baseline_rather_than_jumping():
    """
    The filter is seeded from wherever the destination already sits, so a
    seam resting on its declared 5.0 L/min eases toward the sender's
    number instead of snapping to it.
    """
    org, gate = body(rate=0.2)
    assert co_ref(org).value == 5.0

    first = org.tick({"lamina_circulatory": {"HR": 200.0}})
    reading = first["gates"][gate.id]["reading"]
    landed = co_ref(org).value

    assert 5.0 < landed < reading, (
        f"expected a step from 5.0 toward {reading:.2f}, landed on {landed:.2f}"
    )
    assert landed == pytest.approx(5.0 + 0.2 * (reading - 5.0))


def test_a_slower_rate_damps_the_senders_own_oscillation():
    """
    G4's claim, measured.  Held at HR 200 the circulatory loop fights the
    rate and CO itself swings; the question is what reaches the far side.
    """
    fast, gate_f = body(rate=1.0)
    slow, gate_s = body(rate=0.05)

    readings, fast_out, slow_out = [], [], []
    for _ in range(12):
        rf = run(fast, 1)["gates"][gate_f.id]
        rs = run(slow, 1)["gates"][gate_s.id]
        readings.append(rf["reading"])
        fast_out.append(rf["transmitted"])
        slow_out.append(rs["transmitted"])

    def swing(series):
        return max(series) - min(series)

    assert swing(readings) > 3.0, (
        f"the sender should be swinging for this to test anything; "
        f"got {swing(readings):.2f}"
    )
    assert swing(fast_out) == pytest.approx(swing(readings), rel=0.01), \
        "rate 1.0 is a wire, and should pass the swing straight through"
    assert swing(slow_out) < swing(fast_out) / 3, (
        f"the low-pass should damp it: fast {swing(fast_out):.2f} vs "
        f"slow {swing(slow_out):.2f}"
    )


def test_a_half_open_gate_moves_at_half_speed_rather_than_halving_the_value():
    """
    The plan multiplied open_fraction into the VALUE.  For a
    physiological quantity that is not a partial reading, it is a false
    one: a half-open gate would report a cardiac output of 2.4 L/min for
    a heart doing 4.8.  It goes into the rate instead.
    """
    full, gate_f = body(rate=0.4, controller=always_open)
    half, gate_h = body(rate=0.4, controller=half_open)

    reading = run(full, 1)["gates"][gate_f.id]["reading"]
    run(half, 1)

    assert co_ref(full).value == pytest.approx(5.0 + 0.4 * (reading - 5.0))
    assert co_ref(half).value == pytest.approx(5.0 + 0.2 * (reading - 5.0))
    # The giveaway: a scaled value would land BELOW where it started,
    # because half of a cardiac output above baseline is still a number
    # that has nothing to do with this heart.
    assert co_ref(half).value > 5.0


def test_the_provenance_says_what_the_filter_is_walking_toward():
    org, gate = body(rate=0.2, delay=0)
    org.tick({"lamina_circulatory": {"HR": 200.0}})

    provenance = co_ref(org).provenance
    assert provenance["state"] == "coupled"
    assert provenance["gate"] == gate.id
    assert provenance["from"] == "lamina_circulatory"
    assert provenance["rate"] == pytest.approx(0.2)
    assert provenance["delay"] == 0
    assert provenance["age"] == 0
    # The gap is visible without differencing two ticks.
    assert provenance["target"] > co_ref(org).value


# ══════════════════════════════════════════════════════════════════════
# on_close
# ══════════════════════════════════════════════════════════════════════

def test_hold_keeps_the_last_value_and_lets_it_age():
    org, gate = body(rate=0.5, on_close="hold")
    run(org, 10)
    held = co_ref(org).value
    assert held > 5.0

    org.register_gate_controller("threshold", shut)
    for _ in range(6):
        org.tick({"lamina_circulatory": {"HR": 72.0}})

    assert co_ref(org).value == pytest.approx(held), "hold means hold"
    assert co_ref(org).provenance["state"] == "held"
    assert co_ref(org).provenance["age"] == 6
    assert co_ref(org).provenance["open_fraction"] == 0.0


def test_decay_to_baseline_walks_back_to_the_declared_resting_value():
    """
    The other honest answer, and the reason <baseline> is required on an
    INTER_LAMINA attribute at all (G9): where a stale coupled value is
    worse than an uninformed one, the seam goes back to the number the
    domain expert wrote down.
    """
    org, gate = body(rate=0.3, on_close="decay_to_baseline")
    run(org, 12)
    peak = co_ref(org).value
    assert peak > 6.0

    org.register_gate_controller("threshold", shut)
    trace = []
    for _ in range(25):
        org.tick({"lamina_circulatory": {"HR": 72.0}})
        trace.append(co_ref(org).value)

    baseline = co_ref(org).baseline
    assert trace[0] < peak, "it should start moving immediately"
    assert trace == sorted(trace, reverse=True), "and move monotonically"
    assert trace[-1] == pytest.approx(baseline, abs=0.05)
    assert co_ref(org).provenance["state"] == "decaying"
    assert co_ref(org).provenance["target"] == baseline


def test_a_seam_no_gate_has_ever_fed_has_nothing_to_hold_or_decay():
    org, gate = body(on_close="decay_to_baseline", controller=shut)
    for _ in range(10):
        org.tick()
    assert co_ref(org).value == 5.0
    assert co_ref(org).provenance is None


# ══════════════════════════════════════════════════════════════════════
# band mode
# ══════════════════════════════════════════════════════════════════════

def test_a_band_gate_carries_a_value_inside_its_band():
    org, gate = body(rate=1.0, mode="band", band=(2.0, 20.0))
    report = run(org, 1)
    assert report["gates"][gate.id]["transmitted"] is not None


def test_a_band_gate_refuses_outside_the_band_rather_than_clamping():
    """
    Clamping is what the soft_range gate used to do, and it silently
    pulled out-of-range physiology back toward normal — a MAP of 120
    displayed as 110, masking the pathology the twin exists to show.
    Refusing says "this seam does not model that", which is true;
    clamping says "it is 6.0", which is not.
    """
    org, gate = body(rate=1.0, mode="band", band=(2.0, 6.0))
    report = run(org, 1)
    entry = report["gates"][gate.id]

    assert entry["reading"] > 6.0, "the sender must be outside for this to test"
    assert entry["transmitted"] is None
    assert co_ref(org).value == 5.0, "not clamped to 6.0, not carried"
    assert entry["transfer"]["close_reason"] == "out of band"


def test_a_band_transfer_must_declare_both_edges(tmp_path):
    path = _organism(tmp_path,
                     '<transfer mode="proportional"',
                     '<transfer mode="band"')
    with pytest.raises(OrganismError, match="band_min and band_max"):
        parse_organism(path)


def test_a_band_written_backwards_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     '<transfer mode="proportional"',
                     '<transfer mode="band" band_min="9" band_max="3"')
    with pytest.raises(OrganismError, match="not below band_max"):
        parse_organism(path)


def test_an_unknown_transfer_mode_does_not_parse(tmp_path):
    path = _organism(tmp_path,
                     '<transfer mode="proportional"',
                     '<transfer mode="teleport"')
    with pytest.raises(OrganismError, match="Known"):
        parse_organism(path)


# ══════════════════════════════════════════════════════════════════════
# What the snapshot carries
# ══════════════════════════════════════════════════════════════════════

def test_the_snapshot_carries_the_whole_provenance():
    org, gate = body(rate=0.2, delay=1)
    run(org, 5)

    entry = _simulation_snapshot(org.twins["lamina_respiratory"])["inbound"]
    provenance = entry["CO_ref"]["provenance"]
    for key in ("state", "gate", "from", "open_fraction", "age", "target",
                "rate", "delay"):
        assert key in provenance, key
    assert provenance["delay"] == 1


def test_the_gate_report_separates_controller_reasoning_from_transfer_state():
    org, gate = body(rate=0.2, delay=2)
    report = run(org, 4)
    entry = report["gates"][gate.id]

    assert entry["state"]["open_fraction"] == 1.0        # the controller's
    assert "transmitted" in entry["transfer"]            # the engine's
    assert "buffer" not in entry["transfer"], (
        "the report is a summary; a reader wants how open and why, not "
        "every value still in flight"
    )


def test_why_it_last_did_not_carry_stops_being_true_when_it_does():
    """An open gate reported beside close_reason='shut' is a small lie."""
    org, gate = body(rate=1.0, mode="band", band=(2.0, 6.0))
    shut_report = run(org, 1)
    assert shut_report["gates"][gate.id]["transfer"]["close_reason"] == \
        "out of band"

    gate.transfer.band_max = 20.0
    open_report = run(org, 1)
    assert open_report["gates"][gate.id]["transmitted"] is not None
    assert "close_reason" not in open_report["gates"][gate.id]["transfer"]
