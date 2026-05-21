"""
Universal Digital Twin - Base Class
====================================
This is the parent class for all Digital Twin laminas.
It provides:
  - XML parsing: reads attribute definitions, function mappings, gates, composites
  - Attribute resolution: when you request an attribute, it auto-resolves dependencies
  - Normalisation: converts raw values to [0,1] vector space
  - Gate validation: checks physiological ranges before propagation
  - Composite vectors: groups attributes into logical vectors

Domain experts modify the XML file, not this code.
Developers add new function models in child classes.
"""

import math
import numpy as np
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────
# Attribute Object (Wrapper)
# ──────────────────────────────────────────────────────────────────────
#
# Phase A of the feedback loop rollout splits the attribute's value into
# two independent vectors per FEEDBACK_LOOP_PLAN.md §2.1:
#
#     X = X' + X''
#
#     value_external (X')  — external ingestion: sensor reads and
#                            computed-from-external results.  Written by
#                            set_value() / set_sensor() / the function
#                            chain.  NEVER touched by the feedback loop
#                            (sensor is sacred, D12).
#
#     value_feedback (X'') — internal feedback: corrective delta produced
#                            by FeedbackController in Phase C.  Written
#                            only by apply_feedback().  Rolled back by
#                            rollback_feedback() when the feedback gate
#                            rejects.
#
# .value is now a read-only @property that combines the two via the
# coupling kernel (default = additive).  In Phase A no feedback ever
# fires, so value_feedback stays 0.0 everywhere and the additive coupling
# yields .value == value_external — exact byte-for-byte compatibility
# with the pre-Phase-A behaviour (this is the Phase A test gate).
#
# The legacy `rollback()` method is preserved as-is so that the existing
# validate_gates() flow keeps working unchanged.  Feedback-side rollback
# uses the new `rollback_feedback()` method.
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Attribute:
    """
    Every attribute in the system is wrapped in this object.
    It carries not just a value, but full metadata.

    Domain experts see this as: "an attribute is not just a number,
    it's a package containing everything we know about that number."
    """
    id: str                          # e.g. "HR", "MAP", "Q"
    name: str                        # e.g. "Heart Rate"
    unit: str                        # e.g. "bpm"
    source: str                      # "SENSOR" or "PRELIMINARY"
    physio_min: float                # lower physiological bound
    physio_max: float                # upper physiological bound
    description: str = ""            # human-readable description
    value_external: Optional[float] = None  # X' — external/computed input
    value_feedback: float = 0.0             # X'' — feedback-loop delta
    normalised: Optional[float] = None  # value in [0, 1] vector space
    timestamp: Optional[datetime] = None
    confidence: float = 1.0          # 1.0 for sensor, lower for estimated
    computed_by: Optional[str] = None   # function id (for PRELIMINARY)
    depends_on: list = field(default_factory=list)  # dependency attribute ids
    _previous_value: Optional[float] = None  # for legacy validate_gates rollback

    @property
    def value(self) -> Optional[float]:
        """
        Combined value:  value_external (X') + value_feedback (X'').

        Uses the default additive coupling kernel inline.  When the
        coupling registry on UniversalTwin holds a non-default kernel
        the controller is responsible for invoking it explicitly; the
        Attribute property always returns the additive view, which is
        sufficient for normalisation and downstream reads.

        Returns None if value_external has never been set — preserves
        the pre-Phase-A semantics where an uninitialised sensor reads
        as None.
        """
        if self.value_external is None:
            # Sensor never set / PRELIMINARY never computed.  Feedback
            # alone is meaningless without an external anchor in v1
            # (X' = 0 invariant applies after initial set).
            return None
        return self.value_external + self.value_feedback

    @value.setter
    def value(self, new_value: Optional[float]):
        """
        Back-compat shim: writing to .value updates the external channel
        only.  Pre-Phase-A code that did `attr.value = x` keeps working.

        Direct callers should prefer set_value() (which also stamps
        timestamp + confidence + normalised) or apply_feedback() for the
        X'' channel.
        """
        self._previous_value = self.value_external
        self.value_external = new_value
        self.normalise()

    def normalise(self) -> Optional[float]:
        """Convert raw value to [0, 1] using physiological range."""
        if self.value is None:
            return None
        range_size = self.physio_max - self.physio_min
        if range_size == 0:
            return 0.5
        self.normalised = max(0.0, min(1.0,
            (self.value - self.physio_min) / range_size
        ))
        return self.normalised

    def set_value(self, value: float, confidence: float = 1.0):
        """
        Update X' (external channel).  Stores previous external value
        for the legacy validate_gates rollback path.

        Phase A note: this writes to value_external only, never to
        value_feedback.  X' is sacred — feedback machinery uses
        apply_feedback() for the X'' channel.
        """
        self._previous_value = self.value_external
        self.value_external = value
        self.confidence = confidence
        self.timestamp = datetime.now()
        self.normalise()

    def apply_feedback(self, delta: float):
        """
        Phase A primitive for the feedback loop (D2 / D12).

        Writes the X'' channel ONLY.  value_external is never touched
        here.  Phase C's FeedbackController.step() calls this once per
        (tag, attribute) target after summing all kernel deltas.

        In Phase A nothing calls this method during normal compute_all()
        runs — it is provided so Phase B/C code can land without
        reshaping the Attribute again.
        """
        self.value_feedback = float(delta)
        self.normalise()

    def rollback(self):
        """
        Legacy rollback used by validate_gates() when a computed value
        leaves its physiological range.  Restores value_external from
        the previously-recorded snapshot.

        Phase A keeps this exact behaviour for backward compatibility.
        Feedback-side rollback (D12 — X'' only, X' sacred) uses
        rollback_feedback() instead.
        """
        if self._previous_value is not None:
            self.value_external = self._previous_value
            self.normalise()

    def rollback_feedback(self):
        """
        Reset the X'' channel to 0.0 (D12).

        Called by FeedbackController.step() in two situations:
          1. Dead-zone snap (step 6 of the 7-step cycle, §5.0 + §9.2)
          2. Feedback gate rejection inside the loop machinery

        NEVER touches value_external — sensor / ground truth is sacred.
        """
        self.value_feedback = 0.0
        self.normalise()


# ──────────────────────────────────────────────────────────────────────
# Gate Definition
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Gate:
    """Permeability gate - validates values before propagation."""
    attribute: str
    gate_type: str         # "range", "positive", "consistency"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    tolerance: Optional[float] = None
    compare: Optional[list] = None
    action_on_fail: str = "hold_previous"
    flag: str = ""


# ──────────────────────────────────────────────────────────────────────
# Function Definition (from XML)
# ──────────────────────────────────────────────────────────────────────
@dataclass
class FunctionDef:
    """Metadata about a function model, parsed from XML."""
    id: str                  # e.g. "pressure_regulation"
    name: str                # e.g. "Pressure Regulation"
    step: str                # e.g. "1", "3a"
    formula: str             # human-readable formula string
    inputs: list             # list of input attribute ids
    output: str              # output attribute id
    description: str = ""


