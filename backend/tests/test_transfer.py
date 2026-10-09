"""
The absorption engine — what the RECEIVER does with an offer.

Three stages between a channel carrying something and a number landing
in the receiving lamina, each one a defence against a different failure:

  delay     a ring buffer `time_delay` cycles long, owned by the
            CHANNEL because a delay is a property of the wire.  Phase 2
            measured that there is no implicit lag to lean on, so a
            delay exists only if it is declared.
  EWMA      the low-pass filter G4 names as the main line against two
            feedback loops pulling on each other through an open
            channel.  `rate` belongs to the receiving gate: how fast to
            believe something is the receiver's business, not the
            sender's.
  on_close  what the receiver is left holding once nothing is crossing,
            and whether it is told.

The sending gate is driven by a stub trigger in most of these.  Driving
it through the real threshold trigger would make every test also a test
of when the pump works hard, and a failure would not say which half
broke.

Bodies are built as XML rather than by poking at the parsed objects,
because the v2 dataclasses are frozen — deliberately, since a
declaration that is also a mutable state bag cannot be reloaded or
compared — so the honest way to test a configuration is to declare it.
"""
import pytest

from organism import Organism, OrganismError, parse_organism
from signal_source import SimulatedSource

# ── Building bodies ───────────────────────────────────────────────────

_BODY = """<?xml version="1.0" encoding="UTF-8"?>
<organism id="bdt_transfer" version="2.0">
  <name>Transfer test body</name>
  <laminae>
    <lamina id="lamina_circulatory" level="1"/>
    <lamina id="lamina_respiratory" level="2"/>
  </laminae>
  <channels>
    <channel id="ch_test" from="lamina_circulatory:output_state"
             to="lamina_respiratory:CO_ref" time_delay="{delay}">
      <extract mode="state"/>
      <transmit>
        <auto_gate id="tx_stub" refractory_cycles="0">
          <threshold aggregate="deviation" reference="0.30"
                     open_above="0.125" close_below="0.09"/>
        </auto_gate>
      </transmit>
      <receive>
        <key_gate id="rx_test" weight="{weight}" rate="{rate}"
                  on_close="{on_close}" confidence="0.8"{band}>
          <key metric="identity"/>
        </key_gate>
      </receive>
    </channel>
  </channels>
</organism>
"""


def always_open(state, source_vec, params):
    return {"open_fraction": 1.0}


def half_open(state, source_vec, params):
    return {"open_fraction": 0.5}


def shut(state, source_vec, params):
    return {"open_fraction": 0.0}


def body_xml(tmp_path, rate=0.2, delay=0, on_close="hold", weight=1.0,
             band=None, name="organism.xml"):
    band_attr = ""
    if band:
        band_attr = f' band_min="{band[0]}" band_max="{band[1]}"'
    path = tmp_path / name
    path.write_text(_BODY.format(delay=delay, rate=rate, on_close=on_close,
                                 weight=weight, band=band_attr),
                    encoding="utf-8")
    return path


@pytest.fixture
def make_body(tmp_path):
    """An organism whose sending gate is driven by a stub trigger."""
    def build(rate=0.2, delay=0, on_close="hold", weight=1.0, band=None,
              trigger=always_open, seed=11):
        org = Organism(body_xml(tmp_path, rate=rate, delay=delay,
                                on_close=on_close, weight=weight, band=band))
        for twin in org.twins.values():
            twin._log = lambda *a, **k: None
        org.seed({lamina_id: SimulatedSource(twin, seed=seed).starting_state()
                  for lamina_id, twin in org.twins.items()})
        org.register_gate_controller("threshold", trigger)
        return org, org.spec.channels[0]
    return build


def co_ref(org):
    return org.twins["lamina_respiratory"].attributes["CO_ref"]


def landed(org, normalised):
    """
    What a normalised offer becomes in the RECEIVER's own units.

    The wire carries the source composite's state value, which lives in
    [0,1] so that it means the same thing whatever the attributes behind
    it are measured in; the receiving lamina maps it onto the range it
    declares for itself.  Tests compare against this rather than against
    the raw offer, because comparing the two directly would be comparing
    a position in the vector space against a cardiac output.
    """
    attr = co_ref(org)
    return attr.physio_min + normalised * (attr.physio_max - attr.physio_min)


