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

#: The most gates any (lamina, side, direction) may carry (rule 8).
#: Lee's L5 says ≤ 8 per lamina, 4 up and 4 down; split across the two
#: sides of the membrane this becomes 4 per (lamina, side, direction),
#: which is the finer rule the parser enforces.
MAX_GATES_PER_SIDE_DIRECTION = 4


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
class Transfer:
    """
    What crosses, and how fast, once the controller has opened the gate.

    `rate` is the EWMA coefficient applied once per cycle of the
    RECEIVING lamina, and `time_delay` is counted in those same cycles.
    Both are here from v1 rather than deferred, because two feedback
    loops pulling on each other through an open gate is the failure mode
    this design most expects, and a low-pass filter is the cheapest
    defence against it (G4).
    """
    mode: str = "proportional"
    rate: float = 0.2
    time_delay: int = 0
    on_close: str = "hold"
    confidence: float = 0.8
    band_min: Optional[float] = None
    band_max: Optional[float] = None


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
class PermeabilityGate:
    """
    One declared crossing between two laminae.

    Carries no runtime state.  The controller's state lives on the
    Organism container in Phase 2, keyed by gate id — the same placement
    as `FeedbackController._kernel_state`, and for the same reason: a
    declaration that is also a mutable state bag cannot be reloaded,
    compared, or serialised without dragging the run along with it.
    """
    id: str
    source: GateEndpoint
    dest: GateEndpoint
    controller: str
    extract: str
    controller_params: dict = field(default_factory=dict)
    transfer: Transfer = field(default_factory=Transfer)
    key_weights: dict = field(default_factory=dict)   # attr → (weight, ref)
    key_params: dict = field(default_factory=dict)
    learnables: list = field(default_factory=list)    # list[Learnable]
    description: str = ""

    @property
    def starts_closed(self) -> bool:
        """
        Rule 1, as a value rather than a comment.

        Always True.  There is no attribute in the schema that could
        make it False, which is the enforcement: closed is not a default
        anyone can override, it is the only state a gate can be born in.
        """
        return True

    def controller_args(self) -> dict:
        """
        Everything this gate's controller needs, in one dict.

        The parser keeps `<controller_params>` and `<key>` apart because
        they are different elements answering to different rules; a
        controller does not care which element a number arrived in, and
        making it care would put XML structure inside the maths.
        """
        args = dict(self.controller_params)
        if self.key_weights or self.key_params:
            args.update(self.key_params)
            args["key_weights"] = self.key_weights
        return args


@dataclass
class OrganismSpec:
    """The parsed `organism.xml`: which laminae, and which gates."""
    id: str
    version: str
    lamina_ids: list
    gates: list                                       # list[PermeabilityGate]
    name: str = ""
    description: str = ""
    #: Each lamina's place in the stack, `<lamina_id> → level` (v2).  v1
    #: bodies have no `<lamina level=...>` and leave this empty; the v2
    #: parser fills it, because adjacency (rule 7) is decided here — the
    #: level is a property of THIS body, not of the lamina, which is why
    #: it sits in the organism file rather than being read off the lamina.
    levels: dict = field(default_factory=dict)
    #: list[Channel] for a v2 body.  v1 keeps using `gates`; the two
    #: lists are never both populated, and the field exists so a spec of
    #: either schema answers "what crosses here?" in one place.
    channels: list = field(default_factory=list)

    def gates_into(self, lamina_id: str) -> list:
        """Every gate whose destination is this lamina."""
        return [g for g in self.gates if g.dest.lamina == lamina_id]

    def gates_out_of(self, lamina_id: str) -> list:
        """Every gate whose source is this lamina."""
        return [g for g in self.gates if g.source.lamina == lamina_id]


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


