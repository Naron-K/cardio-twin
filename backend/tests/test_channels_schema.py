"""
The v2 `<channels>` contract, checked at parse time.

Every rule here is enforced when the file is READ, not when the body is
run, and that placement is the point being tested.  A body that couples
two laminae four levels apart, or hands one lamina nine gates on one
face, is not a body that behaves oddly later — it is a body that never
loads, with a message naming what to change.

Each test breaks exactly one thing in an otherwise valid declaration.
The valid declaration lives in `_body()` below rather than in a file, so
these tests cannot drift into agreeing with a shipped XML that has moved
on; the shipped bodies are still v1 at this point and are migrated in a
later phase.

Rules 2 and 3 (the source is a composite, the destination is declared
INTER_LAMINA) need the laminae themselves and so are not checked here —
they belong to `validate_against_laminae`, the same way they do in v1.
"""
import pytest

from organism import (
    AutoGate,
    Channel,
    KeyGate,
    OrganismError,
    parse_organism_v2,
)

# ── The valid declaration every test below mutates ────────────────────

AUTO_GATE = (
    '<auto_gate id="ta1" refractory_cycles="5">'
    '<threshold aggregate="deviation" reference="0.30"'
    ' open_above="0.125" close_below="0.09"/>'
    '</auto_gate>'
)
KEY_GATE = (
    '<key_gate id="rk1" weight="1.0" rate="0.2" on_close="hold"'
    ' confidence="0.8"><key metric="identity"/></key_gate>'
)
EXTRACT = '<extract mode="state"/>'

CIRC = "lamina_circulatory:output_state"
RESP = "lamina_respiratory:CO_ref"

TWO_LAMINAE = (
    '<lamina id="lamina_circulatory" level="1"/>'
    '<lamina id="lamina_respiratory" level="2"/>'
)
THREE_LAMINAE = TWO_LAMINAE + '<lamina id="lamina_third" level="3"/>'


def _channel(cid="c", frm=CIRC, to=RESP, transmit=AUTO_GATE, receive=KEY_GATE,
             extract=EXTRACT, time_delay="0"):
    """One `<channel>`, every part swappable."""
    return (
        f'<channel id="{cid}" from="{frm}" to="{to}" time_delay="{time_delay}">'
        f'{extract}'
        f'<transmit>{transmit}</transmit>'
        f'<receive>{receive}</receive>'
        f'</channel>'
    )


def _body(channels=None, laminae=TWO_LAMINAE):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<organism id="body_under_test" version="2.0">'
        '<name>Body under test</name>'
        f'<laminae>{laminae}</laminae>'
        f'<channels>{_channel() if channels is None else channels}</channels>'
        '</organism>'
    )


def _parse(tmp_path, xml, name="organism_v2.xml"):
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return parse_organism_v2(path)


def _auto(gate_id):
    return AUTO_GATE.replace('"ta1"', f'"{gate_id}"')


def _key(gate_id, **swaps):
    out = KEY_GATE.replace('"rk1"', f'"{gate_id}"')
    for old, new in swaps.items():
        out = out.replace(old, new)
    return out


# ── The declaration parses, and says what it declared ─────────────────

def test_a_valid_v2_body_parses_and_records_the_stack(tmp_path):
    """
    `levels` is the whole reason adjacency can be checked here: the stack
    is a property of THIS body, not of either lamina, so it is read off
    the organism file and nowhere else.
    """
    spec = _parse(tmp_path, _body())
    assert spec.levels == {
        "lamina_circulatory": 1,
        "lamina_respiratory": 2,
    }


def test_the_channel_carries_its_two_ends_and_one_extracted_attribute(tmp_path):
    channel = _parse(tmp_path, _body()).channels[0]
    assert isinstance(channel, Channel)
    assert (channel.source.lamina, channel.source.member) == \
        ("lamina_circulatory", "output_state")
    assert (channel.dest.lamina, channel.dest.member) == \
        ("lamina_respiratory", "CO_ref")
    assert channel.carry == "state"


def test_each_side_owns_its_own_gates(tmp_path):
    """
    L4, in one assertion: the gates are not a single list on the channel,
    they belong to a SIDE.  A transmit gate and a receive gate are two
    laminae's separate decisions about the same crossing.
    """
    channel = _parse(tmp_path, _body()).channels[0]
    assert [type(g) for g in channel.transmit] == [AutoGate]
    assert [type(g) for g in channel.receive] == [KeyGate]
    assert channel.transmit[0].side == "transmit"
    assert channel.receive[0].side == "receive"


