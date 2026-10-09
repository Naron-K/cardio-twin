"""
Metabolic Lamina - Specific Child Class
=======================================
Inherits from UniversalTwin and registers the Python functions that compute
each attribute declared in metabolic_lamina.xml.

Architecture (identical to CirculatoryLamina and RespiratoryLamina, which is
the point):
  - UniversalTwin (parent): reads XML, resolves dependencies, gates
  - MetabolicLamina (child): contains the actual math

Functions receive generic positional inputs in the order the XML's <inputs>
list declares, and never see an attribute name.

WHY THIS LAMINA EXISTS, beyond the physiology
---------------------------------------------
It is the first receiving end of a channel that carries error BACK.  The
tissue is the one place in this body that cannot fix its own problem: it
has no pump and no lung, so when oxygen supply falls short every available
correction lives one lamina down.  That is exactly the case a return path
is for, and until this lamina existed the backward pass had nowhere on a
real body to run.

WHAT ARRIVES, AND WHAT IT IS NOT
--------------------------------
`supply_index` is a composite STATE VALUE — the single normalised number
respiration's four-attribute `transport_state` face weighs itself into.
It is an INDEX in [0,1], not oxygen delivery in mL/min, and the XML says so
at length.  Measured on the shipped feed: that face sits at 0.6663 while
respiration's own DO2 reads 988 mL/min, so treating the index as a delivery
would overstate it by 74%.  This lamina turns the index into a consumption
ceiling using its OWN declared `VO2_capacity`, which is the right place for
that conversion — how much oxygen a tissue could use is a fact about the
tissue, not about the lung.

Scope: a steady-state supply/demand model at one operating point, for
teaching and for exercising the universal machinery.  No regional
distribution, no oxygen debt repayment over time, no lactate clearance
kinetics, no acid-base coupling.  Not a clinical tool, and none of it is
calibrated to an individual patient.

Sources for the relations implemented below:
  - The biphasic DO2/VO2 relationship: consumption is supply-INDEPENDENT
    above a critical delivery threshold and supply-DEPENDENT below it
    (Cain SM, "Oxygen delivery and uptake in dogs during anemic and hypoxic
    hypoxia", J Appl Physiol 1977)
  - Oxygen extraction ratio as VO2/DO2, normally about 0.25 at rest and
    rising to roughly 0.6-0.7 before consumption becomes supply-limited
  - Lactate as the marker of anaerobic metabolism once consumption can no
    longer meet demand (Vincent JL & De Backer D, "Circulatory shock",
    NEJM 2013)
"""

import math

from universal_twin import UniversalTwin


def _require(**named) -> None:
    """
    Raise with the offending input's NAME rather than its index.

    Defined here rather than imported from a sibling lamina on purpose: a
    lamina has to keep working when it is run on its own, and reaching into
    respiratory_lamina for a helper would make this file unloadable without
    one it has nothing else to do with.  circulatory_lamina.py validates
    inline for the same reason.

    Stricter than the respiratory copy in one way that matters here: it
    rejects NaN and infinity as well as None.  Every number in this chain
    is either divided by or multiplied into a ratio, and an infinity that
    survives to `lactate` would arrive at the outcome as a confident
    reading rather than as an error.
    """
    missing = [name for name, value in named.items() if value is None]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} must be available before computing "
            f"this attribute"
        )
    unusable = [
        f"{name}={value!r}" for name, value in named.items()
        if not math.isfinite(value)
    ]
    if unusable:
        raise ValueError(
            f"{', '.join(unusable)} is not a finite number; refusing to "
            f"compute a metabolic quantity from it"
        )


def _arity(inputs: list, expected: int, order: str) -> None:
    """A short input list is a wiring error, and silence would hide it."""
    if len(inputs) < expected:
        raise ValueError(
            f"expected {expected} inputs in the order [{order}], got a list "
            f"of length {len(inputs)} — the XML <inputs> and this function "
            f"have drifted apart"
        )