def run(org, cycles, hr=200.0):
    for _ in range(cycles):
        report = org.tick({"lamina_circulatory": {"HR": hr}})
    return report


def entry(report, channel):
    return report["channels"][channel.id]


# ══════════════════════════════════════════════════════════════════════
# The delay line
# ══════════════════════════════════════════════════════════════════════

def test_no_declared_delay_means_no_delay(make_body):
    """
    Phase 2 measured that the receiver re-derives within the same tick,
    so there is no implicit lag hiding here: time_delay=0 has to be
    genuinely zero, and the first cycle has to deliver.
    """
    org, channel = make_body(rate=1.0, delay=0)
    report = run(org, 1)
    assert entry(report, channel)["transmitted"] is not None


@pytest.mark.parametrize("delay", [1, 3])
def test_a_declared_delay_shifts_the_stream_by_exactly_that_many_cycles(
        make_body, delay):
    """
    Nothing arrives while the line is filling, and what arrives after is
    what was offered `delay` cycles ago — not a smoothed approximation
    of it.
    """
    org, channel = make_body(rate=1.0, delay=delay)
    offered: list = []
    for cycle in range(delay + 3):
        report = org.tick({"lamina_circulatory": {"HR": 200.0}})
        record = entry(report, channel)
        offered.append(record["reading"])
        if cycle < delay:
            assert record["transmitted"] is None, (
                f"cycle {cycle}: the line is still filling and delivered "
                f"anyway"
            )
        else:
            assert record["transmitted"] == pytest.approx(
                landed(org, offered[cycle - delay])), (
                f"cycle {cycle}: delivered something other than the reading "
                f"from {delay} cycles back"
            )


def test_the_delay_line_survives_a_gate_writing_its_own_state(make_body):
    """
    The bug the three-way state split was made for.

    A gate's contract is that its RETURN VALUE is its whole new state,
    so the container replaces that dict wholesale every cycle.  When the
    delay buffer shared the dict, it was emptied between being filled
    and being read, and a channel declaring `time_delay=1` delivered
    nothing, ever.  The buffer belongs to the CHANNEL now, and no gate
    can reach it.
    """
    org, channel = make_body(
        rate=1.0, delay=1,
        trigger=lambda s, v, p: {"open_fraction": 1.0, "noisy": True})
    report = run(org, 4)

    assert org._gate_state["tx_stub"] == {"open_fraction": 1.0, "noisy": True}
    assert "buffer" in org._channel_state[channel.id], (
        "the delay line is not in the channel's own state"
    )
    assert entry(report, channel)["transmitted"] is not None


def test_the_gate_and_the_channel_keep_separate_state(make_body):
    """
    Stated directly, because it is an invariant rather than a detail:
    neither owner's keys appear in the other's bag.
    """
    org, channel = make_body(rate=1.0, delay=1)
    run(org, 4)
    gate_state = org._gate_state["tx_stub"]
    channel_state = org._channel_state[channel.id]
    assert "buffer" not in gate_state
    assert "open_fraction" not in channel_state


# ══════════════════════════════════════════════════════════════════════
# The EWMA
# ══════════════════════════════════════════════════════════════════════

def test_the_receiver_walks_out_of_its_baseline_rather_than_jumping(make_body):
    """
    On the first crossing the filter is seeded from where the receiver
    already sits, so a seam resting on its declared 5.0 walks toward the
    sender instead of snapping to it.
    """
    org, channel = make_body(rate=0.2)
    first = org.tick({"lamina_circulatory": {"HR": 200.0}})
    target = landed(org, entry(first, channel)["reading"])
    arrived = co_ref(org).value
    assert 5.0 < arrived < target, (
        f"expected a step from 5.0 toward {target}, landed on {arrived}"
    )


def test_a_slower_rate_damps_the_senders_own_oscillation(make_body):
    """
    G4's main line.  Held at HR 200 the circulation's own loop makes
    cardiac output swing; a fast rate hands the receiver that argument
    verbatim, a slow one walks it up to the average.
    """
    def swing(rate):
        org, _ = make_body(rate=rate)
        seen = []
        for _ in range(12):
            org.tick({"lamina_circulatory": {"HR": 200.0}})
            seen.append(co_ref(org).value)
        return max(seen[4:]) - min(seen[4:])

    assert swing(0.2) < swing(1.0), (
        "a slower rate has to damp more, not less"
    )


