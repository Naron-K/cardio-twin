"""
Respiratory Lamina - Specific Child Class
=========================================
Inherits from UniversalTwin and registers the actual Python functions
that compute each attribute declared in respiratory_lamina.xml.

Architecture (identical to CirculatoryLamina, which is the point):
  - UniversalTwin (parent): reads XML, resolves dependencies, gates
  - RespiratoryLamina (child): contains the actual math

Functions receive generic positional inputs in the order the XML's <inputs>
list declares, and never see an attribute name.

Scope: steady-state gas exchange at rest, for teaching and for exercising the
universal machinery. No time integration, no ventilation/perfusion
distribution, no shunt fraction, no CO2 dissociation curve. Not a ventilator
management tool, and nothing here is calibrated to an individual patient.

Sources for the relations implemented below:
  - Alveolar ventilation equation and the 0.863 STPD/BTPS constant
  - Alveolar gas equation, with 47 mmHg saturated vapour pressure at 37 C
  - Severinghaus JW, "Simple, accurate equations for human blood O2
    dissociation computations", J Appl Physiol 1979 — the inverse form
  - Hufner's number 1.34 mL O2 per gram of haemoglobin (in vivo)
  - Amato MBP et al, NEJM 2015 — driving pressure in ARDS
"""

import math

from universal_twin import UniversalTwin


