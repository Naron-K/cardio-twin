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
import sys

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
def _opt_float(text: Optional[str]) -> Optional[float]:
    """Parse an optional numeric XML element; absent or blank stays None."""
    if text is None or not text.strip():
        return None
    return float(text)


# ──────────────────────────────────────────────────────────────────────
# Attribute sources
# ──────────────────────────────────────────────────────────────────────
#
# `<source>` answers one question: who is allowed to write this
# attribute's X'.  There were two answers; inter-lamina coupling adds a
# third, and it is deliberately NOT a kind of sensor.
#
#   SENSOR        measured outside the model.  Written by set_sensor().
#                 Sacred (D12) — the feedback loop never touches it.
#
#   PRELIMINARY   computed by this lamina's own function chain.  The only
#                 source the feedback loop may write X'' onto.
#
#   INTER_LAMINA  supplied by ANOTHER lamina through a permeability gate.
#                 Written by set_inter_lamina().  Also sacred, for the
#                 same reason a sensor is: it is somebody else's ground
#                 truth, and this lamina's internal loop has no standing
#                 to correct it.  Gate decision G1 puts inter-lamina
#                 values in X' rather than X'' precisely so that
#                 "external input is not feedback" keeps holding once
#                 there is more than one lamina in the room.
#
# The split that matters most in the code below is EXTERNAL vs computed:
# an attribute whose value arrives from outside the chain must not be
# handed to _resolve() as something to compute, whichever outside it
# came from.
SENSOR       = "SENSOR"
PRELIMINARY  = "PRELIMINARY"
INTER_LAMINA = "INTER_LAMINA"

#: X' arrives from outside this lamina's function chain.
EXTERNAL_SOURCES = frozenset({SENSOR, INTER_LAMINA})
#: Everything a `<source>` element is allowed to say.
VALID_SOURCES = frozenset({SENSOR, PRELIMINARY, INTER_LAMINA})

