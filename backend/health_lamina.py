"""
Health Lamina - Specific Child Class
====================================
Inherits from UniversalTwin and registers the Python functions that compute
each attribute declared in health_lamina.xml.

Architecture (identical to the wearable lamina):
  - UniversalTwin (parent): reads XML, resolves dependencies, gates
  - HealthLamina (child): contains the actual math

Functions receive generic positional inputs in the order the XML's <inputs>
list declares, and never see an attribute name.

EVERY MODEL HERE IS A PLACEHOLDER
---------------------------------
The coefficients are invented.  They are not a published equation and must
not be read as one.  They exist so the frame runs end to end, so a missing
entry fails loudly, and so an expert can replace them without touching the
frame.

Replacing one means rewriting one method here and its <formula> in
health_lamina.xml.  Nothing else in this file needs to move.

WHAT THIS LAMINA IS
-------------------
It takes what a person enters about themselves, the weekly activity dose from
the Daily Activity lamina, and reports a risk of disease now and with a plan,
plus screening flags.  Risk values are returned in percent.

NO CORRECTION, NO GATES, NO TAGS
--------------------------------
This lamina reads and reports.  It does not move an entered figure or an
activity dose to explain an outcome.

GUARDS
------
Every function refuses None, NaN and infinity by name, through the _require
helper imported from metabolic_lamina; a short input list is refused through
_arity for the same reason.  Beyond that:

  - every logarithm argument must be positive;
  - height and body mass must be positive;
  - every yes/no answer must be exactly 0 or 1;
  - cvd_S0 must lie strictly between 0 and 1;
  - act_scale must be positive and act_max must lie in [0, 1);
  - a weekly activity dose must be non-negative;
  - risk_now must lie in [0, 100] and every relative risk must be positive;
  - dose_jump_ratio must be at least 1;
  - a flag threshold must be positive.

A result is never silently clipped: a risk outside [0, 100] raises, and so
does a relative risk outside (0, 1].  A wrong input must fail loudly rather
than produce a confident-looking answer.
"""

import math

from metabolic_lamina import _arity, _require
from universal_twin import UniversalTwin


def _binary(name: str, value: float) -> None:
    """Refuse a yes/no answer that is not exactly 0 or 1, naming it."""
    if value != 0.0 and value != 1.0:
        raise ValueError(
            f"{name}={value} must be exactly 0 or 1. This input is a yes/no "
            f"answer: 1 for yes, 0 for no. A fractional or out-of-range "
            f"value is a unit or entry error, not a partial answer."
        )


def _positive_log_argument(name: str, value: float) -> None:
    """Refuse a non-positive value that is about to enter a logarithm."""
    if value <= 0.0:
        raise ValueError(
            f"{name}={value} must be greater than zero. It enters a "
            f"logarithm, and logarithms of zero or negative numbers are not "
            f"a risk score; this is a unit or entry error."
        )


def _risk_percent(name: str, value: float) -> float:
    """Return a risk in percent only if it lies in [0, 100]."""
    if not math.isfinite(value) or value < 0.0 or value > 100.0:
        raise ValueError(
            f"{name}={value} is outside [0, 100] percent. A risk outside "
            f"that range is not a probability; refusing to report it rather "
            f"than clipping it into a confident-looking answer."
        )
    return value