# ──────────────────────────────────────────────────────────────────────
# Composite Definition
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Composite:
    """
    Logical grouping of attributes for vector space.

    Two parallel 1D numpy vectors (shape: N,) live on every composite,
    one per concern.  Decision D2 of the feedback loop audit deliberately
    keeps them separate so the learning loop and the feedback loop never
    fight over the same numbers:

      absorption_vector
        Seeds the Auto Controller's learning step
          W_new = W_old + ΔW
        FROZEN during Phases A–E of the feedback loop rollout (D17).
        Re-activated only in Phase G.

      distribution_vector
        Provides w_i in the gate-kernel formula (§2.3):
          raw = polarity · gain · w_i · G(d) · d · tolerance
        The feedback loop reads this vector but NEVER mutates it —
        updates happen only via XML edits by the domain expert.

    Both default to equal 1/N weights when their XML block is missing.
    Both are full multipliers, not probabilities — sums are NOT
    normalised (D2).
    """
    id: str
    name: str
    attribute_ids: list
    description: str = ""
    absorption_vector: Optional[np.ndarray] = field(default=None, repr=False)
    distribution_vector: Optional[np.ndarray] = field(default=None, repr=False)

    def update_weights(self, new_values):
        """Set/replace the absorption vector. Called by the Auto Controller after each feedback cycle."""
        self.absorption_vector = np.array(new_values, dtype=float)

    def update_distribution(self, new_values):
        """
        Set/replace the distribution vector.

        Phase A leaves this as a domain-expert API (called by the XML
        parser).  The feedback loop in Phase C reads but never writes
        this vector.
        """
        self.distribution_vector = np.array(new_values, dtype=float)

    def apply_absorption(self, attribute_values: list) -> np.ndarray:
        """
        Value_new = Attribute_existing × Weight_absorb  (element-wise).
        Returns absorbed vector, same length as attribute_ids.
        Falls back to unweighted values if no vector is initialised.
        """
        vals = np.array(attribute_values, dtype=float)
        if self.absorption_vector is None or len(self.absorption_vector) != len(vals):
            return vals
        return vals * self.absorption_vector

    def get_distribution_weight(self, attr_id: str) -> float:
        """
        Look up the gate-fanout weight w_i for a specific attribute in
        this composite.  Returns 1.0 if the attribute is not in this
        composite or the distribution vector is uninitialised — a safe
        identity multiplier so callers never have to special-case the
        missing-vector path.
        """
        if self.distribution_vector is None:
            return 1.0
        try:
            idx = self.attribute_ids.index(attr_id)
        except ValueError:
            return 1.0
        if idx >= len(self.distribution_vector):
            return 1.0
        return float(self.distribution_vector[idx])


# ──────────────────────────────────────────────────────────────────────
# Behavioural Outcome Definition
# ──────────────────────────────────────────────────────────────────────
@dataclass
class BehaviouralOutcome:
    """
    Domain-expert defined numerical target for a specific attribute.
    Acts as the 'truth' metric that the Auto Controller compares against
    real-world sensor data (e.g. Apple Watch readings) to compute the
    error signal ΔW for weight adjustment.
    """
    id: str
    name: str
    attribute_id: str    # attribute being tracked, e.g. "Q", "CO"
    target_value: float  # expected healthy value defined by domain expert
    tolerance: float     # acceptable absolute deviation from target
    unit: str = ""
    description: str = ""

    def evaluate(self, actual_value: float) -> dict:
        """
        Compare actual vs target and return a Feedback Object.
        The deviation field is the ΔW input for auto_adjust_weights().
        """
        deviation = actual_value - self.target_value
        deviation_pct = deviation / self.target_value if self.target_value != 0 else 0.0
        within_tolerance = abs(deviation) <= self.tolerance
        return {
            "outcome_id":        self.id,
            "name":              self.name,
            "attribute_id":      self.attribute_id,
            "unit":              self.unit,
            "target":            self.target_value,
            "actual":            round(actual_value, 4),
            "deviation":         round(deviation, 4),
            "deviation_pct":     round(deviation_pct, 4),
            "within_tolerance":  within_tolerance,
            "status":            "normal" if within_tolerance else ("above" if deviation > 0 else "below"),
        }


# ──────────────────────────────────────────────────────────────────────
# Segment Definition
# ──────────────────────────────────────────────────────────────────────
@dataclass
class Segment:
    """Named sub-section of a lamina, grouping related attributes/functions."""
    id: str
    name: str
    attribute_ids: list
    composite_ids: list
    function_ids: list
    description: str = ""
    behavioural_outcomes: list = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# Tag pipeline (Phase B — Feedback Loop)
# ──────────────────────────────────────────────────────────────────────
#
# A Tag binds a BehaviouralOutcome to a gate kernel and a list of
# composite targets that should receive corrective signal when the
# outcome leaves its tolerance band.  See FEEDBACK_LOOP_PLAN.md §3.3.
#
# Lifecycle:
#   1. Domain expert declares <tag> in XML (or a future helper API).
#   2. UniversalTwin parses tags at load time.
#   3. Identifier.emit_tags() polls every outcome each cycle (D9).
#      For each outcome whose deviation breaks tolerance the configured
#      emitter (default: binary) decides whether to emit, and the
#      matching Tag from the registry is appended to the emission list.
#   4. Phase C's FeedbackController consumes that list, runs the gate
#      kernel for each (tag, target) pair, sums deltas (D10), and
#      applies them once at the cycle end (D11).
# ──────────────────────────────────────────────────────────────────────


# Friendly aliases the XML accepts.  Anything else passes through
# float() — see resolve_polarity() below.  Per D7 the dataclass field
# is always a float so the kernel never has to branch on a string.
POLARITY_MAP = {
    "negative": -1.0,
    "positive": +1.0,
}


def resolve_polarity(raw) -> float:
    """
    Convert an XML polarity declaration to a float (D7).

    Accepted inputs:
      - "negative"    → -1.0   (corrective feedback, default)
      - "positive"    → +1.0   (amplifying feedback)
      - "0" / 0       →  0.0   (monitor-only — tag still emits and logs
                                 but produces no X'')
      - "0.5"         → +0.5   (fractional positive)
      - "-1.0" / -1.0 → -1.0   (numeric direct)
      - None / ""     → -1.0   (default — corrective)

    Raises ValueError if the string is neither a known alias nor a
    parseable number — fail loudly at parse time per the "fail fast"
    rule that runs through the audit decisions.
    """
    if raw is None or raw == "":
        return -1.0
    if isinstance(raw, (int, float)):
        return float(raw)
    raw_str = str(raw).strip()
    if raw_str in POLARITY_MAP:
        return POLARITY_MAP[raw_str]
    try:
        return float(raw_str)
    except ValueError as e:
        raise ValueError(
            f"Tag polarity '{raw}' is not a known alias "
            f"({list(POLARITY_MAP.keys())}) and is not a parseable number."
        ) from e


@dataclass
class TagTarget:
    """
    A single composite address a Tag fans corrective signal into.

    `address` syntax: "[<lamina_id>:]<composite_id>".  Bare composite
    ids resolve to the host lamina (local-first).  Cross-lamina prefix
    becomes meaningful in Phase G when more than one lamina exists.

    `weight` (D8): the FULL deviation is multiplied by this weight for
    each target — deviation is NOT split proportionally across targets.
    Default 1.0 means "send the entire signal here".
    """
    address: str
    weight: float = 1.0


