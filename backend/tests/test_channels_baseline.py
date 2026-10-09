"""
The acceptance test for the seam: which numbers moved, and exactly why.

Read this file before changing a threshold — it is the only place that
says what the composite-only wire costs.

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

The two files are both in the repo on purpose, and diffing them is the
fastest way to see the whole story.

TWO REFACTORS ARE RECORDED HERE, and they have different verdicts.

The first moved the valve from between two laminae onto the membrane of
each.  Its verdict was equality: 1800 of 1800 numbers untouched, only
names different.

The second — this one — made the composite the only thing a gate can
see.  A crossing no longer picks an attribute out of the source; the
absorption vector weighs the composite into ONE state value, and that
value is what both membranes decide on and what crosses.  Its verdict is
narrower, and the narrowing is the finding:

  SEVEN of the nine scenarios still reproduce the one-valve photograph
  EXACTLY, to twelve decimals.  That is not luck.  The wire carries a
  normalised quantity and the receiver maps it back through the range it
  declares; circulation's face is `output_state`, whose state value IS
  cardiac output, and CO and CO_ref declare the same range, so the round
  trip is the identity.

  TWO diverge — organism.xml/hr200 and organism_key.xml/hr150_edv55 —
  and both for one reason: the model is driven past the range its own
  file declares.  Held at HR 200 the circulation computes a cardiac
  output of 13.2 L/min against CO's declared physio_max of 12.  A state
  value lives in [0,1] BY CONSTRUCTION — that is what lets one set of
  thresholds mean the same thing in L/min and in mmHg — so 13.2
  normalises to 1.0, and the most the wire can offer the receiver is
  12.  The old wire read the attribute directly and handed the filter
  13.2.

  Measured, and worth stating at full size rather than as "a small
  difference".  Saturation is RARE — cycles 3 and 5 of 40 for hr200,
  cycle 4 of 40 for hr150_edv55 — but its effect is not small:

      organism.xml/hr200          max |Δ CO_ref| 0.736 L/min
                                  max |Δ DO2|    275.0 mL/min
      organism_key.xml/hr150_edv55  max |Δ CO_ref| 0.162 L/min
                                    max |Δ DO2|     31.9 mL/min

  275 mL/min is larger than the respiratory lamina's own declared
  tolerance on oxygen delivery, which is ±250.  So this is not a
  rounding difference to wave through: at HR 200 the two wires disagree
  by more than the far side's outcome band, and once they disagree the
  receiver's EWMA carries the difference to the end of the run.

  THE FINDING IS NOT ABOUT THE SEAM.  Both wires are doing the only
  thing they can with a number the declaration says is impossible.  What
  the divergence measures is that CO's physio_max of 12 has been
  outgrown by the model that computes CO — at HR 200 it produces 13.2
  routinely.  Widening that range is a domain decision, made in the
  lamina file by whoever owns the physiology, and deliberately not made
  here.  What the seam owes is honesty about it, which is why every
  trace record carries `saturated` naming the attribute that ran out of
  declared room, and why the receiving attribute's provenance carries it
  too.
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

#: The scenarios that drive an attribute past its declared physio_max,
#: mapped to the largest CO_ref divergence each one is allowed to show,
#: in the receiver's own units.  Named rather than detected, so a THIRD
#: scenario appearing is a failure to explain rather than a silent
#: addition to the list; bounded rather than merely exempted, so a
#: change that widens the divergence fails even though the scenario is
#: already known to diverge.  Both figures are measured, not chosen.
SATURATING = {
    ("organism.xml", "hr200"):           0.7358602577650002,
    ("organism_key.xml", "hr150_edv55"): 0.16157719538500004,
}


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
def test_the_composite_only_container_reproduces_the_baseline(
        organism, scenario):
    """
    The load-bearing assertion, one scenario at a time so a failure
    names which one moved.

    Compared to twelve decimal places rather than approximately: these
    are the same arithmetic on the same inputs in the same order, so
    they are not merely close, they are equal. A difference in the
    twelfth decimal would mean an operation was reordered, and that is
    worth failing on rather than tolerating.

    A saturating scenario is SKIPPED here and asserted in full by
    `test_the_two_that_moved_moved_only_where_the_model_left_its_range`
    below — skipped rather than loosened, because a tolerance wide
    enough to swallow a 1.2 L/min clamp would swallow a real regression
    with it.
    """
    if (organism, scenario) in SATURATING:
        pytest.skip("saturates; asserted exactly by the next test")
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


def test_nothing_moved_in_any_scenario_that_stayed_inside_its_range():
    """
    States the claim positively over the whole run at once: seven of the
    nine scenarios, forty cycles each, every recorded number identical.
    """
    moved: list = []
    for (organism, scenario), block in _baseline_scenarios().items():
        if (organism, scenario) in SATURATING:
            continue
        for want, got in zip(block["cycles"], _v2_cycles(organism, scenario)):
            for field in NUMERIC_FIELDS:
                if field in want and want[field] != got.get(field):
                    moved.append(f"{organism}/{scenario} c{want['cycle']} "
                                 f"{field}: {want[field]} -> {got.get(field)}")
    assert not moved, "numbers moved:\n  " + "\n  ".join(moved[:20])


def _destination_ceiling(organism: str) -> float:
    """The physio_max of the attribute this body's channel lands on."""
    org = Organism(None if organism == "organism.xml" else organism)
    channel = org.spec.channels[0]
    return org.twins[channel.dest.lamina].attributes[
        channel.dest.member].physio_max