# Confidence stamped on an INTER_LAMINA attribute resting at its declared
# baseline because nothing is coupled to it yet (G9).  Below a sensor's
# 1.0 and a computed value's 0.9 on purpose: it is a number the domain
# expert wrote down as "where this sits at rest", standing in for a
# coupling that does not exist, and it should not read as either a
# measurement or a derivation.
UNCOUPLED_CONFIDENCE = 0.5


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
    source: str                      # one of VALID_SOURCES, above
    physio_min: float                # lower physiological bound
    physio_max: float                # upper physiological bound
    description: str = ""            # human-readable description
    # Resting value a synthetic feed should sit at, when the domain expert
    # declares one.  A midpoint of the physiological range is NOT a substitute:
    # the midpoint of an FiO2 range of 0.21–1.0 is 0.6, which is a patient on
    # heavy respiratory support rather than anyone at rest.  Absent → the
    # midpoint is used and the twin simply starts somewhere legal.
    baseline: Optional[float] = None
    # Noise std dev for a synthetic feed, in the attribute's own unit.  Absent
    # → a small fraction of the declared range, which keeps a trace alive
    # without pretending to a measurement error anyone characterised.
    noise_sigma: Optional[float] = None
    value_external: Optional[float] = None  # X' — external/computed input
    value_feedback: float = 0.0             # X'' — feedback-loop delta
    normalised: Optional[float] = None  # value in [0, 1] vector space
    timestamp: Optional[datetime] = None
    confidence: float = 1.0          # 1.0 for sensor, lower for estimated
    computed_by: Optional[str] = None   # function id (for PRELIMINARY)
    depends_on: list = field(default_factory=list)  # dependency attribute ids
    # Where an INTER_LAMINA value came from, when one has arrived: gate id,
    # source lamina, how old the value is, how open the gate was.  None on
    # every other source, and on an INTER_LAMINA attribute nothing has
    # coupled to yet — which is a state worth reporting rather than hiding,
    # since the attribute is then sitting on a declared baseline and looks
    # exactly like a live coupled value if nobody says otherwise (G9).
    provenance: Optional[dict] = None
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

        The delta is clamped so the VISIBLE value stays physiological
        (Phase 0-B).  A function guards the value it returns, not the
        value anyone reads: `_calc_alveolar_ventilation` floors V_A at
        0.05 L/min and the loop adds X'' afterwards, so the screen
        showed −2.88 L/min of alveolar ventilation; the A-a gradient
        clamps at zero in code and displayed −2.69 mmHg.  Additive
        coupling makes that inherent, so the guard has to live after the
        coupling, and this method is where both the controller's step 5
        and the kernel-state restore path meet.

        The allowed band is the declared physiological range WIDENED to
        contain X' wherever X' has already left it:

            lo = min(physio_min, X')     hi = max(physio_max, X')
            X'' <- clamp(X'', lo - X', hi - X')

        Widening rather than clamping to the declared range is the whole
        point.  A pathological reading is a reading: MAP 120 against a
        declared max of 110 must stay 120 on the screen, which is the
        soft_range lesson from 2026-06-23 and not one to relearn.  What
        the band forbids is the FEEDBACK making a value unphysical — so
        with X' already above the range, X'' can only pull back toward
        it, never push further out.

        Callers that need to know a clamp happened compare the delta
        they asked for against `value_feedback` afterwards; the kernel's
        own `x_pp` state is deliberately left alone, which lets it
        disagree with the applied value exactly the way rollback_feedback
        already does.  The dead-zone snap clears the disagreement.
        """
        delta = float(delta)
        if self.value_external is not None:
            x_prime = self.value_external
            lo = min(self.physio_min, x_prime)
            hi = max(self.physio_max, x_prime)
            delta = max(lo - x_prime, min(hi - x_prime, delta))
        self.value_feedback = delta
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
    gate_type: str         # "range", "positive", "consistency", "soft_range"
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    tolerance: Optional[float] = None
    compare: Optional[list] = None
    action_on_fail: str = "hold_previous"
    flag: str = ""
    steepness: float = 2.0  # soft_range: sigmoid slope around each boundary


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
# The error signal, in one place
# ──────────────────────────────────────────────────────────────────────
def normalised_error(deviation: float, tolerance: float) -> float:
    """
    An outcome's error expressed in TOLERANCES, in excess of the band:

        E = sign(dev) · max(0, |dev| − tol) / tol

    Two decisions in one line, and they are here rather than inlined at
    each caller because there are now two of them — the lamina's own
    learning loop and the channel's backward pass — and an error signal
    that means one thing locally and another across a seam is a loop
    whose convergence nobody can reason about.

    Dividing by the tolerance is what keeps it universal: it is the one
    form of the error that means the same thing for an outcome in mL/min
    and one in mmHg, so nothing downstream carries a unit.

    The dead-zone is there because measuring said so.  Without it the
    raw dev/tol is non-zero whenever the outcome is anywhere but exactly
    on target, so the weights keep moving while the model is already
    inside the band the domain expert declared acceptable — a loop with
    nothing to converge on, grinding against its own clamps.

    Raises rather than guessing: a non-finite deviation is not an error
    measurement, and a tolerance of zero or less gives the division no
    scale, so returning 0.0 would report "on target" for an outcome
    nobody can be on target for.
    """
    if not math.isfinite(deviation):
        raise ValueError(
            f"normalised_error was handed a non-finite deviation "
            f"({deviation}); that is not a measurement of anything."
        )
    if not math.isfinite(tolerance) or tolerance <= 0.0:
        raise ValueError(
            f"normalised_error was handed tolerance={tolerance}. There is "
            f"no scale to normalise an error against, and answering 0.0 "
            f"would claim an outcome is on target when nothing can be."
        )
    excess = abs(deviation) - tolerance
    if excess <= 0.0:
        return 0.0
    return math.copysign(excess, deviation) / tolerance


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
    #: How this composite's absorption weights LEARN, when the domain
    #: expert has declared that they may:
    #:     {"outcome": id, "rate": float, "min": float, "max": float}
    #: None means the weights are what the file says and stay there.
    #: The clamp is not optional — a weight that may move must declare
    #: how far, or the loop that moves it is unbounded, and an unbounded
    #: loop inside a closed one is how a model walks away from its own
    #: physiology while every individual step looks reasonable.
    absorption_learning: Optional[dict] = field(default=None, repr=False)

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

    def state_value(self, attribute_values: list, weights=None) -> float:
        """
        Collapse the composite's attribute values into a single state value:
        the weighted mean  Σ(v_i·w_i) / Σw_i,  with the absorption vector
        acting as the weight matrix.  Where get_absorbed_vector still returns
        one number per channel, this is the one scalar that stands for the
        whole composite — e.g. a single "how is pressure_state doing right
        now" read for the summary probes downstream.

        The absorption vector is an all-or-nothing contract, exactly as in
        apply_absorption: when it is None or its length does not match the
        values, the weights degrade to equal 1/N and the result is a plain
        arithmetic mean, so an uninitialised composite can always summarise
        itself.  get_composite_state passes an explicit `weights` list when
        it has dropped unreadable (None) attributes, so the surviving values
        are always weighed by the weights that still have a value to weigh.

        A wrong input must fail loudly rather than produce a confident
        answer.  This raises ValueError when the value list is empty (there
        is no mean of nothing), when any value or weight is NaN or infinite
        (they would silently poison the ratio), when a value falls outside
        the [0, 1] normalised range the composite lives in, or when the
        weights sum to zero or less — a zero-sum weight matrix makes the
        division meaningless, and guessing 0.0 would lie.
        """
        vals = np.asarray(attribute_values, dtype=float)
        if vals.ndim != 1:
            raise ValueError(
                f"Composite '{self.id}' state_value expects a flat list of "
                f"numbers, got a {vals.ndim}-dimensional input instead"
            )
        if vals.size == 0:
            raise ValueError(
                f"Composite '{self.id}' state_value has no attribute values "
                "to summarise; refusing to average nothing"
            )
        if not np.all(np.isfinite(vals)):
            raise ValueError(
                f"Composite '{self.id}' state_value received NaN or infinite "
                "attribute values; refusing to build a state value from them"
            )
        if np.any(vals < 0.0) or np.any(vals > 1.0):
            raise ValueError(
                f"Composite '{self.id}' state_value expects normalised values "
                f"in [0, 1] but got range [{vals.min():g}, {vals.max():g}]; "
                "a summary outside the vector space would be meaningless"
            )
        if weights is None:
            source = self.absorption_vector
        else:
            source = np.asarray(weights, dtype=float)
        if source is None:
            w = np.ones(vals.size)
        else:
            w = np.asarray(source, dtype=float)
            if w.ndim != 1:
                raise ValueError(
                    f"Composite '{self.id}' absorption weights must be a "
                    f"1D vector, got {w.ndim} dimensions"
                )
            if w.size != vals.size:
                w = np.ones(vals.size)
            elif not np.all(np.isfinite(w)):
                raise ValueError(
                    f"Composite '{self.id}' state_value received NaN or "
                    "infinite weights; refusing to build a state value with them"
                )
        total = float(w.sum())
        if total <= 0.0:
            raise ValueError(
                f"Composite '{self.id}' state_value weights sum to {total:g}; "
                "a zero-or-negative weight sum makes the weighted mean "
                "undefined, so no state value is returned"
            )
        return float(np.dot(vals, w) / total)

    def adapt_absorption(self, values: list, deviation: float) -> list:
        """
        One learning step on the absorption weights, and the gradient it
        follows.

        The state value is  s = Σ vᵢwᵢ / Σw,  so

            ∂s/∂wᵢ = (vᵢ − s) / Σw

        and the step is that gradient PROJECTED onto the surface where
        Σw does not change:

            Δwᵢ = rate · deviation · (vᵢ − v̄)

        which is (vᵢ − s) minus its own mean, and so sums to zero by
        construction.  An attribute sitting on the composite's average
        gets no weight change, which is right: it carries no
        information about which way to move.

        WHY THE PROJECTION, and it is not tidiness.  The unprojected
        step Δwᵢ = rate·deviation·(vᵢ − s) sums to
        rate·deviation·(Σv − n·s), which is zero only while the weights
        are equal.  The moment they are not, Σw drifts — and Σw is
        exactly the invariant that makes this composite's state value
        the inner product AᵀX the architecture says it is.  Measured on
        a three-attribute probe at v = [0.9, 0.5, 0.1] starting from
        w = [0.7, 0.2, 0.1], four steps at rate 0.1 and deviation +1:

            step   Σw       AᵀX       state value
            0      1.000    0.7400    0.7400
            1      0.928    0.7360    0.7931
            2      0.873    0.7274    0.8328
            3      0.847    0.7168    0.8464

        AᵀX falls while the state value rises.  Those are the same
        quantity when Σw = 1, and after three learning steps they
        disagree about which WAY the composite is moving — a sign flip
        in the one number that crosses a channel.  The projected step
        holds Σw at whatever the file declared, so the two never part.

        Note it preserves the DECLARED sum, not the number 1: a domain
        expert who writes weights summing to 2 keeps a sum of 2, and
        whatever relationship held between AᵀX and the state value at
        load time holds for the rest of the run.

        Δs is still positive for a positive error — substituting the
        projected step into ∂s/∂wᵢ gives
        Δs = rate·deviation·n·Var(v)/Σw — so the loop still moves the
        state the way the outcome says it is missing, and it stops only
        when the attributes agree with each other, which is the one
        case where no reweighting can move the summary at all.

        Every weight is then clamped into the declared band, and the
        residual the clamp pinned is handed back to the weights that
        are still free, so the sum survives a clamp too.

        One honest note on the projection, since it is easy to overstate
        what it buys.  When no clamp binds, writing the step projected
        and writing it unprojected-then-corrected give the SAME numbers
        — the correction −rate·deviation·(v̄ − s) is exactly the
        difference between the two forms.  The projection is therefore
        the direct statement of what the pair computes anyway, and it
        earns its place by needing no correction: the sum is right
        before anything is redistributed, so a clamp that binds is
        redistributing only what the clamp took, never what the step
        left over.

        Returns the new weights; raises rather than guessing when the
        inputs cannot support a step.
        """
        rule = self.absorption_learning
        if rule is None:
            raise ValueError(
                f"Composite '{self.id}' was asked to adapt its absorption "
                f"weights but declares no learning rule. Declare "
                f"learns_from, learning_rate, clamp_min and clamp_max on "
                f"its <absorption_vector>, or do not call this."
            )
        if self.absorption_vector is None:
            raise ValueError(
                f"Composite '{self.id}' declares absorption learning but has "
                f"no absorption vector to learn on."
            )
        if not math.isfinite(deviation):
            raise ValueError(
                f"Composite '{self.id}' was handed a non-finite deviation "
                f"({deviation}); a step of that size is not a step."
            )
        vals = np.asarray(values, dtype=float)
        if vals.size != len(self.absorption_vector):
            raise ValueError(
                f"Composite '{self.id}' has {len(self.absorption_vector)} "
                f"weights but was handed {vals.size} values. Learning on a "
                f"mismatched pair would move the wrong weights."
            )
        if not np.all(np.isfinite(vals)):
            raise ValueError(
                f"Composite '{self.id}' was handed NaN or infinite attribute "
                f"values to learn from."
            )
        step = float(rule["rate"]) * float(deviation) * (vals - vals.mean())
        declared_sum = float(np.sum(self.absorption_vector))
        new = _clamp_preserving_sum(self.absorption_vector + step,
                                    declared_sum,
                                    float(rule["min"]), float(rule["max"]))
        self.update_weights(new)
        return [float(w) for w in new]

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


def _clamp_preserving_sum(vec, target_sum: float,
                          low: float, high: float):
    """
    Clamp into [low, high] and give the clamped-off residual back to the
    weights that are still free, so Σw survives the clamp.

    The clamp is the hard bound — a weight that may move has to say how
    far, and that promise outranks the sum — so a residual that cannot
    be placed is LEFT UNPLACED rather than pushed past an edge.  That
    happens only when every weight is pinned, which is a saturated
    composite: a real state, and one a caller can see by summing the
    vector it gets back.

    Four passes at most.  Each one hands the residual equally to the
    weights that have room in the direction it needs to go, and either
    it lands or another weight pins and the next pass has fewer to
    share it between.
    """
    v = np.clip(np.asarray(vec, dtype=float), low, high)
    for _ in range(4):
        residual = target_sum - float(v.sum())
        if abs(residual) < 1e-12:
            break
        free = (v < high - 1e-12) if residual > 0 else (v > low + 1e-12)
        count = int(np.count_nonzero(free))
        if count == 0:
            break
        v = np.clip(np.where(free, v + residual / count, v), low, high)
    return v


def _parse_absorption_learning(av_el, comp_id: str) -> Optional[dict]:
    """
    The optional learning rule on an `<absorption_vector>`.

    All four attributes or none.  A learning_rate without a clamp is
    refused rather than defaulted, because a default clamp is a bound
    nobody chose sitting inside a closed loop — and the whole reason the
    absorption vector may move at all is that somebody decided how far.
    """
    declared = {k: av_el.get(k) for k in
                ("learns_from", "learning_rate", "clamp_min", "clamp_max")}
    present = {k: v for k, v in declared.items() if v not in (None, "")}
    if not present:
        return None
    missing = sorted(set(declared) - set(present))
    if missing:
        raise ValueError(
            f"Composite '{comp_id}' declares absorption learning but is "
            f"missing {missing}. A weight that may move has to say what it "
            f"learns from, how fast, and how far it may go — a default "
            f"bound inside a closed loop is a bound nobody chose."
        )
    try:
        rate = float(present["learning_rate"])
        low = float(present["clamp_min"])
        high = float(present["clamp_max"])
    except ValueError as exc:
        raise ValueError(
            f"Composite '{comp_id}' has a non-numeric absorption learning "
            f"parameter: {exc}"
        ) from exc
    if not math.isfinite(rate) or rate <= 0.0:
        raise ValueError(
            f"Composite '{comp_id}' has learning_rate={rate}. A rate of "
            f"zero or less is a loop that reports learning and does none."
        )
    if not (math.isfinite(low) and math.isfinite(high)) or not low < high:
        raise ValueError(
            f"Composite '{comp_id}' has clamp_min={low} and clamp_max="
            f"{high}. The band has to have width, or the weights are "
            f"pinned and the declaration is untrue."
        )
    if low < 0.0:
        raise ValueError(
            f"Composite '{comp_id}' has clamp_min={low}. A negative "
            f"absorption weight would flip an attribute's contribution to "
            f"the state value, which is what polarity is for."
        )
    return {"outcome": present["learns_from"], "rate": rate,
            "min": low, "max": high}


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

    `polarity`: the sign of the coupling between THIS composite and the
    outcome the tag watches, which is not necessarily the same sign for
    every target a tag fans into.  PACO2_DEVIATION reaches both
    `ventilation_state` and `gas_exchange_state`, and "does raising this
    composite raise or lower PaCO2?" is a separate question per
    composite — a sign carried on the tag can only answer it once.

    None means "inherit the tag's polarity", which is what every XML
    written before this field existed says by omission.  A declared
    value overrides the tag for this target only.  Note the inheritance
    is resolved at USE time, not parse time, so a runtime tag-polarity
    override (see main._apply_tag_overrides) still reaches the targets
    that inherit and correctly leaves the ones that declare alone.
    """
    address: str
    weight: float = 1.0
    polarity: Optional[float] = None


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
# Adaptive Feedback Loop — persistent meta-state (slow loop)
# ──────────────────────────────────────────────────────────────────────
#
# Implements the persistent half of the two-timescale split from the
# Adaptive Feedback Loop spec.  The fast loop (FeedbackController) keeps
# TRANSIENT per-(tag, attr) kernel state that the dead-zone snap wipes
# every time an outcome settles.  This object is the PERSISTENT half:
# one record per behavioural outcome that survives the snap, survives
# reset_kernel_state(), and accumulates learning across episodes (and,
# when server-side persistence is added later, across runs).
#
# It lives on UniversalTwin (parent), NOT on FeedbackController — that
# placement is exactly what keeps a controller built to forget within an
# episode able to still learn across episodes.  See
# `adaptive_feedback_architecture.md` §"Layer 2 / Invariant" and the
# locked kernel decisions (2026-06-11).
#
# v1 adaptation scope (locked): the slow loop may move `gain` and
# `operating_point` only.  Gate steepness adaptation is deferred to v2,
# so there is intentionally no steepness field that the slow loop writes.
# ──────────────────────────────────────────────────────────────────────
@dataclass
class MetaState:
    """
    Persistent per-outcome learning state for the slow adaptation loop.

    Fields:
        gain             learned proportional gain handed down to the fast
                         loop.  None until seeded from the tag/XML default
                         so the slow loop never starts from a hard-coded
                         number that disagrees with the lamina config.
        operating_point  cumulative target shift folded into the outcome
                         (native units).  Applied with bumpless transfer:
                         shifting by ΔX subtracts ΔX from the fast loop's
                         leaky integrator so total tone stays continuous.
        perf_ewma        EWMA of |normalised deviation| — the performance
                         accumulator, the only input the slow loop reads.
                         None until the first cycle feeds it.
        prev_perf        perf_ewma snapshot at the last slow-loop tick;
                         the MIT-rule compares against it to decide whether
                         the last adjustment helped.
        last_direction   sign (+1/-1/0) of the last gain nudge — MIT-rule
                         memory so an improving direction is continued and
                         a worsening one is reversed.
        updates          count of slow-loop adjustments applied (telemetry
                         + lets a kernel ramp its rate down over time).
    """
    gain: Optional[float] = None
    operating_point: float = 0.0
    perf_ewma: Optional[float] = None
    prev_perf: Optional[float] = None
    last_direction: float = 0.0
    updates: int = 0


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

        # Which attributes failed to compute, id → reason (Phase 0-C).
        #
        # When a function raises, _resolve() logs and moves on, and the
        # attribute keeps whatever it held last cycle.  Nothing
        # downstream could tell: the screen showed a PaCO2 frozen at
        # 1928 mmHg as live and confidently, because a stale number and
        # a fresh one are the same number.  The log line was the only
        # trace, and a log line is not something a value renderer can
        # read.  This is, and the snapshot carries it out to the view.
        #
        # Cleared at the top of every compute_all(), so membership means
        # "failed on the most recent full pass" rather than "failed once,
        # ever".  A direct get() outside compute_all() adds to it too —
        # that resolve is just as capable of failing.
        self.failed_attributes: dict[str, str] = {}

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

        # ── Adaptive feedback loop registry (slow loop) ──────────────
        #
        # Sixth registry slot, parallel to the gate-kernel registry, per
        # the Adaptive Feedback Loop spec's implementation-placement
        # table.  Holds the pluggable slow-loop adaptation kernels.  The
        # default is model-free (MIT-rule); RLS is registered as a
        # deferred stub (locked decision 2026-06-11).
        self._adaptation_kernel_registry: dict[str, callable] = {}

        # PERSISTENT meta-state store, keyed by behavioural-outcome id.
        # Deliberately a plain dict on the parent so it is structurally
        # separate from FeedbackController._kernel_state (transient).
        # The dead-zone snap and reset_kernel_state() touch only the
        # transient store, never this one — that separation is the whole
        # point of the two-timescale design.
        self._meta_state: dict[str, MetaState] = {}

        # XML-declared selections (parsed below, defaults applied if
        # the optional blocks are absent).
        self.coupling_type: str = "additive"
        self.behaviour_solver_type: str = "algebraic_chain"
        self.behaviour_solver_dt: float = 1.0
        self.behaviour_solver_unit: str = "second"
        # Loose solver params carried verbatim from the <behaviour_solver>
        # XML attributes other than type/dt/unit.  Values arrive as strings
        # from XML; each registered solver coerces the ones it understands.
        self.behaviour_solver_params: dict[str, str] = {}

        # Slow-loop config (numbers live in XML, algorithm in parent).
        # Defaults keep the slow loop INERT until a lamina opts in:
        #   - adaptation_kernel_type selects the registered kernel
        #   - slow_loop_cadence N = 0 disables the slow loop entirely
        #     (Phase 1 ships the mechanism switched off; Phase 5 wires
        #     real numbers into circulatory_lamina.xml)
        self.adaptation_kernel_type: str = "model_free"
        self.slow_loop_cadence: int = 0
        # Slow-loop tuning knobs + safe bounds.  Parsed from the optional
        # <adaptation> XML block; these framework defaults apply when the
        # block (or an individual attribute) is absent.  Tight + slow per
        # the locked design rules.
        self.adaptation_params: dict[str, float] = {
            "perf_alpha": 0.10,   # EWMA smoothing for the perf accumulator
            "gain_rate":  0.02,   # per-tick gain nudge (slow)
            "gain_min":   0.05,
            "gain_max":   2.0,
            "op_rate":    0.10,   # fraction of sustained correction folded/tick
            "op_min":    -1.0,    # operating-point shift clamp (fraction of tol)
            "op_max":     1.0,
            "settle_band": 0.5,   # |norm deviation| under this ⇒ "near settled"
        }

        # Register the v1 default kernels.  Phase A registered coupling
        # only; Phase B adds the deviation + emitter defaults; Phase C
        # adds the gate kernel + solver defaults so the full pipeline
        # can run end-to-end.
        self._register_default_coupling()
        self._register_default_deviation()
        self._register_default_emitter()
        self._register_default_gate_kernel()
        self._register_default_solver()
        self._register_default_adaptation_kernel()

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

        def fixed_point(twin, params):
            """
            Iterate the function chain to a fixed point.

            Runs compute_all() repeatedly until the largest absolute change
            across every PRELIMINARY attribute that holds a number drops
            below `tol`, or `max_iter` passes have run.  A lamina whose
            chain is already consistent converges after two passes (the
            second pass just confirms the first); one with a dependency
            cycle relaxes toward its fixed point pass by pass.

            Params arrive as STRINGS (they come from XML attributes), so
            both are coerced here and validated loudly: a wrong knob must
            fail rather than run a loop with an unreadable budget.

            A loop that hits max_iter without converging does NOT raise —
            but it never looks like one that did.  Every PRELIMINARY
            attribute still moving by more than `tol` on the final pass is
            recorded in twin.failed_attributes with its residual, so a
            value present after this solver returns is a value marked
            untrustworthy wherever it was still changing.
            """
            max_iter = 25
            tol = 1e-6
            raw_max_iter = params.get("max_iter")
            if raw_max_iter is not None:
                try:
                    max_iter = int(str(raw_max_iter).strip())
                except ValueError:
                    raise ValueError(
                        f"fixed_point solver was handed max_iter="
                        f"'{raw_max_iter}', which is not an integer. Say how "
                        "many passes the loop may run, or leave it out for "
                        "the default of 25."
                    )
            if max_iter < 2:
                raise ValueError(
                    f"fixed_point solver was handed max_iter={max_iter}. "
                    "Convergence is a comparison between two passes, so one "
                    "pass cannot measure it: max_iter=1 returned the very "
                    "first estimate with an empty failed_attributes, which "
                    "is a wrong answer wearing a clean bill of health. Ask "
                    "for at least 2 — or name algebraic_chain, which is "
                    "what a single pass actually is."
                )
            raw_tol = params.get("tol")
            if raw_tol is not None:
                try:
                    tol = float(str(raw_tol).strip())
                except ValueError:
                    raise ValueError(
                        f"fixed_point solver was handed tol='{raw_tol}', "
                        "which is not a number. Give a positive finite "
                        "tolerance, or leave it out for the default of 1e-6."
                    )
            if not math.isfinite(tol):
                raise ValueError(
                    f"fixed_point solver was handed tol={tol}. A tolerance "
                    "that is not finite gives the convergence test no scale, "
                    "so the loop is refused."
                )
            if tol <= 0.0:
                raise ValueError(
                    f"fixed_point solver was handed tol={tol}. A tolerance "
                    "of zero or less makes 'converged' mean something no "
                    "floating-point chain can ever reach."
                )

            previous: Optional[dict[str, float]] = None
            current: dict[str, float] = {}
            for iteration in range(max_iter):
                twin.compute_all()
                current = {
                    attr_id: attr.value
                    for attr_id, attr in twin.attributes.items()
                    if attr.source == PRELIMINARY and attr.value is not None
                }
                if previous is not None:
                    largest = 0.0
                    for attr_id, value in current.items():
                        if attr_id in previous:
                            largest = max(
                                largest, abs(value - previous[attr_id])
                            )
                        else:
                            largest = float("inf")
                            break
                    if largest < tol:
                        return
                if iteration < max_iter - 1:
                    previous = current

            # max_iter reached without converging.  `previous` holds the
            # pass before the last — it stays None when max_iter == 1, in
            # which case no movement was ever measured and there is nothing
            # honest to report.  compute_all() cleared failed_attributes on
            # the final pass, so the entries written here survive: name
            # every attribute still moving and how far.
            if previous is not None:
                for attr_id, value in current.items():
                    residual = (
                        abs(value - previous[attr_id])
                        if attr_id in previous else float("inf")
                    )
                    if residual > tol:
                        twin.failed_attributes[attr_id] = (
                            f"fixed_point solver did not converge in "
                            f"{max_iter} passes; '{attr_id}' residual "
                            f"{residual:.6g} exceeds tol {tol:g}"
                        )

        self._solver_registry["fixed_point"] = fixed_point

    def register_solver(self, name: str, fn) -> None:
        """
        Add or replace a behaviour solver.

        The extension point a solver arrives through, and the one XML
        selects when <behaviour_solver type="..."/> names it.  Signature
        contract (frozen):
            solver(twin: UniversalTwin, params: dict) -> None
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError(
                f"register_solver needs a non-empty name, got {name!r}."
            )
        if not callable(fn):
            raise ValueError(
                f"register_solver was handed a {type(fn).__name__} for "
                f"solver '{name}'; a solver must be callable as "
                "solver(twin, params)."
            )
        self._solver_registry[name] = fn

    def _register_default_adaptation_kernel(self):
        """
        Register the v1 slow-loop adaptation kernels.

        Two kernels land here (locked decision 2026-06-11):

          model_free  — the default.  A MIT-rule / gradient nudge that
                        adapts the fast loop's `gain` and folds steady
                        residual into the `operating_point`.  Domain-free:
                        it reads only the dimensionless performance summary
                        and the (already normalised) sustained correction,
                        so a brand-new lamina inherits it with no extra
                        adaptation code — only math + config.

          rls         — recursive least squares.  DEFERRED.  Registered so
                        XML can reference it and the registry shape is
                        stable, but it raises NotImplementedError if
                        actually selected (fail-fast, matching the rest of
                        this codebase).  Implemented in a later pass.

        Signature contract (frozen — Phase 3's slow-loop controller and
        any future kernel must honour it):

            kernel(meta: MetaState,
                   ctx:  dict,
                   params: dict) -> dict

          ctx (supplied by the slow-loop controller each tick):
              "perf"                 float  EWMA of |normalised deviation|
              "settled"              bool   fast loop settled this episode
              "sustained_correction" float  steady X'' the fast loop holds,
                                            already normalised by tolerance
                                            (dimensionless) — keeps the
                                            kernel domain-free
          params: self.adaptation_params merged with any XML overrides.

          returns:
              "gain"            float  new fast-loop gain (clamped)
              "operating_point" float  new operating point (clamped)
              "op_delta"        float  ΔX applied this tick — the controller
                                       subtracts it from the leaky
                                       integrator for bumpless transfer
              "direction"       float  new last_direction (MIT-rule memory)
              "consolidated"    bool   whether operating_point moved

        The kernel is PURE w.r.t. meta: it reads meta but does not mutate
        it.  The controller writes the returned values back into meta and
        owns the bumpless-transfer application — keeps this function easy
        to unit-test in isolation.
        """
        def model_free(meta, ctx, params):
            perf = float(ctx.get("perf", 0.0))
            settled = bool(ctx.get("settled", False))
            sustained = float(ctx.get("sustained_correction", 0.0))

            gain_rate = float(params.get("gain_rate", 0.02))
            gain_min  = float(params.get("gain_min", 0.05))
            gain_max  = float(params.get("gain_max", 2.0))
            op_rate   = float(params.get("op_rate", 0.10))
            op_min    = float(params.get("op_min", -1.0))
            op_max    = float(params.get("op_max", 1.0))

            # Seed gain from whatever the lamina configured if the slow
            # loop has never run for this outcome (None means unseeded).
            gain = meta.gain if meta.gain is not None else float(
                params.get("gain_seed", 0.6)
            )
            operating_point = float(meta.operating_point)

            # ── Gain adaptation (MIT-rule) ───────────────────────────
            # Compare current performance to the snapshot taken at the
            # last tick.  perf is an error measure, so LOWER is better.
            #   improved  → keep nudging gain the same way
            #   worsened  → reverse direction
            #   first tick (prev_perf None) → probe upward (+1)
            if meta.prev_perf is None:
                direction = 1.0 if meta.last_direction == 0.0 else meta.last_direction
            else:
                improved = perf < meta.prev_perf
                if improved:
                    direction = meta.last_direction if meta.last_direction != 0.0 else 1.0
                else:
                    direction = -meta.last_direction if meta.last_direction != 0.0 else -1.0

            new_gain = gain + gain_rate * direction
            new_gain = max(gain_min, min(gain_max, new_gain))

            # ── Operating-point consolidation ────────────────────────
            # Only fold the SETTLED residual into the operating point:
            # we want the steady compensation the fast loop genuinely
            # needs, not the transient overshoot.  Consolidating mid-
            # transient would ratchet the operating point past target.
            op_delta = 0.0
            consolidated = False
            if settled and abs(sustained) > 0.0:
                op_delta = op_rate * sustained
                new_op = operating_point + op_delta
                new_op = max(op_min, min(op_max, new_op))
                # Recover the clamp-adjusted actual delta so the
                # controller's bumpless subtraction stays exact.
                op_delta = new_op - operating_point
                operating_point = new_op
                consolidated = op_delta != 0.0

            return {
                "gain":            new_gain,
                "operating_point": operating_point,
                "op_delta":        op_delta,
                "direction":       direction,
                "consolidated":    consolidated,
            }

        def rls(meta, ctx, params):
            raise NotImplementedError(
                "The 'rls' adaptation kernel is a deferred stub. "
                "Select 'model_free' (the default) until RLS lands."
            )

        self._adaptation_kernel_registry["model_free"] = model_free
        self._adaptation_kernel_registry["rls"] = rls

    # ── Meta-state store (persistent slow-loop state) ────────────────

    def get_meta_state(self, outcome_id: str) -> "MetaState":
        """
        Return the persistent MetaState for a behavioural outcome,
        lazily creating an empty one on first access.

        This is the only sanctioned way to reach the persistent store —
        callers never index self._meta_state directly so the lazy-create
        invariant holds everywhere.
        """
        ms = self._meta_state.get(outcome_id)
        if ms is None:
            ms = MetaState()
            self._meta_state[outcome_id] = ms
        return ms

    def reset_meta_state(self):
        """
        Wipe ALL persistent learning.

        Deliberately NOT called by the dead-zone snap or by
        FeedbackController.reset_kernel_state() — those reset only the
        transient fast-loop store.  Persistent learning is erased only
        when a caller explicitly asks (e.g. starting a fresh patient /
        loading factory defaults).
        """
        self._meta_state.clear()
        self._log("META-STATE RESET: all persistent slow-loop learning cleared")

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
            # Every attribute other than the three the parser owns goes
            # straight to the solver, verbatim (strings).  type/dt/unit are
            # framework concerns; anything else — max_iter, tol, ... — is
            # that solver's own tuning knob.
            self.behaviour_solver_params = {
                key: value for key, value in solver_el.attrib.items()
                if key not in ("type", "dt", "unit")
            }

        # ── Adaptive feedback loop (slow loop) declaration ───────────
        #
        # Optional <adaptation> block.  Absent → slow loop stays inert
        # (cadence 0), so every pre-adaptive XML keeps running unchanged.
        #
        #   <adaptation kernel="model_free" cadence="20">
        #     <param name="gain_rate" value="0.02"/>
        #     <param name="gain_max"  value="2.0"/>
        #     ...
        #   </adaptation>
        #
        # kernel must name a registered adaptation kernel (fail fast on a
        # typo so a misconfigured lamina never silently runs with no
        # learning).  cadence is the fixed N from the locked decision.
        # Each <param> overrides one entry of self.adaptation_params; all
        # are plain floats (numbers in XML, algorithm in the parent).
        adapt_el = root.find("adaptation")
        if adapt_el is not None:
            self.adaptation_kernel_type = adapt_el.get(
                "kernel", self.adaptation_kernel_type
            )
            if self.adaptation_kernel_type not in self._adaptation_kernel_registry:
                raise ValueError(
                    f"<adaptation> selects unknown kernel "
                    f"'{self.adaptation_kernel_type}'. Registered kernels: "
                    f"{sorted(self._adaptation_kernel_registry.keys())}."
                )
            cadence_text = adapt_el.get("cadence")
            if cadence_text is not None:
                cadence = int(cadence_text)
                if cadence < 0:
                    raise ValueError(
                        f"<adaptation cadence='{cadence_text}'> must be >= 0 "
                        "(0 disables the slow loop)."
                    )
                self.slow_loop_cadence = cadence
            for param_el in adapt_el.findall("param"):
                pname = param_el.get("name")
                pval = param_el.get("value")
                if pname and pval is not None:
                    self.adaptation_params[pname] = float(pval)

        # Parse attributes
        for attr_el in root.findall(".//attributes/attribute"):
            attr_id = attr_el.get("id")
            depends_text = attr_el.findtext("depends_on", "")
            depends = [d.strip() for d in depends_text.split(",") if d.strip()]

            # An unrecognised source used to fall through as "not
            # PRELIMINARY", which is now the same branch an inter-lamina
            # attribute takes — so a typo would quietly become an input
            # nobody feeds, resting at whatever it was declared with.
            # Naming the legal set is what stops that.
            source = attr_el.findtext("source", SENSOR).strip()
            if source not in VALID_SOURCES:
                raise ValueError(
                    f"Attribute '{attr_id}' declares source '{source}'. "
                    f"Legal sources: {sorted(VALID_SOURCES)}."
                )

            self.attributes[attr_id] = Attribute(
                id=attr_id,
                name=attr_el.findtext("n", attr_el.findtext("name", attr_id)),
                unit=attr_el.findtext("unit", ""),
                source=source,
                physio_min=float(attr_el.findtext("physio_min", "0")),
                physio_max=float(attr_el.findtext("physio_max", "1")),
                description=attr_el.findtext("description", ""),
                baseline=_opt_float(attr_el.findtext("baseline")),
                noise_sigma=_opt_float(attr_el.findtext("noise_sigma")),
                computed_by=attr_el.findtext("computed_by"),
                depends_on=depends,
            )

        # G9: an INTER_LAMINA attribute rests at its declared baseline until
        # something couples to it.  Nothing else will seed it — the synthetic
        # feed reads list_attributes("SENSOR") and correctly does not emit
        # for this source — so without this the whole chain downstream of the
        # seam goes dark the moment an attribute stops being a sensor, and a
        # lamina running standalone would visibly regress for a change that
        # is supposed to leave it exactly where it was.
        for attr in self.attributes.values():
            if attr.source != INTER_LAMINA:
                continue
            if attr.baseline is None:
                self._log(
                    f"WARNING: INTER_LAMINA '{attr.id}' declares no <baseline>, "
                    f"so it has no value until a gate supplies one."
                )
                continue
            attr.set_value(attr.baseline, confidence=UNCOUPLED_CONFIDENCE)

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
                comp.absorption_learning = _parse_absorption_learning(
                    av_el, comp_id)
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
                steepness=float(gate_el.findtext("steepness", "2.0")),
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
                  <target address="gas_exchange_state" weight="0.4"
                          polarity="negative"/>
                </targets>
                <params gain="0.6" decay="0.10" threshold_k="4.0"
                        saturation="0.3" epsilon_ratio="0.001"/>
              </tag>
            </tags>

        `polarity` on a <target> is optional and inherits the tag's sign
        when absent, so every XML written before the attribute existed
        parses to exactly the behaviour it had.  It exists because a tag
        with two targets couples to its outcome through each of them
        separately, and the two couplings can have opposite signs.

        Validation performed here (fail fast):
          - duplicate tag id → ValueError
          - outcome reference unknown to any segment → ValueError
          - polarity unparseable → ValueError (via resolve_polarity)
          - target address ambiguous local lookup → ValueError (D5)
          - target weight negative → ValueError
          - acting target polarity on a monitor-only tag → ValueError
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
                    # Per-target polarity is OPTIONAL and inherits the
                    # tag's sign when absent.  Only call resolve_polarity
                    # when the attribute is actually present: it maps a
                    # missing declaration to -1.0, which is the right
                    # default for a <tag> and exactly the wrong one here,
                    # where absent means "inherit" rather than "negative".
                    tgt_polarity = None
                    if "polarity" in tgt_el.attrib:
                        tgt_polarity = resolve_polarity(tgt_el.get("polarity"))
                        # A monitor-only tag that fans into an acting
                        # target is a contradiction, and the tag-level
                        # check in FeedbackController.step() short-circuits
                        # before any target is read — so the declaration
                        # would sit in the XML looking effective and do
                        # nothing.  Refuse it at parse time instead.
                        if polarity == 0.0 and tgt_polarity != 0.0:
                            raise ValueError(
                                f"Tag '{tag_id}' is monitor-only (polarity=0) "
                                f"but its target '{addr}' declares "
                                f"polarity='{tgt_el.get('polarity')}'. A "
                                f"monitor-only tag emits no correction on any "
                                f"target; drop the tag's polarity=0 or the "
                                f"target's polarity."
                            )
                    # Validate the address now so typos surface at load
                    # time, not on the first feedback cycle (D5).
                    self.resolve_tag_address(addr, tag_id=tag_id)
                    targets.append(TagTarget(address=addr, weight=weight,
                                             polarity=tgt_polarity))

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
        if attr.source != SENSOR:
            raise ValueError(
                f"'{attr_id}' is {attr.source}, not SENSOR. Cannot set "
                f"directly."
                + (" Inter-lamina values arrive through set_inter_lamina()."
                   if attr.source == INTER_LAMINA else "")
            )
        attr.set_value(value, confidence)
        self._log(f"SENSOR SET: {attr_id} = {value} {attr.unit}")

    def set_inter_lamina(self, attr_id: str, value: float,
                         confidence: float = 1.0,
                         provenance: Optional[dict] = None):
        """
        Write a value that came from another lamina (G1).

        This is the ONLY door into an INTER_LAMINA attribute, and it is a
        separate door from set_sensor() on purpose.  Both write X', and
        both produce a value this lamina's feedback loop must not touch —
        but they are different claims about where a number came from, and
        collapsing them would make "sensor" mean "anything I did not
        compute", which is exactly the distinction the coupling design
        rests on.

        `provenance` is whatever the caller knows about the crossing —
        gate id, source lamina, age of the value, how open the gate was.
        It is stored verbatim and reported in the snapshot, so a reader
        can tell a live coupled value from a stale one, and both from an
        attribute still resting on its declared baseline.
        """
        if attr_id not in self.attributes:
            raise KeyError(f"Attribute '{attr_id}' not defined in XML")
        attr = self.attributes[attr_id]
        if attr.source != INTER_LAMINA:
            raise ValueError(
                f"'{attr_id}' is {attr.source}, not INTER_LAMINA. Only an "
                f"attribute declared as the receiving end of a permeability "
                f"gate may be written this way."
            )
        attr.set_value(value, confidence)
        attr.provenance = provenance
        self._log(f"INTER-LAMINA SET: {attr_id} = {value} {attr.unit}")

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

        # Anything whose X' arrives from outside the chain — a sensor
        # reading or a value another lamina pushed through a gate — is
        # not this function's to compute.  Both should already hold a
        # value; neither has a `computed_by`, so falling through would
        # send them into the "no function registered" branch and mark
        # them stale (0-C) for the crime of being an input.
        if attr.source in EXTERNAL_SOURCES:
            if attr.value is None:
                self._log(
                    f"WARNING: {attr.source} '{attr_id}' has no value set"
                )
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
                self.failed_attributes.pop(attr_id, None)
                self._log(f"COMPUTED: {attr_id} = {result:.4f} {attr.unit} (via {func_id})")
            except Exception as e:
                # 0-C: record it, not just log it.  The attribute still
                # holds last cycle's value and still reads as live —
                # this is the only thing that says otherwise.
                self.failed_attributes[attr_id] = f"{type(e).__name__}: {e}"
                self._log(f"ERROR computing {attr_id}: {e}")
        else:
            self.failed_attributes[attr_id] = (
                f"No function registered for '{func_id}'"
            )
            self._log(f"WARNING: No function registered for '{func_id}'")

    def compute_all(self):
        """
        Run the full computation chain in step order.
        Reads step order from XML function definitions.
        """
        self._computation_log = []
        # 0-C: this pass owns the failure list.  An attribute that failed
        # last cycle and computes cleanly this one is not stale any more,
        # and one that stays broken is re-recorded below.
        self.failed_attributes = {}
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

            elif gate.gate_type == "soft_range":
                # Continuous sigmoid conductance — neuron-inspired MONITOR.
                #
                # Each boundary contributes a conductance g ∈ (0, 1]:
                #   g_low  = σ( steepness · (v − min) )  → 0 when v ≪ min
                #   g_high = σ( steepness · (max − v) )  → 0 when v ≫ max
                #   g      = g_low · g_high               (g ≈ 1 inside range)
                #
                # NOTE (2026-06-23): this gate no longer rewrites the
                # attribute value.  It previously blended the computed value
                # toward the boundary
                #   effective = boundary · (1 − g) + v · g
                # which SILENTLY pulled out-of-range physiology back toward
                # "normal" — e.g. a hypertensive MAP of 120 mmHg was quietly
                # displayed as ~110, masking the very pathology the twin
                # exists to show.  The gate now only REPORTS how far open it
                # is and leaves the true value intact, so the chart shows the
                # real number and the feedback loop acts on the real
                # deviation.  Hard numerical safety (e.g. R > 0, signal
                # bounds) still lives in the "positive"/"range" gates and the
                # signal source.
                attr = self.attributes.get(gate.attribute)
                if attr and attr.value is not None:
                    v = attr.value
                    if gate.min_val is not None:
                        exp_lo = max(-700.0, min(700.0,
                            -gate.steepness * (v - gate.min_val)))
                        g_low = 1.0 / (1.0 + math.exp(exp_lo))
                    else:
                        g_low = 1.0
                    if gate.max_val is not None:
                        exp_hi = max(-700.0, min(700.0,
                            -gate.steepness * (gate.max_val - v)))
                        g_high = 1.0 / (1.0 + math.exp(exp_hi))
                    else:
                        g_high = 1.0
                    g = g_low * g_high
                    # g < 0.5 ⇔ v is past a boundary — flag it, do not alter.
                    if g < 0.5:
                        flags.append(
                            f"GATE SOFT: {gate.attribute} = {v:.2f} "
                            f"out of [{gate.min_val}, {gate.max_val}] "
                            f"(open={g:.3f}) | {gate.flag}"
                        )

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

    def get_composite_state(self, composite_id: str) -> Optional[float]:
        """
        Summarise a composite as one scalar in [0, 1] — the weighted mean
        of its readable attribute values, the absorption vector acting as
        the weight matrix.  Where get_composite_vector still lists every
        channel, this is the single number that stands for the composite as
        a whole (e.g. one "is this pressure state healthy" probe for the
        feedback loop's summaries).

        An attribute whose normalised value is None cannot be weighed, so it
        is dropped together with its matching weight — an unmeasured channel
        must not drag the summary towards 0.0 as if it read "fully
        unhealthy".  When nothing readable is left there is no summary to
        give, so the result is None rather than a fabricated number.

        NOT rounded, unlike get_absorbed_vector beside it.  That one is
        read by the snapshot and a reader wants six decimals; this one is
        arithmetic — an inter-lamina channel carries it, maps it into the
        receiving attribute's units and low-passes it — and rounding at
        six decimals put a 5e-6 L/min error into every value crossing the
        shipped seam, visible against the frozen baseline at the seventh
        significant figure.  Round where a number is displayed, never
        where it is still being computed.
        """
        if composite_id not in self.composites:
            raise KeyError(f"Composite '{composite_id}' not defined in XML")

        comp = self.composites[composite_id]
        weighted = (
            comp.absorption_vector is not None
            and len(comp.absorption_vector) == len(comp.attribute_ids)
        )
        values = []
        kept_weights = []
        for i, attr_id in enumerate(comp.attribute_ids):
            normalised = self.get(attr_id).normalised
            if normalised is None:
                continue
            values.append(float(normalised))
            if weighted:
                kept_weights.append(float(comp.absorption_vector[i]))
        if not values:
            return None
        if weighted:
            # Every surviving weight is zero: the composite declares that
            # the attributes it still has a reading for do not count
            # towards its state, which is not the same news as a state of
            # 0.0.  Saying None keeps the gate that reads this shut and
            # able to say why, instead of opening on a fabricated floor.
            if sum(kept_weights) <= 0.0:
                return None
            return comp.state_value(values, weights=kept_weights)
        return comp.state_value(values)

    def get_all_composite_states(self) -> dict:
        """Get the summary state value for every composite."""
        return {
            comp_id: self.get_composite_state(comp_id)
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
        """
        Add to the computation log, and echo it.

        The echo is wrapped because it has taken the whole process down.
        Windows opens stdout as cp1252, this codebase writes prose, and
        prose here contains arrows and dashes: one `->` written as U+2192
        in a feedback message raised UnicodeEncodeError inside print(),
        which killed the streaming runtime's control task and left the
        socket open and silent. Five frames, then nothing, with no error
        anywhere a reader would look.

        A log line is a side effect. It is never worth more than the run
        it is describing, so a console that cannot spell a character gets
        a replacement character and the model keeps going. The in-memory
        log above is written first and keeps the real text, because that
        is what the snapshot and the warnings list read.
        """
        self._computation_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
        line = f"  {message}"
        try:
            print(line)
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", None) or "ascii"
            print(line.encode(encoding, "replace").decode(encoding, "replace"))


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