@dataclass
class Tag:
    """
    Declarative binding between a BehaviouralOutcome and a gate kernel.

    Field defaults match the v1 registry defaults so a domain expert
    can write a minimal <tag> (just id, outcome, targets) and get
    sensible behaviour out of the box.
    """
    id: str
    outcome: str                       # BehaviouralOutcome.id this tag listens to
    deviation_type: str = "absolute"   # key into _deviation_registry
    emitter: str = "binary"            # key into _emitter_registry
    gate_kernel: str = "sigmoid_leaky_tanh"  # key into _gate_kernel_registry
    polarity: float = -1.0             # D7 — float, default corrective
    targets: list = field(default_factory=list)  # list[TagTarget]
    params: dict = field(default_factory=dict)   # loose kernel params (D15)


# ──────────────────────────────────────────────────────────────────────
# Universal Digital Twin (Parent Class)
# ──────────────────────────────────────────────────────────────────────
class UniversalTwin:
    """
    Base class for all Digital Twin laminas.

    Reads an XML definition file and provides:
    - get(attr_id): resolve and return an attribute (auto-computes if PRELIMINARY)
    - set_sensor(attr_id, value): set a sensor reading
    - get_composite_vector(composite_id): get normalised vector for a composite
    - validate_gates(): run all permeability gates
    - compute_all(): run the full computation chain

    Child classes override _register_functions() to provide actual formulas.
    """

    def __init__(self, xml_path: str):
        self.xml_path = xml_path
        self.lamina_name = ""
        self.lamina_id = ""
        self.lamina_level = 0
        self.upper_lamina_id = "none"
        self.lower_lamina_id = "none"
        self.attributes: dict[str, Attribute] = {}
        self.functions: dict[str, FunctionDef] = {}
        self.composites: dict[str, Composite] = {}
        self.segments: dict[str, Segment] = {}
        self.tags: dict[str, Tag] = {}  # Phase B — feedback tag registry
        self.channel_mappings: dict[str, str] = {}  # attribute_id -> channel_id
        self.gates: list[Gate] = []
        self._function_registry: dict[str, callable] = {}
        self._computation_log: list[str] = []

        # ── Feedback loop registries (Phase A scaffolding) ───────────
        #
        # Five pluggable extension points per FEEDBACK_LOOP_PLAN.md §3.1.
        # Phase A only wires the coupling registry with the default
        # `additive` kernel — the rest land in Phase C alongside the
        # FeedbackController.  The registries are declared here so the
        # interface stays stable across phases.
        self._deviation_registry:  dict[str, callable] = {}
        self._emitter_registry:    dict[str, callable] = {}
        self._gate_kernel_registry: dict[str, callable] = {}
        self._coupling_registry:   dict[str, callable] = {}
        self._solver_registry:     dict[str, callable] = {}

        # XML-declared selections (parsed below, defaults applied if
        # the optional blocks are absent).
        self.coupling_type: str = "additive"
        self.behaviour_solver_type: str = "algebraic_chain"
        self.behaviour_solver_dt: float = 1.0
        self.behaviour_solver_unit: str = "second"

        # Register the v1 default kernels.  Phase A registered coupling
        # only; Phase B adds the deviation + emitter defaults; Phase C
        # adds the gate kernel + solver defaults so the full pipeline
        # can run end-to-end.
        self._register_default_coupling()
        self._register_default_deviation()
        self._register_default_emitter()
        self._register_default_gate_kernel()
        self._register_default_solver()

        # Parse XML
        self._parse_xml(xml_path)

        # Let child classes register their function implementations
        self._register_functions()

    # ── Default Kernel Registrations ─────────────────────────────────

    def _register_default_coupling(self):
        """
        Register the v1 default `additive` coupling kernel (D6).

        Signature contract (frozen):
            coupling(x_prime: float | None,
                     x_pp: float,
                     params: dict) -> float

        When x_prime is None (sensor never set / PRELIMINARY not yet
        computed), return x_pp directly so the controller does not need
        to special-case the missing-anchor path.
        """
        def additive(x_prime, x_pp, params):
            if x_prime is None:
                return x_pp
            return x_prime + x_pp
        self._coupling_registry["additive"] = additive

    def _register_default_deviation(self):
        """
        Register the v1 default `absolute` deviation function.

        Signature contract:
            deviation_fn(actual: float,
                         target: float,
                         params: dict) -> float

        `absolute` is just `actual - target`, identical to what
        BehaviouralOutcome.evaluate() already computes.  Registering it
        here means Phase C's controller can dispatch by the Tag's
        deviation_type field without special-casing the default.
        """
        def absolute(actual, target, params):
            return actual - target
        self._deviation_registry["absolute"] = absolute

    def _register_default_emitter(self):
        """
        Register the v1 default `binary` emitter (D9 polling model).

        Signature contract:
            emitter_fn(deviation: float,
                       tolerance: float,
                       params: dict) -> bool

        Returns True when the absolute deviation exceeds the outcome's
        tolerance, False otherwise.  In-tolerance outcomes are filtered
        out at the Identifier layer so the gate kernel never runs on
        signals smaller than the sigmoid's threshold knob anyway —
        cheap early-exit that keeps the cycle log readable.
        """
        def binary(deviation, tolerance, params):
            return abs(deviation) > tolerance
        self._emitter_registry["binary"] = binary

    def _register_default_gate_kernel(self):
        """
        Register the v1 default `sigmoid_leaky_tanh` gate kernel
        (FEEDBACK_LOOP_PLAN.md §2.3).

        Signature contract (frozen):
            kernel(prev_state: dict,
                   deviation:  float,   # normalised d_t = ΔOV / tolerance
                   weight:     float,   # w_i from composite.distribution_vector
                   params:     dict)
              -> dict                   # new state, must contain "x_pp"

        Params consumed (with defaults):
            polarity     -1.0    direction; carried by Tag (D7)
            gain          0.6    overall magnitude knob
            decay         0.10   λ in the leaky integrator (D1)
            threshold_k   4.0    sigmoid steepness; kills in-tolerance noise
            a_max         None   tanh saturation in NATIVE units; if None
                                 falls back to `saturation` for demo compat
            saturation    1.0    raw a_max when a_max is missing
            tolerance     1.0    multiplied back in to restore native units

        Formula (per §2.3):
            G    = 1 / (1 + exp(-k · (|d| - 1)))
            raw  = polarity · gain · w · G · d · tolerance
            x_pp = a_max · tanh( ((1 - λ) · x_pp_prev + raw) / a_max )

        Decay lives INSIDE the kernel (D1) — the framework cycle does
        not re-decay outside this function.  Convergence proof in §2.3:
        at x_pp = 0 with no deviation, raw = 0, leaky term pulls back
        to 0 → fixed point.  Tanh keeps the trajectory inside
        [-a_max, +a_max].
        """
        def sigmoid_leaky_tanh(prev_state, deviation, weight, params):
            polarity    = float(params.get("polarity", -1.0))
            gain        = float(params.get("gain", 0.6))
            decay       = float(params.get("decay", 0.10))
            threshold_k = float(params.get("threshold_k", 4.0))
            tolerance   = float(params.get("tolerance", 1.0))

            # a_max takes precedence; saturation is the demo-style raw
            # fallback so feedback_kernel_demo.py keeps working with the
            # registered kernel without code changes.
            a_max_raw = params.get("a_max")
            a_max = float(a_max_raw) if a_max_raw is not None else float(
                params.get("saturation", 1.0)
            )

            d = float(deviation)
            x_pp_prev = float(prev_state.get("x_pp", 0.0)) if prev_state else 0.0

            # G(d) sigmoid threshold — clamps in-tolerance noise.
            # math.exp on huge |d| overflows; clamp the exponent.
            exponent = -threshold_k * (abs(d) - 1.0)
            if exponent > 700:           # exp(700) ≈ 1e304, near float64 cap
                g_open = 0.0
            elif exponent < -700:
                g_open = 1.0
            else:
                g_open = 1.0 / (1.0 + math.exp(exponent))

            raw = polarity * gain * weight * g_open * d * tolerance

            if a_max <= 0:
                # Pathological: no saturation cap.  Skip the tanh and
                # let the leaky integrator run linearly — the snap
                # dead-zone (D3) will still clean up small residuals.
                x_pp = (1.0 - decay) * x_pp_prev + raw
            else:
                inner = ((1.0 - decay) * x_pp_prev + raw) / a_max
                # tanh saturates around ±1 cleanly even for huge inner.
                x_pp = a_max * math.tanh(inner)

            return {"x_pp": x_pp}

        self._gate_kernel_registry["sigmoid_leaky_tanh"] = sigmoid_leaky_tanh

    def _register_default_solver(self):
        """
        Register the v1 default `algebraic_chain` behaviour solver.

        Signature contract:
            solver(twin: UniversalTwin, params: dict) -> None

        The default is a thin wrapper over compute_all() — runs the
        existing function chain in step order, suitable for any
        steady-state lamina.  Phase G can register `ode_rk4` here
        without breaking the FeedbackController interface.
        """
        def algebraic_chain(twin, params):
            twin.compute_all()
        self._solver_registry["algebraic_chain"] = algebraic_chain

    # ── XML Parsing ──────────────────────────────────────────────────

    def _parse_xml(self, path: str):
        """Parse the XML definition file into internal structures."""
        tree = ET.parse(path)
        root = tree.getroot()

        # Lamina-level metadata
        self.lamina_name = root.get("name", "Unknown")
        self.lamina_id = root.get("id", "")
        self.lamina_level = int(root.get("level", "0"))
        upper_el = root.find("upper_lamina")
        self.upper_lamina_id = upper_el.get("id", "none") if upper_el is not None else "none"
        lower_el = root.find("lower_lamina")
        self.lower_lamina_id = lower_el.get("id", "none") if lower_el is not None else "none"

        # Channel mappings: attribute_id -> channel_id
        for mapping_el in root.findall(".//channel_mappings/mapping"):
            attr_id = mapping_el.get("attribute_id")
            channel_id = mapping_el.get("channel_id")
            if attr_id and channel_id:
                self.channel_mappings[attr_id] = channel_id

        # ── Feedback loop XML declarations (Phase A) ─────────────────
        #
        # Both blocks are optional.  Defaults set in __init__ stay in
        # effect when the XML does not declare them — guarantees Phase A
        # backward compatibility with pre-feedback XML files.

        coupling_el = root.find("coupling")
        if coupling_el is not None:
            self.coupling_type = coupling_el.get("type", self.coupling_type)

        solver_el = root.find("behaviour_solver")
        if solver_el is not None:
            self.behaviour_solver_type = solver_el.get(
                "type", self.behaviour_solver_type
            )
            dt_text = solver_el.get("dt")
            if dt_text is not None:
                self.behaviour_solver_dt = float(dt_text)
            self.behaviour_solver_unit = solver_el.get(
                "unit", self.behaviour_solver_unit
            )

        # Parse attributes
        for attr_el in root.findall(".//attributes/attribute"):
            attr_id = attr_el.get("id")
            depends_text = attr_el.findtext("depends_on", "")
            depends = [d.strip() for d in depends_text.split(",") if d.strip()]

            self.attributes[attr_id] = Attribute(
                id=attr_id,
                name=attr_el.findtext("n", attr_el.findtext("name", attr_id)),
                unit=attr_el.findtext("unit", ""),
                source=attr_el.findtext("source", "SENSOR"),
                physio_min=float(attr_el.findtext("physio_min", "0")),
                physio_max=float(attr_el.findtext("physio_max", "1")),
                description=attr_el.findtext("description", ""),
                computed_by=attr_el.findtext("computed_by"),
                depends_on=depends,
            )

        # Parse functions
        for func_el in root.findall(".//functions/function"):
            func_id = func_el.get("id")
            inputs_text = func_el.findtext("inputs", "")
            inputs = [i.strip() for i in inputs_text.split(",") if i.strip()]

            self.functions[func_id] = FunctionDef(
                id=func_id,
                name=func_el.findtext("n", func_el.findtext("name", func_id)),
                step=func_el.get("step", ""),
                formula=func_el.findtext("formula", ""),
                inputs=inputs,
                output=func_el.findtext("o", func_el.findtext("output", "")),
                description=func_el.findtext("description", ""),
            )

        # Parse composites
        for comp_el in root.findall(".//composites/composite"):
            comp_id = comp_el.get("id")
            attrs_text = comp_el.findtext("attributes", "")
            attrs = [a.strip() for a in attrs_text.split(",") if a.strip()]

            comp = Composite(
                id=comp_id,
                name=comp_el.findtext("n", comp_el.findtext("name", comp_id)),
                attribute_ids=attrs,
                description=comp_el.findtext("description", ""),
            )

            # Build absorption vector: 1D numpy array ordered by attribute_ids.
            # <weight attribute="X">value</weight> entries in XML define the seeds.
            # Missing attributes fall back to equal weight 1/N.
            av_el = comp_el.find("absorption_vector")
            if av_el is not None:
                seed = 1.0 / len(attrs) if attrs else 1.0
                weight_map = {
                    w.get("attribute"): float(w.text)
                    for w in av_el.findall("weight")
                    if w.get("attribute") and w.text
                }
                comp.update_weights([weight_map.get(a, seed) for a in attrs])

            # Build distribution vector (D2): the w_i feeding the gate
            # kernel formula in §2.3.  Independent of absorption_vector
            # so the future learning loop (Phase G) cannot accidentally
            # rewrite gate fanouts.
            #
            # XML rules (D2):
            #   - missing block            → default 1/N for every attr
            #   - missing weight for attr  → 1/N (silent default)
            #   - negative weight          → ValueError at parse time
            #   - weight for unknown attr  → ValueError at parse time
            #     (catches typos before they surface as silent no-ops)
            #   - sums NOT normalised      → distribution is a multiplier,
            #                                not a probability
            dv_el = comp_el.find("distribution_vector")
            if dv_el is not None:
                seed = 1.0 / len(attrs) if attrs else 1.0
                dist_map: dict[str, float] = {}
                for w in dv_el.findall("weight"):
                    attr_id_w = w.get("attribute")
                    text_w = (w.text or "").strip()
                    if not attr_id_w or not text_w:
                        continue
                    val = float(text_w)
                    if val < 0:
                        raise ValueError(
                            f"distribution_vector weight for '{attr_id_w}' "
                            f"in composite '{comp_id}' is negative ({val}); "
                            "direction is carried by tag polarity, not weight (D2/D7)."
                        )
                    if attr_id_w not in attrs:
                        raise ValueError(
                            f"distribution_vector references attribute "
                            f"'{attr_id_w}' that is not in composite "
                            f"'{comp_id}' (attrs: {attrs}).  Likely a typo (D2)."
                        )
                    dist_map[attr_id_w] = val
                comp.update_distribution([dist_map.get(a, seed) for a in attrs])
            else:
                # No XML block — every attribute gets the 1/N default so
                # later gate-kernel lookups never see None.
                if attrs:
                    seed = 1.0 / len(attrs)
                    comp.update_distribution([seed] * len(attrs))

            self.composites[comp_id] = comp

        # Parse segments
        for seg_el in root.findall(".//segments/segment"):
            seg_id = seg_el.get("id")
            attrs_text = seg_el.findtext("attributes", "")
            comps_text = seg_el.findtext("composites", "")
            funcs_text = seg_el.findtext("functions", "")

            # Parse behavioural outcomes: domain-expert numerical targets
            outcomes = []
            bo_el = seg_el.find("behavioural_outcomes")
            if bo_el is not None:
                for oc_el in bo_el.findall("outcome"):
                    outcomes.append(BehaviouralOutcome(
                        id=oc_el.get("id", ""),
                        name=oc_el.get("name", ""),
                        attribute_id=oc_el.get("attribute", ""),
                        target_value=float(oc_el.get("target", "0")),
                        tolerance=float(oc_el.get("tolerance", "0")),
                        unit=oc_el.get("unit", ""),
                        description=oc_el.findtext("description", ""),
                    ))

            self.segments[seg_id] = Segment(
                id=seg_id,
                name=seg_el.get("name", seg_id),
                attribute_ids=[a.strip() for a in attrs_text.split(",") if a.strip()],
                composite_ids=[c.strip() for c in comps_text.split(",") if c.strip()],
                function_ids=[f.strip() for f in funcs_text.split(",") if f.strip()],
                description=seg_el.findtext("description", ""),
                behavioural_outcomes=outcomes,
            )

        # Parse gates
        for gate_el in root.findall(".//gates/gate"):
            compare_text = gate_el.findtext("compare", "")
            compare = [c.strip() for c in compare_text.split(",") if c.strip()] or None

            self.gates.append(Gate(
                attribute=gate_el.get("attribute"),
                gate_type=gate_el.get("type", "range"),
                min_val=float(gate_el.findtext("min")) if gate_el.findtext("min") else None,
                max_val=float(gate_el.findtext("max")) if gate_el.findtext("max") else None,
                tolerance=float(gate_el.findtext("tolerance")) if gate_el.findtext("tolerance") else None,
                compare=compare,
                action_on_fail=gate_el.findtext("action_on_fail", "hold_previous"),
                flag=gate_el.findtext("flag", ""),
            ))

        # ── Phase B: parse feedback <tags> block ─────────────────────
        # Optional.  Missing block → empty self.tags, which is fine —
        # Identifier.emit_tags() will return [] every cycle and the
        # feedback loop becomes a no-op.
        self._parse_tags(root)

    def _parse_tags(self, root):
        """
        Parse <tags>/<tag> declarations and populate self.tags.

        XML shape (see FEEDBACK_LOOP_PLAN.md §3.3):

            <tags>
              <tag id="CO_DEVIATION" outcome="target_co"
                   deviation_type="absolute" emitter="binary"
                   gate_kernel="sigmoid_leaky_tanh" polarity="negative">
                <targets>
                  <target address="pump_state" weight="1.0"/>
                </targets>
                <params gain="0.6" decay="0.10" threshold_k="4.0"
                        saturation="0.3" epsilon_ratio="0.001"/>
              </tag>
            </tags>

        Validation performed here (fail fast):
          - duplicate tag id → ValueError
          - outcome reference unknown to any segment → ValueError
          - polarity unparseable → ValueError (via resolve_polarity)
          - target address ambiguous local lookup → ValueError (D5)
          - target weight negative → ValueError
        """
        known_outcomes = {
            outcome.id
            for seg in self.segments.values()
            for outcome in seg.behavioural_outcomes
        }

        for tag_el in root.findall(".//tags/tag"):
            tag_id = tag_el.get("id")
            if not tag_id:
                raise ValueError("Encountered a <tag> element with no id attribute.")
            if tag_id in self.tags:
                raise ValueError(f"Duplicate tag id '{tag_id}' in XML.")

            outcome_id = tag_el.get("outcome", "")
            if not outcome_id:
                raise ValueError(f"Tag '{tag_id}' must declare an outcome= attribute.")
            if known_outcomes and outcome_id not in known_outcomes:
                raise ValueError(
                    f"Tag '{tag_id}' references unknown outcome '{outcome_id}'. "
                    f"Known outcomes: {sorted(known_outcomes)}"
                )

            polarity = resolve_polarity(tag_el.get("polarity"))

            # Parse <targets>/<target> children.
            targets: list[TagTarget] = []
            targets_el = tag_el.find("targets")
            if targets_el is not None:
                for tgt_el in targets_el.findall("target"):
                    addr = tgt_el.get("address", "").strip()
                    if not addr:
                        raise ValueError(
                            f"Tag '{tag_id}' has a <target> with no address."
                        )
                    weight_raw = tgt_el.get("weight", "1.0")
                    try:
                        weight = float(weight_raw)
                    except ValueError as e:
                        raise ValueError(
                            f"Tag '{tag_id}' target '{addr}' has invalid "
                            f"weight '{weight_raw}'."
                        ) from e
                    if weight < 0:
                        raise ValueError(
                            f"Tag '{tag_id}' target '{addr}' weight is "
                            f"negative ({weight}). Direction is carried by "
                            f"polarity, not by target weights (D2/D7)."
                        )
                    # Validate the address now so typos surface at load
                    # time, not on the first feedback cycle (D5).
                    self.resolve_tag_address(addr, tag_id=tag_id)
                    targets.append(TagTarget(address=addr, weight=weight))

            # Parse <params .../> — loose dict, kernel decides defaults (D15).
            params: dict = {}
            params_el = tag_el.find("params")
            if params_el is not None:
                for k, v in params_el.attrib.items():
                    try:
                        params[k] = float(v)
                    except ValueError:
                        # Non-numeric param values pass through as strings
                        # (e.g. a future "mode='asymmetric'" knob).
                        params[k] = v

            self.tags[tag_id] = Tag(
                id=tag_id,
                outcome=outcome_id,
                deviation_type=tag_el.get("deviation_type", "absolute"),
                emitter=tag_el.get("emitter", "binary"),
                gate_kernel=tag_el.get("gate_kernel", "sigmoid_leaky_tanh"),
                polarity=polarity,
                targets=targets,
                params=params,
            )

    def resolve_tag_address(self, address: str, tag_id: str = "?") -> tuple:
        """
        Resolve a tag target address `[<lamina>:]<composite>` (D5).

        Returns the tuple (lamina_id_or_None, composite_id).  A bare
        composite resolves to the local lamina; a prefixed address
        leaves cross-lamina dispatch to Phase G's controller (which
        does not yet exist — for now we just record the prefix).

        Validation:
          - empty address                  → ValueError
          - composite unknown locally and  → ValueError (no resolver yet
            no explicit lamina prefix         for cross-lamina lookup)
          - the same bare composite id     → already prevented because
            existing on multiple laminas      a single UniversalTwin only
                                              owns its own composites;
                                              when Phase G adds the
                                              registry the ambiguity
                                              check moves there.
        """
        addr = (address or "").strip()
        if not addr:
            raise ValueError(f"Tag '{tag_id}' has empty target address.")

        if ":" in addr:
            lamina_part, _, comp_part = addr.partition(":")
            lamina_part = lamina_part.strip()
            comp_part = comp_part.strip()
            if not lamina_part or not comp_part:
                raise ValueError(
                    f"Tag '{tag_id}' target address '{address}' must be of "
                    f"the form '<lamina_id>:<composite_id>' or a bare "
                    f"'<composite_id>'."
                )
            # Cross-lamina dispatch happens in Phase G; for now we still
            # validate the local case if the prefix matches this lamina.
            if lamina_part == self.lamina_id and comp_part not in self.composites:
                raise ValueError(
                    f"Tag '{tag_id}' references composite '{comp_part}' on "
                    f"lamina '{lamina_part}' but no such composite exists."
                )
            return (lamina_part, comp_part)

        # Bare composite — local-first lookup.
        if addr not in self.composites:
            raise ValueError(
                f"Tag '{tag_id}' target '{address}' does not match any "
                f"composite on lamina '{self.lamina_id}'. Known composites: "
                f"{sorted(self.composites.keys())}."
            )
        return (None, addr)

    # ── Function Registry (overridden by child classes) ──────────────

    def _register_functions(self):
        """
        Child classes override this to register actual Python functions.
        Example:
            self._function_registry["pressure_regulation"] = self._calc_map
        """
        pass

    def _resolve_inputs(self, func_id: str) -> list:
        """
        Read the <inputs> list from the XML function definition and resolve
        current attribute values in that order.

        Returns a plain list of values — functions receive generic positional
        inputs and are not coupled to attribute names.
        """
        func_def = self.functions.get(func_id)
        if not func_def:
            return []
        return [self.attributes[attr_id].value for attr_id in func_def.inputs]

    # ── Core Operations ──────────────────────────────────────────────

    def set_sensor(self, attr_id: str, value: float, confidence: float = 1.0):
        """
        Set a sensor reading. Domain experts call this to input data.

        Example:
            twin.set_sensor("HR", 72)
            twin.set_sensor("SBP", 120)
        """
        if attr_id not in self.attributes:
            raise KeyError(f"Attribute '{attr_id}' not defined in XML")
        attr = self.attributes[attr_id]
        if attr.source != "SENSOR":
            raise ValueError(f"'{attr_id}' is PRELIMINARY, not SENSOR. Cannot set directly.")
        attr.set_value(value, confidence)
        self._log(f"SENSOR SET: {attr_id} = {value} {attr.unit}")

    def get(self, attr_id: str) -> Attribute:
        """
        Get an attribute. If PRELIMINARY and not yet computed, auto-resolves.
        """
        if attr_id not in self.attributes:
            raise KeyError(f"Attribute '{attr_id}' not defined in XML")

        attr = self.attributes[attr_id]

        # Only resolve if not yet computed
        if attr.source == "PRELIMINARY" and attr.computed_by and attr.value is None:
            self._resolve(attr_id)

        return attr

    def _resolve(self, attr_id: str, visited: set = None):
        """
        Recursively resolve an attribute's dependencies and compute its value.
        Uses visited set to prevent infinite loops (acts as a gate).
        """
        if visited is None:
            visited = set()

        if attr_id in visited:
            self._log(f"GATE: Circular dependency detected for '{attr_id}'. Halting.")
            return
        visited.add(attr_id)

        attr = self.attributes[attr_id]

        # If sensor, it should already have a value
        if attr.source == "SENSOR":
            if attr.value is None:
                self._log(f"WARNING: Sensor '{attr_id}' has no value set")
            return

        # Resolve all dependencies first
        for dep_id in attr.depends_on:
            dep_attr = self.attributes.get(dep_id)
            if dep_attr and dep_attr.source == "PRELIMINARY" and dep_attr.value is None:
                self._resolve(dep_id, visited)

        # Now compute using the registered function
        func_id = attr.computed_by
        if func_id in self._function_registry:
            try:
                inputs = self._resolve_inputs(func_id)
                result = self._function_registry[func_id](inputs)
                attr.set_value(result, confidence=0.9)
                self._log(f"COMPUTED: {attr_id} = {result:.4f} {attr.unit} (via {func_id})")
            except Exception as e:
                self._log(f"ERROR computing {attr_id}: {e}")
        else:
            self._log(f"WARNING: No function registered for '{func_id}'")

    def compute_all(self):
        """
        Run the full computation chain in step order.
        Reads step order from XML function definitions.
        """
        self._computation_log = []
        self._log(f"=== Computing {self.lamina_name} Lamina ===")

        # Sort functions by step
        sorted_funcs = sorted(
            self.functions.values(),
            key=lambda f: f.step
        )

        for func_def in sorted_funcs:
            attr_id = func_def.output
            if attr_id in self.attributes:
                self._resolve(attr_id)

        # Run gate validation
        self.validate_gates()
        self._log("=== Computation Complete ===")

    def validate_gates(self) -> list[str]:
        """
        Run all permeability gates. Returns list of flags triggered.
        If a gate fails, the attribute rolls back to its previous value.
        """
        flags = []
        for gate in self.gates:
            if gate.gate_type == "range":
                attr = self.attributes.get(gate.attribute)
                if attr and attr.value is not None:
                    if gate.min_val is not None and attr.value < gate.min_val:
                        flags.append(f"GATE FAIL: {gate.attribute} = {attr.value:.2f} < {gate.min_val} | {gate.flag}")
                        if gate.action_on_fail == "hold_previous":
                            attr.rollback()
                    elif gate.max_val is not None and attr.value > gate.max_val:
                        flags.append(f"GATE FAIL: {gate.attribute} = {attr.value:.2f} > {gate.max_val} | {gate.flag}")
                        if gate.action_on_fail == "hold_previous":
                            attr.rollback()

            elif gate.gate_type == "positive":
                attr = self.attributes.get(gate.attribute)
                if attr and attr.value is not None and attr.value <= 0:
                    flags.append(f"GATE FAIL: {gate.attribute} = {attr.value:.2f} <= 0 | {gate.flag}")
                    if gate.action_on_fail == "hold_previous":
                        attr.rollback()

            elif gate.gate_type == "consistency":
                if gate.compare and len(gate.compare) == 2:
                    a1 = self.attributes.get(gate.compare[0])
                    a2 = self.attributes.get(gate.compare[1])
                    if a1 and a2 and a1.value and a2.value:
                        avg = (abs(a1.value) + abs(a2.value)) / 2
                        if avg > 0:
                            diff = abs(a1.value - a2.value) / avg
                            if diff > gate.tolerance:
                                flags.append(
                                    f"GATE FAIL: {gate.compare[0]}={a1.value:.2f} vs "
                                    f"{gate.compare[1]}={a2.value:.2f} "
                                    f"(diff={diff:.1%} > {gate.tolerance:.0%}) | {gate.flag}"
                                )

        for f in flags:
            self._log(f)
        return flags

    # ── Vector Space ─────────────────────────────────────────────────

    def get_composite_vector(self, composite_id: str) -> dict:
        """
        Get the normalised vector for a composite grouping.
        Returns dict with attribute ids as keys and normalised values.

        Example:
            twin.get_composite_vector("pressure_state")
            → {"SBP": 0.33, "DBP": 0.33, "MAP": 0.67}
        """
        if composite_id not in self.composites:
            raise KeyError(f"Composite '{composite_id}' not defined in XML")

        comp = self.composites[composite_id]
        vector = {}
        for attr_id in comp.attribute_ids:
            attr = self.get(attr_id)
            vector[attr_id] = attr.normalised
        return vector

    def get_all_vectors(self) -> dict:
        """Get all composite vectors."""
        return {
            comp_id: self.get_composite_vector(comp_id)
            for comp_id in self.composites
        }

    # ── Absorption Vector ────────────────────────────────────────────

    def get_absorbed_vector(self, composite_id: str) -> Optional[dict]:
        """
        Apply the absorption vector to the composite's normalised attribute values.
        Returns {attr_id: absorbed_value} where absorbed_i = normalised_i × weight_i.
        This is the dampened/amplified view of the composite state.
        """
        comp = self.composites.get(composite_id)
        if not comp or comp.absorption_vector is None:
            return None
        normalised = [self.get(a).normalised or 0.0 for a in comp.attribute_ids]
        absorbed = comp.apply_absorption(normalised)
        return {
            attr_id: round(float(absorbed[i]), 6)
            for i, attr_id in enumerate(comp.attribute_ids)
        }

    def get_all_absorbed_vectors(self) -> dict:
        """Get absorbed vectors for all composites."""
        return {
            comp_id: self.get_absorbed_vector(comp_id)
            for comp_id in self.composites
        }

    def update_composite_weights(self, composite_id: str, new_weights: list):
        """
        Directly overwrite absorption vector weights for a composite.
        Use when the Auto Controller wants to set weights explicitly
        rather than applying an incremental ΔW step.
        """
        comp = self.composites.get(composite_id)
        if not comp:
            raise KeyError(f"Composite '{composite_id}' not found")
        comp.update_weights(new_weights)
        self._log(f"WEIGHTS SET: {composite_id} -> {new_weights}")

    def auto_adjust_weights(self, composite_id: str, deviation: float,
                            learning_rate: float = 0.01):
        """
        Implements  W_new = W_old + ΔW,  where  ΔW = learning_rate × deviation.

        Called by the Auto Controller after comparing a Behavioural Outcome
        against real-world sensor data (e.g. Apple Watch reading).

        ⚠️  FROZEN during Phases A–E of the feedback loop rollout (D17).
            Calling this from production code while X = X' + X'' is being
            stabilised is a bug — the gate kernel (Phase C) and the
            learning loop must not be active simultaneously, otherwise
            the absorption_vector and distribution_vector would couple
            through indirect feedback.

            Touches `absorption_vector` ONLY.  Never `distribution_vector`
            — that is owned by the domain expert via XML and read by the
            feedback loop.  This boundary is what lets Phase G re-enable
            learning without breaking the feedback loop already in place.

            See FEEDBACK_LOOP_PLAN.md §D2 and §D17 for the full rationale.

        Args:
            composite_id:  composite whose weights to adjust
            deviation:     error signal — use BehaviouralOutcome.evaluate()["deviation"]
            learning_rate: step size (default 0.01; tune per convergence needs)
        """
        comp = self.composites.get(composite_id)
        if not comp:
            raise KeyError(f"Composite '{composite_id}' not found")
        if comp.absorption_vector is None:
            raise ValueError(f"Composite '{composite_id}' has no absorption vector initialised")

        delta_w = learning_rate * deviation
        new_weights = np.clip(comp.absorption_vector + delta_w, 0.0, 1.0)
        comp.update_weights(new_weights)
        self._log(
            f"WEIGHTS ADJUSTED: {composite_id} | "
            f"deviation={deviation:.4f} | lr={learning_rate} | dW={delta_w:.6f}"
        )

    # ── Behavioural Outcomes ─────────────────────────────────────────

    def evaluate_segment_outcomes(self, segment_id: str) -> list:
        """
        Evaluate all behavioural outcomes for a segment.
        Returns a list of Feedback Objects (each a dict) comparing the
        current computed value against the domain-expert target.
        """
        seg = self.segments.get(segment_id)
        if not seg:
            return []
        results = []
        for outcome in seg.behavioural_outcomes:
            attr = self.attributes.get(outcome.attribute_id)
            if attr and attr.value is not None:
                results.append(outcome.evaluate(attr.value))
        return results

    def evaluate_all_outcomes(self) -> dict:
        """Evaluate all segment behavioural outcomes. Returns {segment_id: [feedback_objects]}."""
        return {
            seg_id: self.evaluate_segment_outcomes(seg_id)
            for seg_id in self.segments
        }

    def feedback_norm(self) -> float:
        """
        Aggregate norm of the feedback channel (D13).

        Definition:
            feedback_norm = Σ |X''_i| / Σ (physio_max_i - physio_min_i)

        Generic across laminas because both numerator and denominator
        scale with the same physio range — produces a dimensionless
        number in [0, ~1] (the saturation cap is normally < a_max ≤
        physio_range, so individual contributions cap at ≤ 1).

        Used by:
          - FeedbackController.step()        (returns it as a probe)
          - the soft circuit breaker (D16, Phase C floor)
          - the Phase E settling test       ("settled" = norm below
                                              threshold for 5 consecutive
                                              cycles, D14)

        Attributes with zero physio range are skipped on both sides so
        a degenerate definition never returns NaN.
        """
        sum_abs = 0.0
        sum_range = 0.0
        for attr in self.attributes.values():
            range_size = attr.physio_max - attr.physio_min
            if range_size <= 0:
                continue
            sum_abs += abs(attr.value_feedback)
            sum_range += range_size
        if sum_range == 0:
            return 0.0
        return sum_abs / sum_range

    # ── Introspection (for domain experts) ───────────────────────────

    def describe_attribute(self, attr_id: str) -> str:
        """Human-readable description of an attribute and its dependencies."""
        attr = self.attributes.get(attr_id)
        if not attr:
            return f"Attribute '{attr_id}' not found"

        lines = [
            f"Attribute: {attr.name} ({attr.id})",
            f"  Unit: {attr.unit}",
            f"  Source: {attr.source}",
            f"  Range: [{attr.physio_min}, {attr.physio_max}]",
            f"  Current value: {attr.value}",
            f"  Normalised: {attr.normalised}",
            f"  Description: {attr.description}",
        ]
        if attr.computed_by:
            func = self.functions.get(attr.computed_by)
            lines.append(f"  Computed by: {func.name if func else attr.computed_by}")
            lines.append(f"  Formula: {func.formula if func else 'N/A'}")
            lines.append(f"  Depends on: {', '.join(attr.depends_on)}")
        return "\n".join(lines)

    def list_attributes(self, source: str = None) -> list[str]:
        """List all attribute ids, optionally filtered by source."""
        return [
            attr_id for attr_id, attr in self.attributes.items()
            if source is None or attr.source == source
        ]

    def list_functions(self) -> list[str]:
        """List all function models with their step order."""
        sorted_funcs = sorted(self.functions.values(), key=lambda f: f.step)
        return [
            f"Step {f.step}: {f.name} | {f.formula} | {', '.join(f.inputs)} → {f.output}"
            for f in sorted_funcs
        ]

    def get_log(self) -> list[str]:
        """Return the computation log."""
        return self._computation_log

    def _log(self, message: str):
        """Add to computation log."""
        self._computation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        print(f"  {message}")


    # ── XML Modification (for domain experts) ────────────────────────

    def add_attribute_to_xml(self, attr_id: str, name: str, unit: str,
                              source: str, physio_min: float, physio_max: float,
                              description: str = "", computed_by: str = None,
                              depends_on: str = ""):
        """
        Add a new attribute to the XML file.
        Domain experts can call this to extend the model without editing XML directly.
        """
        tree = ET.parse(self.xml_path)
        root = tree.getroot()
        attrs_el = root.find(".//attributes")

        new_attr = ET.SubElement(attrs_el, "attribute", id=attr_id)
        ET.SubElement(new_attr, "n").text = name
        ET.SubElement(new_attr, "unit").text = unit
        ET.SubElement(new_attr, "source").text = source
        ET.SubElement(new_attr, "physio_min").text = str(physio_min)
        ET.SubElement(new_attr, "physio_max").text = str(physio_max)
        ET.SubElement(new_attr, "description").text = description
        if computed_by:
            ET.SubElement(new_attr, "computed_by").text = computed_by
        if depends_on:
            ET.SubElement(new_attr, "depends_on").text = depends_on

        tree.write(self.xml_path, encoding="unicode", xml_declaration=True)

        # Reload
        self._parse_xml(self.xml_path)
        self._log(f"XML UPDATED: Added attribute '{attr_id}'")

    def modify_gate_threshold(self, attribute: str, new_min: float = None,
                               new_max: float = None):
        """
        Modify gate thresholds in the XML.
        Domain experts can adjust physiological ranges.
        """
        tree = ET.parse(self.xml_path)
        root = tree.getroot()

        for gate_el in root.findall(".//gates/gate"):
            if gate_el.get("attribute") == attribute:
                if new_min is not None:
                    min_el = gate_el.find("min")
                    if min_el is not None:
                        min_el.text = str(new_min)
                if new_max is not None:
                    max_el = gate_el.find("max")
                    if max_el is not None:
                        max_el.text = str(new_max)

        tree.write(self.xml_path, encoding="unicode", xml_declaration=True)
        self._parse_xml(self.xml_path)
        self._log(f"XML UPDATED: Gate thresholds for '{attribute}' modified")