class HealthLamina(UniversalTwin):
    """
    The Health Lamina — entered test results and history, an activity dose,
    placeholder disease-risk models and screening flags.

        mass_kg, height_cm ──▶ BMI ───────────────────┐
        age, sbp, lipids, smoking, ... ──▶ cvd_lp ──▶ cvd_risk_now ──┐
        age, BMI, glucose, family, ... ──▶ dm_lp ──▶ dm_risk_now ───┤
        dose, act_max, act_scale ──▶ cvd_rr / dm_rr ────────────────┼─▶ plan risk
        sbp, dbp, thresholds ──▶ flag_bp                             │
        dose_planned, dose_current, ratio ──▶ flag_dose_jump         │
        hr_medicine ──▶ flag_medicine                                │

    The chain is a weighted sum turned into a probability, and a curve of
    relative risk against weekly activity.  Every coefficient is invented.
    """

    def _register_functions(self):
        """Map each XML function id to the method that computes it."""
        self._function_registry["body_mass_index"] = (
            self._calc_body_mass_index
        )
        self._function_registry["cvd_score"] = self._calc_cvd_score
        self._function_registry["cvd_risk_now"] = self._calc_cvd_risk_now
        self._function_registry["dm_score"] = self._calc_dm_score
        self._function_registry["dm_risk_now"] = self._calc_dm_risk_now
        self._function_registry["cvd_rr_current"] = (
            self._calc_activity_relative_risk
        )
        self._function_registry["cvd_rr_planned"] = (
            self._calc_activity_relative_risk
        )
        self._function_registry["dm_rr_current"] = (
            self._calc_activity_relative_risk
        )
        self._function_registry["dm_rr_planned"] = (
            self._calc_activity_relative_risk
        )
        self._function_registry["cvd_risk_plan"] = self._calc_risk_at_ratio
        self._function_registry["dm_risk_plan"] = self._calc_risk_at_ratio
        self._function_registry["flag_bp"] = self._calc_flag_bp
        self._function_registry["flag_dose_jump"] = self._calc_flag_dose_jump
        self._function_registry["flag_medicine"] = self._calc_flag_medicine

    # ── The chain ────────────────────────────────────────────────────

    def _calc_body_mass_index(self, inputs: list) -> float:
        """
        BMI = mass_kg / (height_cm / 100)^2   (kg/m2)

        Body mass divided by the square of height in metres.  This is the
        standard definition, not a placeholder model.

        Height and body mass must be positive: a height of zero divides by
        zero, and a negative height or mass is a unit or entry error rather
        than a body mass index.
        inputs: [mass_kg, height_cm]
        """
        _arity(inputs, 2, "mass_kg, height_cm")
        mass_kg, height_cm = inputs[0], inputs[1]
        _require(mass_kg=mass_kg, height_cm=height_cm)
        if height_cm <= 0.0:
            raise ValueError(
                f"height_cm={height_cm} must be greater than zero. Height is "
                f"squared in the denominator of body mass index; zero would "
                f"divide by zero and a negative value is a unit or entry "
                f"error, not a body."
            )
        if mass_kg <= 0.0:
            raise ValueError(
                f"mass_kg={mass_kg} must be greater than zero. A body mass "
                f"of zero or less is a unit or entry error, not a person."
            )
        return mass_kg / (height_cm / 100.0) ** 2

    def _calc_cvd_score(self, inputs: list) -> float:
        """
        cvd_lp = c_age*ln(age) + c_sbp*ln(sbp) + c_tc*ln(chol_total)
                 + c_hdl*ln(chol_hdl) + c_smoker*smoker
                 + c_diabetes*diabetes + c_treated*bp_treated
                 + c_male*sex_male   (1)

        A weighted sum of the entered figures, in the shape of a survival
        model's risk equation.  PLACEHOLDER: the weights are invented.

        Age, systolic pressure, total cholesterol and HDL cholesterol enter
        logarithms and must be positive.  The listed history answers are
        yes/no and must be exactly 0 or 1.
        inputs: [age, sbp, chol_total, chol_hdl, smoker, diabetes,
                 bp_treated, sex_male, c_age, c_sbp, c_tc, c_hdl,
                 c_smoker, c_diabetes, c_treated, c_male]
        """
        _arity(
            inputs, 16,
            "age, sbp, chol_total, chol_hdl, smoker, diabetes, bp_treated, "
            "sex_male, c_age, c_sbp, c_tc, c_hdl, c_smoker, c_diabetes, "
            "c_treated, c_male",
        )
        (age, sbp, chol_total, chol_hdl, smoker, diabetes, bp_treated,
         sex_male, c_age, c_sbp, c_tc, c_hdl, c_smoker, c_diabetes,
         c_treated, c_male) = inputs[:16]
        _require(
            age=age, sbp=sbp, chol_total=chol_total, chol_hdl=chol_hdl,
            smoker=smoker, diabetes=diabetes, bp_treated=bp_treated,
            sex_male=sex_male, c_age=c_age, c_sbp=c_sbp, c_tc=c_tc,
            c_hdl=c_hdl, c_smoker=c_smoker, c_diabetes=c_diabetes,
            c_treated=c_treated, c_male=c_male,
        )
        _positive_log_argument("age", age)
        _positive_log_argument("sbp", sbp)
        _positive_log_argument("chol_total", chol_total)
        _positive_log_argument("chol_hdl", chol_hdl)
        _binary("smoker", smoker)
        _binary("diabetes", diabetes)
        _binary("bp_treated", bp_treated)
        _binary("sex_male", sex_male)
        return (
            c_age * math.log(age)
            + c_sbp * math.log(sbp)
            + c_tc * math.log(chol_total)
            + c_hdl * math.log(chol_hdl)
            + c_smoker * smoker
            + c_diabetes * diabetes
            + c_treated * bp_treated
            + c_male * sex_male
        )

    def _calc_cvd_risk_now(self, inputs: list) -> float:
        """
        cvd_risk_now = 100 * (1 - cvd_S0 ^ exp(cvd_lp - cvd_lp_ref))   (%)

        Turns the cardiovascular score into a chance over the period.  The
        survival form is the usual one; cvd_S0 and cvd_lp_ref are invented.

        cvd_S0 must lie strictly between 0 and 1: it is a survival share, so
        zero or one would make the model claim certainty for everyone.  The
        result is a percentage and is refused outside [0, 100] rather than
        clipped.
        inputs: [cvd_lp, cvd_S0, cvd_lp_ref]
        """
        _arity(inputs, 3, "cvd_lp, cvd_S0, cvd_lp_ref")
        cvd_lp, cvd_s0, cvd_lp_ref = inputs[0], inputs[1], inputs[2]
        _require(cvd_lp=cvd_lp, cvd_S0=cvd_s0, cvd_lp_ref=cvd_lp_ref)
        if not 0.0 < cvd_s0 < 1.0:
            raise ValueError(
                f"cvd_S0={cvd_s0} must be strictly between 0 and 1. It is "
                f"the share of reference people free of cardiovascular "
                f"disease; zero or one would claim certainty for everyone."
            )
        try:
            exponent = math.exp(cvd_lp - cvd_lp_ref)
        except OverflowError as exc:
            raise ValueError(
                f"cvd_lp - cvd_lp_ref = {cvd_lp - cvd_lp_ref} overflows when "
                f"exponentiated. That score is outside any plausible range; "
                f"refusing to report a confident-looking risk from it."
            ) from exc
        risk = 100.0 * (1.0 - cvd_s0 ** exponent)
        return _risk_percent("cvd_risk_now", risk)

    def _calc_dm_score(self, inputs: list) -> float:
        """
        dm_lp = d_0 + d_age*age + d_bmi*BMI + d_glucose*glucose_fasting
                + d_family*family_diabetes + d_treated*bp_treated   (1)

        A weighted sum of the entered figures in the shape of a logistic
        risk score.  PLACEHOLDER: every coefficient is invented.

        Age, BMI and fasting glucose must be positive, and the family-history
        and blood-pressure-medicine answers must be exactly 0 or 1.
        inputs: [age, BMI, glucose_fasting, family_diabetes, bp_treated,
                 d_0, d_age, d_bmi, d_glucose, d_family, d_treated]
        """
        _arity(
            inputs, 11,
            "age, BMI, glucose_fasting, family_diabetes, bp_treated, d_0, "
            "d_age, d_bmi, d_glucose, d_family, d_treated",
        )
        (age, bmi, glucose_fasting, family_diabetes, bp_treated, d_0, d_age,
         d_bmi, d_glucose, d_family, d_treated) = inputs[:11]
        _require(
            age=age, BMI=bmi, glucose_fasting=glucose_fasting,
            family_diabetes=family_diabetes, bp_treated=bp_treated,
            d_0=d_0, d_age=d_age, d_bmi=d_bmi, d_glucose=d_glucose,
            d_family=d_family, d_treated=d_treated,
        )
        if age <= 0.0:
            raise ValueError(
                f"age={age} must be greater than zero. A zero or negative "
                f"age is an entry error, not a person."
            )
        if bmi <= 0.0:
            raise ValueError(
                f"BMI={bmi} must be greater than zero. A zero or negative "
                f"body mass index is an entry or unit error."
            )
        if glucose_fasting <= 0.0:
            raise ValueError(
                f"glucose_fasting={glucose_fasting} must be greater than "
                f"zero. Fasting glucose cannot be zero or negative; this is "
                f"a unit or entry error."
            )
        _binary("family_diabetes", family_diabetes)
        _binary("bp_treated", bp_treated)
        return (
            d_0
            + d_age * age
            + d_bmi * bmi
            + d_glucose * glucose_fasting
            + d_family * family_diabetes
            + d_treated * bp_treated
        )

    def _calc_dm_risk_now(self, inputs: list) -> float:
        """
        dm_risk_now = 100 / (1 + exp(-dm_lp))   (%)

        Turns the diabetes score into a chance over the period with the
        logistic form.  The result is a percentage and is refused outside
        [0, 100] rather than clipped.
        inputs: [dm_lp]
        """
        _arity(inputs, 1, "dm_lp")
        dm_lp = inputs[0]
        _require(dm_lp=dm_lp)
        try:
            risk = 100.0 / (1.0 + math.exp(-dm_lp))
        except OverflowError as exc:
            raise ValueError(
                f"dm_lp={dm_lp} is so negative that exp(-dm_lp) overflows. "
                f"That score is outside any plausible range; refusing to "
                f"report a confident-looking risk from it."
            ) from exc
        return _risk_percent("dm_risk_now", risk)

    def _calc_activity_relative_risk(self, inputs: list) -> float:
        """
        rr = 1 - act_max * (1 - exp(-dose / act_scale))   (1)

        Relative risk against no activity.  It falls quickly with the first
        hours of weekly activity and flattens.  PLACEHOLDER: the invented
        curve has the saturating shape dose-response studies report, but is
        not a published curve.

        The dose must be non-negative, act_max must lie in [0, 1) because it
        is the share by which risk can fall, and act_scale must be positive
        because it is a divisor.  The result is a relative risk and is
        refused outside (0, 1] rather than clipped.
        inputs: [dose, act_max, act_scale]
        """
        _arity(inputs, 3, "dose, act_max, act_scale")
        dose, act_max, act_scale = inputs[0], inputs[1], inputs[2]
        _require(dose=dose, act_max=act_max, act_scale=act_scale)
        if dose < 0.0:
            raise ValueError(
                f"dose={dose} is negative. A weekly activity dose cannot be "
                f"below zero; a negative value is a unit or wiring error, "
                f"not negative activity."
            )
        if not 0.0 <= act_max < 1.0:
            raise ValueError(
                f"act_max={act_max} must lie in [0, 1). It is the share by "
                f"which relative risk falls at very high activity, so it "
                f"cannot be negative or reach one."
            )
        if act_scale <= 0.0:
            raise ValueError(
                f"act_scale={act_scale} must be greater than zero. It is "
                f"the dose scale in the exponent's denominator; zero or "
                f"negative would make the curve meaningless."
            )
        rr = 1.0 - act_max * (1.0 - math.exp(-dose / act_scale))
        if not math.isfinite(rr) or not 0.0 < rr <= 1.0:
            raise ValueError(
                f"relative risk={rr} is outside (0, 1]. A relative risk "
                f"must be positive and cannot exceed one; refusing to report "
                f"a curve value outside that range."
            )
        return rr

    def _calc_risk_at_ratio(self, inputs: list) -> float:
        """
        risk_plan = 100 * (1 - (1 - risk_now/100) ^ (rr_planned/rr_current))
                    (%)

        Moves the risk now by the ratio of the two relative risks, applied to
        a survival probability as a hazard ratio: an approximation.  A plan
        below the current activity raises the risk.

        risk_now must lie in [0, 100] because it is a percentage, and both
        relative risks must be positive because one divides the other.  The
        result is a percentage and is refused outside [0, 100] rather than
        clipped.
        inputs: [risk_now, rr_planned, rr_current]
        """
        _arity(inputs, 3, "risk_now, rr_planned, rr_current")
        risk_now, rr_planned, rr_current = inputs[0], inputs[1], inputs[2]
        _require(
            risk_now=risk_now, rr_planned=rr_planned, rr_current=rr_current
        )
        if not 0.0 <= risk_now <= 100.0:
            raise ValueError(
                f"risk_now={risk_now} is outside [0, 100] percent. It is a "
                f"risk in percent and cannot lie outside that range."
            )
        if rr_planned <= 0.0:
            raise ValueError(
                f"rr_planned={rr_planned} must be greater than zero. A "
                f"relative risk is a positive multiplier, and a non-positive "
                f"one has no meaning in the ratio."
            )
        if rr_current <= 0.0:
            raise ValueError(
                f"rr_current={rr_current} must be greater than zero. A "
                f"relative risk is a positive multiplier, and it is the "
                f"divisor of the ratio, so zero or negative is undefined."
            )
        survival = 1.0 - risk_now / 100.0
        try:
            moved = survival ** (rr_planned / rr_current)
        except (OverflowError, ZeroDivisionError) as exc:
            raise ValueError(
                f"rr_planned / rr_current = {rr_planned / rr_current} "
                f"cannot be applied to a survival probability."
            ) from exc
        risk = 100.0 * (1.0 - moved)
        return _risk_percent("risk_plan", risk)

    def _calc_flag_bp(self, inputs: list) -> float:
        """
        flag_bp = 1 when sbp >= sbp_flag or dbp >= dbp_flag, else 0   (1)

        Raised when resting blood pressure is at or above either declared
        threshold.  PLACEHOLDER thresholds.

        Both thresholds must be positive: a non-positive threshold would
        raise the flag for every reading, including a healthy one.
        inputs: [sbp, dbp, sbp_flag, dbp_flag]
        """
        _arity(inputs, 4, "sbp, dbp, sbp_flag, dbp_flag")
        sbp, dbp, sbp_flag, dbp_flag = inputs[0], inputs[1], inputs[2], inputs[3]
        _require(sbp=sbp, dbp=dbp, sbp_flag=sbp_flag, dbp_flag=dbp_flag)
        if sbp_flag <= 0.0:
            raise ValueError(
                f"sbp_flag={sbp_flag} must be greater than zero. A "
                f"non-positive threshold would flag every pressure reading."
            )
        if dbp_flag <= 0.0:
            raise ValueError(
                f"dbp_flag={dbp_flag} must be greater than zero. A "
                f"non-positive threshold would flag every pressure reading."
            )
        if sbp < 0.0:
            raise ValueError(
                f"sbp={sbp} is negative. Systolic pressure cannot be below "
                f"zero; this is a unit or entry error."
            )
        if dbp < 0.0:
            raise ValueError(
                f"dbp={dbp} is negative. Diastolic pressure cannot be below "
                f"zero; this is a unit or entry error."
            )
        return 1.0 if sbp >= sbp_flag or dbp >= dbp_flag else 0.0

    def _calc_flag_dose_jump(self, inputs: list) -> float:
        """
        flag_dose_jump = 1 when dose_planned > dose_jump_ratio * dose_current,
                         else 0   (1)

        Raised when the plan asks for much more weekly activity than the
        person does now.  PLACEHOLDER threshold.

        Both doses must be non-negative and the ratio must be at least 1.
        A ratio below one would call an ordinary reduction a jump.
        inputs: [dose_planned, dose_current, dose_jump_ratio]
        """
        _arity(
            inputs, 3, "dose_planned, dose_current, dose_jump_ratio"
        )
        dose_planned, dose_current, dose_jump_ratio = (
            inputs[0], inputs[1], inputs[2]
        )
        _require(
            dose_planned=dose_planned, dose_current=dose_current,
            dose_jump_ratio=dose_jump_ratio,
        )
        if dose_planned < 0.0:
            raise ValueError(
                f"dose_planned={dose_planned} is negative. A weekly activity "
                f"dose cannot be below zero; this is a unit or wiring error."
            )
        if dose_current < 0.0:
            raise ValueError(
                f"dose_current={dose_current} is negative. A weekly activity "
                f"dose cannot be below zero; this is a unit or wiring error."
            )
        if dose_jump_ratio < 1.0:
            raise ValueError(
                f"dose_jump_ratio={dose_jump_ratio} must be at least 1. A "
                f"ratio below one would call an ordinary reduction a jump."
            )
        return (
            1.0
            if dose_planned > dose_jump_ratio * dose_current
            else 0.0
        )

    def _calc_flag_medicine(self, inputs: list) -> float:
        """
        flag_medicine = hr_medicine   (1)

        Raised when the person takes a heart-rate-lowering medicine.  This
        is a statement of fact about the entered answer, so the answer must
        be exactly 0 or 1.
        inputs: [hr_medicine]
        """
        _arity(inputs, 1, "hr_medicine")
        hr_medicine = inputs[0]
        _require(hr_medicine=hr_medicine)
        _binary("hr_medicine", hr_medicine)
        return float(hr_medicine)