def test_absorption_settings_belong_to_the_receiving_gate(tmp_path):
    """
    C6.  How fast a value is taken up is the receiver's business, so
    `rate` and `on_close` are read off the receive gate rather than off a
    transfer block shared with the sender.
    """
    receive_gate = _parse(tmp_path, _body()).channels[0].receive[0]
    assert receive_gate.rate == 0.2
    assert receive_gate.on_close == "hold"
    assert receive_gate.confidence == 0.8


def test_a_three_lamina_stack_couples_one_step_at_a_time(tmp_path):
    """1 → 2 → 3 is legal; 1 → 3 is the test below."""
    spec = _parse(tmp_path, _body(
        laminae=THREE_LAMINAE,
        channels=_channel("c_up")
        + _channel("c_up2", frm="lamina_respiratory:transport_state",
                   to="lamina_third:X", transmit=_auto("ta2"),
                   receive=_key("rk2")),
    ))
    assert [c.id for c in spec.channels] == ["c_up", "c_up2"]
    assert spec.levels["lamina_third"] == 3


def test_four_gates_on_one_face_is_the_limit_and_parses(tmp_path):
    """Rule 8 allows four; the fifth is refused in the test below."""
    four = "".join(_auto(f"ta{i}") for i in range(4))
    channel = _parse(tmp_path, _body(_channel(transmit=four))).channels[0]
    assert len(channel.transmit) == 4


def test_two_channels_may_leave_one_lamina_on_the_same_composite(tmp_path):
    """
    Rule 9 constrains the composite, not the number of channels: a lamina
    presents ONE face upward and may run several wires from it.
    """
    spec = _parse(tmp_path, _body(
        _channel("c1")
        + _channel("c2", to="lamina_respiratory:OTHER",
                   transmit=_auto("ta2"), receive=_key("rk2")),
    ))
    assert len(spec.channels) == 2


# ── Rule 1 — closed is the resting state ──────────────────────────────

def test_rule_1_a_gate_may_not_declare_itself_open(tmp_path):
    opened = AUTO_GATE.replace('refractory_cycles="5"',
                               'refractory_cycles="5" start_open="true"')
    with pytest.raises(OrganismError, match="CLOSED"):
        _parse(tmp_path, _body(_channel(transmit=opened)))


# ── Rule 4 — two boundaries, the shut one under the open one ──────────

def test_rule_4_one_boundary_does_not_parse(tmp_path):
    one_sided = AUTO_GATE.replace(' close_below="0.09"', '')
    with pytest.raises(OrganismError, match="close_below"):
        _parse(tmp_path, _body(_channel(transmit=one_sided)))


def test_rule_4_the_band_must_be_the_right_way_round(tmp_path):
    inverted = AUTO_GATE.replace('close_below="0.09"', 'close_below="0.5"')
    with pytest.raises(OrganismError, match="not below"):
        _parse(tmp_path, _body(_channel(transmit=inverted)))


def test_rule_4_does_not_apply_to_an_identity_key(tmp_path):
    """
    A label either matches or it does not.  There is no noise for a
    single boundary to chatter on, so demanding a band from `identity`
    would be a rule applied where its reason does not reach.
    """
    channel = _parse(tmp_path, _body()).channels[0]
    assert channel.receive[0].key["metric"] == "identity"


# ── Rule 6 — one destination attribute, one channel ───────────────────

def test_rule_6_two_channels_may_not_feed_one_attribute(tmp_path):
    """The message names BOTH channels: the reader has to pick one."""
    with pytest.raises(OrganismError, match="c1"):
        _parse(tmp_path, _body(
            _channel("c1")
            + _channel("c2", transmit=_auto("ta2"), receive=_key("rk2")),
        ))


# ── Rule 7 — only adjacent laminae couple ─────────────────────────────

def test_rule_7_a_channel_may_not_skip_a_level(tmp_path):
    with pytest.raises(OrganismError, match="level 1"):
        _parse(tmp_path, _body(laminae=THREE_LAMINAE,
                               channels=_channel(to="lamina_third:X")))


def test_rule_7_names_both_levels_so_the_reader_can_fix_it(tmp_path):
    with pytest.raises(OrganismError) as excinfo:
        _parse(tmp_path, _body(laminae=THREE_LAMINAE,
                               channels=_channel(to="lamina_third:X")))
    message = str(excinfo.value)
    assert "level 1" in message and "level 3" in message