def _parse_gate(gate_el) -> PermeabilityGate:
    """One `<gate>`, with every rule that can be checked without the laminae."""
    gate_id = (gate_el.get("id") or "").strip()
    if not gate_id:
        raise OrganismError("Encountered a <gate> with no id attribute.")

    controller = (gate_el.get("controller") or "").strip()
    if controller not in KNOWN_CONTROLLERS:
        raise OrganismError(
            f"Gate '{gate_id}' names controller '{controller}'. Known "
            f"controllers: {sorted(KNOWN_CONTROLLERS)}."
        )

    source = _endpoint(gate_el.get("from", ""), gate_id, "from")
    dest = _endpoint(gate_el.get("to", ""), gate_id, "to")
    if source.lamina == dest.lamina:
        raise OrganismError(
            f"Gate '{gate_id}' runs from lamina '{source.lamina}' to itself. "
            f"A value moving inside one lamina is what its function chain "
            f"and its feedback loop are for; a gate is for crossing between."
        )

    extract_el = gate_el.find("extract")
    if extract_el is None or not (extract_el.get("attribute") or "").strip():
        raise OrganismError(
            f"Gate '{gate_id}' declares no <extract attribute=\"...\"/>. The "
            f"source is a composite (rule 2), so the gate has to say which "
            f"of its attributes goes on the wire."
        )
    extract = extract_el.get("attribute").strip()

    # ── controller params, including rule 4 ──────────────────────────
    params: dict = {}
    cp_el = gate_el.find("controller_params")
    if cp_el is not None:
        for k, v in cp_el.attrib.items():
            try:
                params[k] = float(v)
            except ValueError:
                params[k] = v      # watch / aggregate are names, not numbers

    if controller == "threshold":
        open_above = params.get("open_above")
        close_below = params.get("close_below")
        if open_above is None or close_below is None:
            raise OrganismError(
                f"Gate '{gate_id}' is a threshold gate and must declare both "
                f"open_above and close_below. One threshold chatters: the "
                f"feed carries deliberate noise, so a value sitting on a "
                f"single boundary opens and shuts the gate every cycle (G3)."
            )
        if not float(close_below) < float(open_above):
            raise OrganismError(
                f"Gate '{gate_id}' has close_below={close_below} which is not "
                f"below open_above={open_above}. Without a gap there is no "
                f"deadband, and without a deadband there is no hysteresis."
            )
        aggregate = params.get("aggregate", "attr")
        if aggregate not in KNOWN_AGGREGATES:
            raise OrganismError(
                f"Gate '{gate_id}' has aggregate='{aggregate}'. Known: "
                f"{sorted(KNOWN_AGGREGATES)}."
            )
        if aggregate in ("attr", "deviation") and not params.get("watch"):
            raise OrganismError(
                f"Gate '{gate_id}' aggregates on a single attribute but names "
                f"none — add watch=\"<attribute id>\"."
            )
        if aggregate == "deviation":
            reference = params.get("reference")
            if reference is None:
                raise OrganismError(
                    f"Gate '{gate_id}' aggregates on deviation but declares no "
                    f"reference. A distance needs a point to be a distance "
                    f"from, and leaving it to default to 0.0 would silently "
                    f"turn the gate back into the one-sided thing deviation "
                    f"exists to replace."
                )
            if not 0.0 <= float(reference) <= 1.0:
                raise OrganismError(
                    f"Gate '{gate_id}' has reference={reference}, outside "
                    f"[0,1]. The reference is a point in the normalised space "
                    f"the vector already lives in, which is what keeps the "
                    f"thresholds domain-neutral (G2)."
                )

    # ── key controller ───────────────────────────────────────────────
    key_weights: dict = {}
    key_params: dict = {}
    key_el = gate_el.find("key")
    if controller == "key":
        if key_el is None:
            raise OrganismError(
                f"Gate '{gate_id}' is a key gate and declares no <key> block."
            )
    if key_el is not None:
        match_threshold = _float_attr(key_el, "match_threshold", gate_id, 0.9)
        # Rule 4 covers this controller too, and it is here because
        # measuring said so rather than by symmetry: a key gate with one
        # threshold, sitting just above it on the noisy feed, flipped
        # open/shut 148 times in 400 cycles.
        release_below = _float_attr(key_el, "release_below", gate_id)
        if release_below is None:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <key> with match_threshold but "
                f"no release_below. One boundary on a noisy signal chatters — "
                f"measured at 148 flips in 400 cycles for a key sitting just "
                f"above its threshold. Declare the shut boundary too."
            )
        if not release_below < match_threshold:
            raise OrganismError(
                f"Gate '{gate_id}' has release_below={release_below} which is "
                f"not below match_threshold={match_threshold}. Without a gap "
                f"there is no deadband."
            )
        key_params = {
            "metric": key_el.get("metric", "weighted_distance"),
            "match_threshold": match_threshold,
            "release_below": release_below,
        }
        for w_el in key_el.findall("weight"):
            attr = (w_el.get("attribute") or "").strip()
            if not attr:
                raise OrganismError(
                    f"Gate '{gate_id}' has a key <weight> with no attribute."
                )
            ref = _float_attr(w_el, "ref", gate_id)
            if ref is None:
                raise OrganismError(
                    f"Gate '{gate_id}' key weight '{attr}' declares no ref. "
                    f"A key is matched against a reference point, so every "
                    f"weighted attribute needs one, in [0,1] (G2)."
                )
            if not 0.0 <= ref <= 1.0:
                raise OrganismError(
                    f"Gate '{gate_id}' key weight '{attr}' has ref={ref}, "
                    f"outside [0,1]. The key lives in normalised space so it "
                    f"stays domain-neutral."
                )
            try:
                weight = float((w_el.text or "1.0").strip())
            except ValueError as e:
                raise OrganismError(
                    f"Gate '{gate_id}' key weight '{attr}' is not a number."
                ) from e
            key_weights[attr] = (weight, ref)
        if not key_weights:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <key> with no weights, so there "
                f"is nothing for it to match on."
            )

    # ── transfer ─────────────────────────────────────────────────────
    transfer = Transfer()
    t_el = gate_el.find("transfer")
    if t_el is not None:
        transfer = Transfer(
            mode=t_el.get("mode", "proportional"),
            rate=_float_attr(t_el, "rate", gate_id, 0.2),
            time_delay=int(_float_attr(t_el, "time_delay", gate_id, 0)),
            on_close=t_el.get("on_close", "hold"),
            confidence=_float_attr(t_el, "confidence", gate_id, 0.8),
            band_min=_float_attr(t_el, "band_min", gate_id),
            band_max=_float_attr(t_el, "band_max", gate_id),
        )
    if transfer.mode not in KNOWN_TRANSFER_MODES:
        raise OrganismError(
            f"Gate '{gate_id}' has transfer mode='{transfer.mode}'. Known: "
            f"{sorted(KNOWN_TRANSFER_MODES)}."
        )
    if transfer.mode == "band":
        if transfer.band_min is None or transfer.band_max is None:
            raise OrganismError(
                f"Gate '{gate_id}' is a band transfer and must declare both "
                f"band_min and band_max. A band with one edge is not a band, "
                f"and the gate would quietly become a one-sided filter."
            )
        if not transfer.band_min < transfer.band_max:
            raise OrganismError(
                f"Gate '{gate_id}' has band_min={transfer.band_min} which is "
                f"not below band_max={transfer.band_max}."
            )
    if transfer.on_close not in KNOWN_ON_CLOSE:
        raise OrganismError(
            f"Gate '{gate_id}' has on_close='{transfer.on_close}'. Known: "
            f"{sorted(KNOWN_ON_CLOSE)}."
        )
    if not 0.0 < transfer.rate <= 1.0:
        raise OrganismError(
            f"Gate '{gate_id}' has rate={transfer.rate}, outside (0,1]. The "
            f"rate is an EWMA coefficient: 0 would never transmit anything "
            f"and above 1 would overshoot every value it carried."
        )
    if transfer.time_delay < 0:
        raise OrganismError(
            f"Gate '{gate_id}' has a negative time_delay."
        )

    return PermeabilityGate(
        id=gate_id,
        source=source,
        dest=dest,
        controller=controller,
        extract=extract,
        controller_params=params,
        transfer=transfer,
        key_weights=key_weights,
        key_params=key_params,
        learnables=_parse_learnables(gate_el, gate_id),
        description=(gate_el.findtext("description", "") or "").strip(),
    )


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
            "gates":   len(root.findall(".//permeability_gates/gate")),
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
    Read `organism.xml` and check everything that does not need the laminae.

    Rules 1, 4 and 5 are decided entirely by this file, along with
    address syntax and the controller/transfer vocabularies.  Rules 2
    and 3 are about what the two laminae actually declare, so they need
    the laminae — see `validate_against_laminae`.  `load_organism`
    does both.
    """
    resolved = resolve_organism(path)
    root = ET.parse(str(resolved)).getroot()
    if root.tag != "organism":
        raise OrganismError(
            f"{resolved} has root <{root.tag}>, expected <organism>."
        )

    lamina_ids: list = []
    for el in root.findall(".//laminae/lamina"):
        lamina_id = (el.get("id") or "").strip()
        if not lamina_id:
            raise OrganismError("Encountered a <lamina> with no id attribute.")
        if lamina_id in lamina_ids:
            raise OrganismError(f"Lamina '{lamina_id}' is listed twice.")
        lamina_ids.append(lamina_id)
    if not lamina_ids:
        raise OrganismError(f"{resolved} lists no laminae.")

    gates: list = []
    seen: set = set()
    feeding: dict = {}                        # destination address -> gate id
    for gate_el in root.findall(".//permeability_gates/gate"):
        gate = _parse_gate(gate_el)
        if gate.id in seen:
            raise OrganismError(f"Duplicate gate id '{gate.id}'.")
        seen.add(gate.id)
        for end, which in ((gate.source, "from"), (gate.dest, "to")):
            if end.lamina not in lamina_ids:
                raise OrganismError(
                    f"Gate '{gate.id}' {which} lamina '{end.lamina}', which "
                    f"this organism does not list. Declared: {lamina_ids}."
                )
        # Rule 6: one seam, one gate.  Measured before it was written —
        # two gates declared onto the same attribute both parse, both
        # report a `transmitted` value as though they carried it, and the
        # one declared LAST silently wins: gate one reported sending 6.64
        # while the attribute held 7.95 from gate two.  Every consumer
        # downstream, the report and the diagram included, then shows a
        # number attributed to a gate that did not put it there.
        #
        # There is no sensible arbitration to write instead.  Two gates
        # feeding one value is two models of where that value comes from,
        # and picking between them is a modelling decision that belongs
        # in the declaration rather than in a tie-break rule nobody reads.
        # A second condition for the same seam is a second CONTROLLER on
        # one gate, or a second attribute to land on — both of which have
        # to be said out loud.
        address = str(gate.dest)
        if address in feeding:
            raise OrganismError(
                f"Gate '{gate.id}' feeds '{address}', which gate "
                f"'{feeding[address]}' already feeds. Two gates onto one "
                f"attribute do not arbitrate: both report carrying a value "
                f"and the one declared last silently overwrites the other, "
                f"so the report names a gate that did not put the number "
                f"there. Give this seam one gate, or give the receiving "
                f"lamina a second attribute to land on."
            )
        feeding[address] = gate.id
        gates.append(gate)

    return OrganismSpec(
        id=root.get("id", resolved.stem),
        version=root.get("version", "1.0"),
        lamina_ids=lamina_ids,
        gates=gates,
        name=(root.findtext("name", "") or "").strip(),
        description=(root.findtext("description", "") or "").strip(),
    )


def validate_against_laminae(spec: OrganismSpec,
                             twins: dict) -> None:
    """
    Rules 2 and 3 — the ones only the laminae can answer.

    2. The source of a crossing is a COMPOSITE (G5).  A composite is the
       unit a lamina already reasons about: it is what a tag addresses
       and what carries the distribution weights, so a gate reading one
       is reading something the model itself says belongs together.  A
       bare attribute would let a gate reach past the model's own idea
       of structure.

    3. The destination is an attribute declared INTER_LAMINA.  Writing
       into another lamina's SENSOR forges a measurement; writing into
       its PRELIMINARY overwrites something it computes for itself.  The
       receiving lamina has to have said "this is where somebody else's
       number attaches" first — which is exactly what the source
       declaration is for.
    """
    for lamina_id in spec.lamina_ids:
        if lamina_id not in twins:
            raise OrganismError(
                f"Organism '{spec.id}' lists lamina '{lamina_id}' but no twin "
                f"was supplied for it."
            )

    for gate in spec.gates:
        src_twin: UniversalTwin = twins[gate.source.lamina]
        dst_twin: UniversalTwin = twins[gate.dest.lamina]

        # ── Rule 2 ───────────────────────────────────────────────────
        if gate.source.member not in src_twin.composites:
            hint = ""
            if gate.source.member in src_twin.attributes:
                hint = (
                    f" '{gate.source.member}' is an attribute there; name the "
                    f"composite that holds it and use <extract> to pick it out."
                )
            raise OrganismError(
                f"Gate '{gate.id}' reads '{gate.source}', which is not a "
                f"composite on lamina '{gate.source.lamina}'.{hint} Known "
                f"composites: {sorted(src_twin.composites)}."
            )
        composite = src_twin.composites[gate.source.member]
        if gate.extract not in composite.attribute_ids:
            raise OrganismError(
                f"Gate '{gate.id}' extracts '{gate.extract}', which is not in "
                f"composite '{gate.source.member}'. It holds: "
                f"{composite.attribute_ids}."
            )
        watch = gate.controller_params.get("watch")
        if watch and watch not in composite.attribute_ids:
            raise OrganismError(
                f"Gate '{gate.id}' watches '{watch}', which is not in "
                f"composite '{gate.source.member}'. It holds: "
                f"{composite.attribute_ids}."
            )
        for attr in gate.key_weights:
            if attr not in composite.attribute_ids:
                raise OrganismError(
                    f"Gate '{gate.id}' keys on '{attr}', which is not in "
                    f"composite '{gate.source.member}'. It holds: "
                    f"{composite.attribute_ids}."
                )

        # ── Rule 3 ───────────────────────────────────────────────────
        dest_attr = dst_twin.attributes.get(gate.dest.member)
        if dest_attr is None:
            raise OrganismError(
                f"Gate '{gate.id}' writes to '{gate.dest}', which lamina "
                f"'{gate.dest.lamina}' does not declare."
            )
        if dest_attr.source != INTER_LAMINA:
            raise OrganismError(
                f"Gate '{gate.id}' writes to '{gate.dest}', declared "
                f"{dest_attr.source}. A gate may only write an attribute the "
                f"receiving lamina declared as {INTER_LAMINA}: writing a "
                f"SENSOR forges a measurement, and writing a PRELIMINARY "
                f"overwrites something that lamina computes for itself."
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
        self.gates: list = self.spec.gates
        self.controllers: dict = {
            lamina_id: FeedbackController(twin, epsilon_ratio, max_norm)
            for lamina_id, twin in self.twins.items()
        }
        self.max_total_norm = float(max_total_norm)

        # Gate-controller state lives HERE, keyed by gate id — not on the
        # PermeabilityGate dataclass.  Same placement as
        # FeedbackController._kernel_state, and for the same reason: a
        # declaration that is also a mutable state bag cannot be
        # reloaded, compared or serialised without dragging the run
        # along with it.
        self._gate_state: dict = {gate.id: {} for gate in self.gates}

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
        gate_report = self._gate_pass(warnings)

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
            "gates":               gate_report,
            "cycle_reports":       cycle_reports,
            "warnings":            warnings,
        }
        for w in warnings:
            print(f"[organism] {w}")
        return report

    # ── Step 3, in detail ────────────────────────────────────────────

    def _gate_pass(self, warnings: list) -> dict:
        """
        Run every gate once, in declaration order.

        A gate's state is split in two, and the split is not tidiness.
        The controller's contract is that its RETURN VALUE is its whole
        new state, so the container replaces the dict wholesale each
        cycle — which quietly wiped the transfer engine's delay buffer
        when both lived in one dict.  Measured: a gate declaring
        `time_delay=1` delivered nothing, ever, because the line was
        emptied between being filled and being read.  Two sub-dicts, one
        per owner, and neither can reach the other's keys.
        """
        report: dict = {}
        for gate in self.gates:
            gate_state = self._gate_state.setdefault(gate.id, {})
            controller_state = gate_state.setdefault("controller", {})
            transfer_state = gate_state.setdefault("transfer", {})
            src_twin = self.twins[gate.source.lamina]

            # The sender's value as of THIS cycle's compute — step 2 has
            # already run, which is the whole reason the gate pass sits
            # where it does.
            src_attr = src_twin.attributes.get(gate.extract)
            reading = src_attr.value if src_attr else None
            source_vec = src_twin.get_composite_vector(gate.source.member)

            open_fraction = self._open_fraction(gate, controller_state,
                                                source_vec, warnings)
            transmitted = self._transfer(gate, reading, open_fraction,
                                         transfer_state)

            report[gate.id] = {
                "open_fraction": round(open_fraction, 6),
                "reading":       reading,
                "transmitted":   transmitted,
                "controller":    gate.controller,
                "state":         _scalars(controller_state),
                "transfer":      _scalars(transfer_state),
            }
        return report

    def _open_fraction(self, gate, state: dict, source_vec: dict,
                       warnings: list) -> float:
        """
        How open this gate is this cycle, in [0, 1].

        Shut whenever the body breaker has fired, and shut whenever no
        controller is registered for the gate's declared type.  The
        second case is not an error: a gate whose controller has not been
        written yet is a declared valve nobody has connected, and a
        declared valve is shut.  Reporting it rather than raising is what
        lets an organism be assembled before every controller exists.
        """
        if self.gates_locked:
            state["reason"] = "organism breaker"
            return 0.0
        controller_fn = self._gate_controller_registry.get(gate.controller)
        if controller_fn is None:
            state["reason"] = f"no '{gate.controller}' controller registered"
            return 0.0
        new_state = dict(controller_fn(state, source_vec,
                                       gate.controller_args()))
        state.clear()
        state.update(new_state)
        fraction = float(new_state.get("open_fraction", 0.0))
        if not 0.0 <= fraction <= 1.0:
            warnings.append(
                f"Gate '{gate.id}' controller returned open_fraction="
                f"{fraction}, outside [0,1] — clamped."
            )
            fraction = max(0.0, min(1.0, fraction))
        return fraction

    def _transfer(self, gate, reading, open_fraction: float, state: dict):
        """
        What actually crosses, and the write into the receiving lamina.

        Three stages, in this order, and each one is a defence against a
        different failure:

          1. DELAY.  The reading goes into a ring buffer `time_delay`
             cycles long and what comes out the far end is what crossed
             that many cycles ago.  Phase 2 measured that there is no
             implicit lag to lean on — the receiver re-derives within the
             same tick — so a delay only exists if it is declared.

          2. EWMA.  transmitted ← transmitted + rate·open_fraction·
             (delayed − transmitted).  A low-pass filter, and G4's main
             line against two feedback loops pulling on each other
             through an open gate.

          3. WRITE, through set_inter_lamina, with provenance saying
             which gate, from which lamina, how open it was, and how old
             the number is.

        On the open_fraction: the plan's formula multiplied it into the
        VALUE — `delayed · f(open_fraction)`.  That is wrong for a
        physiological quantity: a half-open gate would report a cardiac
        output of 2.4 L/min, which is not a partial reading of 4.8, it is
        a different and false one.  It goes into the RATE instead, so a
        half-open gate moves the receiver toward the true value at half
        speed — which is what a half-open valve does.  For the shipped
        gate the two are identical anyway, because binary mode only ever
        produces 0 or 1; the difference is real only for a proportional
        gate, which is exactly where a scaled value would do damage.

        The receiver eases out of wherever it already sits rather than
        jumping: on the first crossing the filter is seeded from the
        destination's current value, so a seam that has been resting on
        its declared baseline of 5.0 walks up to the sender's number
        instead of snapping to it.
        """
        transfer = gate.transfer
        dst_twin = self.twins[gate.dest.lamina]
        dst_attr = dst_twin.attributes.get(gate.dest.member)
        if dst_attr is None:
            return None

        delayed = self._through_delay(state, reading, transfer.time_delay)

        # A band gate carries the value only while it lies inside the
        # declared band, and refuses outside it rather than clamping.
        # Clamping is what the soft_range gate used to do, and it
        # silently pulled out-of-range physiology back toward normal —
        # a MAP of 120 displayed as 110, masking the pathology the twin
        # exists to show.  Refusing says "this seam does not model that",
        # which is true; clamping says "it is 110", which is not.
        out_of_band = (
            transfer.mode == "band" and delayed is not None and not (
                (transfer.band_min is None or delayed >= transfer.band_min)
                and (transfer.band_max is None or delayed <= transfer.band_max)
            )
        )

        if open_fraction <= 0.0 or delayed is None or out_of_band:
            reason = (
                "out of band" if out_of_band
                else "waiting for the delay line" if delayed is None
                else "shut"
            )
            return self._on_close(gate, state, dst_attr, reason)

        previous = state.get("transmitted")
        if previous is None:
            previous = dst_attr.value if dst_attr.value is not None else delayed
        effective_rate = max(0.0, min(1.0, transfer.rate * open_fraction))
        transmitted = previous + effective_rate * (delayed - previous)

        dst_twin.set_inter_lamina(
            gate.dest.member,
            transmitted,
            confidence=transfer.confidence,
            provenance={
                # Self-describing: the snapshot supplies "coupled" as a
                # default for provenance that says nothing, so anything
                # that CAN say should, and `held` needs somewhere to be
                # said from.
                "state":         "coupled",
                "gate":          gate.id,
                "from":          gate.source.lamina,
                "open_fraction": round(open_fraction, 4),
                "age":           0,
                # What the filter is walking toward, so a reader can see
                # the gap rather than inferring it from two ticks.
                "target":        round(delayed, 6),
                "rate":          round(effective_rate, 6),
                "delay":         transfer.time_delay,
            },
        )
        state["transmitted"] = transmitted
        state["last_transmitted"] = transmitted
        # Why it last DIDN'T carry stops being true the moment it does.
        # A report showing an open gate beside close_reason="shut" is a
        # small lie of the same family as everything else this phase
        # spent its time on.
        state.pop("close_reason", None)
        return transmitted

    def _through_delay(self, state: dict, reading, time_delay: int):
        """
        Push this cycle's reading into the gate's delay line, pop what is
        due.

        A plain list rather than a deque because the state travels on the
        snapshot and has to survive JSON.  `time_delay` is counted in
        cycles of the RECEIVING lamina, which on an organism tick is the
        same cycle for both — one tick, one entry.

        Returns None while the line is still filling.  That is a real
        state, not an error: a gate with a five-cycle delay genuinely has
        nothing to deliver for its first five cycles, and inventing
        something for it to say would be the point at which the delay
        stopped meaning anything.
        """
        if reading is None:
            return None
        buffer = state.setdefault("buffer", [])
        buffer.append(reading)
        if len(buffer) > max(0, int(time_delay)):
            return buffer.pop(0)
        return None

    def _on_close(self, gate, state: dict, dst_attr, reason: str):
        """
        What the receiver is left holding when nothing crosses.

        `hold` keeps the last value that arrived and lets it age, so the
        far side sees an old number labelled old rather than a value
        snapping back to a baseline nobody chose.

        `decay_to_baseline` walks it back to the attribute's declared
        `<baseline>` at the transfer rate — the right choice where a
        stale coupled value is worse than an honest uninformed one, and
        the reason `<baseline>` is required on an INTER_LAMINA attribute
        in the first place (G9).
        """
        state["close_reason"] = reason

        # Nothing this gate ever carried is nothing this gate may claim.
        # A seam still resting on its declared baseline must keep
        # reporting itself uncoupled: decaying an untouched value toward
        # the baseline it is already sitting on changes no number, but
        # stamps provenance on it, and an untouched baseline that looks
        # like a decayed coupled value is worse than either.
        if state.get("transmitted") is None:
            return None

        if gate.transfer.on_close == "decay_to_baseline" \
                and dst_attr.baseline is not None:
            current = state["transmitted"]
            decayed = current + gate.transfer.rate * (dst_attr.baseline - current)
            state["transmitted"] = decayed
            age = int((dst_attr.provenance or {}).get("age", 0)) + 1
            self.twins[gate.dest.lamina].set_inter_lamina(
                gate.dest.member,
                decayed,
                confidence=gate.transfer.confidence,
                provenance={
                    "state":         "decaying",
                    "gate":          gate.id,
                    "from":          gate.source.lamina,
                    "open_fraction": 0.0,
                    "age":           age,
                    "target":        dst_attr.baseline,
                    "reason":        reason,
                },
            )
            return None

        self._age_held_value(gate, reason)
        return None

    def _age_held_value(self, gate, reason: str = "shut") -> None:
        """
        Mark the receiver's held value as one cycle older.

        Only touches a value THIS gate put there: an attribute still on
        its declared baseline has nothing to age, and one fed by another
        gate is that gate's to account for.
        """
        attr = self.twins[gate.dest.lamina].attributes.get(gate.dest.member)
        if attr is None or not attr.provenance:
            return
        if attr.provenance.get("gate") != gate.id:
            return
        attr.provenance = {
            **attr.provenance,
            "state":         "held",
            "open_fraction": 0.0,
            "age":           int(attr.provenance.get("age", 0)) + 1,
            "reason":        reason,
        }

    # ── Reporting ────────────────────────────────────────────────────

    def snapshot(self) -> dict:
        """
        One payload describing the whole body.

        Per-lamina snapshots keep the exact shape a single-lamina session
        already sends, nested under their lamina id, so anything that can
        read one lamina can read one of these without learning a second
        format.

        `gates` is the reader-facing view of each seam: what it was
        declared to be and what it is doing right now, in one entry.  It
        used to be `gate_declarations` and carry only the first half,
        which is exactly the split that makes a consumer go looking for
        the state somewhere else and then draw a valve without one.

        Related but not the same thing as `tick()`'s report: the report
        is what happened on ONE cycle, including the controller's reason
        for it, and it is the thing a test reads.  This is the standing
        state of the body, and it is the thing a screen reads.
        """
        return {
            "organism_id": self.spec.id,
            "name":        self.spec.name,
            "laminae":     {
                lamina_id: _simulation_snapshot(twin)
                for lamina_id, twin in self.twins.items()
            },
            "gates":       [self._gate_entry(gate) for gate in self.gates],
        }

    def _gate_entry(self, gate) -> dict:
        """
        One gate, declaration and live state together.

        The provenance comes off the RECEIVING attribute rather than off
        the gate's own state, and that is deliberate: it is the same
        object the receiving lamina's own snapshot shows under `inbound`,
        so the seam drawn on a body diagram and the value shown beside
        the far side's inputs can never disagree about how old the number
        is.  Two places computing the same claim is how they drift.
        """
        state = self._gate_state.get(gate.id, {})
        controller_state = state.get("controller", {})
        transfer_state = state.get("transfer", {})
        dst_attr = self.twins[gate.dest.lamina].attributes.get(gate.dest.member)
        provenance = dict(dst_attr.provenance) if (
            dst_attr is not None and dst_attr.provenance) else {}
        # A seam this gate has never fed is not this gate's to describe.
        if provenance.get("gate") != gate.id:
            provenance = {}

        open_fraction = float(controller_state.get("open_fraction", 0.0))
        return {
            # Declaration — what the XML says this seam is.
            "id":            gate.id,
            "from":          str(gate.source),
            "to":            str(gate.dest),
            "from_lamina":   gate.source.lamina,
            "to_lamina":     gate.dest.lamina,
            "controller":    gate.controller,
            "extract":       gate.extract,
            "mode":          gate.transfer.mode,
            "description":   gate.description,
            # Live — what it is doing.
            "open_fraction": round(open_fraction, 6),
            "open":          open_fraction > 0.0,
            "reason":        controller_state.get("reason", ""),
            "watch_value":   controller_state.get("watch_value"),
            "last_value":    transfer_state.get("last_transmitted"),
            "provenance":    provenance,
        }


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
    side: str = ""                                  # "transmit" | "receive"
    learnables: list = field(default_factory=list)  # list[Learnable]


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
        elif child.tag == "learnable":
            continue
        else:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <{child.tag}>. An auto gate "
                f"answers to one <threshold> or <pattern> trigger and may "
                f"carry <learnable>s — nothing else."
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
        elif child.tag == "learnable":
            continue
        else:
            raise OrganismError(
                f"Gate '{gate_id}' declares a <{child.tag}>. A key gate "
                f"carries one <key> and may carry <learnable>s — nothing "
                f"else."
            )
    if key_el is None:
        raise OrganismError(
            f"Gate '{gate_id}' is a key gate and declares no <key> block."
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
    side_counts: dict = {}                # (lamina, side, direction) -> int
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

        # ── Rule 8: at most 4 gates per (lamina, side, direction) ──────
        for side in ("transmit", "receive"):
            lamina = (ch.source.lamina if side == "transmit"
                      else ch.dest.lamina)
            key = (lamina, side, direction)
            side_counts[key] = (
                side_counts.get(key, 0) + len(getattr(ch, side))
            )
            if side_counts[key] > MAX_GATES_PER_SIDE_DIRECTION:
                raise OrganismError(
                    f"Channel '{ch.id}' brings {side_counts[key]} gates to "
                    f"lamina '{lamina}', side '{side}', direction "
                    f"'{direction}'. Rule 8: at most "
                    f"{MAX_GATES_PER_SIDE_DIRECTION} gates per (lamina, "
                    f"side, direction). A lamina that needs more "
                    f"conditions than that on one face is more than one "
                    f"lamina."
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
        gates=[],
        name=(root.findtext("name", "") or "").strip(),
        description=(root.findtext("description", "") or "").strip(),
        levels=levels,
        channels=channels,
    )