class MetabolicLamina(UniversalTwin):
    """
    The Metabolic Lamina — tissue oxygen supply, demand and the lactate
    that appears when the two stop matching.

        supply_index ──▶ ceiling ──┐
                                   ├─▶ VO2 ──▶ O2_deficit ──▶ lactate
        VO2_demand ────────────────┘     │
                                         └─▶ O2_utilisation

    The whole point of the chain is its ELBOW.  Above the critical supply
    the tissue consumes exactly what it demands and lactate stays at
    baseline; below it consumption is capped by what arrives, the shortfall
    is anaerobic, and lactate rises.  A model without that elbow would let
    oxygen delivery fall to zero while reporting a healthy tissue.
    """

    def _register_functions(self):
        """Map each XML function id to the method that computes it."""
        self._function_registry["o2_consumption"] = self._calc_vo2
        self._function_registry["supply_utilisation"] = self._calc_utilisation
        self._function_registry["oxygen_deficit"] = self._calc_deficit
        self._function_registry["lactate_production"] = self._calc_lactate

    # ── The chain ────────────────────────────────────────────────────

    def _calc_vo2(self, inputs: list) -> float:
        """
        VO2 = min(VO2_demand, supply_index * VO2_capacity)   (mL/min)

        The biphasic relationship in one line.  `supply_index *
        VO2_capacity` is the ceiling: the most this tissue could consume
        given what has arrived.  Below that ceiling consumption is set by
        DEMAND and is independent of supply, which is why a healthy person
        does not consume more oxygen by breathing harder.  At the ceiling
        it becomes supply-dependent, and the difference is what the rest of
        this chain measures.

        A negative demand is refused rather than clamped: it is not a
        tissue consuming backwards, it is a wiring or unit error, and
        min() would quietly return it as the answer.
        inputs: [VO2_demand, supply_index, VO2_capacity]
        """
        _arity(inputs, 3, "VO2_demand, supply_index, VO2_capacity")
        demand, index, capacity = inputs[0], inputs[1], inputs[2]
        _require(VO2_demand=demand, supply_index=index,
                 VO2_capacity=capacity)
        if demand < 0.0:
            raise ValueError(
                f"VO2_demand={demand} is negative. A tissue does not consume "
                f"oxygen backwards; this is a unit or wiring error, and "
                f"min() would return it as though it were a reading."
            )
        if capacity <= 0.0:
            raise ValueError(
                f"VO2_capacity={capacity} is zero or less. A tissue that "
                f"could consume nothing at full supply has no supply "
                f"relationship to model."
            )
        return min(demand, index * capacity)

    def _calc_utilisation(self, inputs: list) -> float:
        """
        O2_utilisation = VO2 / (supply_index * VO2_capacity)

        What fraction of the CONSUMABLE oxygen is being used — so it
        reaches exactly 1.0 at the elbow, by construction.

        Deliberately not called the oxygen extraction ratio.  A true O2ER
        is VO2 over oxygen DELIVERED, and this lamina never receives a
        delivery in mL/min — only an index.  Putting a familiar clinical
        label on a different quantity is the mistake `Q` carries in the
        circulatory lamina, and it cost this project real effort to undo.

        The denominator is the same ceiling, recomputed rather than passed
        in, so the two can never disagree about what was on offer.  A
        ceiling of zero or less is refused rather than divided by: an
        extraction ratio of infinity is not a measurement, and reporting it
        would send a confident number to an outcome.
        inputs: [VO2, supply_index, VO2_capacity]
        """
        _arity(inputs, 3, "VO2, supply_index, VO2_capacity")
        vo2, index, capacity = inputs[0], inputs[1], inputs[2]
        _require(VO2=vo2, supply_index=index, VO2_capacity=capacity)
        available = index * capacity
        if available <= 0.0:
            raise ValueError(
                f"supply_index * VO2_capacity = {available} is zero or less, "
                f"so no oxygen is on offer and a utilisation FRACTION is "
                f"undefined. Refusing rather than reporting an infinite or "
                f"negative fraction as a reading."
            )
        return vo2 / available

    def _calc_deficit(self, inputs: list) -> float:
        """
        O2_deficit = max(0, VO2_demand - VO2)   (mL/min)

        The shortfall, and the only quantity in this lamina that is zero
        when everything is fine.  Floored at zero because a tissue getting
        more than it asked for has no surplus to bank — consumption is
        already capped at demand upstream, so a negative value here could
        only mean the two inputs came from different cycles.
        inputs: [VO2_demand, VO2]
        """
        _arity(inputs, 2, "VO2_demand, VO2")
        demand, vo2 = inputs[0], inputs[1]
        _require(VO2_demand=demand, VO2=vo2)
        return max(0.0, demand - vo2)

    def _calc_lactate(self, inputs: list) -> float:
        """
        lactate = lactate_base + lactate_k * O2_deficit   (mmol/L)

        A deliberately linear stand-in for anaerobic metabolism: no
        clearance, no time constant, no acid-base coupling.  What it gets
        right is the only thing this body needs from it — lactate sits at
        baseline while supply meets demand and rises once it does not, so
        it is an outcome that goes out of band for a reason no correction
        inside THIS lamina could fix.

        That is the point of putting it here.  The tissue has no pump and
        no lung; every available correction lives one lamina down, which is
        what the channel's return path is for.

        `lactate_k` is declared in the XML rather than written here,
        following the CVP lesson: a coefficient buried in Python is one a
        domain expert can neither see nor change.
        inputs: [lactate_base, lactate_k, O2_deficit]
        """
        _arity(inputs, 3, "lactate_base, lactate_k, O2_deficit")
        base, k, deficit = inputs[0], inputs[1], inputs[2]
        _require(lactate_base=base, lactate_k=k, O2_deficit=deficit)
        if k < 0.0:
            raise ValueError(
                f"lactate_k={k} is negative, which would make lactate FALL "
                f"as the oxygen deficit grows — the sign of the whole "
                f"relationship inverted, and a shocked tissue reported as "
                f"improving."
            )
        if deficit < 0.0:
            raise ValueError(
                f"O2_deficit={deficit} is negative. The deficit is floored "
                f"at zero where it is computed, so a negative one here means "
                f"it did not come from there."
            )
        return base + k * deficit