# ── Rule 8 — at most four gates per (lamina, side, direction) ─────────

def test_rule_8_a_fifth_gate_on_one_face_does_not_parse(tmp_path):
    five = "".join(_auto(f"ta{i}") for i in range(5))
    with pytest.raises(OrganismError, match="at most 4"):
        _parse(tmp_path, _body(_channel(transmit=five)))


# ── Rule 9 — one interface composite per (lamina, direction) ─────────

def test_rule_9_one_lamina_presents_one_composite(tmp_path):
    """
    L1: from outside, a lamina IS its interface composite.  Two channels
    leaving it on different composites means the lamina is two different
    things to its neighbours, and the message names both channels.
    """
    with pytest.raises(OrganismError, match="c1"):
        _parse(tmp_path, _body(
            _channel("c1")
            + _channel("c2", frm="lamina_circulatory:other_state",
                       to="lamina_respiratory:OTHER",
                       transmit=_auto("ta2"), receive=_key("rk2")),
        ))


def test_rule_9_the_face_is_the_same_one_in_every_direction(tmp_path):
    """
    Q2, settled 2026-09-03: the strict reading.  A lamina in the middle
    of a stack does not get to show one composite upward and a different
    one downward — that is two laminae wearing one id.

    This is the case the looser per-direction reading would have let
    through, so it is the test that tells the two apart: `lamina_
    respiratory` sits at level 2 and here reaches both up to level 3 and
    down to level 1, on two different composites.
    """
    with pytest.raises(OrganismError, match="ONE interface composite"):
        _parse(tmp_path, _body(
            laminae=THREE_LAMINAE,
            channels=_channel("c_up", frm="lamina_respiratory:transport_state",
                              to="lamina_third:X")
            + _channel("c_down", frm="lamina_respiratory:other_state",
                       to="lamina_circulatory:CO_ref",
                       transmit=_auto("ta2"), receive=_key("rk2")),
        ))


def test_rule_9_the_same_face_in_both_directions_parses(tmp_path):
    """The converse: one composite reaching both neighbours is legal."""
    spec = _parse(tmp_path, _body(
        laminae=THREE_LAMINAE,
        channels=_channel("c_up", frm="lamina_respiratory:transport_state",
                          to="lamina_third:X")
        + _channel("c_down", frm="lamina_respiratory:transport_state",
                   to="lamina_circulatory:CO_ref",
                   transmit=_auto("ta2"), receive=_key("rk2")),
    ))
    assert [c.id for c in spec.channels] == ["c_up", "c_down"]


# ── Rule 10 — the lambda is deferred, and says so ────────────────────

def test_rule_10_a_transform_is_refused_rather_than_ignored(tmp_path):
    """
    Refusing beats ignoring: a body carrying a transform nobody applies
    would run, and quietly mean something other than what it says.
    """
    with_transform = EXTRACT + '<transform><formula>x*2</formula></transform>'
    with pytest.raises(OrganismError, match="transform"):
        _parse(tmp_path, _body(_channel(extract=with_transform)))


# ── Rule 11 — the v1 schema is refused, and points at the new one ────

def test_rule_11_the_old_schema_is_refused(tmp_path):
    old = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<organism id="body_under_test" version="2.0"><name>Old</name>'
        f'<laminae>{TWO_LAMINAE}</laminae>'
        '<permeability_gates><gate id="g" from="a:b" to="c:d"'
        ' controller="threshold"/></permeability_gates>'
        '</organism>'
    )
    with pytest.raises(OrganismError, match="<channels>"):
        _parse(tmp_path, old)


def test_rule_11_the_message_names_the_replacement_not_just_the_problem(
        tmp_path):
    """
    C13.  A v1 body that "almost" ran on the v2 container is the hardest
    class of bug to see, so the refusal has to hand the reader the name
    of the thing to write instead.
    """
    old = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<organism id="b" version="2.0"><name>Old</name>'
        f'<laminae>{TWO_LAMINAE}</laminae>'
        '<permeability_gates><gate id="g" from="a:b" to="c:d"'
        ' controller="threshold"/></permeability_gates>'
        '</organism>'
    )
    with pytest.raises(OrganismError) as excinfo:
        _parse(tmp_path, old)
    assert "<channels>" in str(excinfo.value)


# ── Rule 12 — neither side may be empty ──────────────────────────────

def test_rule_12_a_channel_needs_a_gate_on_the_sending_side(tmp_path):
    with pytest.raises(OrganismError, match="transmit"):
        _parse(tmp_path, _body(_channel(transmit="")))


