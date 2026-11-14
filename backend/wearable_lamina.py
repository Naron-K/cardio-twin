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
expected to replace them later.  That is also why step_rate is declared but
unused: activity reaches the heart-rate model through AE_rate, and adding a
second path before the first is fitted would be guessing.

A workout's kind reaches the drive through one gain per kind.  The three
indicators and the three gains are SENSORs, so the XML names the categories
and the Python never names a workout type: activity_gain selects the gain the
recording set and passes it to hr_drive, which multiplies the drive by it.
With no workout every indicator is zero and the gain is one, so a minute that
is not a workout is unchanged.

The lamina is no longer lag-free.  HR_model approaches its target with the
heart rate's own first-order lag, and kcal_active_cum accumulates the day's
active energy, so both carry state from one minute to the next.  That state
is committed by the engine once per tick, after every compute_all() pass in
the tick has read the same value; it is never advanced inside a function.

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
refuses a negative AE_rate, a fractional power of which is not a heart rate,
and a non-positive g_activity, which would claim activity does not drive the
heart.  activity_gain refuses an indicator outside [0, 1] and two indicators
at once: a minute cannot be two kinds of workout, and adding their gains
would invent a fourth kind nobody declared.

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
        is_walk, is_strength, is_cardio,           │
        g_walk, g_strength, g_cardio ──▶ g_activity┤
        k_I, AE_rate, p_I, g_activity ──▶ HR_drive ┘
        AE_rate, dt_s, hour_local ──▶ kcal_active_cum

    The forward chain is a straight line in one operating point.  It states
    what the measured heart rate is and what the declared drives expect;
    the gap between them is the outcome, not something this lamina steers.
    HR_model lags its target and kcal_active_cum accumulates the day, so the
    engine commits their state once per tick rather than on every pass.
    """

    def _register_functions(self):
        """Map each XML function id to the method that computes it."""
        self._function_registry["measured_hr"] = self._calc_measured_hr
        self._function_registry["energy_total"] = self._calc_energy_total
        self._function_registry["vo2_estimate"] = self._calc_vo2_estimate
        self._function_registry["hr_circadian"] = self._calc_hr_circadian
        self._function_registry["hr_thermal"] = self._calc_hr_thermal
        self._function_registry["activity_gain"] = self._calc_activity_gain
        self._function_registry["hr_drive"] = self._calc_hr_drive
        self._function_registry["hr_target"] = self._calc_hr_target
        self._function_registry["hr_model"] = self._calc_hr_model
        self._function_registry["hr_residual"] = self._calc_hr_residual
        self._function_registry["kcal_cumulative"] = self._calc_kcal_cumulative

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

    def _calc_activity_gain(self, inputs: list) -> float:
        """
        g_activity = 1 + (g_walk - 1)*is_walk + (g_strength - 1)*is_strength
                       + (g_cardio - 1)*is_cardio   (1)

        Selects this person's gain for the kind of workout the minute is in.
        With no workout all three indicators are zero and the gain is one, so
        a minute that is not a workout is unchanged.  The XML names the
        categories through the indicators, so no workout type appears here.

        Each indicator must be 0 or 1: a value outside [0, 1] is a unit or
        wiring error, not a partial workout.  Two indicators at once are
        refused rather than added — a minute cannot be two kinds of workout,
        and summing their gains would invent a fourth kind nobody declared.
        inputs: [is_walk, is_strength, is_cardio, g_walk, g_strength, g_cardio]
        """
        _arity(inputs, 6,
               "is_walk, is_strength, is_cardio, g_walk, g_strength, g_cardio")
        is_walk, is_strength, is_cardio, g_walk, g_strength, g_cardio = inputs
        _require(is_walk=is_walk, is_strength=is_strength, is_cardio=is_cardio,
                 g_walk=g_walk, g_strength=g_strength, g_cardio=g_cardio)
        indicators = {
            "is_walk": is_walk,
            "is_strength": is_strength,
            "is_cardio": is_cardio,
        }
        for name, value in indicators.items():
            if value < 0.0 or value > 1.0:
                raise ValueError(
                    f"{name}={value} is outside [0, 1]. An indicator is 1 "
                    f"during a minute of that kind of workout and 0 "
                    f"otherwise; a fractional or out-of-range value is a "
                    f"unit or wiring error."
                )
        active = [name for name, value in indicators.items() if value > 0.0]
        if len(active) > 1:
            raise ValueError(
                f"{', '.join(active)} are all set for this minute; a minute "
                f"cannot be two kinds of workout at once. Refusing to add "
                f"gains for a combination the recording never declared."
            )
        return (
            1.0
            + (g_walk - 1.0) * is_walk
            + (g_strength - 1.0) * is_strength
            + (g_cardio - 1.0) * is_cardio
        )

    def _calc_hr_drive(self, inputs: list) -> float:
        """
        HR_drive = k_I * g_activity * AE_rate ** p_I   (bpm)

        Activity energy turned into a heart-rate drive, scaled by the gain for
        this minute's workout kind.  The exponent makes the first minutes of
        activity count for more than later minutes at the same rate.

        A negative AE_rate is refused rather than exponentiated: a
        fractional power of a negative number is not a heart rate, and the
        error would surface as a complex or NaN value further along where
        it is harder to attribute.  A g_activity of zero or less is refused
        too: a gain that small would claim activity does not drive the
        heart, which is the opposite of what the model declares.
        inputs: [k_I, AE_rate, p_I, g_activity]
        """
        _arity(inputs, 4, "k_I, AE_rate, p_I, g_activity")
        gain, ae_rate, exponent, activity_gain = (
            inputs[0], inputs[1], inputs[2], inputs[3]
        )
        _require(k_I=gain, AE_rate=ae_rate, p_I=exponent,
                 g_activity=activity_gain)
        if ae_rate < 0.0:
            raise ValueError(
                f"AE_rate={ae_rate} is negative. A fractional power of a "
                f"negative energy rate is not a heart rate; this is a unit "
                f"or wiring error, and hr_drive must not report a complex "
                f"or NaN drive as though it were a measurement."
            )
        if activity_gain <= 0.0:
            raise ValueError(
                f"g_activity={activity_gain} is not positive. The activity "
                f"gain multiplies the drive and must stay above zero; zero "
                f"or negative would claim activity does not drive the heart."
            )
        return gain * activity_gain * (ae_rate ** exponent)

    def _calc_hr_target(self, inputs: list) -> float:
        """
        HR_target = clamp(HR_level + HR_offset + HR_circ + HR_thermal
                          + HR_drive, 35, HR_max)   (bpm)

        Sums the resting level, its fitted offset and the three declared
        drives, and clamps the result to the physiological floor and the
        personal maximum.  The clamp is the model saying it will not report
        a target outside what a heart can do, not a correction applied
        after the fact.
        inputs: [HR_level, HR_offset, HR_circ, HR_thermal, HR_drive, HR_max]
        """
        _arity(inputs, 6,
               "HR_level, HR_offset, HR_circ, HR_thermal, HR_drive, HR_max")
        level, offset, circadian, thermal, drive, hr_max = inputs
        _require(HR_level=level, HR_offset=offset, HR_circ=circadian,
                 HR_thermal=thermal, HR_drive=drive, HR_max=hr_max)
        total = level + offset + circadian + thermal + drive
        return max(35.0, min(hr_max, total))

    def _calc_hr_model(self, inputs: list) -> float:
        """
        HR_model = prev + (1 - exp(-dt_s / tau)) * (HR_target - prev)   (bpm)

        Approaches the target with the heart rate's own first-order lag:
        tau_on while the target is above the previous value, tau_off while
        it is below.  On the first tick, and after a gap, prev is None and
        the model restarts at HR_target rather than carrying a stale value
        forward.  A tau of zero means no lag at all, so the answer is the
        target itself.

        The state is the engine's: prev is the value committed by end_tick()
        at the end of the previous tick, never a value this function writes.
        Every pass inside one tick therefore sees the same prev.
        inputs: [HR_target, dt_s, tau_on, tau_off, prev]
        """
        _arity(inputs, 5, "HR_target, dt_s, tau_on, tau_off, prev")
        target, dt_s, tau_on, tau_off, prev = (
            inputs[0], inputs[1], inputs[2], inputs[3], inputs[4]
        )
        _require(HR_target=target, dt_s=dt_s, tau_on=tau_on, tau_off=tau_off)
        if prev is not None and not math.isfinite(prev):
            raise ValueError(
                f"HR_model's previous value prev={prev!r} is not a finite "
                f"number. The committed state must be a real heart rate or "
                f"None; a NaN or infinity here would poison every later tick."
            )
        if dt_s <= 0.0:
            raise ValueError(
                f"dt_s={dt_s} is not a positive interval. A lag needs a "
                f"positive elapsed time; zero or negative would divide the "
                f"time constant by nothing meaningful."
            )
        if tau_on < 0.0 or tau_off < 0.0:
            raise ValueError(
                f"tau_on={tau_on} and tau_off={tau_off} must be "
                f"non-negative time constants. A negative tau would run the "
                f"lag backwards, which is a unit or wiring error."
            )
        if prev is None:
            return target
        tau = tau_on if target > prev else tau_off
        if tau == 0.0:
            return target
        return prev + (1.0 - math.exp(-dt_s / tau)) * (target - prev)

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

    def _calc_kcal_cumulative(self, inputs: list) -> float:
        """
        kcal_active_cum = prev + AE_rate * dt_s / 60   (kcal)

        Adds this minute's active energy to the running total.  The first
        minute of a local day — prev None, or hour_local * 3600 < dt_s —
        starts the total rather than adding to yesterday's.

        The state is committed by end_tick() once per tick, so a minute with
        no active-energy record holds the previous total instead of
        inventing energy for a minute nobody recorded.  This function never
        writes that state itself.
        inputs: [AE_rate, dt_s, hour_local, prev]
        """
        _arity(inputs, 4, "AE_rate, dt_s, hour_local, prev")
        ae_rate, dt_s, hour_local, prev = (
            inputs[0], inputs[1], inputs[2], inputs[3]
        )
        _require(AE_rate=ae_rate, dt_s=dt_s, hour_local=hour_local)
        if prev is not None and not math.isfinite(prev):
            raise ValueError(
                f"kcal_active_cum's previous value prev={prev!r} is not a "
                f"finite number. The committed total must be a real energy "
                f"or None; a NaN or infinity here would poison every later "
                f"tick."
            )
        if ae_rate < 0.0:
            raise ValueError(
                f"AE_rate={ae_rate} is negative. Active energy expenditure "
                f"does not run backwards, and subtracting it would make the "
                f"day's total shrink."
            )
        if dt_s <= 0.0:
            raise ValueError(
                f"dt_s={dt_s} is not a positive interval. Energy is a rate "
                f"integrated over time; zero or negative would add a "
                f"meaningless amount."
            )
        increment = ae_rate * dt_s / 60.0
        if prev is None or hour_local * 3600.0 < dt_s:
            return increment
        return prev + increment
