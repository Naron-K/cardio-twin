"""
Circulatory Lamina - Specific Child Class
==========================================
Inherits from UniversalTwin and registers the actual Python functions
that compute each attribute.

Architecture:
  - UniversalTwin (parent): reads XML, resolves dependencies, gates
  - CirculatoryLamina (child): contains the actual math

When a domain expert adds a new function to the XML, a developer
adds the corresponding method here and registers it.
"""

import math
from universal_twin import UniversalTwin


class CirculatoryLamina(UniversalTwin):
    """
    The Circulatory Lamina of the Cardiac Digital Twin.

    Contains all function models for cardiovascular simulation:
      Step 1:  Pressure Regulation  (MAP = ⅓SBP + ⅔DBP)
      Step 2:  Vascular Resistance  (R = 8ηL / πr⁴)
      Step 3a: Cardiac Filling      (SV ∝ EDV, Frank-Starling)
      Step 3b: Cardiac Pump         (CO = HR × SV)
      Step 4:  Hemodynamic Flow     (Q = ΔP / R)
      Step 5:  Electrical Conduction (λ = √(rₘ / (rᵢ + rₑ)))
      Step 6:  Systemic Resistance  (SVR = (MAP − CVP) / CO)

    Usage:
        twin = CirculatoryLamina("circulatory_lamina.xml")
        twin.set_sensor("SBP", 120)
        twin.set_sensor("DBP", 80)
        twin.set_sensor("HR", 72)
        twin.set_sensor("eta", 3.5)
        twin.set_sensor("L", 20)
        twin.set_sensor("r", 0.4)
        twin.set_sensor("EDV", 120)
        twin.set_sensor("r_m", 5000)
        twin.set_sensor("r_i", 200)
        twin.set_sensor("r_e", 300)
        twin.compute_all()
        print(twin.get("Q").value)  # Blood flow rate
    """

    # Starling constant: proportion of EDV that becomes SV
    # Domain experts can adjust this to model different patient conditions
    STARLING_K = 0.55
    STARLING_LIMIT_EDV = 200  # mL, beyond this SV plateaus

    def _register_functions(self):
        """Register all function implementations mapped to XML function ids."""
        self._function_registry = {
            "pressure_regulation":  self._calc_map,
            "vascular_resistance":  self._calc_resistance,
            "cardiac_filling":      self._calc_stroke_volume,
            "cardiac_pump":         self._calc_cardiac_output,
            "hemodynamic_flow":     self._calc_flow,
            "cardiac_rhythm":       self._calc_cycle_length,
            "systolic_interval":    self._calc_systolic_interval,
            "electrical_conduction": self._calc_lambda,
            "systemic_resistance":  self._calc_svr,
        }

    # ── Step 1: Pressure Regulation ──────────────────────────────────

    def _calc_map(self, inputs: list) -> float:
        """
        MAP = (1/3) * SBP + (2/3) * DBP

        Mean Arterial Pressure: the average driving pressure.
        DBP weighted 2/3 because diastole is ~2× longer than systole.
        inputs: [SBP, DBP]  — order defined in XML <inputs>
        """
        sbp, dbp = inputs[0], inputs[1]

        if sbp is None or dbp is None:
            raise ValueError("inputs[0] (SBP) and inputs[1] (DBP) must be set before computing MAP")

        return (1/3) * sbp + (2/3) * dbp

    # ── Step 2: Vascular Resistance ──────────────────────────────────

    def _calc_resistance(self, inputs: list) -> float:
        """
        R = 8ηL / (πr⁴)

        Poiseuille's Law. The r⁴ term makes this extremely sensitive
        to vessel radius changes:
          - r ↓ 20% → R ↑ 2.44×
          - r ↓ 50% → R ↑ 16×
        inputs: [eta, L, r]  — order defined in XML <inputs>
        """
        eta, length, radius = inputs[0], inputs[1], inputs[2]

        if any(v is None for v in [eta, length, radius]):
            raise ValueError("inputs[0] (eta), inputs[1] (L), inputs[2] (r) must be set before computing R")
        if radius <= 0:
            raise ValueError("Vessel radius must be positive")

        # Raw Poiseuille in CGS units (dyne·s/cm⁵)
        r_cgs = (8 * eta * length) / (math.pi * radius**4)

        # Convert to mmHg·min/L for consistency with MAP (mmHg) → Q in L/min
        # 1 mmHg = 1333.22 dyne/cm², 1 L = 1000 cm³, 1 min = 60 s
        # Conversion factor: 1 dyne·s/cm⁵ = 60/(1333.22 * 1000) mmHg·min/L
        conversion = 60.0 / (1333.22 * 1000)
        return r_cgs * conversion

    # ── Step 3a: Cardiac Filling (Frank-Starling) ────────────────────

    def _calc_stroke_volume(self, inputs: list) -> float:
        """
        SV ∝ EDV (Frank-Starling Law)

        Heart pumps what it receives. Implemented as:
          SV = k × EDV       (when EDV < Starling limit)
          SV = k × limit     (when EDV >= limit, plateau)

        The Starling constant (k) and limit can be adjusted by
        domain experts to model different patient conditions:
          - Normal: k=0.55, limit=200
          - Heart failure: k=0.30, limit=150
          - Athletic heart: k=0.65, limit=220
        inputs: [EDV]  — order defined in XML <inputs>
        """
        edv = inputs[0]

        if edv is None:
            raise ValueError("inputs[0] (EDV) must be set before computing SV")

        effective_edv = min(edv, self.STARLING_LIMIT_EDV)
        return self.STARLING_K * effective_edv

    # ── Step 3b: Cardiac Pump ────────────────────────────────────────

    def _calc_cardiac_output(self, inputs: list) -> float:
        """
        CO = HR × SV / 1000

        Cardiac Output in L/min. HR from Apple Watch (bpm),
        SV from cardiac_filling (mL). Division by 1000 converts mL to L.
        inputs: [HR, SV]  — order defined in XML <inputs>
        """
        hr, sv = inputs[0], inputs[1]

        if hr is None or sv is None:
            raise ValueError("inputs[0] (HR) and inputs[1] (SV) must be available before computing CO")

        return hr * sv / 1000

    # ── Step 3c: Cardiac Rhythm ──────────────────────────────────────

    def _calc_cycle_length(self, inputs: list) -> float:
        """
        T_cycle = 60 / HR   (seconds)

        Arithmetically trivial on purpose.  Its job is architectural: a
        consumer that needs beat timing reads this computed attribute rather
        than reaching for the HR sensor, so the raw stream stays behind the
        model.  When rhythm grows real content — conduction delay, ectopy —
        it grows here and no consumer changes.
        inputs: [HR]
        """
        hr = inputs[0]

        if hr is None:
            raise ValueError("inputs[0] (HR) must be set before computing T_cycle")
        if hr <= 0:
            raise ValueError(f"HR must be positive to derive a cycle length, got {hr}")

        return 60.0 / hr

    # ── Step 3d: Systolic Interval ───────────────────────────────────

    def _calc_systolic_interval(self, inputs: list) -> float:
        """
        T_sys = 0.413 − 0.0017 · HR   (seconds)

        Weissler's regression for left ventricular ejection time.  Ejection
        time falls with rate far more slowly than cycle length does, so
        systole occupies a *larger* fraction of a fast cycle — which is why a
        fixed systolic fraction misrepresents both tachycardia and
        bradycardia.  Population regression, not per-patient.
        inputs: [HR]
        """
        hr = inputs[0]

        if hr is None:
            raise ValueError("inputs[0] (HR) must be set before computing T_sys")

        # The regression goes non-physiological past ~240 bpm; floor it so a
        # slider at the end of its travel cannot produce a negative systole.
        return max(0.05, 0.413 - 0.0017 * hr)

    # ── Step 4: Hemodynamic Flow ─────────────────────────────────────

    def _calc_flow(self, inputs: list) -> float:
        """
        Q = ΔP / R,  with  ΔP = MAP − CVP

        Ohm's Law for hemodynamics. The driving pressure is the
        arterio-venous gradient (MAP minus central venous pressure), not
        MAP alone — flow stops when arterial pressure falls to venous
        pressure, not to zero. MAP comes from Step 1, R from Step 2, and
        CVP from the declared CVP sensor (declared in the XML so a domain
        expert can change it; it replaces what used to be the
        CENTRAL_VENOUS_PRESSURE class constant).

        This is the central formula of the lamina.
        Q is the primary Behaviour Outcome.
        inputs: [MAP, R, CVP]  — order defined in XML <inputs>
        """
        mean_arterial, resistance, cvp = inputs[0], inputs[1], inputs[2]

        if mean_arterial is None or resistance is None or cvp is None:
            raise ValueError(
                "inputs[0] (MAP), inputs[1] (R) and inputs[2] (CVP) must be "
                "computed before computing Q"
            )
        if resistance <= 0:
            raise ValueError("Resistance must be positive to compute flow")

        delta_p = mean_arterial - cvp
        return delta_p / resistance

    # ── Step 5: Electrical Conduction ────────────────────────────────

    def _calc_lambda(self, inputs: list) -> float:
        """
        λ = √(rₘ / (rᵢ + rₑ))

        Cable Theory length constant. Determines how far an electrical
        signal propagates before decaying.

        Links to ECG P-wave analysis:
          - λ high → good conduction → regular HR
          - λ low → abnormal P-wave → arrhythmia risk
        inputs: [r_m, r_i, r_e]  — order defined in XML <inputs>
        """
        rm, ri, re = inputs[0], inputs[1], inputs[2]

        if any(v is None for v in [rm, ri, re]):
            raise ValueError("inputs[0] (r_m), inputs[1] (r_i), inputs[2] (r_e) must be set before computing lambda")
        if (ri + re) <= 0:
            raise ValueError("Sum of intracellular and extracellular resistance must be positive")

        return math.sqrt(rm / (ri + re))

    # ── Step 6: Systemic Vascular Resistance ─────────────────────────

    def _calc_svr(self, inputs: list) -> float:
        """
        SVR = (MAP − CVP) / CO

        Whole-body systemic vascular resistance, derived from what the
        twin already measures: MAP from the SBP/DBP cuff (Step 1), CO
        from the HR/EDV sensors (Step 3b), CVP from the declared CVP
        sensor.  Unlike R (Step 2), a single-segment Poiseuille estimate
        that cannot move with the pump, SVR falls as cardiac output
        rises — high resistance at low output is compensated shock, low
        resistance at high output is exercise.

        Inputs are caller-supplied attribute values, so this refuses a
        wrong input loudly rather than reporting a confident-looking
        resistance: a missing value, a non-finite number, or a cardiac
        output of zero or less all raise ValueError.  Dividing by a
        non-positive CO would report an infinite or a NEGATIVE resistance
        as though it were a measurement.
        inputs: [MAP, CO, CVP]  — order defined in XML <inputs>
        """
        if len(inputs) < 3:
            raise ValueError(
                "inputs must be [MAP, CO, CVP]; got a list of "
                f"length {len(inputs)} — refusing to divide by a missing "
                "cardiac output"
            )

        mean_arterial, cardiac_output, cvp = inputs[0], inputs[1], inputs[2]

        if any(v is None for v in [mean_arterial, cardiac_output, cvp]):
            raise ValueError(
                "inputs[0] (MAP), inputs[1] (CO) and inputs[2] (CVP) must "
                "be set before computing SVR"
            )
        if any(not math.isfinite(v) for v in [mean_arterial, cardiac_output, cvp]):
            raise ValueError(
                "inputs (MAP, CO, CVP) must all be finite numbers to compute "
                f"SVR, got {inputs} — NaN or infinity is not a resistance"
            )
        if cardiac_output <= 0:
            raise ValueError(
                "Cardiac output must be positive to compute SVR; "
                f"got CO = {cardiac_output}, which would report a "
                "resistance that is not a measurement"
            )

        return (mean_arterial - cvp) / cardiac_output

    # ── Convenience Methods ──────────────────────────────────────────

    def set_patient_profile(self, profile: str = "normal"):
        """
        Adjust Starling parameters for different patient conditions.
        Domain experts can call this or modify XML directly.

        Profiles:
          - "normal":        k=0.55, limit=200
          - "heart_failure":  k=0.30, limit=150
          - "athletic":       k=0.65, limit=220
        """
        profiles = {
            "normal":        (0.55, 200),
            "heart_failure": (0.30, 150),
            "athletic":      (0.65, 220),
        }
        if profile in profiles:
            self.STARLING_K, self.STARLING_LIMIT_EDV = profiles[profile]
            self._log(f"PROFILE SET: {profile} (k={self.STARLING_K}, limit={self.STARLING_LIMIT_EDV})")
        else:
            self._log(f"Unknown profile: {profile}. Available: {list(profiles.keys())}")

    def summary(self) -> str:
        """Print a human-readable summary of the current lamina state."""
        lines = [
            f"\n{'='*60}",
            f"  {self.lamina_name} Lamina - Current State",
            f"{'='*60}",
            "",
            "  SENSOR DATA:",
        ]
        for attr_id in self.list_attributes("SENSOR"):
            attr = self.attributes[attr_id]
            val = f"{attr.value:.2f}" if attr.value is not None else "NOT SET"
            norm = f"[{attr.normalised:.3f}]" if attr.normalised is not None else ""
            lines.append(f"    {attr.id:>8}: {val:>10} {attr.unit:<12} {norm}")

        lines.append("")
        lines.append("  PRELIMINARY DATA:")
        for attr_id in self.list_attributes("PRELIMINARY"):
            attr = self.attributes[attr_id]
            val = f"{attr.value:.4f}" if attr.value is not None else "NOT COMPUTED"
            norm = f"[{attr.normalised:.3f}]" if attr.normalised is not None else ""
            lines.append(f"    {attr.id:>8}: {val:>12} {attr.unit:<12} {norm}")

        lines.append("")
        lines.append("  COMPOSITE VECTORS:")
        for comp_id, comp in self.composites.items():
            try:
                vec = self.get_composite_vector(comp_id)
                vec_str = ", ".join(f"{k}={v:.3f}" if v else f"{k}=N/A" for k, v in vec.items())
                lines.append(f"    {comp.name}: [{vec_str}]")
            except Exception:
                lines.append(f"    {comp.name}: [not computed]")

        lines.append(f"\n{'='*60}")
        return "\n".join(lines)
