"""
Wearable Lamina - Specific Child Class
======================================
Inherits from UniversalTwin and registers the Python functions that compute
each attribute declared in wearable_lamina.xml.

Architecture (identical to the three laminae below it):
  - UniversalTwin (parent): reads XML, resolves dependencies, gates
  - WearableLamina (child): contains the actual math

Functions receive generic positional inputs in the order the XML's <inputs>
list declares, and never see an attribute name.

WHAT THIS LAMINA IS
-------------------
The lowest lamina in the stack: what a wrist-worn device measures, the energy
the day is spending, and a first heart-rate model built from a resting level,
a circadian swing, heat, and activity drive.  What none of those explain is
reported as HR_residual rather than corrected away.

The coefficients are seeded defaults, not fitted values.  They exist so the
structure runs and so a wrong input fails loudly; a fitted params.json is
expected to replace them later.  That is also why step_rate and dt_s are
declared but unused: activity reaches the heart-rate model through AE_rate,
and adding a second path before the first is fitted would be guessing.

NO CORRECTION
-------------
This lamina monitors and corrects nothing — the same decision the metabolic
lamina made.  A residual is an observation about the person or about a term
the model is missing; no quantity this lamina owns can be moved to explain a
measured heart rate.  With no <tags> there is also no <gates> block, because
a gate protects a correction and there is none here to protect.

GUARDS
------
Every function refuses None, NaN and infinity by name.  A wrong input must
fail loudly: a confident-looking heart rate computed from a missing reading
is worse than an attribute the engine can mark stale.  hr_drive additionally
refuses a negative AE_rate, a fractional power of which is not a heart rate.

The input checks are imported from metabolic_lamina rather than redefined:
that module's _require already rejects None, NaN and infinity, and _arity
already names a drifted <inputs> list.  A second copy would be a second place
for the rule to be relaxed.
"""

import math

from metabolic_lamina import _arity, _require
from universal_twin import UniversalTwin


