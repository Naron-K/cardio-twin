"""
The acceptance test for the two-sided refactor: no number moved.

Moving the valve from between two laminae onto the membrane of each is
meant to change WHERE decisions are made and nothing about what the
model computes.  Same thresholds, same EWMA, same delay, same order —
only a different owner.  So the criterion is equality, and equality
needs a photograph taken before the first line changed.

`gate_traces_v1.json` is that photograph: nine scenarios, forty cycles,
seed 11, captured while the single `PermeabilityGate` was still the only
thing that existed.  It is FROZEN — nothing regenerates it, and it is
the one file in this directory that must never be rewritten.

`gate_traces_v2.json` is the same nine scenarios under `<channels>`, and
`tools/capture_gate_traces.py` regenerates it.

The two files are both in the repo on purpose.  A reader who does not
want to take this test's word for it can diff them and see for
themselves that the only lines that differ are the NAMES of things —
`pg_co_to_resp` became `ch_co_to_resp`, and a trigger that was misfiled
as `controller="key"` is now honestly a `pattern` — while all 1800
numbers are untouched.
"""
import json

import pytest

from organism import Organism
from signal_source import SimulatedSource
from tools.capture_gate_traces import (
    CYCLES,
    FIXTURE_DIR,
    SCENARIOS,
    SEED,
    capture_scenario,
)

BASELINE_FILE = FIXTURE_DIR / "gate_traces_v1.json"

#: The fields that are the MODEL rather than the naming.  A refactor is
#: allowed to rename a gate; it is not allowed to move one of these.
NUMERIC_FIELDS = ("open_fraction", "transmitted", "CO_ref", "DO2",
                  "provenance_state", "match", "drift")


def _baseline():
    assert BASELINE_FILE.exists(), (
        "gate_traces_v1.json is missing. It is the frozen photograph of the "
        "one-valve behaviour and nothing regenerates it — restore it from "
        "git rather than re-capturing."
    )
    return json.loads(BASELINE_FILE.read_text())


def _baseline_scenarios():
    return {(s["organism"], s["scenario"]): s for s in _baseline()["scenarios"]}


def _v2_cycles(organism, scenario):
    """Drive the CURRENT two-sided container through one scenario."""
    return capture_scenario(organism, scenario)["cycles"]


def test_the_baseline_was_taken_under_the_same_conditions():
    """
    Equality only means anything if both runs were driven identically.
    Seed and cycle count are the two knobs that would quietly invalidate
    every comparison below, so they are asserted rather than assumed.
    """
    baseline = _baseline()
    assert baseline["seed"] == SEED
    assert baseline["cycles_per_scenario"] == CYCLES


def test_every_scenario_in_the_baseline_still_exists():
    """
    A refactor that silently dropped a scenario would pass every
    remaining comparison. The set has to match, not just overlap.
    """
    declared = {(organism, scenario) for organism, scenario, _ in SCENARIOS}
    assert set(_baseline_scenarios()) == declared


@pytest.mark.parametrize("organism,scenario", sorted(
    (organism, scenario) for organism, scenario, _ in SCENARIOS
))
def test_the_two_sided_container_reproduces_the_baseline(organism, scenario):
    """
    The load-bearing assertion of the whole refactor, one scenario at a
    time so a failure names which one moved.

    Compared to twelve decimal places rather than approximately: these
    are the same arithmetic on the same inputs in the same order, so
    they are not merely close, they are equal. A difference in the
    twelfth decimal would mean an operation was reordered, and that is
    worth failing on rather than tolerating.
    """
    expected = _baseline_scenarios()[(organism, scenario)]["cycles"]
    actual = _v2_cycles(organism, scenario)

    assert len(actual) == len(expected), (
        f"{organism}/{scenario} ran {len(actual)} cycles, baseline has "
        f"{len(expected)}"
    )
    for expected_cycle, actual_cycle in zip(expected, actual):
        cycle = expected_cycle["cycle"]
        for field in NUMERIC_FIELDS:
            if field not in expected_cycle:
                continue
            want, got = expected_cycle[field], actual_cycle.get(field)
            if isinstance(want, (int, float)) and isinstance(got, (int, float)):
                assert round(got, 12) == round(want, 12), (
                    f"{organism}/{scenario} cycle {cycle}: {field} was "
                    f"{want}, is now {got}"
                )
            else:
                assert got == want, (
                    f"{organism}/{scenario} cycle {cycle}: {field} was "
                    f"{want!r}, is now {got!r}"
                )


def test_only_the_names_changed_between_the_two_photographs():
    """
    States the claim positively, over the whole run at once: across all
    nine scenarios and 40 cycles each, every recorded number is
    identical, and the fields that DID change are exactly the two
    naming ones.
    """
    baseline = _baseline_scenarios()
    moved: list = []
    for (organism, scenario), block in baseline.items():
        for want, got in zip(block["cycles"], _v2_cycles(organism, scenario)):
            for field in NUMERIC_FIELDS:
                if field in want and want[field] != got.get(field):
                    moved.append(f"{organism}/{scenario} c{want['cycle']} "
                                 f"{field}: {want[field]} -> {got.get(field)}")
    assert not moved, "numbers moved:\n  " + "\n  ".join(moved[:20])


def test_a_channel_the_receiver_refuses_holds_the_value_and_ages_it():
    """
    The state the one-valve design could not represent.

    With the sender open and the receiver shut, the value is neither
    across nor gone: it sits in the channel and gets older. The old
    design had nowhere to put it, so the only two answers available were
    "crossed" and "did not", and a reader could not tell "the sender has
    not offered" from "the receiver has not taken".

    Driven by shutting the receive gate directly rather than by
    declaring a second body, so the assertion is about the container and
    not about a particular XML.
    """
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lid: SimulatedSource(twin, seed=SEED).starting_state()
              for lid, twin in org.twins.items()})

    channel = org.spec.channels[0]
    receiver = org.twins[channel.dest.lamina].attributes[channel.dest.member]

    # Force the sender wide open, and make the receiving gate refuse
    # everything by giving it a label it will never be shown.
    channel.receive[0].key["expect"] = "__nothing_will_match_this__"

    for cycle in range(8):
        report = org.tick({"lamina_circulatory": {"HR": 200.0}}
                          if cycle >= 2 else None)

    entry = report["channels"][channel.id]
    assert entry["state"] == "waiting", (
        "the sender is open and the receiver is shut, which is neither "
        "crossing nor shut"
    )
    assert entry["offered"] is not None, "the channel is holding nothing"
    assert entry["transmitted"] is None, "nothing may have crossed"
    assert receiver.value == receiver.baseline, (
        "the receiver moved despite refusing the offer"
    )


def test_a_shut_sender_leaves_the_channel_empty_rather_than_waiting():
    """
    The converse, so `waiting` cannot be read as "anything not
    crossing". Nothing offered is not the same as something offered and
    declined, which is the distinction the state exists to make.
    """
    org = Organism()
    for twin in org.twins.values():
        twin._log = lambda *a, **k: None
    org.seed({lid: SimulatedSource(twin, seed=SEED).starting_state()
              for lid, twin in org.twins.items()})

    # Rest: the deviation trigger never opens, so nothing is ever offered.
    for _ in range(6):
        report = org.tick()

    entry = report["channels"][org.spec.channels[0].id]
    assert entry["state"] != "waiting"
    assert entry["offered"] is None