def test_rule_12_a_channel_needs_a_gate_on_the_receiving_side(tmp_path):
    """
    A receive side with no gate is a wire that writes straight into the
    far lamina's state — precisely the arrangement the two-sided design
    exists to forbid, so it is refused rather than defaulted.
    """
    with pytest.raises(OrganismError, match="receive"):
        _parse(tmp_path, _body(_channel(receive="")))


# ── The stack must be declared ───────────────────────────────────────

def test_a_lamina_without_a_level_does_not_parse(tmp_path):
    no_level = ('<lamina id="lamina_circulatory"/>'
                '<lamina id="lamina_respiratory" level="2"/>')
    with pytest.raises(OrganismError, match="level"):
        _parse(tmp_path, _body(laminae=no_level))


def test_a_level_that_is_not_a_whole_number_does_not_parse(tmp_path):
    fractional = TWO_LAMINAE.replace('level="1"', 'level="1.5"')
    with pytest.raises(OrganismError, match="integer"):
        _parse(tmp_path, _body(laminae=fractional))


# ── Guards — malformed numbers fail loudly ───────────────────────────

@pytest.mark.parametrize("attribute,bad,needle", [
    ("weight", "1.7", "weight"),
    ("rate", "-0.2", "rate"),
    ("confidence", "2.5", "confidence"),
])
def test_a_fraction_outside_its_range_does_not_parse(
        tmp_path, attribute, bad, needle):
    """
    Every one of these lives in the normalised [0, 1] space.  A weight of
    1.7 is not a stronger coupling, it is a declaration nobody has
    defined a meaning for.
    """
    gate = KEY_GATE.replace(f'{attribute}="1.0"', f'{attribute}="{bad}"') \
                   .replace(f'{attribute}="0.2"', f'{attribute}="{bad}"') \
                   .replace(f'{attribute}="0.8"', f'{attribute}="{bad}"')
    with pytest.raises(OrganismError, match=needle):
        _parse(tmp_path, _body(_channel(receive=gate)))


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf"])
def test_a_non_finite_number_does_not_parse(tmp_path, bad):
    """
    NaN makes every comparison False — a gate that can never decide — and
    an infinity makes a deadband no signal can leave.  Both would run.
    """
    gate = KEY_GATE.replace('confidence="0.8"', f'confidence="{bad}"')
    with pytest.raises(OrganismError, match="finite"):
        _parse(tmp_path, _body(_channel(receive=gate)))


def test_a_non_numeric_number_does_not_parse(tmp_path):
    gate = KEY_GATE.replace('weight="1.0"', 'weight="banana"')
    with pytest.raises(OrganismError, match="non-numeric"):
        _parse(tmp_path, _body(_channel(receive=gate)))


def test_an_unknown_on_close_does_not_parse(tmp_path):
    gate = KEY_GATE.replace('on_close="hold"', 'on_close="explode"')
    with pytest.raises(OrganismError, match="on_close"):
        _parse(tmp_path, _body(_channel(receive=gate)))


def test_an_unknown_key_metric_does_not_parse(tmp_path):
    gate = KEY_GATE.replace('metric="identity"', 'metric="telepathy"')
    with pytest.raises(OrganismError, match="metric"):
        _parse(tmp_path, _body(_channel(receive=gate)))


def test_a_negative_time_delay_does_not_parse(tmp_path):
    """A delay line cannot run backwards, and a negative one would be
    read as an unsigned length somewhere downstream."""
    with pytest.raises(OrganismError, match="delay"):
        _parse(tmp_path, _body(_channel(time_delay="-3")))


def test_an_address_without_a_lamina_half_does_not_parse(tmp_path):
    with pytest.raises(OrganismError, match="lamina_id"):
        _parse(tmp_path, _body(_channel(frm="no_colon")))


def test_a_bad_address_is_blamed_on_the_channel_not_on_a_gate(tmp_path):
    """
    In v2 both ends belong to the CHANNEL and the gates sit on them, so
    a message saying "Gate" would send the reader hunting for a gate id
    that is not in their file.
    """
    with pytest.raises(OrganismError, match="Channel"):
        _parse(tmp_path, _body(_channel(frm="no_colon")))


def test_a_channel_without_an_id_does_not_parse(tmp_path):
    with pytest.raises(OrganismError, match="id"):
        _parse(tmp_path, _body(_channel(cid="")))
