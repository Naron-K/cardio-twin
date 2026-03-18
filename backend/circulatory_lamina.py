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
            "electrical_conduction": self._calc_lambda,
        }

    # ── Step 1: Pressure Regulation ──────────────────────────────────

    def _calc_map(self) -> float:
        """
        MAP = (1/3) * SBP + (2/3) * DBP

        Mean Arterial Pressure: the average driving pressure.
        DBP weighted 2/3 because diastole is ~2× longer than systole.
        """
        sbp = self.attributes["SBP"].value
        dbp = self.attributes["DBP"].value

        if sbp is None or dbp is None:
            raise ValueError("SBP and DBP must be set before computing MAP")

        return (1/3) * sbp + (2/3) * dbp

    # ── Step 2: Vascular Resistance ──────────────────────────────────

    def _calc_resistance(self) -> float:
        """
        R = 8ηL / (πr⁴)

        Poiseuille's Law. The r⁴ term makes this extremely sensitive
        to vessel radius changes:
          - r ↓ 20% → R ↑ 2.44×
          - r ↓ 50% → R ↑ 16×
        """
        eta = self.attributes["eta"].value
        length = self.attributes["L"].value
        radius = self.attributes["r"].value

        if any(v is None for v in [eta, length, radius]):
            raise ValueError("eta, L, r must be set before computing R")
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

    def _calc_stroke_volume(self) -> float:
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
        """
        edv = self.attributes["EDV"].value

        if edv is None:
            raise ValueError("EDV must be set before computing SV")

        effective_edv = min(edv, self.STARLING_LIMIT_EDV)
        return self.STARLING_K * effective_edv

    # ── Step 3b: Cardiac Pump ────────────────────────────────────────

    def _calc_cardiac_output(self) -> float:
        """
        CO = HR × SV / 1000

        Cardiac Output in L/min. HR from Apple Watch (bpm),
        SV from cardiac_filling (mL). Division by 1000 converts mL to L.
        """
        hr = self.attributes["HR"].value
        sv = self.attributes["SV"].value

        if hr is None or sv is None:
            raise ValueError("HR and SV must be available before computing CO")

        return hr * sv / 1000

    # ── Step 4: Hemodynamic Flow ─────────────────────────────────────

    def _calc_flow(self) -> float:
        """
        Q = ΔP / R

        Ohm's Law for hemodynamics. ΔP = MAP (from Step 1),
        R = Vascular Resistance (from Step 2).

        This is the central formula of the lamina.
        Q is the primary Behaviour Outcome.
        """
        delta_p = self.attributes["MAP"].value
        resistance = self.attributes["R"].value

        if delta_p is None or resistance is None:
            raise ValueError("MAP and R must be computed before computing Q")
        if resistance <= 0:
            raise ValueError("Resistance must be positive to compute flow")

        return delta_p / resistance

    # ── Step 5: Electrical Conduction ────────────────────────────────

    def _calc_lambda(self) -> float:
        """
        λ = √(rₘ / (rᵢ + rₑ))

        Cable Theory length constant. Determines how far an electrical
        signal propagates before decaying.

        Links to ECG P-wave analysis:
          - λ high → good conduction → regular HR
          - λ low → abnormal P-wave → arrhythmia risk
        """
        rm = self.attributes["r_m"].value
        ri = self.attributes["r_i"].value
        re = self.attributes["r_e"].value

        if any(v is None for v in [rm, ri, re]):
            raise ValueError("r_m, r_i, r_e must be set before computing lambda")
        if (ri + re) <= 0:
            raise ValueError("Sum of intracellular and extracellular resistance must be positive")

        return math.sqrt(rm / (ri + re))

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
