"""
Organism — the body-level declaration, and the rules it must obey.

A lamina is one system.  An organism is several, plus the topology
joining them, which belongs to none of them: "circulation feeds oxygen
delivery" is not a fact about the circulatory file or the respiratory
one, and writing it into either would make that lamina un-runnable
alone.  `organism.xml` holds it instead, one level up.

Two things live here.

`parse_organism` / `load_organism` are the CONTRACT (Phase 1): the shape
of the declaration and the five rules enforced the moment it is read.

`Organism` is the CONTAINER (Phase 2): several laminae, their feedback
controllers, and the one tick order that says when a value crosses
between them.

`threshold_gate_controller` / `key_gate_controller` are the two v1 gate
controllers (Phase 3): the first decides whether the source composite is
doing enough to be worth passing on, the second whether it looks like a
state somebody is waiting for.

`Organism._transfer` is the transfer engine (Phase 4): a delay line, a
low-pass filter, and a policy for what the receiver is left holding once
the gate shuts.

The rules are enforced at PARSE time on purpose.  A topology error —
a gate pointed at an attribute that cannot receive, a hysteresis band
written backwards — is a statement about the model that is wrong, and
the cheapest moment to say so is before anything runs.  The same
argument as `_parse_tags` validating tag addresses rather than
discovering them on the first feedback cycle (D5).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from feedback_controller import (
    DEFAULT_EPSILON_RATIO,
    DEFAULT_MAX_NORM,
    FeedbackController,
)
from laminae import load_twin, resolve_lamina
from snapshot import _simulation_snapshot
from universal_twin import INTER_LAMINA, UniversalTwin

#: Where `<organism>` lives when nobody names a file.
DEFAULT_ORGANISM = Path(__file__).parent / "organism.xml"

#: Address separator for a cross-lamina reference, `<lamina>:<member>`.
_ADDR_SEP = ":"

#: Gate controllers the schema accepts.  Their implementations land in
#: Phase 3; naming the set here is what makes an unknown one a parse
#: error rather than a gate that silently never opens.
KNOWN_CONTROLLERS = frozenset({"threshold", "key"})

#: What a gate does with its last transmitted value once it shuts.
KNOWN_ON_CLOSE = frozenset({"hold", "decay_to_baseline"})

#: How the controller reduces the source composite's normalised vector
#: to the single number its thresholds compare against.
#:
#: `deviation` is the two-sided one, and it exists because the other
#: three are not.  A threshold on a raw value can only ask "is this high
#: enough"; a seam that opens when a pump runs fast and stays shut when
#: the same pump fails is watching one half of the thing it claims to
#: watch.  `deviation` compares against a declared reference point in the
#: same [0,1] space, so departure in EITHER direction reads as one
#: number and one pair of thresholds covers both.
KNOWN_AGGREGATES = frozenset({"attr", "mean", "max", "deviation"})

#: What the transfer stage does with the value once the gate is open.
#: `proportional` carries it, smoothed; `band` carries it only while it
#: lies inside a declared range and refuses outside, rather than
#: clamping — see _transfer for why refusing beats clamping.
KNOWN_TRANSFER_MODES = frozenset({"proportional", "band"})

#: The metric a v2 `<key>` may match on (GATE_CHANNELS_PLAN C3).
#: `identity` matches a LABEL — the composite id carried on the channel —
#: and so needs no thresholds: a label either matches or it does not,
#: which is exactly what rule 4's exemption is for.  `weighted_distance`
#: and `cosine` match a SHAPE, which lives in normalised [0,1] space and
#: needs the same two-boundary deadband as every other trigger (G3).
KNOWN_KEY_METRICS = frozenset({"identity", "weighted_distance", "cosine"})

#: The trigger an `<auto_gate>` answers to.  `<threshold>` is the v1
#: deviation/attr decision made local to its own lamina; `<pattern>` is
#: where a weighted-distance match against the lamina's OWN composite
#: lands — the failing-pump recogniser from organism_key.xml recognises
#: an internal state, so in Lee's transmit/receive split it is an auto
#: gate with a pattern trigger, never a key gate.
KNOWN_TRIGGER_KINDS = frozenset({"threshold", "pattern"})

#: The two gate elements a v2 transmit/receive side may carry.  Naming
#: the set here is what makes a third element a parse error rather than
#: a declared gate that silently never runs (the v1 lesson of
#: KNOWN_CONTROLLERS).
KNOWN_V2_GATE_TAGS = frozenset({"auto_gate", "key_gate"})

#: The most gates one FACE of a lamina may carry (rule 8).
#:
#: L5 says at most 8 per lamina, 4 up and 4 down.  A lamina has exactly
#: two faces — one toward the layer above, one toward the layer below —
#: and every gate it owns sits on one of them, whether it is transmitting
#: through that face or receiving through it.  So the count is per
#: (lamina, face) with both sides summed, and 4 + 4 comes to Lee's 8.
#:
#: Counting per (lamina, side, face) instead would allow sixteen, which
#: is not the rule Lee wrote; and taking the CHANNEL's direction as the
#: face for both ends would file a receiving lamina's gates under the
#: direction the value travels rather than the direction it arrives
#: from — putting the respiratory lamina's receptors on its upward face
#: when the wire reaches it from below.
MAX_GATES_PER_FACE = 4


class OrganismError(ValueError):
    """A declaration that breaks one of the five rules."""


# ──────────────────────────────────────────────────────────────────────
# Parsed shapes
# ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class GateEndpoint:
    """One end of a gate: `<lamina_id>:<member_id>`."""
    lamina: str
    member: str

    def __str__(self) -> str:                      # pragma: no cover — display
        return f"{self.lamina}{_ADDR_SEP}{self.member}"


@dataclass
@dataclass
class Learnable:
    """
    A parameter something is allowed to adapt, and the box it must stay in.

    Rule 5 / G8.  Nothing in v1 learns any of these — the key vector is
    static and drift is measured before it is corrected (G7) — but the
    clamp is mandatory at declaration time, while there is one place to
    require it, rather than after the number of learnable parameters has
    grown past the point where anyone can list them.
    """
    name: str
    min: float
    max: float
    initial: Optional[float] = None


@dataclass
class OrganismSpec:
    """The parsed `organism.xml`: which laminae, where they stand, and
    what crosses between them."""
    id: str
    version: str
    lamina_ids: list
    #: list[Channel] — every one-way crossing this body declares.
    channels: list = field(default_factory=list)
    name: str = ""
    description: str = ""
    #: Each lamina's place in the stack, `<lamina_id> → level`.  The
    #: level is a property of THIS body, not of the lamina — the same
    #: lamina can stand at a different height in another organism —
    #: which is why it is read here and not off the lamina file, and why
    #: adjacency (rule 7) is decided against this.
    levels: dict = field(default_factory=dict)

    def channels_into(self, lamina_id: str) -> list:
        """Every channel whose destination is this lamina."""
        return [c for c in self.channels if c.dest.lamina == lamina_id]

    def channels_out_of(self, lamina_id: str) -> list:
        """Every channel whose source is this lamina."""
        return [c for c in self.channels if c.source.lamina == lamina_id]

    def gates_on(self, lamina_id: str) -> list:
        """
        Every gate sitting on this lamina's membrane, either side.

        A gate belongs to the lamina it is ON, which is the transmit
        side of a channel leaving it and the receive side of a channel
        arriving at it — the two faces rule 8 counts separately.
        """
        out = []
        for channel in self.channels:
            if channel.source.lamina == lamina_id:
                out.extend(channel.transmit)
            if channel.dest.lamina == lamina_id:
                out.extend(channel.receive)
        return out


# ──────────────────────────────────────────────────────────────────────
# Parsing
# ──────────────────────────────────────────────────────────────────────

def _endpoint(raw: str, gate_id: str, which: str,
              owner_kind: str = "Gate") -> GateEndpoint:
    """
    Split `<lamina>:<member>`, refusing anything else.

    `owner_kind` names what is being blamed.  In v1 both ends of a
    crossing belong to a gate; in v2 they belong to the CHANNEL and the
    gates sit on its two ends, so a v2 message that said "Gate" would
    send the reader looking for a gate id that is not in their file.
    """
    addr = (raw or "").strip()
    if _ADDR_SEP not in addr:
        raise OrganismError(
            f"{owner_kind} '{gate_id}' {which}='{raw}' must be of the form "
            f"'<lamina_id>{_ADDR_SEP}<member_id>'. A crossing runs between "
            f"laminae, so both ends name the lamina they are on."
        )
    lamina, _, member = addr.partition(_ADDR_SEP)
    lamina, member = lamina.strip(), member.strip()
    if not lamina or not member:
        raise OrganismError(
            f"{owner_kind} '{gate_id}' {which}='{raw}' has an empty half."
        )
    return GateEndpoint(lamina=lamina, member=member)


def _float_attr(el, name: str, gate_id: str,
                default: Optional[float] = None) -> Optional[float]:
    raw = el.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return float(raw)
    except ValueError as e:
        raise OrganismError(
            f"Gate '{gate_id}' has non-numeric {name}='{raw}'."
        ) from e


def _parse_learnables(gate_el, gate_id: str) -> list:
    """
    Rule 5 / G8 — a learnable parameter without a clamp does not parse.

    The check is on the DECLARATION, not on any adaptation code, so it
    holds before there is adaptation code to check.
    """
    out: list = []
    for el in gate_el.findall(".//learnable"):
        name = (el.get("name") or "").strip()
        if not name:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <learnable> with no name."
            )
        lo, hi = el.get("min"), el.get("max")
        if lo is None or hi is None:
            raise OrganismError(
                f"Gate '{gate_id}' learnable '{name}' declares no "
                f"{'min' if lo is None else 'max'}. Anything that may be "
                f"learned must be declared with a clamp on it — an "
                f"unbounded learnable parameter is how a model stops "
                f"being something anyone can account for (G8)."
            )
        lo_f, hi_f = float(lo), float(hi)
        if not lo_f < hi_f:
            raise OrganismError(
                f"Gate '{gate_id}' learnable '{name}' has min={lo_f} "
                f"which is not below max={hi_f}."
            )
        initial = _float_attr(el, "initial", gate_id)
        if initial is not None and not lo_f <= initial <= hi_f:
            raise OrganismError(
                f"Gate '{gate_id}' learnable '{name}' starts at {initial}, "
                f"outside its own clamp [{lo_f}, {hi_f}]."
            )
        out.append(Learnable(name=name, min=lo_f, max=hi_f, initial=initial))
    return out


def available_organisms() -> list:
    """
    Every body file this backend can serve.

    Mirrors `available_laminae`, and for the same reason it exists there:
    adding a body should be dropping an XML file into `backend/`, not that
    plus an edit to a list somewhere else that will be forgotten. Anything
    matching `organism*.xml` whose root is <organism> and which carries an
    id is offered.

    A file that does not parse is skipped rather than listed, because this
    is a menu of things you can open and a broken file is not one. It is
    still refused BY NAME if somebody asks for it directly — silently
    dropping it from a listing and silently substituting the default for a
    direct request are different failures, and only the second one lies.
    """
    found: list = []
    for path in sorted(DEFAULT_ORGANISM.parent.glob("organism*.xml")):
        try:
            root = ET.parse(str(path)).getroot()
        except ET.ParseError:
            continue
        if root.tag != "organism" or not root.get("id"):
            continue
        found.append({
            "id":      root.get("id"),
            "name":    (root.findtext("name", "") or path.stem).strip(),
            "file":    path.name,
            "default": path.resolve() == DEFAULT_ORGANISM.resolve(),
            "channels": len(root.findall(".//channels/channel")),
        })
    return found


def resolve_organism(organism: str | Path | None) -> Path:
    """
    The file for a body, named by its id, its filename, or a path.

    Id first, the same way `resolve_lamina` works: a URL should not depend
    on where a file sits on disk. Filename and path still resolve, because
    the WebSocket has accepted them since Phase 2 and tests address temp
    files that way.

    An unknown name raises FileNotFoundError rather than falling back to
    the default — handing somebody the default body when they asked for a
    different one is the mismatch this resolution exists to prevent, and
    it arrives looking like a success.
    """
    if organism is None:
        return DEFAULT_ORGANISM
    for entry in available_organisms():
        if organism in (entry["id"], entry["file"]):
            return DEFAULT_ORGANISM.parent / entry["file"]
    candidate = Path(organism)
    if candidate.exists():
        return candidate
    known = [e["id"] for e in available_organisms()]
    raise FileNotFoundError(
        f"No organism '{organism}'. Known bodies: {known}."
    )


def parse_organism(path: Path | str | None = None) -> OrganismSpec:
    """
    Read a body file and check everything that does not need the laminae.

    One entry point, one schema.  `resolve_organism` turns an id, a
    filename or a path into a file; `parse_organism_v2` reads it and
    enforces every rule decidable from the declaration alone — 1, 4, 5,
    6 and the stack rules 7 to 12.  Rules 2 and 3 are about what the two
    laminae actually declare, so they need the laminae; see
    `validate_against_laminae`.  `load_organism` does both.

    There is deliberately no v1 fallback.  A `<permeability_gates>` body
    is refused by name, with a message pointing at `<channels>`, rather
    than being reinterpreted: a one-valve declaration running "almost
    right" on a two-sided container is the hardest class of bug to see,
    because every number it produces looks plausible.
    """
    return parse_organism_v2(resolve_organism(path))


def validate_against_laminae(spec: OrganismSpec,
                             twins: dict) -> None:
    """
    Rules 2 and 3 — the ones only the laminae can answer.

    2. The source of a crossing is a COMPOSITE (G5).  A composite is the
       unit a lamina already reasons about: it is what a tag addresses
       and what carries the distribution weights, so a channel reading
       one is reading something the model itself says belongs together.
       A bare attribute would let a channel reach past the model's own
       idea of structure.

    3. The destination is an attribute declared INTER_LAMINA.  Writing
       into another lamina's SENSOR forges a measurement; writing into
       its PRELIMINARY overwrites something it computes for itself.  The
       receiving lamina has to have said "this is where somebody else's
       number attaches" first — which is exactly what the source
       declaration is for.

    A gate's own coordinates are checked against the composite it will
    actually be given at runtime, and which composite that is depends on
    the side the gate sits on: a transmit gate reads its own lamina's
    face, and so does a receive-side AUTO gate, while a receive-side KEY
    gate reads what the channel presents — which is the sender's face.
    Checking the wrong one here would pass a body that fails on its
    first tick, which is the failure this function exists to move
    forward in time.
    """
    for lamina_id in spec.lamina_ids:
        if lamina_id not in twins:
            raise OrganismError(
                f"Organism '{spec.id}' lists lamina '{lamina_id}' but no twin "
                f"was supplied for it."
            )

    for channel in spec.channels:
        src_twin: UniversalTwin = twins[channel.source.lamina]
        dst_twin: UniversalTwin = twins[channel.dest.lamina]

        # ── Rule 2 ───────────────────────────────────────────────────
        if channel.source.member not in src_twin.composites:
            hint = ""
            if channel.source.member in src_twin.attributes:
                hint = (
                    f" '{channel.source.member}' is an attribute there; name "
                    f"the composite that holds it and use <extract> to pick "
                    f"it out."
                )
            raise OrganismError(
                f"Channel '{channel.id}' reads '{channel.source}', which is "
                f"not a composite on lamina '{channel.source.lamina}'.{hint} "
                f"Known composites: {sorted(src_twin.composites)}."
            )
        composite = src_twin.composites[channel.source.member]
        if channel.extract not in composite.attribute_ids:
            raise OrganismError(
                f"Channel '{channel.id}' extracts '{channel.extract}', which "
                f"is not in composite '{channel.source.member}'. It holds: "
                f"{composite.attribute_ids}."
            )

        # ── Rule 3 ───────────────────────────────────────────────────
        dest_attr = dst_twin.attributes.get(channel.dest.member)
        if dest_attr is None:
            raise OrganismError(
                f"Channel '{channel.id}' writes to '{channel.dest}', which "
                f"lamina '{channel.dest.lamina}' does not declare."
            )
        if dest_attr.source != INTER_LAMINA:
            raise OrganismError(
                f"Channel '{channel.id}' writes to '{channel.dest}', declared "
                f"{dest_attr.source}. A channel may only write an attribute "
                f"the receiving lamina declared as {INTER_LAMINA}: writing a "
                f"SENSOR forges a measurement, and writing a PRELIMINARY "
                f"overwrites something that lamina computes for itself."
            )

        # ── Every gate's coordinates exist on the composite it reads ──
        for gate in channel.transmit:
            _validate_gate_coordinates(gate, channel, composite,
                                       channel.source.member)
        for gate in channel.receive:
            if isinstance(gate, AutoGate):
                face = _lamina_face(spec, channel.dest.lamina)
                if face is None:
                    raise OrganismError(
                        f"Gate '{gate.id}' is an auto gate on lamina "
                        f"'{channel.dest.lamina}', so it reads that lamina's "
                        f"own interface composite — but no channel leaves "
                        f"that lamina, so it has not declared one. Give the "
                        f"lamina an outgoing channel, or make this a key "
                        f"gate reading what the channel presents."
                    )
                own = twins[channel.dest.lamina].composites[face]
                _validate_gate_coordinates(gate, channel, own, face)
            else:
                _validate_gate_coordinates(gate, channel, composite,
                                           channel.source.member)


def _lamina_face(spec: OrganismSpec, lamina_id: str):
    """
    The composite a lamina presents to its neighbours, or None.

    Rule 9 guarantees there is at most one, so the first channel leaving
    the lamina names it.  A lamina at the end of a stack sends nothing
    and therefore has no face — which is only a problem for a gate that
    wants to read one, and is reported there rather than here.
    """
    for channel in spec.channels:
        if channel.source.lamina == lamina_id:
            return channel.source.member
    return None


def _validate_gate_coordinates(gate, channel, composite,
                               composite_id: str) -> None:
    """
    Every attribute a gate names has to exist on the composite it will
    be handed.

    A coordinate that is not there does not raise at runtime — the
    controller simply cannot read it, and a key that silently drops a
    coordinate matches on a different vector than the one written down.
    That is a wrong answer rather than a crash, so it is caught here.
    """
    named: list = []
    if isinstance(gate, AutoGate):
        watch = gate.trigger.get("watch")
        if watch:
            named.append(watch)
        named.extend(gate.trigger.get("weights") or {})
    else:
        named.extend(gate.key.get("weights") or {})

    for attr in named:
        if attr not in composite.attribute_ids:
            raise OrganismError(
                f"Gate '{gate.id}' (channel '{channel.id}') reads '{attr}', "
                f"which is not in composite '{composite_id}'. It holds: "
                f"{composite.attribute_ids}."
            )


def load_organism(path: Path | str | None = None) -> tuple:
    """
    Parse the organism, build its laminae, and check every rule.

    Returns `(spec, twins)` — the declaration and one twin per lamina,
    keyed by lamina id.  Phase 2's container takes both; nothing here
    runs a cycle.
    """
    spec = parse_organism(path)
    twins = {
        lamina_id: load_twin(resolve_lamina(lamina_id))
        for lamina_id in spec.lamina_ids
    }
    validate_against_laminae(spec, twins)
    return spec, twins



# ──────────────────────────────────────────────────────────────────────
# Phase 3 — the gate controllers
# ──────────────────────────────────────────────────────────────────────
#
# Two of them, and they answer different questions.
#
#   threshold  "is this composite doing enough to be worth passing on?"
#              A two-threshold state machine with a deadband.  Lee calls
#              this the Auto Controller; the name here is `threshold`
#              because "Auto Controller" already means something else in
#              this codebase — the weight-learning loop in
#              auto_adjust_weights, frozen since D17 — and two things
#              with one name is how a design note becomes a bug.
#
#   key        "does this composite look like the state I am waiting
#              for?"  A weighted match against a reference point, in
#              normalised space so the key stays domain-neutral (G2).
#
# Signature, frozen, and the same shape as the gate kernels in
# universal_twin.py:
#
#     controller(state: dict,
#                source_vec: dict[str, float],
#                params: dict) -> dict
#
# The returned dict IS the new state and must carry "open_fraction" in
# [0, 1].  Everything else in it is the controller's own memory, and has
# to stay JSON-serialisable — the state goes out on the snapshot, and a
# gate whose reasoning cannot be inspected is a gate nobody can debug.

#: Sigmoid slope for proportional mode, when the gate declares none.
DEFAULT_STEEPNESS = 8.0

#: EWMA coefficient for the key controller's drift telemetry.
DEFAULT_DRIFT_ALPHA = 0.05


def _scalars(state: dict) -> dict:
    """
    The JSON-safe scalar half of a state dict, for the report.

    The delay buffer is a list and the report is a summary, not a dump —
    a reader wants to know how open the gate is and why, not to re-read
    every value still in flight.
    """
    return {k: v for k, v in state.items()
            if isinstance(v, (int, float, str, bool)) or v is None}


def _sigmoid(x: float) -> float:
    """σ(x), with the exponent clamped so a large |x| cannot overflow."""
    exponent = max(-700.0, min(700.0, -x))
    return 1.0 / (1.0 + math.exp(exponent))


def _aggregate(source_vec: dict, params: dict) -> Optional[float]:
    """
    Reduce the source composite's normalised vector to one number.

    `attr` reads the single attribute named by `watch`; `mean` and `max`
    take the whole vector; `deviation` reads `watch` and returns its
    DISTANCE from a declared `reference`.  All four work in [0,1] because
    that is the space the vector already lives in, which is what lets one
    set of thresholds mean the same thing whether the attribute is in
    L/min or mmHg.

    The reason `deviation` exists: the other three are one-sided.  A gate
    watching a raw normalised value can only open when that value is
    HIGH, so a seam declared to open "while the pump is remarkable" opens
    for a racing heart and stays shut for a failing one.  Measured on the
    shipped circulation, holding HR at 35: cardiac output settles at 3.39
    L/min and the seam never opens, so the respiratory lamina keeps
    computing oxygen delivery from its uncoupled baseline of 5.0 — a 32%
    error, silently, in the direction that matters most.  Distance from a
    reference makes both directions the same number.

    Returns None when there is nothing to read — an attribute that has
    not computed yet, or an empty composite.  A gate cannot decide
    anything from that, and guessing a number would be worse than
    saying so.
    """
    values = [v for v in source_vec.values() if v is not None]
    mode = params.get("aggregate", "attr")
    if mode == "mean":
        return sum(values) / len(values) if values else None
    if mode == "max":
        return max(values) if values else None
    watched = params.get("watch")
    if not watched:
        return None
    value = source_vec.get(watched)
    if mode == "deviation":
        if value is None:
            return None
        return abs(value - float(params.get("reference", 0.0)))
    return value


def threshold_gate_controller(state: dict, source_vec: dict,
                              params: dict) -> dict:
    """
    Two thresholds, a deadband between them, and a refractory hold.

    Closed → open when the watched value reaches `open_above`.
    Open → closed when it falls to `close_below`.  Between the two
    nothing happens, which is the whole point: the feed carries
    deliberate Gaussian noise, so a single threshold would be crossed
    and re-crossed every cycle by a value that is not actually going
    anywhere.  The parser refuses a gate that declares only one (rule
    4), so this function can assume both exist.

    `refractory_cycles` holds the state after a transition regardless of
    what the value does.  The deadband stops chatter from noise; the
    refractory stops it from a fast genuine swing, and gives whatever is
    downstream a few cycles to respond before the gate changes its mind
    again.

    `mode`:
      binary        (default) open_fraction is 0.0 or 1.0.
      proportional  open_fraction eases in with a sigmoid once the state
                    machine has opened — the same σ(k·(v − boundary))
                    conductance the soft_range gate uses in
                    validate_gates(), anchored on `open_above`, so it
                    reads 0.5 at the threshold and approaches 1 above it.
                    Shutting is still the state machine's call: a gate
                    the deadband says is closed passes nothing, whatever
                    the sigmoid would have said.
    """
    watch_value = _aggregate(source_vec, params)
    is_open = bool(state.get("open", False))          # G6: born closed
    refractory = int(state.get("refractory", 0))
    transitioned = False

    if watch_value is None:
        # Nothing readable to decide on.  Hold whatever the gate already
        # was rather than defaulting either way — a missing reading is
        # not evidence that the pump stopped.
        reason = "no readable value to watch"
    elif refractory > 0:
        refractory -= 1
        reason = f"refractory ({refractory} to go)"
    else:
        open_above = float(params.get("open_above", 1.0))
        close_below = float(params.get("close_below", 0.0))
        if not is_open and watch_value >= open_above:
            is_open, transitioned = True, True
            reason = f"opened: {watch_value:.3f} >= {open_above}"
        elif is_open and watch_value <= close_below:
            is_open, transitioned = False, True
            reason = f"closed: {watch_value:.3f} <= {close_below}"
        else:
            reason = "in deadband" if not transitioned else ""
        if transitioned:
            refractory = int(params.get("refractory_cycles", 0))

    if not is_open:
        open_fraction = 0.0
    elif params.get("mode") == "proportional" and watch_value is not None:
        steepness = float(params.get("steepness", DEFAULT_STEEPNESS))
        open_fraction = _sigmoid(
            steepness * (watch_value - float(params.get("open_above", 1.0)))
        )
    else:
        open_fraction = 1.0

    return {
        "open_fraction": open_fraction,
        "open":          is_open,
        "refractory":    refractory,
        "watch_value":   watch_value,
        "transitions":   int(state.get("transitions", 0)) + int(transitioned),
        "reason":        reason,
    }


def key_gate_controller(state: dict, source_vec: dict, params: dict) -> dict:
    """
    Open when the composite looks enough like the state being waited for.

    The key is a reference POINT in the normalised [0,1] vector space,
    one coordinate per weighted attribute, with a weight saying how much
    each coordinate matters.  Matching is within tolerance rather than
    exact (G2): real data is noisy, so an exact match on a float never
    happens, and a key that can never fire is not a gate.

    `metric`:
      weighted_distance  (default) Σ wᵢ·|vᵢ − refᵢ| / Σ wᵢ.  Reads as
                         "average weighted coordinate error", which is
                         what a domain expert setting a threshold is
                         actually thinking about.
      cosine             1 − cos(v, ref) over the weighted coordinates.
                         Ignores overall magnitude and matches on
                         direction — the right choice when "the same
                         shape of state, scaled" should still count.

    `match = 1 − distance`, and the gate opens at `match_threshold`.

    DRIFT TELEMETRY, from v1 rather than later (G7).  A static key drifts
    away from the state it was written for as the model, the patient or
    the calibration moves, and the tempting fix is to make the key
    adaptive.  That is a v2 decision and it should be made on evidence:
    so every evaluation records the distance, an EWMA of it, and the
    range it has covered.  If the EWMA climbs steadily across a run, the
    key is drifting and adaptation has a case.  If it does not, it does
    not — and this is the cheapest way to find out which, rather than
    building a slow loop first and asking afterwards.

    HYSTERESIS, because measuring said so.  A key gate was first written
    with a single `match_threshold`, on the reasoning that a match is
    already a tolerance and does not need a band.  Measured on the noisy
    feed with the match sitting just above the threshold (0.9150 against
    0.90), it flipped open/shut 148 times in 400 cycles.  So `release_below`
    is mandatory here for exactly the reason `close_below` is mandatory
    on a threshold gate (G3): a single boundary on a noisy signal is
    crossed and re-crossed by a value that is not going anywhere.  Opens
    at `match >= match_threshold`, shuts at `match <= release_below`, and
    holds between them.
    """
    weights = params.get("key_weights") or {}
    metric = params.get("metric", "weighted_distance")

    pairs = [
        (float(w), float(ref), float(source_vec[attr]))
        for attr, (w, ref) in weights.items()
        if source_vec.get(attr) is not None
    ]
    if not pairs:
        return {
            "open_fraction": 0.0,
            "open":          False,
            "reason":        "no key coordinate is readable",
            "evaluations":   int(state.get("evaluations", 0)),
        }

    if metric == "cosine":
        dot = sum(w * ref * v for w, ref, v in pairs)
        n_ref = math.sqrt(sum(w * ref * ref for w, ref, _ in pairs))
        n_v = math.sqrt(sum(w * v * v for w, _, v in pairs))
        similarity = dot / (n_ref * n_v) if n_ref > 0 and n_v > 0 else 0.0
        distance = 1.0 - max(-1.0, min(1.0, similarity))
    else:
        total_weight = sum(w for w, _, _ in pairs)
        distance = (
            sum(w * abs(v - ref) for w, ref, v in pairs) / total_weight
            if total_weight > 0 else 1.0
        )

    match = max(0.0, min(1.0, 1.0 - distance))
    threshold = float(params.get("match_threshold", 0.9))
    release = float(params.get("release_below", threshold))
    was_open = bool(state.get("open", False))          # G6: born closed
    if not was_open and match >= threshold:
        is_open = True
    elif was_open and match <= release:
        is_open = False
    else:
        is_open = was_open                              # inside the band

    # ── drift telemetry ──────────────────────────────────────────────
    alpha = float(params.get("drift_alpha", DEFAULT_DRIFT_ALPHA))
    previous = state.get("distance_ewma")
    ewma = distance if previous is None else (
        previous + alpha * (distance - previous)
    )
    evaluations = int(state.get("evaluations", 0)) + 1
    d_min = min(distance, state.get("distance_min", distance))
    d_max = max(distance, state.get("distance_max", distance))
    first = state.get("distance_first", distance)

    return {
        "open_fraction":  1.0 if is_open else 0.0,
        "open":           is_open,
        "match":          match,
        "distance":       distance,
        "reason":         (
            f"match {match:.3f} vs open>={threshold} shut<={release}"
            + ("" if is_open == was_open else
               f" — {'opened' if is_open else 'shut'}")
        ),
        "transitions":    int(state.get("transitions", 0))
                          + int(is_open != was_open),
        # Telemetry.  `drift` is the whole question in one number: how
        # far the EWMA has moved from the distance this key saw the very
        # first time it was evaluated.
        "evaluations":    evaluations,
        "distance_ewma":  ewma,
        "distance_first": first,
        "distance_min":   d_min,
        "distance_max":   d_max,
        "drift":          ewma - first,
    }

# ──────────────────────────────────────────────────────────────────────
# Phase 2 — the container
# ──────────────────────────────────────────────────────────────────────

#: Sum of every lamina's feedback_norm above which the organism shuts
#: every gate.  Each lamina already has its own breaker at
#: DEFAULT_MAX_NORM; this one is about the BODY diverging, which is a
#: different failure — two laminae can each sit under their own limit
#: while feeding each other through an open gate, and no per-lamina
#: breaker can see that.  Set well above any settled state (a resting
#: lamina runs at norm ~1e-3) and below anything mistakable for
#: physiology.
DEFAULT_MAX_TOTAL_NORM = 10.0


class Organism:
    """
    Several laminae, the gates between them, and one tick order.

    What this class owns that nothing else can is the ORDER.  Each lamina
    already knows how to compute itself and how to run its own feedback
    loop, and neither of them can decide when a value crosses to the
    other — that question only exists once there is more than one.

    Deliberately not a superclass of anything, and deliberately not
    something `Session` knows about.  A single-lamina session is the
    common case and it keeps working exactly as it did; an organism
    stands beside it rather than becoming a thing everything now has to
    route through.
    """

    def __init__(self,
                 path: Path | str | None = None,
                 epsilon_ratio: float = DEFAULT_EPSILON_RATIO,
                 max_norm: float = DEFAULT_MAX_NORM,
                 max_total_norm: float = DEFAULT_MAX_TOTAL_NORM) -> None:
        self.spec, self.twins = load_organism(path)
        self.channels: list = self.spec.channels
        #: Every gate on every channel, both sides, flattened for the
        #: places that address a gate by id and do not care which
        #: membrane it sits on.
        self.gates: list = [g for ch in self.channels
                            for g in (*ch.transmit, *ch.receive)]
        self.controllers: dict = {
            lamina_id: FeedbackController(twin, epsilon_ratio, max_norm)
            for lamina_id, twin in self.twins.items()
        }
        self.max_total_norm = float(max_total_norm)

        # Gate state lives HERE, keyed by gate id — not on the AutoGate
        # or KeyGate dataclass.  Same placement as
        # FeedbackController._kernel_state, and for the same reason: a
        # declaration that is also a mutable state bag cannot be
        # reloaded, compared or serialised without dragging the run
        # along with it.
        self._gate_state: dict = {gate.id: {} for gate in self.gates}

        # Channel state is a SEPARATE bag with a separate owner: the
        # delay line, what is currently on offer, and how long it has
        # been sitting there.  A gate controller replaces its own state
        # wholesale every cycle, so anything it could reach would be
        # wiped — measured under v1, where a declared time_delay
        # delivered nothing, ever, because the buffer shared a dict with
        # a controller.
        self._channel_state: dict = {ch.id: {} for ch in self.channels}

        # Pluggable gate controllers, mirroring the five registries on
        # UniversalTwin.  The two v1 controllers are registered here;
        # a gate naming one that is not in this dict cannot open, which
        # is the same resting state a gate is born in anyway (G6) rather
        # than an error — an organism can be assembled before every
        # controller it names has been written.
        #
        # Contract (frozen):
        #     controller(state: dict,
        #                source_vec: dict[str, float],
        #                params: dict) -> dict
        # The returned dict IS the new state and must carry
        # "open_fraction" in [0, 1].
        self._gate_controller_registry: dict = {}
        self._register_default_gate_controllers()

        self.cycle: int = 0
        #: Set by the body breaker; no gate opens again until reset().
        self.gates_locked: bool = False

    # ── State ────────────────────────────────────────────────────────

    def reset(self) -> None:
        """Wipe every lamina's feedback state and every gate's."""
        for controller in self.controllers.values():
            controller.reset_kernel_state()
        self._gate_state = {gate.id: {} for gate in self.gates}
        self._channel_state = {ch.id: {} for ch in self.channels}
        self.cycle = 0
        self.gates_locked = False

    def seed(self, sensor_data: dict | None = None) -> None:
        """
        Write starting sensor values into each lamina and derive its chain.

        Takes `{lamina_id: {attr_id: value}}`.  Separate from __init__
        for the same reason Session.seed is: a synthetic feed is built
        FROM a twin and so cannot exist before it.  Values addressed to
        an attribute a lamina does not declare, or to one it declares as
        something other than a sensor, are skipped rather than raising —
        a caller holding the wrong lamina's baselines is making a mistake
        worth surviving.
        """
        for lamina_id, twin in self.twins.items():
            for attr_id, value in ((sensor_data or {}).get(lamina_id) or {}).items():
                try:
                    twin.set_sensor(attr_id, value)
                except (KeyError, ValueError):
                    continue
            twin.compute_all()

    def _register_default_gate_controllers(self) -> None:
        """The two v1 controllers, by the name a gate declares."""
        self._gate_controller_registry["threshold"] = threshold_gate_controller
        self._gate_controller_registry["key"] = key_gate_controller

    def register_gate_controller(self, name: str, fn) -> None:
        """
        Add or replace a gate controller.

        The extension point a new controller arrives through, and the one
        a test uses to drive a gate deterministically without pretending
        a real controller decided something.
        """
        self._gate_controller_registry[name] = fn

    def total_feedback_norm(self) -> float:
        """Sum of every lamina's own feedback norm — the body-level probe."""
        return sum(twin.feedback_norm() for twin in self.twins.values())

    # ── The tick ─────────────────────────────────────────────────────

    def tick(self, sensor_updates: dict | None = None) -> dict:
        """
        One organism cycle.  THE ORDER IS THE POINT OF THIS METHOD.

            1. Write sensors into every lamina
            2. compute_all() on every lamina
            3. Gate pass — read the sender's POST-COMPUTE value, run the
                           gate controller, transfer what crosses, write
                           it into the receiver's X'
            4. controller.step() on every lamina

        Why this order and not another, argued once here so nobody has to
        re-derive it from the code:

        Step 3 sits AFTER every compute and BEFORE every feedback step.
        After compute, because a gate reading the sender before its chain
        ran would carry last cycle's number while claiming to carry this
        one's — the same "stale value looking live" the snapshot's
        `stale` flag exists to stop, one layer up.  Before the feedback
        steps, because an inter-lamina value is X' (G1): it is an INPUT
        to the receiving lamina's cycle, and a loop that ran before its
        input arrived would be correcting against a state that no longer
        holds.

        Two consequences of that placement, both measured rather than
        assumed, because the obvious guess about each one is wrong.

        The RECEIVER sees a crossing on the SAME tick, not the next.  It
        is tempting to reason that step 2 has already run so the value
        must wait — but step 4 is `FeedbackController.step()`, whose last
        act is another `compute_all()`.  So the gate writes at step 3 and
        the receiving chain re-derives from it a moment later, within the
        same tick, and its outcome evaluation sees it too.  Measured on
        the CO → CO_ref seam: DO2 moves from 988.42 to 1043.77 on the
        tick the value crosses.  There is therefore NO implicit one-cycle
        delay to lean on — `time_delay=0` means zero — and the EWMA rate
        is the whole of the anti-oscillation defence, which is what G4
        says it is anyway.

        The SENDER's contribution is one feedback cycle old.  The gate
        reads between step 2 and step 4, so the value carries this
        cycle's X' and last cycle's X''.  That is the price of running
        the gate before the loops rather than after: the alternative
        hands the receiver a number its own loop has already reacted to.

        Every lamina keeps its own circuit breaker, untouched.  The one
        added here is about the body, and it shuts the gates while
        leaving the laminae alone: a lamina's internal loop is its own
        business, and the thing that went wrong is the coupling.
        """
        self.cycle += 1
        updates = sensor_updates or {}
        warnings: list = []

        # ── Step 1: sensors ──────────────────────────────────────────
        for lamina_id, twin in self.twins.items():
            for attr_id, value in (updates.get(lamina_id) or {}).items():
                try:
                    twin.set_sensor(attr_id, value)
                except (KeyError, ValueError):
                    # Same tolerance as Session.seed: a caller holding a
                    # reading for another lamina is making a mistake
                    # worth surviving, and an INTER_LAMINA attribute
                    # refusing a sensor write is the contract working.
                    continue

        # ── Step 2: derive every chain ───────────────────────────────
        for twin in self.twins.values():
            twin.compute_all()

        # ── Step 3: the gate pass ────────────────────────────────────
        channel_report = self._gate_pass(warnings)

        # ── Step 4: each lamina's own feedback cycle ─────────────────
        cycle_reports: dict = {}
        for lamina_id, controller in self.controllers.items():
            cycle_reports[lamina_id] = controller.step()

        # ── Body-level breaker ───────────────────────────────────────
        total_norm = self.total_feedback_norm()
        if total_norm > self.max_total_norm and not self.gates_locked:
            self.gates_locked = True
            warnings.append(
                f"ORGANISM BREAKER: total feedback_norm={total_norm:.4f} > "
                f"{self.max_total_norm} at cycle {self.cycle}. Every gate is "
                f"shut; the laminae keep running on their own."
            )

        report = {
            "organism_id":         self.spec.id,
            "cycle":               self.cycle,
            "total_feedback_norm": round(total_norm, 6),
            "gates_locked":        self.gates_locked,
            "channels":            channel_report,
            "cycle_reports":       cycle_reports,
            "warnings":            warnings,
        }
        for w in warnings:
            print(f"[organism] {w}")
        return report

    # ── Step 3, in detail ────────────────────────────────────────────

    def _gate_pass(self, warnings: list) -> dict:
        """
        Run every channel once, in declaration order.

        A crossing is now TWO decisions and a wire between them.  The
        sending lamina's gates decide whether anything is offered; the
        receiving lamina's gates decide whether anything is taken; and
        the channel holds what has been offered and not yet taken.  That
        middle state is the one the single-valve design could not
        represent, and the reason a value can now be `waiting` rather
        than only crossing or not.

        State is split three ways, and the split is not tidiness.  Each
        gate's controller state is its own, because a controller's
        contract is that its RETURN VALUE is its whole new state and the
        container replaces it wholesale.  The channel's state — the
        delay line, what is on offer, how old it is — belongs to the
        channel, because a controller that could reach it would wipe it.
        Measured under v1, when both lived in one dict: a seam declaring
        `time_delay=1` delivered nothing, ever, because the line was
        emptied between being filled and being read.
        """
        report: dict = {}
        for channel in self.channels:
            report[channel.id] = self._run_channel(channel, warnings)
        return report

    # ── Step 3, in detail ────────────────────────────────────────────

    def _face_vector(self, lamina_id: str):
        """
        The normalised vector of a lamina's interface composite.

        Rule 9 says a lamina presents ONE composite in every direction,
        so the face is whatever composite its channels leave on — which
        makes this derivable rather than a second thing to declare and
        keep in step.

        A lamina at the end of a stack sends nothing and so has declared
        no face.  That is not an error here; it only becomes one if a
        gate actually asks to read it, and `_gate_opening` raises there,
        naming the gate.
        """
        for channel in self.channels:
            if channel.source.lamina == lamina_id:
                return self.twins[lamina_id].get_composite_vector(
                    channel.source.member)
        return None

    def _gate_opening(self, gate, own_vec, presented, warnings) -> dict:
        """
        One gate's decision this cycle: how open, and on what grounds.

        The two kinds read different things, and that difference IS the
        distinction between them.  An auto gate is handed `own_vec`, the
        composite of the lamina it sits on — it never sees the other
        side.  A key gate is handed `presented`, what the channel is
        carrying — it never sees its own lamina's internals.

        The arithmetic underneath is shared on purpose: a threshold and
        a shape-match are the same hysteresis machinery pointed at
        different inputs, and giving them separate implementations would
        be two places for the deadband to drift apart.
        """
        state = self._gate_state.setdefault(gate.id, {})
        if isinstance(gate, AutoGate):
            if own_vec is None:
                raise OrganismError(
                    f"Gate '{gate.id}' reads its own lamina's interface "
                    f"composite, but that lamina declares none because no "
                    f"channel leaves it. An auto gate reads the face of the "
                    f"lamina it sits on; give that lamina an outgoing "
                    f"channel, or make this a key gate."
                )
            params = dict(gate.trigger)
            params["refractory_cycles"] = gate.refractory_cycles
            if gate.trigger_kind == "threshold":
                fn = self._gate_controller_registry.get("threshold")
            else:
                params["key_weights"] = params.pop("weights", {})
                params.setdefault("metric", "weighted_distance")
                fn = self._gate_controller_registry.get("key")
            vector = own_vec
        else:
            metric = gate.key.get("metric", "identity")
            if metric == "identity":
                return self._identity_opening(gate, presented, state)
            params = dict(gate.key)
            params["key_weights"] = params.pop("weights", {})
            params["refractory_cycles"] = 0
            fn = self._gate_controller_registry.get("key")
            vector = (presented or {}).get("vector")
            if vector is None:
                state.clear()
                state.update({
                    "open_fraction": 0.0,
                    "open":          False,
                    "reason":        "nothing is presented at the channel",
                })
                return {"fraction": 0.0, "flood": False, "state": state}

        if fn is None:
            state["open_fraction"] = 0.0
            state["reason"] = "no controller registered"
            return {"fraction": 0.0, "flood": False, "state": state}

        new_state = dict(fn(state, vector, params))
        state.clear()
        state.update(new_state)
        fraction = float(new_state.get("open_fraction", 0.0))
        if not 0.0 <= fraction <= 1.0:
            warnings.append(
                f"Gate '{gate.id}' returned open_fraction={fraction}, "
                f"outside [0,1] — clamped."
            )
            fraction = max(0.0, min(1.0, fraction))
        return {"fraction": fraction,
                "flood": isinstance(gate, AutoGate) and fraction > 0.0,
                "state": state}

    def _identity_opening(self, gate, presented, state: dict) -> dict:
        """
        An identity key: the right KIND of thing arrived.

        No band, and rule 4 exempts it for the reason the exemption
        exists — a label matches or it does not, and there is no noise
        between the two for a single boundary to chatter on.  `expect`
        names the label this receptor accepts; a receptor naming none
        accepts whatever the channel it sits on carries, which is the
        honest default for a channel that only ever carries one thing.
        """
        offered_label = (presented or {}).get("label")
        expected = gate.key.get("expect")
        if offered_label is None:
            fraction, reason = 0.0, "nothing is presented at the channel"
        elif expected and offered_label != expected:
            fraction, reason = 0.0, (
                f"'{offered_label}' is not the '{expected}' this gate takes")
        else:
            fraction, reason = 1.0, f"'{offered_label}' recognised"
        state.clear()
        state.update({
            "open_fraction": fraction,
            "open":          fraction > 0.0,
            "reason":        reason,
            "metric":        "identity",
            "label":         offered_label,
        })
        return {"fraction": fraction, "flood": False, "state": state}

    def _side(self, gates, own_vec, presented, warnings) -> dict:
        """
        One membrane's decision, from the gates on it.

        Auto gates are evaluated FIRST and, when one opens, the key
        gates on that side are not consulted at all.  That ordering is
        the whole content of "an auto gate is a protection layer": a
        relief valve does not ask the controller for permission, and a
        configuration that could suppress it would not be a protection
        layer.

        A side is open when ANY of its gates is open, because gates on
        one membrane sit in parallel — four ion channels in a patch of
        membrane do not have to agree before anything passes.  Rule 8
        caps that parallelism at four per face.

        A flood is DECLARED HERE AND STAYS HERE (C4, Q3 settled
        2026-09-03): it sets THIS side's rate to 1 and bypasses THIS
        side's weighting, and says nothing whatever about the far side's
        gates.  If a sender's emergency could force a receiver open, the
        sender's fail-safe would be a forced write into another lamina —
        the disorder the gates exist to prevent, arriving through the
        door marked "safety".
        """
        opening = {"fraction": 0.0, "flood": False, "weight": 1.0,
                   "gate": None, "gates": []}
        for kind in (AutoGate, KeyGate):
            for gate in [g for g in gates if isinstance(g, kind)]:
                result = self._gate_opening(gate, own_vec, presented, warnings)
                opening["gates"].append({
                    "id":            gate.id,
                    "kind":          ("auto" if isinstance(gate, AutoGate)
                                      else "key"),
                    "open":          result["fraction"] > 0.0,
                    "open_fraction": round(result["fraction"], 6),
                    "flood":         result["flood"],
                    "reason":        result["state"].get("reason", ""),
                    # The gate's own working, carried beside its verdict.
                    # A pattern trigger's drift telemetry lives here, and
                    # G7 says measure the drift before correcting it —
                    # which needs it to be readable every cycle rather
                    # than only off the snapshot.
                    "state":         _scalars(result["state"]),
                })
                if result["fraction"] > opening["fraction"]:
                    opening["fraction"] = result["fraction"]
                    opening["gate"] = gate
                    opening["weight"] = float(getattr(gate, "weight", 1.0))
                if result["flood"]:
                    opening["flood"] = True
            if opening["flood"]:
                break
        if opening["flood"]:
            # A flood bypasses this side's WEIGHTING and sets its rate to
            # 1; it does not decide how open the valve is.  Forcing the
            # fraction to 1 here turned a half-open protection gate into
            # a fully open one, which is a valve reporting a position it
            # is not in — and it made the open fraction of a
            # proportional auto gate unobservable.
            opening["weight"] = 1.0
        return opening

    def _breaker_shut(self, gates) -> dict:
        """
        Every gate on one side, shut by the body breaker and SAYING so.

        A valve that reports only a boolean makes the reader guess
        between "the value is inside the deadband" and "the breaker
        fired", which are not the same news.  Worse, leaving each gate's
        last reason in place would have the snapshot explain a shut
        valve with the reason it shut for some earlier, unrelated
        cycle.
        """
        entries = []
        for gate in gates:
            state = self._gate_state.setdefault(gate.id, {})
            state.clear()
            state.update({"open_fraction": 0.0, "open": False,
                          "reason": "organism breaker"})
            entries.append({
                "id":            gate.id,
                "kind":          "auto" if isinstance(gate, AutoGate) else "key",
                "open":          False,
                "open_fraction": 0.0,
                "flood":         False,
                "reason":        "organism breaker",
                "state":         _scalars(state),
            })
        return {"fraction": 0.0, "flood": False, "weight": 1.0,
                "gate": gates[0] if gates else None, "gates": entries}

    def _run_channel(self, channel, warnings: list) -> dict:
        """
        One channel, both membranes, in the order C11 fixes.

        Transmit is resolved before receive because the receiver's key
        gates match against what is actually on offer, and "what is on
        offer" is not known until the sender has decided.  That is the
        same one-directional ordering the tick already uses between
        laminae, applied inside a single crossing.
        """
        cstate = self._channel_state.setdefault(channel.id, {})
        src_twin = self.twins[channel.source.lamina]
        dst_twin = self.twins[channel.dest.lamina]
        dst_attr = dst_twin.attributes.get(channel.dest.member)

        src_attr = src_twin.attributes.get(channel.extract)
        reading = src_attr.value if src_attr else None
        src_vec = src_twin.get_composite_vector(channel.source.member)

        if self.gates_locked:
            tx = self._breaker_shut(channel.transmit)
        else:
            tx = self._side(channel.transmit, src_vec, None, warnings)

        # ── The sender offers, or the offer ages where it lies ───────
        if tx["fraction"] > 0.0 and reading is not None:
            cstate["offered"] = reading
            cstate["label"] = channel.source.member
            cstate["offered_age"] = 0
        elif cstate.get("offered") is not None:
            cstate["offered_age"] = int(cstate.get("offered_age", 0)) + 1

        presented = {
            "label":  cstate.get("label"),
            "value":  cstate.get("offered"),
            "vector": src_vec if tx["fraction"] > 0.0 else None,
        }
        if self.gates_locked:
            rx = self._breaker_shut(channel.receive)
        else:
            rx = self._side(channel.receive, self._face_vector(
                channel.dest.lamina), presented, warnings)

        open_fraction = tx["fraction"] * rx["fraction"]
        cstate.pop("close_reason", None)
        transmitted = self._absorb(channel, cstate, dst_attr, dst_twin,
                                   tx, rx, open_fraction)

        return {
            "open_fraction": round(open_fraction, 6),
            "reading":       reading,
            "transmitted":   transmitted,
            "offered":       cstate.get("offered"),
            "offered_age":   int(cstate.get("offered_age", 0)),
            "state":         self._channel_report_state(
                tx, rx, dst_attr, transmitted, cstate),
            "transmit":      tx["gates"],
            "receive":       rx["gates"],
            "flood":         bool(tx["flood"] or rx["flood"]),
            # The channel's OWN state, reported beside the gates' rather
            # than merged into them.  Two owners, and a reader can see
            # that neither reaches the other's keys — which is the
            # arrangement a measured bug produced: a shared dict let a
            # controller wipe the delay line between its being filled
            # and being read.
            "channel_state": _scalars(cstate),
        }

    def _channel_report_state(self, tx, rx, dst_attr, transmitted,
                              cstate) -> str:
        """
        One word for what this channel is doing, and `waiting` is the
        new one.

        `waiting` and `held` are the pair worth keeping apart: waiting
        means the sender has put something down and the receiver has not
        picked it up; held means the receiver picked something up a
        while ago and it is going stale.  Reading one as the other is
        the same family of mistake as reading a dead stream as a live
        one, which is what most of this project's measured bugs have
        turned out to be.
        """
        if tx["fraction"] > 0.0 and rx["fraction"] > 0.0:
            # Both gates open is not the same as something having
            # crossed: a declared band can refuse the VALUE while the
            # gate that would carry it is wide open. Reporting
            # "crossing" then would name a number that never landed,
            # which is the class of small lie the rest of this file
            # spends its time preventing.
            if transmitted is not None:
                return "crossing"
            return cstate.get("close_reason") or "shut"
        if tx["fraction"] > 0.0:
            return "waiting"
        provenance = (dst_attr.provenance or {}) if dst_attr else {}
        state = provenance.get("state")
        if state in ("held", "decaying"):
            return state
        return "shut"

    def _absorb(self, channel, cstate, dst_attr, dst_twin, tx, rx,
                open_fraction: float):
        """
        What the receiver takes, and the write into its state.

        Three stages, each a defence against a different failure:

          1. DELAY — the offer goes into a ring buffer `time_delay`
             cycles long and what comes out is what was offered that
             many cycles ago.  The buffer belongs to the CHANNEL because
             a delay is a property of the wire.

          2. WEIGHT — received = baseline + weight*(offered - baseline)
             (C5, Q4 settled 2026-09-03).  The weight multiplies the
             DEVIATION from what the receiver was already assuming, not
             the value.  Multiplying the value would turn a cardiac
             output of 4.8 at weight 0.5 into 2.4 L/min, which is not a
             partial reading of 4.8 — it is a different and false one.
             Information is the departure from the assumption, so that
             is what a partial coupling takes a fraction of.

          3. EWMA — x <- x + rate*open*(target - x), the low-pass line
             against two feedback loops pulling on each other through an
             open channel.  `rate` comes from the RECEIVING gate,
             because how fast to believe something is the receiver's
             business.  A flood sets its own side's rate to 1; the
             receiver's rate still governs the receiver.

        The receiver eases out of wherever it already sits rather than
        jumping: on the first crossing the filter is seeded from the
        destination's current value, so a seam resting on its declared
        baseline of 5.0 walks up to the sender's number instead of
        snapping to it.
        """
        if dst_attr is None:
            return None
        rx_gate = rx["gate"]

        if open_fraction <= 0.0:
            reason = ("the receiving side is shut" if tx["fraction"] > 0.0
                      else "shut")
            return self._on_close(channel, cstate, dst_attr, rx_gate, reason)

        delayed = self._through_delay(cstate, cstate.get("offered"),
                                      channel.time_delay)
        if delayed is None:
            return self._on_close(channel, cstate, dst_attr, rx_gate,
                                  "waiting for the delay line")

        # A receptor with a declared band carries the value only while it
        # lies inside it, and REFUSES outside rather than clamping.
        # Clamping is what the old soft_range gate did, and it silently
        # pulled out-of-range physiology back toward normal — a MAP of
        # 120 displayed as 110, masking the pathology the twin exists to
        # show. Refusing says "this seam does not model that", which is
        # true; clamping says "it is 110", which is not.
        band_min = getattr(rx_gate, "band_min", None)
        band_max = getattr(rx_gate, "band_max", None)
        if band_min is not None and not band_min <= delayed <= band_max:
            return self._on_close(channel, cstate, dst_attr, rx_gate,
                                  "out of band")

        weight = tx["weight"] * rx["weight"]
        baseline = dst_attr.baseline
        if weight != 1.0 and baseline is not None:
            target = baseline + weight * (delayed - baseline)
        else:
            target = delayed

        previous = cstate.get("transmitted")
        if previous is None:
            previous = dst_attr.value if dst_attr.value is not None else target
        rate = 1.0 if rx["flood"] else float(getattr(rx_gate, "rate", 1.0))
        effective_rate = max(0.0, min(1.0, rate * open_fraction))
        transmitted = previous + effective_rate * (target - previous)

        dst_twin.set_inter_lamina(
            channel.dest.member,
            transmitted,
            confidence=float(getattr(rx_gate, "confidence", 1.0)),
            provenance={
                "state":         "coupled",
                "channel":       channel.id,
                "gate":          rx_gate.id if rx_gate else channel.id,
                "transmit":      [g["id"] for g in tx["gates"] if g["open"]],
                "receive":       [g["id"] for g in rx["gates"] if g["open"]],
                "from":          channel.source.lamina,
                "open_fraction": round(open_fraction, 4),
                "age":           0,
                "target":        round(target, 6),
                "rate":          round(effective_rate, 6),
                "weight":        round(weight, 6),
                "flood":         bool(tx["flood"] or rx["flood"]),
                "delay":         channel.time_delay,
            },
        )
        cstate["transmitted"] = transmitted
        cstate["last_transmitted"] = transmitted
        cstate.pop("close_reason", None)
        return transmitted

    def _through_delay(self, cstate: dict, reading, time_delay: int):
        """
        Push this cycle's offer into the channel's delay line, pop what
        is due.

        A plain list rather than a deque because the state travels on
        the snapshot and has to survive JSON.  Returns None while the
        line is still filling — a real state, not an error: a channel
        with a five-cycle delay genuinely has nothing to deliver for its
        first five cycles, and inventing something for it to say is the
        point at which the delay stops meaning anything.
        """
        if reading is None:
            return None
        buffer = cstate.setdefault("buffer", [])
        buffer.append(reading)
        if len(buffer) > max(0, int(time_delay)):
            return buffer.pop(0)
        return None

    def _on_close(self, channel, cstate: dict, dst_attr, rx_gate, reason: str):
        """
        What the receiver is left holding when nothing crosses.

        `hold` keeps the last value that arrived and lets it age, so the
        far side sees an old number labelled old rather than a value
        snapping back to a baseline nobody chose.

        `decay_to_baseline` walks it back to the attribute's declared
        `<baseline>` at the receiving gate's rate — the right choice
        where a stale coupled value is worse than an honest uninformed
        one, and the reason `<baseline>` is required on an INTER_LAMINA
        attribute in the first place (G9).
        """
        cstate["close_reason"] = reason

        # Nothing this channel ever carried is nothing it may claim.  A
        # seam still resting on its declared baseline must keep
        # reporting itself uncoupled: decaying an untouched value toward
        # the baseline it already sits on changes no number but stamps
        # provenance on it, and an untouched baseline that looks like a
        # decayed coupled value is worse than either.
        if cstate.get("transmitted") is None:
            return None

        on_close = getattr(rx_gate, "on_close", "hold")
        rate = float(getattr(rx_gate, "rate", 0.0))
        if on_close == "decay_to_baseline" and dst_attr.baseline is not None:
            current = cstate["transmitted"]
            decayed = current + rate * (dst_attr.baseline - current)
            cstate["transmitted"] = decayed
            age = int((dst_attr.provenance or {}).get("age", 0)) + 1
            self.twins[channel.dest.lamina].set_inter_lamina(
                channel.dest.member,
                decayed,
                confidence=float(getattr(rx_gate, "confidence", 1.0)),
                provenance={
                    "state":         "decaying",
                    "channel":       channel.id,
                    "gate":          rx_gate.id if rx_gate else channel.id,
                    "from":          channel.source.lamina,
                    "open_fraction": 0.0,
                    "age":           age,
                    "target":        dst_attr.baseline,
                    "reason":        reason,
                },
            )
            return None

        self._age_held_value(channel, rx_gate, reason)
        return None

    def _age_held_value(self, channel, rx_gate, reason: str = "shut") -> None:
        """
        Mark the receiver's held value as one cycle older.

        The number does not move; only its age and the reason it stopped
        moving do.  A reader looking at a held value has to be able to
        tell how stale it is without diffing two snapshots.
        """
        dst_twin = self.twins[channel.dest.lamina]
        dst_attr = dst_twin.attributes.get(channel.dest.member)
        if dst_attr is None or dst_attr.value is None:
            return
        provenance = dict(dst_attr.provenance or {})
        if not provenance:
            return
        provenance.update({
            "state":         "held",
            "channel":       channel.id,
            "gate":          rx_gate.id if rx_gate else channel.id,
            "open_fraction": 0.0,
            "age":           int(provenance.get("age", 0)) + 1,
            "reason":        reason,
        })
        dst_twin.set_inter_lamina(
            channel.dest.member,
            dst_attr.value,
            confidence=float(getattr(rx_gate, "confidence", 1.0)),
            provenance=provenance,
        )

    # ── Reporting ────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """
        One payload describing the whole body.

        Per-lamina snapshots keep the exact shape a single-lamina
        session already sends, nested under their lamina id, so anything
        that can read one lamina can read one of these without learning
        a second format.

        `channels` is the reader-facing view of each seam: what it was
        declared to be and what it is doing right now, both ends of it,
        in one entry.
        """
        return {
            "organism_id": self.spec.id,
            "name":        self.spec.name,
            "levels":      dict(self.spec.levels),
            "laminae":     {
                lamina_id: _simulation_snapshot(twin)
                for lamina_id, twin in self.twins.items()
            },
            "channels":    [self._channel_entry(ch) for ch in self.channels],
        }

    def _channel_entry(self, channel) -> dict:
        """
        One channel, declaration and live state together, both sides.

        The provenance comes off the RECEIVING attribute rather than off
        the channel's own state, and that is deliberate: it is the same
        object the receiving lamina's own snapshot shows under
        `inbound`, so the seam drawn on a body diagram and the value
        shown beside the far side's inputs can never disagree about how
        old the number is.  Two places computing the same claim is how
        they drift.
        """
        cstate = self._channel_state.get(channel.id, {})
        dst_attr = self.twins[channel.dest.lamina].attributes.get(
            channel.dest.member)
        provenance = dict(dst_attr.provenance) if (
            dst_attr is not None and dst_attr.provenance) else {}
        if provenance.get("channel") != channel.id:
            provenance = {}

        return {
            "id":          channel.id,
            "from":        str(channel.source),
            "to":          str(channel.dest),
            "from_lamina": channel.source.lamina,
            "to_lamina":   channel.dest.lamina,
            "extract":     channel.extract,
            "time_delay":  channel.time_delay,
            "description": channel.description,
            "transmit":    [self._gate_entry(g) for g in channel.transmit],
            "receive":     [self._gate_entry(g) for g in channel.receive],
            "offered":     cstate.get("offered"),
            "offered_age": int(cstate.get("offered_age", 0)),
            "last_value":  cstate.get("last_transmitted"),
            "provenance":  provenance,
        }

    def _gate_entry(self, gate) -> dict:
        """One gate: what it was declared to be, and what it just did."""
        state = self._gate_state.get(gate.id, {})
        fraction = float(state.get("open_fraction", 0.0))
        entry = {
            "id":            gate.id,
            "kind":          "auto" if isinstance(gate, AutoGate) else "key",
            "side":          gate.side,
            "description":   gate.description,
            "open_fraction": round(fraction, 6),
            "open":          fraction > 0.0,
            "reason":        state.get("reason", ""),
            "state":         _scalars(state),
        }
        if isinstance(gate, AutoGate):
            entry["trigger"] = gate.trigger_kind
        else:
            entry["metric"] = gate.key.get("metric", "identity")
            entry["weight"] = gate.weight
            entry["rate"] = gate.rate
            entry["on_close"] = gate.on_close
        return entry


# ──────────────────────────────────────────────────────────────────────
# v2 — the channels schema
# ──────────────────────────────────────────────────────────────────────
#
# v1 declared a seam as one `PermeabilityGate` sitting BETWEEN two
# laminae: a controller reading the sender and a transfer writing
# straight into the receiver.  v2 replaces the single mid-air valve
# with a CHANNEL and a gate on EACH side of it (GATE_CHANNELS_PLAN
# C1/C2): the sender owns transmit-side gates, the receiver owns
# receive-side gates, and a value crosses only when BOTH sides let it.
#
# This section is the v2 SCHEMA CONTRACT — the additive Phase 1 of that
# plan, and nothing more.  `parse_organism_v2` reads a `<channels>`
# body and enforces, at parse time, the rules that live entirely in the
# organism file: 1, 4, 5 and 6 carried over unchanged, plus the new
# 7–12.  Rules 2 and 3 need the laminae themselves, so they stay where
# they already are — enforced against the twins by the caller, exactly
# as v1 does.  Nothing here runs a cycle, and nothing here touches the
# v1 path: `parse_organism`, `load_organism`, the shipped bodies and
# the v1 dataclasses keep working exactly as they did.  Switching the
# shipped bodies onto this schema and deleting v1 is a later step.
#
# The rules enforced here, with their wording kept from the v1 header
# where they overlap:
#
#   1  A gate is CLOSED until its trigger opens it.  There is no
#      `open` / `start_open` attribute to write.
#   4  Every threshold/pattern/key trigger declares TWO boundaries and
#      the shut one sits strictly below the open one.  `metric=
#      "identity"` is exempt: a label matches or it does not, so there
#      is no noise for a single boundary to chatter on.
#   5  Any `<learnable>` needs a clamp (reused `_parse_learnables`).
#   6  One destination attribute, one channel.
#   7  ADJACENCY: |level(from) − level(to)| == 1.  The two laminae must
#      be neighbours in the stack this body declares.
#   8  At most 4 gates per (lamina, side, direction) — direction is
#      "up" when the channel climbs to a higher level, "down"
#      otherwise — counted across every channel the lamina takes part
#      in.
#   9  ONE interface composite per lamina, the same one in every
#      direction: every channel leaving a lamina reads the same
#      composite, because from outside the lamina IS that composite.
#  10  `<transform>` is recognised and refused: the v2 lambda, not
#      supported yet.
#  11  `<permeability_gates>` is refused, pointing at `<channels>`.
#  12  Both `<transmit>` and `<receive>` carry at least one gate.  A
#      bare side would be a wire writing straight into the far lamina.

@dataclass(frozen=True)
class Channel:
    """
    One declared crossing between two ADJACENT laminae, one direction.

    The wire itself (the "synaptic cleft", C1): it carries `time_delay`
    because a delay is a property of the LINE, not of either lamina, and
    it owns the two gate lists — `transmit` on the sender's membrane,
    `receive` on the receiver's — because the value only crosses when
    both ends are open.  Carries no runtime state; a declaration that is
    also a mutable state bag cannot be reloaded, compared or serialised
    without dragging the run along with it (same argument as
    PermeabilityGate).
    """
    id: str
    source: GateEndpoint
    dest: GateEndpoint
    extract: str
    time_delay: int = 0
    transmit: list = field(default_factory=list)    # list[AutoGate | KeyGate]
    receive: list = field(default_factory=list)     # list[AutoGate | KeyGate]

    def __str__(self) -> str:                       # pragma: no cover — display
        return f"{self.source} → {self.dest}"
    description: str = ""


@dataclass(frozen=True)
class AutoGate:
    """
    A gate that reads ITS OWN lamina's composite (C3, the relief valve).

    Auto is internal: it answers to what the lamina it belongs to is
    doing, never to what is being presented from outside.  Its trigger
    is a `<threshold>` (the v1 deviation/attr decision) or a `<pattern>`
    (a weighted-distance match against that same own composite — where
    the failing-pump recogniser from organism_key.xml lands).  When it
    fires it is allowed to flood the channel with `weight == rate == 1`
    (C4); that is a RUNTIME decision, and the parse-time rule is the
    smaller one that a gate is born shut (rule 1).
    """
    id: str
    trigger_kind: str
    trigger: dict
    refractory_cycles: int = 0
    side: str = ""                                  # "transmit" | "receive"
    learnables: list = field(default_factory=list)  # list[Learnable]
    description: str = ""


@dataclass(frozen=True)
class KeyGate:
    """
    A gate that reads what is presented to it on the channel (C3).

    On the transmit side the presentation is the far lamina's need — its
    interface composite; on the receive side it is what the sender has
    offered.  The `key` is the reference it matches against; `weight`
    scales HOW MUCH of the offered deviation is absorbed (C5), and
    `rate` / `on_close` / `confidence` are the receiving behaviour moved
    here from the old Transfer by C6.
    """
    id: str
    key: dict
    weight: float = 1.0
    rate: float = 0.2
    on_close: str = "hold"
    confidence: float = 0.8
    #: The range this receptor will accept a value inside.  Outside it
    #: the value is REFUSED, not clamped: clamping silently pulls
    #: out-of-range physiology back toward normal, which is how a MAP of
    #: 120 gets displayed as 110 and masks the pathology the twin exists
    #: to show.  Refusing says "this seam does not model that", which is
    #: true; clamping says "it is 110", which is not.  Both edges or
    #: neither — half a band is a bound nobody declared.
    band_min: Optional[float] = None
    band_max: Optional[float] = None
    side: str = ""                                  # "transmit" | "receive"
    learnables: list = field(default_factory=list)  # list[Learnable]
    description: str = ""


def _finite_attr(el, name: str, owner: str, default: Optional[float] = None):
    """
    A numeric attribute that is finite, or an OrganismError saying so.

    `_float_attr` turns the text into a float, which accepts `nan` and
    `inf` as happily as it accepts `0.3`; this adds the check that the
    number is real.  A NaN boundary would silently make every comparison
    False — a gate that can never decide — and an infinite one would
    make a deadband no signal could ever leave, so a non-finite number
    is a loud parse error rather than a quietly weird run.  `owner` is
    the "Gate '<id>'" / "Channel '<id>'" prefix that names the offender.
    """
    # Parsed here rather than through `_float_attr`, which builds its own
    # "Gate '<id>'" prefix and would double the one `owner` already
    # carries.  v2 owners are Channels as well as Gates, so the prefix has
    # to come from the caller.
    raw = el.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(raw)
    except ValueError as e:
        raise OrganismError(
            f"{owner} has non-numeric {name}='{raw}'."
        ) from e
    if not math.isfinite(value):
        raise OrganismError(
            f"{owner} has {name}='{el.get(name)}', which is not finite. "
            f"NaN or an infinite number would poison every comparison it "
            f"feeds — a boundary must be a real number."
        )
    return value


def _int_attr(el, name: str, owner: str, default: Optional[int] = None):
    """An attribute that must parse as a whole number, or not at all."""
    raw = el.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError as e:
        raise OrganismError(
            f"{owner} declares {name}='{raw}', which is not an integer. "
            f"Integer-valued declarations that arrive as '2.0' or 'soon' "
            f"are a mistake that would only surface mid-run."
        ) from e


def _fraction(el, name: str, owner: str, default: float) -> float:
    """A finite number in [0,1], where every scaled quantity must live."""
    value = _finite_attr(el, name, owner, default)
    if value is not None and not 0.0 <= value <= 1.0:
        raise OrganismError(
            f"{owner} has {name}={value}, outside [0,1]. The normalised "
            f"space is what lets one set of numbers mean the same thing "
            f"whether the attribute is in L/min or mmHg (G2); a fraction "
            f"outside it is a declaration in the wrong units."
        )
    return value


def _reject_open_declaration(gate_el, gate_id: str) -> None:
    """
    Rule 1 — a gate is CLOSED until its trigger opens it.

    v1 enforced this by having no attribute to write.  v2 has other
    attributes on a gate, so the enforcement has to be active: an
    `open`/`start_open` someone adds is recognised and refused rather
    than ignored, because a declaration that is not read but looks as
    though it should have been is how a model lies to its reader.
    """
    for banned in ("open", "start_open"):
        raw = gate_el.get(banned)
        if raw is not None:
            raise OrganismError(
                f"Gate '{gate_id}' declares {banned}='{raw}'. Rule 1: a "
                f"gate is CLOSED until its trigger opens it — closed is "
                f"the stable state, and a valve that may be born open is "
                f"not a valve. Remove the attribute; the only way to open "
                f"a gate is through its trigger."
            )


def _parse_match_weights(container, gate_id: str) -> dict:
    """
    The `<weight>` list of a `<pattern>` or a shape `<key>`.

    Each weight names an attribute of the composite being matched, a
    `ref` point in [0,1] for it to be compared against, and the text
    weight saying how much that coordinate matters.  Mirrors the v1 key
    weights; a match with nothing to match on is refused the same way.
    """
    weights: dict = {}
    for w_el in container.findall("weight"):
        attr = (w_el.get("attribute") or "").strip()
        if not attr:
            raise OrganismError(
                f"Gate '{gate_id}' has a <weight> with no attribute."
            )
        ref = _finite_attr(w_el, "ref", f"Gate '{gate_id}'")
        if ref is None:
            raise OrganismError(
                f"Gate '{gate_id}' key weight '{attr}' declares no ref. A "
                f"match is scored against a reference point, so every "
                f"weighted attribute needs one, in [0,1] (G2)."
            )
        if not 0.0 <= ref <= 1.0:
            raise OrganismError(
                f"Gate '{gate_id}' key weight '{attr}' has ref={ref}, "
                f"outside [0,1]. The key lives in normalised space so it "
                f"stays domain-neutral."
            )
        raw_weight = (w_el.text or "1.0").strip()
        try:
            weight = float(raw_weight)
        except ValueError as e:
            raise OrganismError(
                f"Gate '{gate_id}' key weight '{attr}' is not a number."
            ) from e
        if not math.isfinite(weight):
            raise OrganismError(
                f"Gate '{gate_id}' key weight '{attr}' is not finite."
            )
        weights[attr] = (weight, ref)
    if not weights:
        raise OrganismError(
            f"Gate '{gate_id}' declares a <{container.tag}> with no "
            f"weights, so there is nothing for it to match on."
        )
    return weights


def _parse_threshold_trigger(trigger_el, gate_id: str) -> dict:
    """
    The `<threshold>` child of an auto gate — rule 4 kept verbatim.

    A threshold trigger watches its own lamina's vector and reduces it
    to one number with `aggregate`; the two boundaries (G3) are
    mandatory and must be the right way round.
    """
    aggregate = (trigger_el.get("aggregate") or "attr").strip()
    if aggregate not in KNOWN_AGGREGATES:
        raise OrganismError(
            f"Gate '{gate_id}' has aggregate='{aggregate}'. Known: "
            f"{sorted(KNOWN_AGGREGATES)}."
        )
    watch = (trigger_el.get("watch") or "").strip()
    if aggregate in ("attr", "deviation") and not watch:
        raise OrganismError(
            f"Gate '{gate_id}' aggregates on a single attribute but names "
            f"none — add watch=\"<attribute id>\"."
        )
    open_above = _finite_attr(trigger_el, "open_above", f"Gate '{gate_id}'")
    close_below = _finite_attr(trigger_el, "close_below", f"Gate '{gate_id}'")
    if open_above is None or close_below is None:
        raise OrganismError(
            f"Gate '{gate_id}' is a threshold trigger and must declare "
            f"both open_above and close_below. One threshold chatters: "
            f"the feed carries deliberate noise, so a value sitting on a "
            f"single boundary opens and shuts the gate every cycle (G3)."
        )
    if not float(close_below) < float(open_above):
        raise OrganismError(
            f"Gate '{gate_id}' has close_below={close_below} which is not "
            f"below open_above={open_above}. Without a gap there is no "
            f"deadband, and without a deadband there is no hysteresis."
        )
    trigger = {
        "aggregate": aggregate,
        "open_above": open_above,
        "close_below": close_below,
    }
    if watch:
        trigger["watch"] = watch
    if aggregate == "deviation":
        reference = _finite_attr(trigger_el, "reference", f"Gate '{gate_id}'")
        if reference is None:
            raise OrganismError(
                f"Gate '{gate_id}' aggregates on deviation but declares no "
                f"reference. A distance needs a point to be a distance "
                f"from, and leaving it to default to 0.0 would silently "
                f"turn the gate back into the one-sided thing deviation "
                f"exists to replace."
            )
        if not 0.0 <= reference <= 1.0:
            raise OrganismError(
                f"Gate '{gate_id}' has reference={reference}, outside "
                f"[0,1]. The reference is a point in the normalised space "
                f"the vector already lives in (G2)."
            )
        trigger["reference"] = reference
    return trigger


def _parse_pattern_trigger(trigger_el, gate_id: str) -> dict:
    """
    The `<pattern>` child of an auto gate — a shape match on its own side.

    Pattern recognition is internal recognition (where organism_key.xml's
    failing-pump gate lands), so a pattern trigger is a weighted-distance
    match against the lamina's OWN composite vector; it still needs the
    two boundaries of rule 4, for the same measured reason every other
    trigger does.
    """
    match_threshold = _finite_attr(trigger_el, "match_threshold",
                                   f"Gate '{gate_id}'")
    release_below = _finite_attr(trigger_el, "release_below",
                                 f"Gate '{gate_id}'")
    if match_threshold is None or release_below is None:
        raise OrganismError(
            f"Gate '{gate_id}' is a pattern trigger and must declare both "
            f"match_threshold and release_below. One boundary on a noisy "
            f"signal chatters — declare the shut boundary too."
        )
    if not float(release_below) < float(match_threshold):
        raise OrganismError(
            f"Gate '{gate_id}' has release_below={release_below} which is "
            f"not below match_threshold={match_threshold}. Without a gap "
            f"there is no deadband."
        )
    return {
        "match_threshold": match_threshold,
        "release_below": release_below,
        "weights": _parse_match_weights(trigger_el, gate_id),
    }


def _parse_key_block(key_el, gate_id: str) -> dict:
    """
    The `<key>` of a key gate, and its metric's own rules.

    `metric='identity'` matches a label (rule 4's exemption): there is no
    noise to chatter on, so no boundaries are required.  The two shape
    metrics score against a reference point and need the two boundaries
    and at least one weight, exactly like a v1 key.  The optional `from`
    names whose composite is being presented — the far lamina's need on
    a transmit-side key (C3).
    """
    metric = (key_el.get("metric") or "weighted_distance").strip()
    if metric not in KNOWN_KEY_METRICS:
        raise OrganismError(
            f"Gate '{gate_id}' has metric='{metric}'. Known: "
            f"{sorted(KNOWN_KEY_METRICS)}."
        )
    block: dict = {"metric": metric}
    raw_from = (key_el.get("from") or "").strip()
    if raw_from:
        block["from"] = _endpoint(raw_from, gate_id, "from")
    if metric != "identity":
        match_threshold = _finite_attr(key_el, "match_threshold",
                                       f"Gate '{gate_id}'")
        release_below = _finite_attr(key_el, "release_below",
                                     f"Gate '{gate_id}'")
        if match_threshold is None or release_below is None:
            raise OrganismError(
                f"Gate '{gate_id}' declares a key with metric '{metric}' "
                f"and must declare both match_threshold and release_below. "
                f"One boundary on a noisy signal chatters — declare the "
                f"shut boundary too."
            )
        if not float(release_below) < float(match_threshold):
            raise OrganismError(
                f"Gate '{gate_id}' has release_below={release_below} which "
                f"is not below match_threshold={match_threshold}. Without "
                f"a gap there is no deadband."
            )
        block["match_threshold"] = match_threshold
        block["release_below"] = release_below
        block["weights"] = _parse_match_weights(key_el, gate_id)
    return block


def _parse_auto_gate(gate_el, channel_id: str, side: str) -> AutoGate:
    """
    One `<auto_gate>`: exactly one trigger, and rule 1 / rule 4 / rule 5.

    An auto gate that declares no trigger would be a gate nothing can
    open, and one that declares two would be a gate nobody can say what
    opened — so both are refused.  Everything else it may carry is a
    `<learnable>`, which `_parse_learnables` guards (rule 5).
    """
    gate_id = (gate_el.get("id") or "").strip()
    if not gate_id:
        raise OrganismError(
            f"Channel '{channel_id}' {side} declares an <auto_gate> with "
            f"no id attribute."
        )
    _reject_open_declaration(gate_el, gate_id)

    trigger_el = None
    for child in gate_el:
        if child.tag in KNOWN_TRIGGER_KINDS:
            if trigger_el is not None:
                raise OrganismError(
                    f"Gate '{gate_id}' declares more than one trigger. An "
                    f"auto gate answers to exactly one <threshold> or "
                    f"<pattern>; two is two gates wearing one id."
                )
            trigger_el = child
        elif child.tag in ("learnable", "description"):
            continue
        else:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <{child.tag}>. An auto gate "
                f"answers to one <threshold> or <pattern> trigger and may "
                f"carry <description> and <learnable>s — nothing else."
            )
    if trigger_el is None:
        raise OrganismError(
            f"Gate '{gate_id}' declares no trigger. An auto gate is "
            f"CLOSED until its <threshold> or <pattern> trigger opens it, "
            f"and a gate with no trigger is a gate that can never open."
        )

    trigger_kind = trigger_el.tag
    if trigger_kind == "threshold":
        trigger = _parse_threshold_trigger(trigger_el, gate_id)
    else:
        trigger = _parse_pattern_trigger(trigger_el, gate_id)

    refractory = _int_attr(gate_el, "refractory_cycles",
                           f"Gate '{gate_id}'", 0)
    if refractory is not None and refractory < 0:
        raise OrganismError(
            f"Gate '{gate_id}' has a negative refractory_cycles. A gate "
            f"cannot hold a state for a negative number of cycles."
        )
    return AutoGate(
        id=gate_id,
        trigger_kind=trigger_kind,
        trigger=trigger,
        refractory_cycles=refractory,
        side=side,
        learnables=_parse_learnables(gate_el, gate_id),
        description=(gate_el.findtext("description", "") or "").strip()
    )


def _parse_key_gate(gate_el, channel_id: str, side: str) -> KeyGate:
    """
    One `<key_gate>`: a `<key>` block plus the receiving behaviour (C6).

    `weight` is how much of the offered deviation this lamina absorbs
    (C5), and it is the one thing rule 5 may be asked to learn.  `rate`,
    `on_close` and `confidence` are the absorbing behaviour that moved
    off the old mid-air Transfer onto the receiver's own gate.
    """
    gate_id = (gate_el.get("id") or "").strip()
    if not gate_id:
        raise OrganismError(
            f"Channel '{channel_id}' {side} declares a <key_gate> with no "
            f"id attribute."
        )
    if gate_el.get("time_delay") is not None:
        raise OrganismError(
            f"Gate '{gate_id}' declares time_delay. A delay is a property "
            f"of the WIRE, not of either end of it, so it belongs on the "
            f"<channel>. Declared here it would be read by nobody, which "
            f"is worse than being refused."
        )
    _reject_open_declaration(gate_el, gate_id)

    weight = _fraction(gate_el, "weight", f"Gate '{gate_id}'", 1.0)
    rate = _fraction(gate_el, "rate", f"Gate '{gate_id}'", 0.2)
    confidence = _fraction(gate_el, "confidence", f"Gate '{gate_id}'", 0.8)
    on_close = (gate_el.get("on_close") or "hold").strip()
    if on_close not in KNOWN_ON_CLOSE:
        raise OrganismError(
            f"Gate '{gate_id}' has on_close='{on_close}'. Known: "
            f"{sorted(KNOWN_ON_CLOSE)}."
        )

    key_el = None
    for child in gate_el:
        if child.tag == "key":
            if key_el is not None:
                raise OrganismError(
                    f"Gate '{gate_id}' declares more than one <key>. A key "
                    f"gate holds exactly one reference to match against."
                )
            key_el = child
        elif child.tag in ("learnable", "description"):
            continue
        else:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <{child.tag}>. A key gate "
                f"carries one <key> and may carry <description> and "
                f"<learnable>s — nothing else."
            )
    if key_el is None:
        raise OrganismError(
            f"Gate '{gate_id}' is a key gate and declares no <key> block."
        )

    band_min = _finite_attr(gate_el, "band_min", f"Gate '{gate_id}'")
    band_max = _finite_attr(gate_el, "band_max", f"Gate '{gate_id}'")
    if (band_min is None) != (band_max is None):
        raise OrganismError(
            f"Gate '{gate_id}' declares only "
            f"{'band_min' if band_max is None else 'band_max'}. A band has "
            f"two edges; one edge is a bound in a direction nobody said, so "
            f"declare both or neither."
        )
    if band_min is not None and not band_min < band_max:
        raise OrganismError(
            f"Gate '{gate_id}' has band_min={band_min} which is not below "
            f"band_max={band_max}. A band that way round accepts nothing."
        )
    return KeyGate(
        id=gate_id,
        key=_parse_key_block(key_el, gate_id),
        weight=weight,
        rate=rate,
        on_close=on_close,
        confidence=confidence,
        side=side,
        learnables=_parse_learnables(gate_el, gate_id),
        description=(gate_el.findtext("description", "") or "").strip(),
        band_min=band_min,
        band_max=band_max
    )


def _no_gate_on_side(channel_id: str, side: str) -> OrganismError:
    """Rule 12 — the message a side that cannot gate anything earns."""
    return OrganismError(
        f"Channel '{channel_id}' has a <{side}> with no gate in it. A "
        f"side without a gate is a wire that writes straight into the far "
        f"lamina, which is the thing this whole design exists to forbid — "
        f"declare at least one <auto_gate> or <key_gate> on the <{side}>."
    )


def _parse_side(side_el, channel_id: str, side: str) -> list:
    """
    One side of a channel: its gates, in declaration order.

    Anything that is not an auto gate or a key gate is refused rather
    than skipped, on the same argument as KNOWN_CONTROLLERS in v1: a
    declared element that is silently not run is a gate nobody knows is
    shut forever.
    """
    gates: list = []
    for gate_el in side_el:
        if gate_el.tag == "auto_gate":
            gates.append(_parse_auto_gate(gate_el, channel_id, side))
        elif gate_el.tag == "key_gate":
            gates.append(_parse_key_gate(gate_el, channel_id, side))
        else:
            raise OrganismError(
                f"Channel '{channel_id}' {side} declares a "
                f"<{gate_el.tag}>. Only {sorted(KNOWN_V2_GATE_TAGS)} live "
                f"on a side."
            )
    return gates


def _parse_channel_v2(channel_el) -> Channel:
    """
    One `<channel>`, with every rule that one channel can answer alone.

    Rules 1, 4, 5, 10 and 12 are decided here.  Rules 6–9 need the other
    channels and the stack, so `parse_organism_v2` checks those against
    the assembled whole.
    """
    channel_id = (channel_el.get("id") or "").strip()
    if not channel_id:
        raise OrganismError("Encountered a <channel> with no id attribute.")

    if channel_el.find(".//transform") is not None:
        raise OrganismError(
            f"Channel '{channel_id}' declares a <transform>. A transform "
            f"is the v2 lambda — not supported yet. Declare what crosses "
            f"with weights and rates instead; a transform is refused now "
            f"so nobody reaches for one and discovers it silently does "
            f"nothing."
        )

    source = _endpoint(channel_el.get("from", ""), channel_id, "from",
                       owner_kind="Channel")
    dest = _endpoint(channel_el.get("to", ""), channel_id, "to",
                     owner_kind="Channel")

    extract_el = channel_el.find("extract")
    if extract_el is None or not (extract_el.get("attribute") or "").strip():
        raise OrganismError(
            f"Channel '{channel_id}' declares no "
            f"<extract attribute=\"...\"/>. The source is a composite "
            f"(rule 2), so the channel has to say which of its attributes "
            f"goes on the wire."
        )
    extract = extract_el.get("attribute").strip()

    time_delay = _int_attr(channel_el, "time_delay",
                           f"Channel '{channel_id}'", 0)
    if time_delay is not None and time_delay < 0:
        raise OrganismError(
            f"Channel '{channel_id}' has a negative time_delay. A delay "
            f"line cannot run for a negative number of cycles."
        )

    # An element the channel does not understand is refused rather than
    # skipped, on the same argument as rule 10.  A <learnable> written
    # here instead of inside a gate parses, is read by nobody, and leaves
    # a file that says a parameter may adapt while nothing ever adapts
    # it — a declaration that is quietly untrue, which is worse than one
    # that fails.
    known = {"description", "extract", "transmit", "receive", "transform"}
    for child in channel_el:
        if child.tag not in known:
            raise OrganismError(
                f"Channel '{channel_id}' declares a <{child.tag}>, which a "
                f"channel does not carry. It holds <description>, "
                f"<extract>, <transmit> and <receive>. A <learnable> "
                f"belongs inside the gate whose parameter it names."
            )

    transmit_el = channel_el.find("transmit")
    receive_el = channel_el.find("receive")
    if transmit_el is None:
        raise _no_gate_on_side(channel_id, "transmit")
    if receive_el is None:
        raise _no_gate_on_side(channel_id, "receive")

    transmit = _parse_side(transmit_el, channel_id, "transmit")
    receive = _parse_side(receive_el, channel_id, "receive")
    if not transmit:
        raise _no_gate_on_side(channel_id, "transmit")
    if not receive:
        raise _no_gate_on_side(channel_id, "receive")

    return Channel(
        id=channel_id,
        source=source,
        dest=dest,
        extract=extract,
        time_delay=time_delay,
        transmit=transmit,
        receive=receive,
        description=(channel_el.findtext("description", "") or "").strip(),
    )


def parse_organism_v2(path: Path | str) -> OrganismSpec:
    """
    Read a `<channels>` (v2) body and check every rule it can, alone.

    This is the v2 sibling of `parse_organism`: the parse-time contract
    for the new schema, enforced the moment the file is read.  Rules 1,
    4, 5 and 12 are decided inside each channel; rules 6–9 need the
    whole body (the stack and every other channel), so they are checked
    here as the channels are assembled.  Rules 2 and 3 need the laminae
    and are NOT checked here — the caller validates them against the
    twins exactly as it would for v1.  Nothing here runs a cycle.

    The v1 schema is refused by name (rule 11) rather than re-read: a
    body written for the old gates would parse into something that looks
    like the new one while meaning something different, and a wrong
    model that parses cleanly is the worst kind of wrong.
    """
    resolved = Path(path)
    root = ET.parse(str(resolved)).getroot()
    if root.tag != "organism":
        raise OrganismError(
            f"{resolved} has root <{root.tag}>, expected <organism>."
        )
    organism_id = (root.get("id") or "").strip()
    if not organism_id:
        raise OrganismError(
            f"{resolved} declares an <organism> with no id attribute."
        )

    # ── Rule 11, first: the old schema is refused, not re-interpreted ──
    # This has to precede the lamina walk, because a v1 body's laminae
    # carry no `level` and would otherwise die on rule 7's input before
    # the reader is told the real fix is to move to <channels>.
    if root.find(".//permeability_gates") is not None:
        raise OrganismError(
            f"Organism '{organism_id}' declares <permeability_gates>, the "
            f"v1 schema. This is the v2 parser: v2 bodies declare "
            f"<channels> instead, one per one-way crossing, with a gate "
            f"on BOTH ends. Migrate the body to <channels>; this parser "
            f"will not quietly re-read the old shape."
        )

    # ── the stack ─────────────────────────────────────────────────────
    laminae_el = root.find("laminae")
    if laminae_el is None:
        raise OrganismError(
            f"Organism '{organism_id}' declares no <laminae> block."
        )
    lamina_ids: list = []
    levels: dict = {}
    for el in laminae_el.findall("lamina"):
        lid = (el.get("id") or "").strip()
        if not lid:
            raise OrganismError(
                f"Organism '{organism_id}' lists a <lamina> with no id "
                f"attribute."
            )
        if lid in lamina_ids:
            raise OrganismError(f"Lamina '{lid}' is listed twice.")
        raw_level = el.get("level")
        if raw_level is None or not str(raw_level).strip():
            raise OrganismError(
                f"Lamina '{lid}' has no level. In v2 the stack is a "
                f"property of the BODY — a lamina can stand at different "
                f"levels in different bodies — so each <lamina> must "
                f"declare level=\"<n>\" here."
            )
        level = _int_attr(el, "level", f"Lamina '{lid}'")
        levels[lid] = level
        lamina_ids.append(lid)
    if not lamina_ids:
        raise OrganismError(
            f"Organism '{organism_id}' lists no laminae."
        )

    # ── the channels ──────────────────────────────────────────────────
    channels_el = root.find("channels")
    if channels_el is None:
        raise OrganismError(
            f"Organism '{organism_id}' declares no <channels> block. This "
            f"is the v2 parser; a v2 body says where values cross under "
            f"<channels>, never under the v1 <permeability_gates>."
        )

    channels: list = []
    seen_channels: set = set()
    seen_gates: dict = {}                 # gate id -> channel id
    feeding: dict = {}                    # destination address -> channel id
    face_counts: dict = {}                # (lamina, face) -> gate count
    faces: dict = {}                      # (lamina, direction) -> (member, id)

    for channel_el in channels_el.findall("channel"):
        ch = _parse_channel_v2(channel_el)
        if ch.id in seen_channels:
            raise OrganismError(f"Duplicate channel id '{ch.id}'.")
        seen_channels.add(ch.id)

        for end, which in ((ch.source, "from"), (ch.dest, "to")):
            if end.lamina not in lamina_ids:
                raise OrganismError(
                    f"Channel '{ch.id}' {which} lamina '{end.lamina}', "
                    f"which this organism does not list. Declared: "
                    f"{lamina_ids}."
                )

        # A channel from a lamina to itself is caught by adjacency below
        # — the distance is 0, not 1 — but the message that produces
        # names the same lamina twice with the same level and reads like
        # a claim about two different ones.  Said plainly here instead.
        if ch.source.lamina == ch.dest.lamina:
            raise OrganismError(
                f"Channel '{ch.id}' runs from lamina '{ch.source.lamina}' "
                f"to itself. A channel couples two laminae; a lamina "
                f"reaching its own attributes is doing that inside its "
                f"own file, where it needs no channel and no gates."
            )

        # ── Rule 7: adjacency ─────────────────────────────────────────
        # A channel is a talk between neighbours.  Coupling a lamina to a
        # grandparent hides the middle of the stack from the thing that
        # should mediate it, which is how cross-laminar chaos arrives.
        from_level = levels[ch.source.lamina]
        to_level = levels[ch.dest.lamina]
        if abs(from_level - to_level) != 1:
            raise OrganismError(
                f"Channel '{ch.id}' couples lamina '{ch.source.lamina}' "
                f"(level {from_level}) to lamina '{ch.dest.lamina}' "
                f"(level {to_level}). Rule 7: only ADJACENT laminae "
                f"couple — a channel steps exactly one level, because "
                f"each lamina is only entitled to talk to its neighbours. "
                f"Add an intermediate lamina, or change a level."
            )
        direction = "up" if to_level > from_level else "down"

        # ── Rule 6: one destination attribute, one channel ─────────────
        # The v1 rule, carried over whole: two channels onto one attribute
        # both report carrying a value and the one declared last silently
        # wins, so every reader downstream names a channel that did not
        # put the number there.
        address = str(ch.dest)
        if address in feeding:
            raise OrganismError(
                f"Channel '{ch.id}' feeds '{address}', which channel "
                f"'{feeding[address]}' already feeds. Two channels onto "
                f"one attribute do not arbitrate: both report carrying a "
                f"value and the one declared last silently overwrites the "
                f"other. Give this seam one channel, or give the "
                f"receiving lamina a second attribute to land on."
            )
        feeding[address] = ch.id

        # ── Rule 8: at most 4 gates on one FACE of a lamina ────────────
        # A face is a direction seen from the lamina itself, which is not
        # the same as the channel's direction.  The sender looks toward
        # the destination; the receiver looks back toward the source, so
        # a wire that travels UP presents the receiving lamina with a
        # DOWNWARD face.  Both sides' gates land on the same face count,
        # because a gate is on the membrane whether it is letting
        # something out through it or in through it.
        for side, lamina, face in (
            ("transmit", ch.source.lamina, direction),
            ("receive", ch.dest.lamina, "down" if direction == "up" else "up"),
        ):
            key = (lamina, face)
            face_counts[key] = (
                face_counts.get(key, 0) + len(getattr(ch, side))
            )
            if face_counts[key] > MAX_GATES_PER_FACE:
                raise OrganismError(
                    f"Channel '{ch.id}' brings lamina '{lamina}' to "
                    f"{face_counts[key]} gates on its {face}ward face. "
                    f"Rule 8: at most {MAX_GATES_PER_FACE} per face, so at "
                    f"most {MAX_GATES_PER_FACE * 2} on a lamina. A face "
                    f"needing more conditions than that is more than one "
                    f"face."
                )

        # ── Rule 9: ONE interface composite per lamina ─────────────────
        # L1, in its strict reading (Q2, settled 2026-09-03): from
        # outside, a lamina IS one composite — not one per direction.
        # Every channel leaving it, upward or downward, reads the same
        # face.  The looser per-direction version would let a lamina be
        # one thing to the layer above and another to the layer below,
        # which is two laminae wearing one id.
        #
        # The cost of the strict reading is deliberate and worth stating:
        # a lamina that sits in the middle of a stack must find a single
        # composite that says everything its neighbours on BOTH sides
        # need.  If no such composite exists, that is a signal the lamina
        # is doing two jobs, and the fix is to split it rather than to
        # give it a second face.
        previous = faces.get(ch.source.lamina)
        if previous is not None and previous[0] != ch.source.member:
            raise OrganismError(
                f"Channel '{ch.id}' leaves lamina '{ch.source.lamina}' on "
                f"composite '{ch.source.member}', but channel "
                f"'{previous[1]}' already leaves it on composite "
                f"'{previous[0]}'. Rule 9: a lamina presents ONE interface "
                f"composite, the same one in every direction — from "
                f"outside, the lamina IS that composite. A lamina needing "
                f"two faces is two laminae."
            )
        faces.setdefault(ch.source.lamina, (ch.source.member, ch.id))

        for gate in [*ch.transmit, *ch.receive]:
            if gate.id in seen_gates:
                raise OrganismError(
                    f"Duplicate gate id '{gate.id}' (channel '{ch.id}'; "
                    f"first declared in channel "
                    f"'{seen_gates[gate.id]}')."
                )
            seen_gates[gate.id] = ch.id

        channels.append(ch)

    return OrganismSpec(
        id=organism_id,
        version=root.get("version", "2.0"),
        lamina_ids=lamina_ids,
        name=(root.findtext("name", "") or "").strip(),
        description=(root.findtext("description", "") or "").strip(),
        levels=levels,
        channels=channels,
    )