class RespiratoryLamina(UniversalTwin):
    """
    The Respiratory Lamina — ventilation, gas exchange, oxygen transport
    and respiratory mechanics as one steady-state chain.

        RR, V_T, V_D ──▶ V_A ──▶ PaCO2 ──▶ PAO2 ──┐
                                                  ├─▶ A_a
        SpO2 ─────────────────────▶ PaO2 ─────────┘
                                     └──▶ CaO2 ──▶ DO2

    Usage:
        twin = RespiratoryLamina("respiratory_lamina.xml")
        twin.set_sensor("RR", 12)
        twin.set_sensor("V_T", 500)
        ...
        twin.compute_all()
        print(twin.get("PaCO2").value)
    """

    # Saturated water vapour pressure at body temperature, mmHg.  Inspired gas
    # is humidified before it reaches the alveolus, so this much of the
    # barometric pressure is unavailable to oxygen.
    WATER_VAPOUR_PRESSURE = 47.0

    # Converts VCO2 in mL/min STPD against alveolar ventilation in L/min BTPS.
    CO2_CONVERSION = 0.863

    # Hufner's number: mL of O2 bound per gram of haemoglobin, in vivo.  The
    # theoretical figure is 1.39; 1.34 is what is measured in whole blood.
    HUFNER = 1.34

    # Oxygen dissolved in plasma, mL per dL per mmHg.  About 1.5% of arterial
    # content at normal tensions, and the only term that keeps rising once
    # haemoglobin is saturated.
    DISSOLVED_O2 = 0.003

    def _register_functions(self):
        """Register all function implementations mapped to XML function ids."""
        self._function_registry = {
            "minute_ventilation":   self._calc_minute_ventilation,
            "alveolar_ventilation": self._calc_alveolar_ventilation,
            "dead_space_fraction":  self._calc_dead_space_fraction,
            "co2_production":       self._calc_co2_production,
            "arterial_co2":         self._calc_arterial_co2,
            "alveolar_gas":         self._calc_alveolar_o2,
            "arterial_o2":          self._calc_arterial_o2,
            "aa_gradient":          self._calc_aa_gradient,
            "oxygenation_index":    self._calc_pf_ratio,
            "oxygen_content":       self._calc_oxygen_content,
            "oxygen_delivery":      self._calc_oxygen_delivery,
            "plateau_pressure":     self._calc_plateau_pressure,
            "driving_pressure":     self._calc_driving_pressure,
        }

    # ── Step 1: ventilation ──────────────────────────────────────────

    def _calc_minute_ventilation(self, inputs: list) -> float:
        """
        V_E = RR * V_T / 1000   (L/min)

        Total gas moved per minute.  Includes dead space, which is why it
        overstates what actually reaches an alveolus.
        inputs: [RR, V_T]
        """
        rr, vt = inputs[0], inputs[1]
        _require(rr=rr, vt=vt)
        return rr * vt / 1000.0

    def _calc_alveolar_ventilation(self, inputs: list) -> float:
        """
        V_A = RR * (V_T - V_D) / 1000   (L/min)

        Only the part of each breath past the dead space reaches gas-exchanging
        alveoli.  This, not V_E, is what sets arterial CO2: rapid shallow
        breathing raises minute ventilation while lowering alveolar
        ventilation, which is the whole reason both attributes exist.

        Floored at a small positive value.  A tidal volume at or below dead
        space means no effective ventilation at all — a real clinical state,
        but one a steady-state model cannot express, since PaCO2 would go to
        infinity rather than to a number.
        inputs: [RR, V_T, V_D]
        """
        rr, vt, vd = inputs[0], inputs[1], inputs[2]
        _require(rr=rr, vt=vt, vd=vd)
        return max(0.05, rr * (vt - vd) / 1000.0)

    def _calc_dead_space_fraction(self, inputs: list) -> float:
        """
        V_D_frac = V_D / V_T

        The wasted fraction of a breath.  Anatomical ratio, not the
        Bohr-Enghoff physiological dead space, which needs mixed expired CO2
        this lamina does not take as input.
        inputs: [V_D, V_T]
        """
        vd, vt = inputs[0], inputs[1]
        _require(vd=vd, vt=vt)
        if vt <= 0:
            raise ValueError("Tidal volume must be positive")
        return vd / vt

    def _calc_co2_production(self, inputs: list) -> float:
        """
        VCO2 = VO2 * R_q   (mL/min STPD)

        The definition of the respiratory quotient, rearranged.
        inputs: [VO2, R_q]
        """
        vo2, rq = inputs[0], inputs[1]
        _require(vo2=vo2, rq=rq)
        return vo2 * rq

    # ── Step 2: arterial CO2 ─────────────────────────────────────────

    def _calc_arterial_co2(self, inputs: list) -> float:
        """
        PaCO2 = 0.863 * VCO2 / V_A   (mmHg)

        The alveolar ventilation equation.  Arterial CO2 is inversely
        proportional to alveolar ventilation — halve V_A and PaCO2 doubles —
        which makes this the single most direct link between how someone is
        breathing and their blood chemistry.

        Assumes arterial and alveolar CO2 are equal.  Good in health; it
        overestimates alveolar CO2 wherever dead space is high.
        inputs: [VCO2, V_A]
        """
        vco2, va = inputs[0], inputs[1]
        _require(vco2=vco2, va=va)
        if va <= 0:
            raise ValueError("Alveolar ventilation must be positive")
        return self.CO2_CONVERSION * vco2 / va

    # ── Step 3: alveolar oxygen ──────────────────────────────────────

    def _calc_alveolar_o2(self, inputs: list) -> float:
        """
        PAO2 = FiO2 * (P_atm - 47) - PaCO2 / R_q   (mmHg)

        The alveolar gas equation.  47 mmHg is the saturated water vapour
        pressure at 37 C, subtracted because inspired gas is humidified before
        it reaches the alveolus.

        The CO2 term is the interesting one: it is why hypoventilation lowers
        alveolar oxygen with no lung disease present at all, and why the
        alveolar-arterial gradient rather than PaO2 alone is what separates a
        failing lung from a failing respiratory drive.
        inputs: [FiO2, P_atm, PaCO2, R_q]
        """
        fio2, patm, paco2, rq = inputs[0], inputs[1], inputs[2], inputs[3]
        _require(fio2=fio2, patm=patm, paco2=paco2, rq=rq)
        if rq <= 0:
            raise ValueError("Respiratory quotient must be positive")
        return fio2 * (patm - self.WATER_VAPOUR_PRESSURE) - paco2 / rq

    # ── Step 4: arterial oxygen ──────────────────────────────────────

    def _calc_arterial_o2(self, inputs: list) -> float:
        """
        Severinghaus's inversion of his own oxyhaemoglobin dissociation curve:

            ln(PaO2) = -0.385 * ln((1/S) - 1) + 3.32 - 1/(72*S) - S^6/6

        with S the saturation as a fraction (J Appl Physiol 1979).  The first
        term is usually printed as `0.385 * ln((1/S) - 1)^-1`, where the -1
        exponent is inside the logarithm's argument, not applied to the
        logarithm; the sign-flipped form above says the same thing without the
        ambiguity.  Checked
        against the textbook curve: S = 0.97 gives 90.5 mmHg, 0.90 gives 58.1,
        0.75 gives 40.2.

        Two limits worth stating rather than burying.  The equation assumes a
        standard curve — normal pH, temperature and 2,3-DPG — so it shifts
        wrong in acidosis, fever or transfused blood.  And above about 97%
        saturation the curve is nearly flat, so a fraction of a percent of
        oximeter error becomes tens of mmHg here; a blood gas measures this
        directly and should be preferred wherever the number matters.
        inputs: [SpO2]  (percent)
        """
        spo2 = inputs[0]
        _require(spo2=spo2)

        # Clamp away from the asymptotes: the log terms are undefined at 0 and
        # at 100% saturation, and the declared range stops short of both.
        s = min(0.999, max(0.001, spo2 / 100.0))

        ln_po2 = (
            -0.385 * math.log(1.0 / s - 1.0)
            + 3.32
            - 1.0 / (72.0 * s)
            - s**6 / 6.0
        )
        return math.exp(ln_po2)

    def _calc_aa_gradient(self, inputs: list) -> float:
        """
        A_a = PAO2 - PaO2   (mmHg)

        Oxygen tension lost between alveolus and artery.  A normal gradient
        with a low PaO2 points at hypoventilation or altitude; a widened one
        points at the lung itself — shunt, V/Q mismatch or a diffusion defect.

        Clamped at zero.  A negative gradient is not physiology, it is the two
        estimates disagreeing: PAO2 comes from the gas equation and PaO2 from
        an oximeter inversion, and on high FiO2 with a well saturated patient
        the arithmetic can cross over.
        inputs: [PAO2, PaO2]
        """
        pao2_alv, pao2_art = inputs[0], inputs[1]
        _require(pao2_alv=pao2_alv, pao2_art=pao2_art)
        return max(0.0, pao2_alv - pao2_art)

    def _calc_pf_ratio(self, inputs: list) -> float:
        """
        PF_ratio = PaO2 / FiO2   (mmHg)

        Oxygenation normalised to inspired oxygen, so a patient on 40% oxygen
        can be compared with one on room air.  The Berlin definition grades
        ARDS at 300, 200 and 100 mmHg, assuming at least 5 cmH2O of PEEP.
        inputs: [PaO2, FiO2]
        """
        pao2, fio2 = inputs[0], inputs[1]
        _require(pao2=pao2, fio2=fio2)
        if fio2 <= 0:
            raise ValueError("Inspired oxygen fraction must be positive")
        return pao2 / fio2

    # ── Step 5: oxygen transport ─────────────────────────────────────

    def _calc_oxygen_content(self, inputs: list) -> float:
        """
        CaO2 = 1.34 * Hb * SpO2/100 + 0.003 * PaO2   (mL/dL)

        Oxygen carried per decilitre of arterial blood.  Overwhelmingly the
        haemoglobin term: the dissolved contribution is roughly 1.5% at normal
        tensions, which is why anaemia starves tissue at a perfect saturation
        and why breathing pure oxygen adds so little to content.
        inputs: [Hb, SpO2, PaO2]
        """
        hb, spo2, pao2 = inputs[0], inputs[1], inputs[2]
        _require(hb=hb, spo2=spo2, pao2=pao2)
        return self.HUFNER * hb * (spo2 / 100.0) + self.DISSOLVED_O2 * pao2

    def _calc_oxygen_delivery(self, inputs: list) -> float:
        """
        DO2 = CaO2 * CO_ref * 10   (mL/min)

        Content times flow; the factor 10 reconciles mL/dL against L/min.
        The endpoint the whole chain exists to serve — and the one attribute
        here that is not respiratory, since it needs a cardiac output this
        lamina does not compute.  CO_ref arrives as an external reading, and
        that is the seam where lamina-to-lamina coupling will attach.
        inputs: [CaO2, CO_ref]
        """
        cao2, co = inputs[0], inputs[1]
        _require(cao2=cao2, co=co)
        return cao2 * co * 10.0

    # ── Step 6: mechanics ────────────────────────────────────────────

    def _calc_plateau_pressure(self, inputs: list) -> float:
        """
        P_plat = V_T / C_rs + PEEP   (cmH2O)

        Compliance rearranged: the pressure a tidal volume requires, on top of
        whatever is already held at end-expiration.  Estimated rather than
        measured, so it ignores airway resistance and intrinsic PEEP — a real
        plateau pressure comes from an inspiratory hold.
        inputs: [V_T, C_rs, PEEP]
        """
        vt, crs, peep = inputs[0], inputs[1], inputs[2]
        _require(vt=vt, crs=crs, peep=peep)
        if crs <= 0:
            raise ValueError("Compliance must be positive")
        return vt / crs + peep

    def _calc_driving_pressure(self, inputs: list) -> float:
        """
        dP = P_plat - PEEP   (cmH2O)

        The pressure swing each breath imposes on the lung — tidal volume
        scaled to the compliance left to receive it.  Associated with
        mortality in ventilated ARDS more strongly than tidal volume or
        plateau pressure alone (Amato 2015).

        Carries a gate and deliberately no behavioural outcome: it is a strong
        association in a specific population, not a set point for a healthy
        resting model to be steered toward.
        inputs: [P_plat, PEEP]
        """
        pplat, peep = inputs[0], inputs[1]
        _require(pplat=pplat, peep=peep)
        return pplat - peep


def _require(**named) -> None:
    """Raise with the offending input's name rather than its index."""
    missing = [name for name, value in named.items() if value is None]
    if missing:
        raise ValueError(
            f"{', '.join(missing)} must be available before computing this attribute"
        )
