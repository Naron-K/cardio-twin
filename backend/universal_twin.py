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

import numpy as np
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any, Optional
from datetime import datetime


# ──────────────────────────────────────────────────────────────────────
# Attribute Object (Wrapper)
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
    value: Optional[float] = None    # current raw value
    normalised: Optional[float] = None  # value in [0, 1] vector space
    timestamp: Optional[datetime] = None
    confidence: float = 1.0          # 1.0 for sensor, lower for estimated
    computed_by: Optional[str] = None   # function id (for PRELIMINARY)
    depends_on: list = field(default_factory=list)  # dependency attribute ids
    _previous_value: Optional[float] = None  # for gate fallback

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
        """Update value, store previous for gate fallback."""
        self._previous_value = self.value
        self.value = value
        self.confidence = confidence
        self.timestamp = datetime.now()
        self.normalise()

    def rollback(self):
        """Revert to previous value (used when gate rejects)."""
        if self._previous_value is not None:
            self.value = self._previous_value
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

    The absorption_vector is a 1D numpy array (shape: N,) where N equals
    the number of attributes in this composite.  Seed values are 1/N
    (equal weights) and are updated dynamically by the Auto Controller
    via the feedback rule:  W_new = W_old + ΔW
    """
    id: str
    name: str
    attribute_ids: list
    description: str = ""
    absorption_vector: Optional[np.ndarray] = field(default=None, repr=False)

    def update_weights(self, new_values):
        """Set/replace the absorption vector. Called by the Auto Controller after each feedback cycle."""
        self.absorption_vector = np.array(new_values, dtype=float)

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
        self.channel_mappings: dict[str, str] = {}  # attribute_id -> channel_id
        self.gates: list[Gate] = []
        self._function_registry: dict[str, callable] = {}
        self._computation_log: list[str] = []

        # Parse XML
        self._parse_xml(xml_path)

        # Let child classes register their function implementations
        self._register_functions()

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