def test_a_half_open_gate_moves_at_half_speed_rather_than_halving_the_value(
        make_body):
    """
    The open fraction goes into the RATE, never into the value.

    Multiplying the value would report a cardiac output of 2.4 L/min for
    a half-open gate on a real 4.8 — not a partial reading but a
    different and false one.  Into the rate, a half-open gate moves the
    receiver toward the true value at half speed, which is what a
    half-open valve does.
    """
    full, _ = make_body(rate=0.4, trigger=always_open)
    half, _ = make_body(rate=0.4, trigger=half_open)
    run(full, 1)
    run(half, 1)

    moved_full = co_ref(full).value - 5.0
    moved_half = co_ref(half).value - 5.0
    assert moved_half == pytest.approx(moved_full / 2, rel=1e-9), (
        "a half-open gate should move half as far, not carry half the value"
    )


def test_the_provenance_says_what_the_filter_is_walking_toward(make_body):
    """
    A reader should see the gap between where the receiver is and where
    it is heading, rather than inferring it from two ticks.
    """
    org, channel = make_body(rate=0.2)
    run(org, 3)
    provenance = co_ref(org).provenance
    assert provenance["channel"] == channel.id
    assert provenance["state"] == "coupled"
    assert provenance["target"] is not None
    assert provenance["rate"] == pytest.approx(0.2)


# ══════════════════════════════════════════════════════════════════════
# The weight — how much of the offer is taken
# ══════════════════════════════════════════════════════════════════════

def test_a_full_weight_takes_the_offer_whole(make_body):
    org, channel = make_body(rate=1.0, weight=1.0)
    report = run(org, 1)
    record = entry(report, channel)
    assert record["transmitted"] == pytest.approx(
        landed(org, record["reading"]))


def test_a_partial_weight_scales_the_deviation_not_the_value(make_body):
    """
    C5, and Q4 settled on 2026-09-03.  `received = baseline +
    weight*(offered - baseline)`.

    The alternative — multiplying the value — turns a cardiac output of
    4.8 at weight 0.5 into 2.4 L/min, which is not a partial reading of
    4.8 but a different and false one.  Information is the departure
    from what the receiver was already assuming, so that is what a
    partial coupling takes a fraction of.
    """
    org, channel = make_body(rate=1.0, weight=0.5)
    report = run(org, 1)
    record = entry(report, channel)
    baseline = co_ref(org).baseline
    offered = landed(org, record["reading"])
    expected = baseline + 0.5 * (offered - baseline)

    assert record["transmitted"] == pytest.approx(expected, rel=1e-9)
    assert record["transmitted"] != pytest.approx(offered * 0.5), (
        "the weight multiplied the value instead of the deviation"
    )


# ══════════════════════════════════════════════════════════════════════
# on_close
# ══════════════════════════════════════════════════════════════════════

def test_hold_keeps_the_last_value_and_lets_it_age(make_body):
    """
    The far side sees an old number labelled old, rather than one
    snapping back to a baseline nobody chose.
    """
    org, channel = make_body(rate=1.0, on_close="hold")
    run(org, 3)
    held = co_ref(org).value

    org.register_gate_controller("threshold", shut)
    run(org, 2)

    assert co_ref(org).value == held, "a held value must not move"
    provenance = co_ref(org).provenance
    assert provenance["state"] == "held"
    assert provenance["age"] >= 1, "a held value has to say how stale it is"


def test_decay_to_baseline_walks_back_to_the_declared_resting_value(make_body):
    """
    The other option, for a seam where a stale coupled value would be
    worse than an honest uninformed one — and the reason `<baseline>` is
    required on an INTER_LAMINA attribute at all (G9).
    """
    org, channel = make_body(rate=0.5, on_close="decay_to_baseline")
    run(org, 3)
    departed = co_ref(org).value
    assert departed != pytest.approx(5.0)

    org.register_gate_controller("threshold", shut)
    run(org, 4)

    assert abs(co_ref(org).value - 5.0) < abs(departed - 5.0), (
        "a decaying value has to move back toward the baseline"
    )
    assert co_ref(org).provenance["state"] == "decaying"


