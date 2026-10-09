"""
Phase 3 — the stack rules, on a body tall enough for them to mean
something.

Rules 7, 8 and 9 are all about a lamina's position among its neighbours,
and with only two laminae every one of them is trivial: two laminae are
always adjacent, a lamina with one neighbour has one face, and "the same
composite in every direction" has only one direction to be the same in.

So these build a three-deep stack, where the middle lamina has a
neighbour above AND below.  That is the shape the rules were written
for, and it is where the reading of each one actually shows.

Everything here is decided at PARSE time, so the bodies name laminae
that do not exist on disk.  What the laminae actually declare is rules 2
and 3, checked against real twins elsewhere; nothing in this file needs
a twin, and giving it one would make every test also a test of
physiology.
"""
import pytest

from organism import MAX_GATES_PER_FACE, OrganismError, parse_organism_v2

# ── Building a stack ──────────────────────────────────────────────────

AUTO = ('<auto_gate id="{gid}" refractory_cycles="0">'
        '<threshold aggregate="state"'
        ' open_above="0.6" close_below="0.4"/>'
        '</auto_gate>')
KEY = ('<key_gate id="{gid}" weight="1.0" rate="0.2" on_close="hold"'
       ' confidence="0.8"><key metric="identity"/></key_gate>')


def gates(template, prefix, count):
    return "".join(template.format(gid=f"{prefix}{i}") for i in range(count))


def channel(cid, frm, to, transmit=1, receive=1, composite="face"):
    """One channel, with however many gates on each of its two ends."""
    return (
        f'<channel id="{cid}" from="{frm}:{composite}" to="{to}:in_{cid}"'
        f' time_delay="0"><extract mode="state"/>'
        f'<transmit>{gates(AUTO, f"{cid}_tx", transmit)}</transmit>'
        f'<receive>{gates(KEY, f"{cid}_rx", receive)}</receive>'
        f'</channel>'
    )


def stack(channels, levels=(("l1", 1), ("l2", 2), ("l3", 3))):
    laminae = "".join(f'<lamina id="{lid}" level="{lvl}"/>'
                      for lid, lvl in levels)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<organism id="stack" version="2.0"><name>Stack</name>'
        f'<laminae>{laminae}</laminae>'
        f'<channels>{"".join(channels)}</channels></organism>'
    )


def parse(tmp_path, xml, name="stack.xml"):
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return parse_organism_v2(path)


# ══════════════════════════════════════════════════════════════════════
# Rule 7 — a channel steps exactly one level
# ══════════════════════════════════════════════════════════════════════

def test_a_stack_is_climbed_one_step_at_a_time(tmp_path):
    spec = parse(tmp_path, stack([
        channel("a", "l1", "l2"),
        channel("b", "l2", "l3"),
    ]))
    assert [c.id for c in spec.channels] == ["a", "b"]
    assert spec.levels == {"l1": 1, "l2": 2, "l3": 3}


def test_a_channel_may_not_skip_the_middle_lamina(tmp_path):
    """
    L2's whole point: coupling a lamina to its grandparent hides the
    layer that should be mediating, which is where cross-laminar chaos
    comes from.  If the middle really has nothing to add, that is a
    claim about the model, and the way to make it is to take the middle
    out of the stack — not to reach around it.
    """
    with pytest.raises(OrganismError) as excinfo:
        parse(tmp_path, stack([channel("skip", "l1", "l3")]))
    message = str(excinfo.value)
    assert "level 1" in message and "level 3" in message, (
        "the message has to name both ends' levels, or the reader cannot "
        "tell which one to move"
    )


def test_the_direction_of_travel_does_not_matter_only_the_distance(tmp_path):
    """Downward is as legal as upward; it is the step size that is ruled on."""
    spec = parse(tmp_path, stack([
        channel("down", "l3", "l2"),
        channel("up", "l2", "l3", composite="face"),
    ]))
    assert len(spec.channels) == 2


def test_a_channel_to_the_same_lamina_is_refused_in_its_own_words(tmp_path):
    """
    Adjacency would catch this anyway — the distance is 0, not 1 — but
    the message it produces names one lamina twice with one level and
    reads like a claim about two different ones.
    """
    with pytest.raises(OrganismError, match="to itself"):
        parse(tmp_path, stack([channel("self", "l2", "l2")]))


def test_a_lamina_with_no_declared_level_has_no_place_in_the_stack(tmp_path):
    xml = stack([channel("a", "l1", "l2")]).replace('<lamina id="l2" level="2"/>',
                                                    '<lamina id="l2"/>')
    with pytest.raises(OrganismError, match="level"):
        parse(tmp_path, xml)


# ══════════════════════════════════════════════════════════════════════
# Rule 8 — four gates to a face, so eight to a lamina
# ══════════════════════════════════════════════════════════════════════

def test_a_lamina_carries_four_gates_on_a_face(tmp_path):
    spec = parse(tmp_path, stack([
        channel("a", "l1", "l2", transmit=MAX_GATES_PER_FACE),
    ]))
    assert len(spec.channels[0].transmit) == MAX_GATES_PER_FACE


def test_a_fifth_gate_on_one_face_is_refused(tmp_path):
    with pytest.raises(OrganismError, match="at most 4 per face"):
        parse(tmp_path, stack([
            channel("a", "l1", "l2", transmit=MAX_GATES_PER_FACE + 1),
        ]))