def test_the_two_that_moved_moved_only_where_the_model_left_its_range():
    """
    The exemption, asserted rather than assumed.

    For each saturating scenario: the run matches the one-valve
    photograph up to the cycle the source attribute first leaves its
    declared range, that cycle is one the trace itself marks
    `saturated`, and what the receiver holds never exceeds the maximum
    IT declares — which the old wire did.

    Written this way so the exemption cannot quietly widen.  A change
    that moved a number in an unsaturated cycle fails here, and so does
    one that stopped labelling the saturation.
    """
    for (organism, scenario), allowed in sorted(SATURATING.items()):
        expected = _baseline_scenarios()[(organism, scenario)]["cycles"]
        actual = _v2_cycles(organism, scenario)

        first_diff = next(
            (w["cycle"] for w, g in zip(expected, actual)
             if any(w[f] != g.get(f) for f in NUMERIC_FIELDS if f in w)),
            None,
        )
        assert first_diff is not None, (
            f"{organism}/{scenario} is listed as saturating but nothing "
            f"moved; either the model changed or the entry is stale"
        )

        by_cycle = {c["cycle"]: c for c in actual}
        assert by_cycle[first_diff]["saturated"], (
            f"{organism}/{scenario} first differs at cycle {first_diff}, "
            f"which the trace does not mark saturated — so the divergence "
            f"has some other cause and this entry does not cover it"
        )

        # Nothing may move BEFORE the model leaves its declared range.
        # Without this the entry would excuse a divergence anywhere in
        # the run merely because saturation happened somewhere in it.
        first_sat = min(c["cycle"] for c in actual if c["saturated"])
        assert first_diff >= first_sat, (
            f"{organism}/{scenario} diverges at cycle {first_diff}, before "
            f"the first saturated cycle {first_sat}"
        )

        drift = max(
            abs(w["CO_ref"] - g["CO_ref"])
            for w, g in zip(expected, actual)
            if w["CO_ref"] is not None and g["CO_ref"] is not None
        )
        assert drift <= allowed + 1e-9, (
            f"{organism}/{scenario} now differs from the one-valve wire by "
            f"{drift:.6f} in the receiver's units, over the {allowed} this "
            f"file records. Saturation being expected does not make a "
            f"LARGER divergence expected."
        )

        ceiling = _destination_ceiling(organism)
        over = [c["cycle"] for c in actual
                if c["CO_ref"] is not None and c["CO_ref"] > ceiling + 1e-9]
        assert not over, (
            f"{organism}/{scenario} landed above the receiver's declared "
            f"maximum of {ceiling} on cycles {over}"
        )


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