class WearableLamina(UniversalTwin):
    """
    The Wearable Lamina — daily activity, context, and a first heart-rate
    model.

        HR_obs ──▶ HR_measured ─────────────────────────────┐
        AE_rate, BE_rate ──▶ EE_total ──▶ VO2_est           │
                                                            ├─▶ HR_residual
        A_circ, phi_circ, hour_local ──▶ HR_circ ──┐        │
        k_T, T_app, T_ref ──▶ HR_thermal ──────────┼─▶ HR_target ──▶ HR_model
        k_I, AE_rate, p_I ──▶ HR_drive ────────────┘

    The whole chain is a straight line in one operating point.  It states
    what the measured heart rate is and what the declared drives expect;
    the gap between them is the outcome, not something this lamina steers.
    """

    def _register_functions(self):
        """Map each XML function id to the method that computes it."""
        self._function_registry["measured_hr"] = self._calc_measured_hr
        self._function_registry["energy_total"] = self._calc_energy_total
        self._function_registry["vo2_estimate"] = self._calc_vo2_estimate
        self._function_registry["hr_circadian"] = self._calc_hr_circadian
        self._function_registry["hr_thermal"] = self._calc_hr_thermal
        self._function_registry["hr_drive"] = self._calc_hr_drive
        self._function_registry["hr_target"] = self._calc_hr_target
        self._function_registry["hr_model"] = self._calc_hr_model
        self._function_registry["hr_residual"] = self._calc_hr_residual

    # ── The chain ────────────────────────────────────────────────────

    def _calc_measured_hr(self, inputs: list) -> float:
        """
        HR_measured = HR_obs   (bpm)

        Carries the one direct measurement into the chain.  A missing or
        non-finite reading is refused rather than passed along, so the
        engine marks HR_measured stale and nothing downstream mistakes an
        absent measurement for a value.
        inputs: [HR_obs]
        """
        _arity(inputs, 1, "HR_obs")
        hr_obs = inputs[0]
        _require(HR_obs=hr_obs)
        return hr_obs

    def _calc_energy_total(self, inputs: list) -> float:
        """
        EE_total = AE_rate + BE_rate   (kcal/min)

        Activity energy plus basal energy.  The simplest defensible total:
        the thermic effect of food and exercise efficiency are corrections
        to fit later, not structure to invent here.

        Negative rates are refused rather than summed.  Energy expenditure
        does not run backwards, and a negative rate here would quietly
        reduce the oxygen estimate as though the day were un-spending.
        inputs: [AE_rate, BE_rate]
        """
        _arity(inputs, 2, "AE_rate, BE_rate")
        ae_rate, be_rate = inputs[0], inputs[1]
        _require(AE_rate=ae_rate, BE_rate=be_rate)
        if ae_rate < 0.0:
            raise ValueError(
                f"AE_rate={ae_rate} is negative. Active energy expenditure "
                f"does not run backwards; this is a unit or wiring error, "
                f"and summing it would make the day's total shrink."
            )
        if be_rate < 0.0:
            raise ValueError(
                f"BE_rate={be_rate} is negative. Basal energy expenditure "
                f"does not run backwards; this is a unit or wiring error."
            )
        return ae_rate + be_rate

    def _calc_vo2_estimate(self, inputs: list) -> float:
        """
        VO2_est = EE_total / 4.86 * 1000   (mL/min)

        4.86 kcal per litre of oxygen is an approximation: the accepted
        range is 4.69 to 5.05 depending on substrate.  It is kept here as
        the single stand-in for that spread, and the estimate is named for
        what it is.

        A negative total is refused for the same reason energy_total
        refuses a negative rate: oxygen consumption cannot be negative.
        inputs: [EE_total]
        """
        _arity(inputs, 1, "EE_total")
        ee_total = inputs[0]
        _require(EE_total=ee_total)
        if ee_total < 0.0:
            raise ValueError(
                f"EE_total={ee_total} is negative. A negative energy rate "
                f"would estimate oxygen consumption backwards; this is a "
                f"unit or wiring error."
            )
        return ee_total / 4.86 * 1000.0

    def _calc_hr_circadian(self, inputs: list) -> float:
        """
        HR_circ = A_circ * cos(2*pi*(hour_local - phi_circ)/24)   (bpm)

        One cosine around the 24-hour clock, peaking at the personal peak
        hour.  It is allowed to be negative: half a day from the peak is a
        genuine trough, not the absence of a rhythm.
        inputs: [A_circ, phi_circ, hour_local]
        """
        _arity(inputs, 3, "A_circ, phi_circ, hour_local")
        amplitude, peak_hour, hour_local = inputs[0], inputs[1], inputs[2]
        _require(A_circ=amplitude, phi_circ=peak_hour, hour_local=hour_local)
        return amplitude * math.cos(
            2.0 * math.pi * (hour_local - peak_hour) / 24.0
        )

    def _calc_hr_thermal(self, inputs: list) -> float:
        """
        HR_thermal = k_T * max(0, T_app - T_ref)   (bpm)

        Heat adds heart rate above the reference temperature and adds
        nothing below it.  The floor is deliberate: this model knows that
        heat raises heart rate and does not claim a cooling effect it has
        not declared.
        inputs: [k_T, T_app, T_ref]
        """
        _arity(inputs, 3, "k_T, T_app, T_ref")
        gain, t_app, t_ref = inputs[0], inputs[1], inputs[2]
        _require(k_T=gain, T_app=t_app, T_ref=t_ref)
        return gain * max(0.0, t_app - t_ref)

    def _calc_hr_drive(self, inputs: list) -> float:
        """
        HR_drive = k_I * AE_rate ** p_I   (bpm)

        Activity energy turned into a heart-rate drive.  The exponent makes
        the first minutes of activity count for more than later minutes at
        the same rate.

        A negative AE_rate is refused rather than exponentiated: a
        fractional power of a negative number is not a heart rate, and the
        error would surface as a complex or NaN value further along where
        it is harder to attribute.
        inputs: [k_I, AE_rate, p_I]
        """
        _arity(inputs, 3, "k_I, AE_rate, p_I")
        gain, ae_rate, exponent = inputs[0], inputs[1], inputs[2]
        _require(k_I=gain, AE_rate=ae_rate, p_I=exponent)
        if ae_rate < 0.0:
            raise ValueError(
                f"AE_rate={ae_rate} is negative. A fractional power of a "
                f"negative energy rate is not a heart rate; this is a unit "
                f"or wiring error, and hr_drive must not report a complex "
                f"or NaN drive as though it were a measurement."
            )
        return gain * (ae_rate ** exponent)

    def _calc_hr_target(self, inputs: list) -> float:
        """
        HR_target = clamp(HR_level + HR_circ + HR_thermal + HR_drive,
                          35, HR_max)   (bpm)

        Sums the four declared drives and clamps the result to the
        physiological floor and the personal maximum.  The clamp is the
        model saying it will not report a target outside what a heart can
        do, not a correction applied after the fact.
        inputs: [HR_level, HR_circ, HR_thermal, HR_drive, HR_max]
        """
        _arity(inputs, 5,
               "HR_level, HR_circ, HR_thermal, HR_drive, HR_max")
        level, circadian, thermal, drive, hr_max = (
            inputs[0], inputs[1], inputs[2], inputs[3], inputs[4]
        )
        _require(HR_level=level, HR_circ=circadian, HR_thermal=thermal,
                 HR_drive=drive, HR_max=hr_max)
        total = level + circadian + thermal + drive
        return max(35.0, min(hr_max, total))

    def _calc_hr_model(self, inputs: list) -> float:
        """
        HR_model = HR_target   (bpm)

        Reports the target as the model's heart rate.  The time lag is
        added in a later phase; until then the model has no lag, which the
        XML and this docstring both say rather than leaving a reader to
        assume a lag that is not there.
        inputs: [HR_target]
        """
        _arity(inputs, 1, "HR_target")
        target = inputs[0]
        _require(HR_target=target)
        return target

    def _calc_hr_residual(self, inputs: list) -> float:
        """
        HR_residual = HR_measured - HR_model   (bpm)

        The measured value minus the modelled value, and the outcome this
        lamina reports.  Zero means the declared drives explained the
        minute; a non-zero residual is the part of the day they did not
        account for.  It is reported, never used to steer a correction:
        this lamina monitors and corrects nothing.
        inputs: [HR_measured, HR_model]
        """
        _arity(inputs, 2, "HR_measured, HR_model")
        measured, model = inputs[0], inputs[1]
        _require(HR_measured=measured, HR_model=model)
        return measured - model