def test_the_limit_is_per_face_and_counts_across_channels(tmp_path):
    """
    Rule 8 is about the LAMINA, not about one declaration.  Three gates
    on one channel and two on another, both leaving the same face, is
    five gates on that face however it was written down.
    """
    with pytest.raises(OrganismError, match="upward face"):
        parse(tmp_path, stack([
            channel("a", "l2", "l3", transmit=3),
            channel("b", "l2", "l3", transmit=2),
        ]))


def test_the_same_gates_split_across_two_faces_are_fine(tmp_path):
    """
    The control for the test above: five gates on one lamina is not the
    problem, five on one FACE is.  Three up and two down is eight short
    of nothing and parses.
    """
    spec = parse(tmp_path, stack([
        channel("up", "l2", "l3", transmit=3),
        channel("down", "l2", "l1", transmit=2),
    ]))
    assert len(spec.channels) == 2


def test_a_middle_lamina_may_carry_a_full_face_in_each_direction(tmp_path):
    """
    Lee's eight, spelled out: four up and four down, on the one lamina in
    this stack that has both.

    `l2` sends up to `l3` and down to `l1`, and receives from each. Its
    upward face carries the gates pointed at `l3` — the ones it transmits
    through and the ones it receives through — and its downward face the
    ones pointed at `l1`.
    """
    spec = parse(tmp_path, stack([
        channel("up_out", "l2", "l3", transmit=2, receive=1),
        channel("up_in", "l3", "l2", transmit=1, receive=2),
        channel("down_out", "l2", "l1", transmit=2, receive=1),
        channel("down_in", "l1", "l2", transmit=1, receive=2),
    ]))
    assert len(spec.channels) == 4
    assert len(spec.gates_on("l2")) == 8, (
        "the middle lamina should hold four gates on each of its two faces"
    )


def test_a_receiving_laminas_gates_sit_on_the_face_the_wire_arrives_at(
        tmp_path):
    """
    The reading the first implementation got wrong, and the reason a
    three-deep stack is needed to see it.

    A wire that travels UP presents the receiving lamina with a DOWNWARD
    face: the sender looks toward the destination, the receiver looks
    back toward the source.  Filing both ends under the channel's own
    direction puts a receiver's gates on the face away from the thing
    they are receiving from, and quietly doubles what a lamina may
    carry.

    Here `l2` receives four gates from below and transmits four upward.
    Those are two different faces and both are legal; under the wrong
    reading they would be one face of eight, and refused.
    """
    spec = parse(tmp_path, stack([
        channel("from_below", "l1", "l2", transmit=1, receive=4),
        channel("to_above", "l2", "l3", transmit=4, receive=1),
    ]))
    assert len(spec.gates_on("l2")) == 8


def test_five_on_the_face_a_wire_arrives_at_is_still_refused(tmp_path):
    """The converse, so the fix above is not just a bigger allowance."""
    with pytest.raises(OrganismError, match="downward face"):
        parse(tmp_path, stack([
            channel("from_below", "l1", "l2", receive=5),
        ]))


# ══════════════════════════════════════════════════════════════════════
# Rule 9 — one interface composite, the same one every way
# ══════════════════════════════════════════════════════════════════════

def test_a_middle_lamina_shows_one_face_to_both_neighbours(tmp_path):
    """
    Q2's strict reading, on the only lamina that can break it.  `l2`
    reaches up to `l3` and down to `l1`, and both channels have to leave
    on the same composite: from outside, `l2` IS that composite, and a
    lamina that is one thing upward and another downward is two laminae
    sharing an id.
    """
    spec = parse(tmp_path, stack([
        channel("up", "l2", "l3", composite="face"),
        channel("down", "l2", "l1", composite="face"),
    ]))
    assert {c.source.member for c in spec.channels} == {"face"}


def test_a_middle_lamina_may_not_show_two_different_faces(tmp_path):
    with pytest.raises(OrganismError, match="ONE interface composite"):
        parse(tmp_path, stack([
            channel("up", "l2", "l3", composite="upper_face"),
            channel("down", "l2", "l1", composite="lower_face"),
        ]))


def test_the_message_names_both_channels_so_either_can_be_the_one_that_moves(
        tmp_path):
    with pytest.raises(OrganismError) as excinfo:
        parse(tmp_path, stack([
            channel("up", "l2", "l3", composite="upper_face"),
            channel("down", "l2", "l1", composite="lower_face"),
        ]))
    message = str(excinfo.value)
    assert "up" in message and "down" in message


def test_two_channels_out_of_one_face_on_one_composite_are_fine(tmp_path):
    """
    Rule 9 constrains the composite, not the number of wires.  A lamina
    presenting one face may run several channels from it — that is what
    one state feeding two downstream systems looks like.
    """
    spec = parse(tmp_path, stack([
        channel("a", "l2", "l3"),
        channel("b", "l2", "l1"),
    ]))
    assert len(spec.channels) == 2


# ══════════════════════════════════════════════════════════════════════
# The stack as a whole
# ══════════════════════════════════════════════════════════════════════

def test_every_lamina_knows_which_channels_touch_it(tmp_path):
    spec = parse(tmp_path, stack([
        channel("a", "l1", "l2"),
        channel("b", "l2", "l3"),
    ]))
    assert [c.id for c in spec.channels_out_of("l2")] == ["b"]
    assert [c.id for c in spec.channels_into("l2")] == ["a"]
    assert spec.channels_into("l1") == []
    assert spec.channels_out_of("l3") == []


def test_a_channel_naming_a_lamina_the_stack_does_not_list_is_refused(
        tmp_path):
    with pytest.raises(OrganismError, match="does not list"):
        parse(tmp_path, stack([channel("a", "l2", "l4")]))