# ──────────────────────────────────────────────────────────────────────
# Identifier + Metrix (Phase B — Feedback Loop)
# ──────────────────────────────────────────────────────────────────────
#
# Both helpers are stateless — they live as classes for clarity (so a
# domain expert reading the code sees the named pipeline components from
# FEEDBACK_LOOP_PLAN.md §3.1) but every public method is a classmethod /
# staticmethod that takes the twin explicitly.
#
# Pipeline position:
#
#     compute_all()
#       └─ evaluate_all_outcomes()           [existing]
#            └─ Identifier.emit_tags(twin, outcome_evaluations)
#                  └─ for each tag → Metrix.lookup(tag) for kernel params
#                        └─ FeedbackController.step()      [Phase C]
# ──────────────────────────────────────────────────────────────────────


class Identifier:
    """
    Polls behavioural outcomes and emits Tag objects for the
    out-of-tolerance ones (D9).  The deviation_type registered for the
    tag drives the actual numeric ΔOV; the emitter (default `binary`)
    decides whether to emit at all.
    """

    @staticmethod
    def emit_tags(twin: "UniversalTwin",
                  outcome_evaluations: dict) -> list:
        """
        Args:
            twin:                the host UniversalTwin (registries live there)
            outcome_evaluations: dict in the shape produced by
                                 evaluate_all_outcomes() —
                                 {segment_id: [feedback_object, ...]}

        Returns:
            list of dicts, one per emission:
            {
              "tag":         Tag,                # registry object
              "outcome_id":  str,                # which outcome fired it
              "attribute_id": str,               # tracked attribute
              "actual":      float,
              "target":      float,
              "tolerance":   float,
              "deviation":   float,              # via deviation_registry
              "deviation_norm": float | None,    # deviation / tolerance
            }

        Behaviour:
          - poll every outcome each call (D9)
          - tags whose `outcome` field doesn't match any evaluated
            outcome are silently skipped (allows a domain expert to
            wire tags ahead of having the outcome in place)
          - in-tolerance outcomes (per the tag's emitter) are skipped
          - monitor-only tags (polarity == 0) DO emit — they still
            produce a log entry, but Phase C will treat them as a
            no-op for X''
        """
        # Flatten outcome_evaluations into {outcome_id: feedback_object}
        # for O(1) lookup by Tag.outcome.
        by_outcome: dict[str, dict] = {}
        for segment_outcomes in outcome_evaluations.values():
            for fb in segment_outcomes:
                by_outcome[fb["outcome_id"]] = fb

        emissions: list[dict] = []

        for tag in twin.tags.values():
            fb = by_outcome.get(tag.outcome)
            if fb is None:
                continue  # outcome not present — silent skip

            # Compute deviation via the registered function so a future
            # `relative` or `rate` deviation type plugs in without code
            # changes in the Identifier.
            dev_fn = twin._deviation_registry.get(tag.deviation_type)
            if dev_fn is None:
                twin._log(
                    f"WARN: Tag '{tag.id}' references unknown "
                    f"deviation_type '{tag.deviation_type}'. Skipped."
                )
                continue

            # Look up tolerance from the segment's BehaviouralOutcome
            # (Identifier doesn't carry tolerance — the outcome owns it).
            tolerance = Identifier._tolerance_for_outcome(twin, tag.outcome)

            deviation = dev_fn(fb["actual"], fb["target"], tag.params)

            # Emitter decides emission.  Binary uses |deviation| > tolerance.
            emit_fn = twin._emitter_registry.get(tag.emitter)
            if emit_fn is None:
                twin._log(
                    f"WARN: Tag '{tag.id}' references unknown emitter "
                    f"'{tag.emitter}'. Skipped."
                )
                continue
            if not emit_fn(deviation, tolerance, tag.params):
                continue  # within tolerance — no emission

            deviation_norm = (
                deviation / tolerance if tolerance else None
            )

            emissions.append({
                "tag":            tag,
                "outcome_id":     tag.outcome,
                "attribute_id":   fb["attribute_id"],
                "actual":         fb["actual"],
                "target":         fb["target"],
                "tolerance":      tolerance,
                "deviation":      deviation,
                "deviation_norm": deviation_norm,
            })

        return emissions

    @staticmethod
    def _tolerance_for_outcome(twin: "UniversalTwin",
                                outcome_id: str) -> float:
        """Look up the outcome's tolerance from segment definitions."""
        for seg in twin.segments.values():
            for outcome in seg.behavioural_outcomes:
                if outcome.id == outcome_id:
                    return outcome.tolerance
        return 0.0


class Metrix:
    """
    Param lookup helper.  Currently a thin wrapper over Tag.params, but
    isolated as a named component so Phase C's controller has a single
    extension point if domain experts want per-tag param overrides
    (e.g. patient-specific saturation) without touching tag definitions.
    """

    # Framework-wide default kernel params (D15 — kernel defaults).
    # Used only when neither the tag nor a future override supplies a
    # value.  Mirrors the demo's sigmoid_leaky_tanh expectations.
    DEFAULTS = {
        "gain":          0.6,
        "decay":         0.10,
        "threshold_k":   4.0,
        "saturation":    1.0,   # raw multiplier; controller scales by
                                # physio range if the tag stored 0.3
                                # following the convention in §2.3
        "epsilon_ratio": 0.001,
    }

    @staticmethod
    def lookup(tag: "Tag", overrides: Optional[dict] = None) -> dict:
        """
        Merge Metrix defaults ← tag.params ← overrides (most specific
        wins).  Returns a fresh dict so callers can mutate without
        side-effects on the registry.
        """
        merged = dict(Metrix.DEFAULTS)
        if tag.params:
            merged.update(tag.params)
        if overrides:
            merged.update(overrides)
        return merged