def test_a_seam_nothing_has_ever_crossed_has_nothing_to_hold_or_decay(
        make_body):
    """
    Nothing this channel ever carried is nothing it may claim.

    Decaying an untouched value toward the baseline it already sits on
    changes no number but stamps provenance on it, and an untouched
    baseline that looks like a decayed coupled value is worse than
    either.
    """
    org, channel = make_body(on_close="decay_to_baseline", trigger=shut)
    run(org, 4)
    assert co_ref(org).value == 5.0
    assert not co_ref(org).provenance, (
        "an uncoupled seam claimed a provenance it never earned"
    )


# ══════════════════════════════════════════════════════════════════════
# The band — refusing rather than clamping
# ══════════════════════════════════════════════════════════════════════

def test_a_banded_receptor_takes_a_value_inside_its_band(make_body):
    org, channel = make_body(rate=1.0, band=(0.0, 20.0))
    report = run(org, 2)
    assert entry(report, channel)["transmitted"] is not None


def test_a_banded_receptor_refuses_outside_the_band_rather_than_clamping(
        make_body):
    """
    Clamping is what the old soft_range gate did, and it silently pulled
    out-of-range physiology back toward normal — a MAP of 120 displayed
    as 110, masking the pathology the twin exists to show.  Refusing
    says "this seam does not model that", which is true; clamping says
    "it is 110", which is not.
    """
    org, channel = make_body(rate=1.0, band=(0.0, 6.0))
    report = run(org, 4, hr=200.0)
    record = entry(report, channel)

    assert record["transmitted"] is None
    assert co_ref(org).value == 5.0, (
        "the receiver took a clamped value instead of refusing"
    )
    assert record["state"] == "out of band", (
        "both gates are open but nothing crossed, and the report has to "
        "say which"
    )


def test_a_band_needs_both_edges(tmp_path):
    path = body_xml(tmp_path, band=(0.0, 6.0))
    path.write_text(path.read_text(encoding="utf-8")
                    .replace(' band_max="6.0"', ''), encoding="utf-8")
    with pytest.raises(OrganismError, match="two edges"):
        parse_organism(path)


def test_a_band_written_backwards_does_not_parse(tmp_path):
    path = body_xml(tmp_path, band=(6.0, 1.0))
    with pytest.raises(OrganismError, match="not below"):
        parse_organism(path)


# ══════════════════════════════════════════════════════════════════════
# Reporting
# ══════════════════════════════════════════════════════════════════════

def test_the_report_separates_gate_reasoning_from_channel_state(make_body):
    """
    Two owners, visible as two sub-objects.  A reader can see that the
    gates' decision and the wire's contents are different things, which
    is what stops the next person merging them again.
    """
    org, channel = make_body(rate=1.0)
    report = run(org, 2)
    record = entry(report, channel)

    assert record["transmit"][0]["open_fraction"] == 1.0     # the gate's
    assert record["channel_state"]["offered"] is not None    # the wire's
    assert "offered" not in record["transmit"][0]
    assert "open_fraction" not in record["channel_state"]


def test_why_it_last_did_not_carry_stops_being_true_when_it_does(make_body):
    """
    A report showing an open channel beside close_reason="out of band"
    is a small lie of the same family as everything else this phase
    spent its time on.
    """
    org, channel = make_body(rate=1.0, band=(0.0, 6.0))
    shut_report = run(org, 3, hr=200.0)
    assert entry(shut_report, channel)["channel_state"]["close_reason"] == \
        "out of band"

    open_report = run(org, 3, hr=72.0)
    record = entry(open_report, channel)
    if record["transmitted"] is not None:
        assert "close_reason" not in record["channel_state"]


def test_the_snapshot_carries_the_whole_provenance(make_body):
    org, channel = make_body(rate=0.2)
    run(org, 3)
    snapshot = org.snapshot()
    provenance = snapshot["channels"][0]["provenance"]
    for field in ("state", "channel", "from", "age", "target", "rate"):
        assert field in provenance, f"the snapshot dropped '{field}'"
