"""
Fit one subject's wearable coefficients from their day bundles.

This tool reads a subject's recorded days, rebuilds exactly the minute inputs
the wearable lamina sees, and fits the coefficients of

    HR_target = clamp(HR_level + HR_offset
                      + A_circ*cos(2*pi*(hour_local - phi_circ)/24)
                      + k_T*max(0, T_app - T_ref)
                      + k_I*g_activity*AE_rate**p_I, 35, HR_max)

    g_activity = 1 + (g_walk - 1)*is_walk + (g_strength - 1)*is_strength
                   + (g_cardio - 1)*is_cardio

    HR_model  = first-order lag of HR_target, tau_on when rising and tau_off
                when falling, seeded with HR_target on the first minute and
                again after any minute where HR_target could not be computed.

No neural network is involved: the structure above is fixed and only its
coefficients are estimated.

PRE-REGISTERED DEFINITIONS (written before the fitting code, not tuned to a
particular subject):

  * WORKOUT_MIN_MINUTES = 10, WORKOUT_DENSE_HR_N = 6.  A workout segment is a
    run of consecutive minutes with the same non-null workout label.  It is
    DENSE when it lasts at least 10 minutes and the mean hr_n over its minutes
    is at least 6.
  * QUIET_AE_MAX = 0.5 kcal/min, QUIET_MARGIN_MIN = 30.  A quiet minute has
    hr present, HR_target computable, AE_rate <= 0.5, and lies outside every
    workout segment and outside the 30 minutes before its start and after its
    end.
  * FIT_FRACTION = 0.70.  Dense workouts sorted by start: the earliest 70%
    (rounded down, at least one left for test) are FIT and the rest TEST.
    split_date is the local date of the first TEST workout.  Quiet minutes on
    days before split_date are FIT; the rest are TEST.
  * LAG_RULE_BPM = 1.0.  The lagged model is shipped only when its TEST MAE
    over workout windows is at least 1.0 bpm lower than the no-lag model's.
    Otherwise the no-lag fit ships with tau_on = tau_off = 0.
  * GAIN_RULE_BPM = 1.0.  The per-workout-kind gains are kept only when the
    TEST MAE over workout windows of the fit with the gains held at 1.0 is at
    least 1.0 bpm higher than the fit with the gains free.  The lag rule above
    is then evaluated inside whichever gain setting this rule selects.
  * MAX_ROUNDS = 4, CONVERGENCE_FRACTION = 0.01.  Stage A and Stage B alternate
    until no free parameter moves by more than 1% of its bound span.

Every fitted number in a params.json belongs to the subject it was fitted on.
It is that person's own measured response, not a population or transferable
value; the file names the subject in "applies_to".

Run from the repository root:

    python backend/tools/fit_hr_model.py --bundle-dir DIR --subject subject_demo

or from backend/:

    python tools/fit_hr_model.py --bundle-dir DIR --subject subject_demo
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bundles import is_finite_number, read_subject_label, validate_bundle  # noqa: E402
from laminae import load_twin  # noqa: E402
from signal_source import ReplayExhausted, ReplaySource  # noqa: E402

# ── Pre-registered constants (do not tune per subject) ───────────────────────

SCHEMA_VERSION = 1
LAMINA_ID = "lamina_wearable"

WORKOUT_MIN_MINUTES = 10
WORKOUT_DENSE_HR_N = 6.0
QUIET_AE_MAX = 0.5
QUIET_MARGIN_MIN = 30
FIT_FRACTION = 0.70

LAG_RULE_BPM = 1.0
GAIN_RULE_BPM = 1.0
MAX_ROUNDS = 4
CONVERGENCE_FRACTION = 0.01

SOFT_L1_F_SCALE = 5.0

WEARABLE_XML = BACKEND_DIR / "wearable_lamina.xml"

HR_TARGET_FLOOR = 35.0

COEFFICIENT_NAMES = (
    "HR_offset",
    "A_circ",
    "phi_circ",
    "k_T",
    "T_ref",
    "k_I",
    "p_I",
    "tau_on",
    "tau_off",
    "HR_max",
    "g_walk",
    "g_strength",
    "g_cardio",
)

GAIN_NAMES = ("g_walk", "g_strength", "g_cardio")

STAGE_A_FREE = ("HR_offset", "A_circ", "phi_circ", "k_T", "T_ref")
STAGE_A_BOUNDS = {
    "HR_offset": (-40.0, 40.0),
    "A_circ": (0.0, 20.0),
    "phi_circ": (0.0, 24.0),
    "k_T": (0.0, 2.0),
    "T_ref": (0.0, 40.0),
}

STAGE_B_FREE = ("k_I", "p_I", "tau_on", "tau_off")
STAGE_B_FREE_NO_LAG = ("k_I", "p_I")
STAGE_B_BOUNDS = {
    "k_I": (0.0, 60.0),
    "p_I": (0.2, 1.5),
    "tau_on": (0.0, 600.0),
    "tau_off": (0.0, 900.0),
    "g_walk": (0.2, 3.0),
    "g_strength": (0.2, 3.0),
    "g_cardio": (0.2, 3.0),
}

_INPUT_FIELDS = ("hour_local", "dt_s", "HR_level", "AE_rate", "T_app")
_INDICATOR_FIELDS = ("is_walk", "is_strength", "is_cardio")


# ── Loading and rebuilding the lamina's inputs ───────────────────────────────


def _is_date_stem(text: str) -> bool:
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return False
    try:
        _date.fromisoformat(text)
    except ValueError:
        return False
    return True


def load_days(bundle_dir: Path, subject: str) -> list[dict]:
    """Every <bundle_dir>/<subject>/<date>.json, validated and sorted by date."""
    bundle_dir = Path(bundle_dir)
    folder = bundle_dir / subject
    if not folder.is_dir():
        raise ValueError(
            f"No bundle folder for subject '{subject}' at {folder}. Expected "
            f"{folder}/<date>.json files."
        )
    paths = sorted(
        path for path in folder.glob("*.json")
        if path.is_file() and _is_date_stem(path.stem)
    )
    if not paths:
        raise ValueError(
            f"No day bundles for subject '{subject}' in {folder}. Expected at "
            f"least one <date>.json file there."
        )

    days: list[dict] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path}: cannot read bundle: {exc}") from exc
        validate_bundle(data, label=str(path))
        if data["subject"] != subject:
            raise ValueError(
                f"{path}: bundle subject is {data['subject']!r}, but "
                f"--subject asked for {subject!r}."
            )
        days.append(data)

    days.sort(key=lambda bundle: bundle["date"])
    return days


def day_inputs(bundle: dict) -> dict[str, np.ndarray]:
    """
    Per-minute model inputs exactly as the wearable lamina receives them.

    The values come from iterating ReplaySource(load_twin(wearable), bundle),
    so clock arithmetic, day-level values and recording gaps are the replay's,
    not a second interpretation.  A reading named in last_missing is NaN.
    """
    twin = load_twin(WEARABLE_XML)
    feed = ReplaySource(twin, bundle)
    n = len(bundle["samples"])

    arrays: dict[str, np.ndarray] = {
        field: np.full(n, np.nan, dtype=float) for field in _INPUT_FIELDS
    }
    for field in _INDICATOR_FIELDS:
        arrays[field] = np.zeros(n, dtype=float)
    arrays["hr"] = np.full(n, np.nan, dtype=float)
    arrays["hr_n"] = np.zeros(n, dtype=float)
    arrays["workout"] = np.empty(n, dtype=object)

    index = 0
    while True:
        try:
            readings = feed.next()
        except ReplayExhausted:
            break
        missing = set(feed.last_missing)
        for field in _INPUT_FIELDS:
            if field in readings and field not in missing:
                arrays[field][index] = float(readings[field])
        for field in _INDICATOR_FIELDS:
            if field in readings:
                arrays[field][index] = float(readings[field])
        row = bundle["samples"][index]
        if row["hr"] is not None:
            arrays["hr"][index] = float(row["hr"])
        arrays["hr_n"][index] = float(row["hr_n"])
        arrays["workout"][index] = row.get("workout")
        index += 1

    if index != n:
        raise ValueError(
            f"Replay produced {index} rows but the bundle declares {n}."
        )
    return arrays


# ── The forward model ────────────────────────────────────────────────────────


def simulate_day(inputs: dict, coef: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Return (HR_target, HR_model) per minute; NaN where the lamina is stale.

    HR_target is stale when any input its formula needs is missing.  HR_model
    is stale whenever HR_target is, and the lag re-seeds at HR_target on the
    next computable minute, exactly as the lamina's committed state does.
    """
    hour = np.asarray(inputs["hour_local"], dtype=float)
    dt_s = np.asarray(inputs["dt_s"], dtype=float)
    level = np.asarray(inputs["HR_level"], dtype=float)
    ae_rate = np.asarray(inputs["AE_rate"], dtype=float)
    t_app = np.asarray(inputs["T_app"], dtype=float)
    is_walk = np.asarray(
        inputs.get("is_walk", np.zeros_like(ae_rate)), dtype=float
    )
    is_strength = np.asarray(
        inputs.get("is_strength", np.zeros_like(ae_rate)), dtype=float
    )
    is_cardio = np.asarray(
        inputs.get("is_cardio", np.zeros_like(ae_rate)), dtype=float
    )

    gain = (
        1.0
        + (coef.get("g_walk", 1.0) - 1.0) * is_walk
        + (coef.get("g_strength", 1.0) - 1.0) * is_strength
        + (coef.get("g_cardio", 1.0) - 1.0) * is_cardio
    )

    with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
        circadian = coef["A_circ"] * np.cos(
            2.0 * math.pi * (hour - coef["phi_circ"]) / 24.0
        )
        thermal = coef["k_T"] * np.maximum(0.0, t_app - coef["T_ref"])
        drive = coef["k_I"] * gain * np.power(ae_rate, coef["p_I"])
        total = level + coef["HR_offset"] + circadian + thermal + drive
        target = np.clip(total, HR_TARGET_FLOOR, coef["HR_max"])

    computable = (
        np.isfinite(hour)
        & np.isfinite(level)
        & np.isfinite(ae_rate)
        & np.isfinite(t_app)
    )
    target = np.asarray(target, dtype=float)
    target[~computable] = np.nan

    model = np.full(target.shape, np.nan, dtype=float)
    previous: float | None = None
    tau_on = float(coef["tau_on"])
    tau_off = float(coef["tau_off"])

    for index in range(target.size):
        value = float(target[index])
        step = float(dt_s[index])
        if not math.isfinite(value) or not math.isfinite(step) or step <= 0.0:
            previous = None
            continue
        if previous is None:
            model[index] = value
            previous = value
            continue
        tau = tau_on if value > previous else tau_off
        if tau == 0.0:
            model[index] = value
        else:
            alpha = 1.0 - math.exp(-step / tau)
            model[index] = previous + alpha * (value - previous)
        previous = float(model[index])

    return target, model


# ── Segments, quiet minutes and the split ────────────────────────────────────


def _workout_segments(inputs: dict) -> list[dict]:
    labels = inputs["workout"]
    hr_n = inputs["hr_n"]
    n = labels.size
    segments: list[dict] = []
    index = 0
    while index < n:
        label = labels[index]
        if label is None:
            index += 1
            continue
        end = index + 1
        while end < n and labels[end] == label:
            end += 1
        length = end - index
        dense = (
            length >= WORKOUT_MIN_MINUTES
            and float(np.mean(hr_n[index:end])) >= WORKOUT_DENSE_HR_N
        )
        segments.append({
            "start": index,
            "end": end,
            "label": str(label),
            "length": length,
            "dense": dense,
        })
        index = end
    return segments


def _quiet_mask(inputs: dict) -> np.ndarray:
    hour = inputs["hour_local"]
    level = inputs["HR_level"]
    ae_rate = inputs["AE_rate"]
    t_app = inputs["T_app"]
    hr = inputs["hr"]
    n = hr.size

    excluded = np.zeros(n, dtype=bool)
    for segment in _workout_segments(inputs):
        lo = max(0, segment["start"] - QUIET_MARGIN_MIN)
        hi = min(n, segment["end"] + QUIET_MARGIN_MIN)
        excluded[lo:hi] = True

    computable = (
        np.isfinite(hour)
        & np.isfinite(level)
        & np.isfinite(ae_rate)
        & np.isfinite(t_app)
    )
    return (
        np.isfinite(hr)
        & computable
        & (ae_rate <= QUIET_AE_MAX)
        & ~excluded
    )


def _prepare(days: list[dict]) -> list[dict]:
    prepared = []
    for bundle in days:
        inputs = day_inputs(bundle)
        prepared.append({
            "bundle": bundle,
            "date": bundle["date"],
            "inputs": inputs,
            "segments": _workout_segments(inputs),
            "quiet": _quiet_mask(inputs),
        })
    return prepared


def _dense_workouts(prepared: list[dict]) -> list[tuple[dict, dict]]:
    raw = [
        (day, segment)
        for day in prepared
        for segment in day["segments"]
        if segment["dense"]
    ]
    raw.sort(key=lambda pair: (pair[0]["date"], pair[1]["start"]))
    return raw


def _window_slice(segment: dict, n: int) -> slice:
    return slice(
        max(0, segment["start"] - QUIET_MARGIN_MIN),
        min(n, segment["end"] + QUIET_MARGIN_MIN),
    )


# ── Fitting ──────────────────────────────────────────────────────────────────


def _bounds(names: tuple[str, ...],
            table: dict) -> tuple[np.ndarray, np.ndarray]:
    lower = np.array([table[name][0] for name in names], dtype=float)
    upper = np.array([table[name][1] for name in names], dtype=float)
    return lower, upper


def _interior(x0: np.ndarray, lower: np.ndarray,
              upper: np.ndarray) -> np.ndarray:
    span = upper - lower
    margin = np.where(span > 0.0, 1e-9 * span, 0.0)
    return np.minimum(np.maximum(x0, lower + margin), upper - margin)


def _least_squares(residual, x0, lower, upper):
    from scipy.optimize import least_squares

    return least_squares(
        residual,
        _interior(np.asarray(x0, dtype=float), lower, upper),
        bounds=(lower, upper),
        loss="soft_l1",
        f_scale=SOFT_L1_F_SCALE,
    )


def _fit_stage_a(prepared: list[dict], coef: dict,
                 fit_days: list[dict]) -> dict:
    names = STAGE_A_FREE
    lower, upper = _bounds(names, STAGE_A_BOUNDS)
    x0 = np.array([coef[name] for name in names], dtype=float)

    def residual(theta):
        trial = dict(coef)
        for name, value in zip(names, theta):
            trial[name] = float(value)
        pieces = []
        for day in fit_days:
            target, _ = simulate_day(day["inputs"], trial)
            mask = day["quiet"]
            difference = day["inputs"]["hr"][mask] - target[mask]
            pieces.append(difference[np.isfinite(difference)])
        if not pieces:
            return np.empty(0, dtype=float)
        return np.concatenate(pieces)

    result = _least_squares(residual, x0, lower, upper)
    fitted = dict(coef)
    for name, value in zip(names, result.x):
        fitted[name] = float(value)
    return fitted


def _fit_stage_b(prepared: list[dict], coef: dict,
                 window_days: list[dict], free: tuple[str, ...],
                 no_lag: bool) -> dict:
    lower, upper = _bounds(free, STAGE_B_BOUNDS)
    x0 = np.array([coef[name] for name in free], dtype=float)

    def residual(theta):
        trial = dict(coef)
        for name, value in zip(free, theta):
            trial[name] = float(value)
        if no_lag:
            trial["tau_on"] = 0.0
            trial["tau_off"] = 0.0
        pieces = []
        for day in window_days:
            _, model = simulate_day(day["inputs"], trial)
            mask = day["fit_window"] & np.isfinite(day["inputs"]["hr"])
            difference = day["inputs"]["hr"][mask] - model[mask]
            pieces.append(difference[np.isfinite(difference)])
        if not pieces:
            return np.empty(0, dtype=float)
        return np.concatenate(pieces)

    result = _least_squares(residual, x0, lower, upper)
    fitted = dict(coef)
    for name, value in zip(free, result.x):
        fitted[name] = float(value)
    if no_lag:
        fitted["tau_on"] = 0.0
        fitted["tau_off"] = 0.0
    return fitted


def _fit_model(prepared: list[dict], seed: dict, fit_days: list[dict],
               fit_window_days: list[dict], no_lag: bool,
               gains_free: bool) -> tuple[dict, int]:
    coef = dict(seed)
    if not gains_free:
        for name in GAIN_NAMES:
            coef[name] = 1.0
    if no_lag:
        coef["tau_on"] = 0.0
        coef["tau_off"] = 0.0
    free_b = STAGE_B_FREE_NO_LAG if no_lag else STAGE_B_FREE
    if gains_free:
        free_b = free_b + GAIN_NAMES

    rounds = 0
    for _ in range(MAX_ROUNDS):
        rounds += 1
        before = dict(coef)

        coef = _fit_stage_a(prepared, coef, fit_days)
        if not gains_free:
            for name in GAIN_NAMES:
                coef[name] = 1.0
        if no_lag:
            coef["tau_on"] = 0.0
            coef["tau_off"] = 0.0

        coef = _fit_stage_b(
            prepared, coef, fit_window_days, free_b, no_lag=no_lag
        )
        if not gains_free:
            for name in GAIN_NAMES:
                coef[name] = 1.0

        moved = False
        for name in STAGE_A_FREE:
            lo, hi = STAGE_A_BOUNDS[name]
            if abs(coef[name] - before[name]) > CONVERGENCE_FRACTION * (hi - lo):
                moved = True
        for name in free_b:
            lo, hi = STAGE_B_BOUNDS[name]
            if abs(coef[name] - before[name]) > CONVERGENCE_FRACTION * (hi - lo):
                moved = True
        if not moved:
            break

    _check_gain_bounds(coef, "fitted model")
    return coef, rounds


# ── Metrics ──────────────────────────────────────────────────────────────────


def _mae(prediction: np.ndarray, observed: np.ndarray,
         mask: np.ndarray) -> float:
    keep = mask & np.isfinite(observed) & np.isfinite(prediction)
    if not np.any(keep):
        return float("nan")
    return float(np.mean(np.abs(observed[keep] - prediction[keep])))


def _day_models(prepared: list[dict], coef: dict) -> dict[str, np.ndarray]:
    return {
        day["date"]: simulate_day(day["inputs"], coef)[1]
        for day in prepared
    }


def _window_metrics(prepared: list[dict], models: dict[str, dict],
                    test_workouts: list[tuple[dict, dict]]) -> tuple[dict,
                                                                   dict,
                                                                   dict]:
    model_predictions = {
        name: _day_models(prepared, coef) for name, coef in models.items()
    }
    model_names = tuple(models)

    windows: list[dict] = []
    fallbacks = 0
    for day, segment in test_workouts:
        inputs = day["inputs"]
        n = inputs["hr"].size
        window = _window_slice(segment, n)
        observed = inputs["hr"][window]

        before = inputs["hr"][max(0, segment["start"] - QUIET_MARGIN_MIN):
                              segment["start"]]
        before = before[np.isfinite(before)]
        if before.size:
            hold = float(np.median(before))
        else:
            fallbacks += 1
            quiet_hr = inputs["hr"][day["quiet"]]
            quiet_hr = quiet_hr[np.isfinite(quiet_hr)]
            if quiet_hr.size:
                hold = float(np.median(quiet_hr))
            else:
                all_hr = inputs["hr"][np.isfinite(inputs["hr"])]
                hold = float(np.median(all_hr))

        keep = np.arange(*window.indices(n))
        valid = np.isfinite(observed)
        record = {
            "label": segment["label"],
            "hold_pre": _mae(np.full(observed.shape, hold), observed, valid),
        }
        for name in model_names:
            prediction = model_predictions[name][day["date"]][keep]
            record[name] = _mae(prediction, observed, valid)
        windows.append(record)

    def summarise(items: list[dict]) -> dict:
        if not items:
            out = {"n": 0, "hold_pre": float("nan")}
            out.update({name: float("nan") for name in model_names})
            return out
        out = {"n": len(items)}
        for name in model_names:
            out[name] = float(np.mean([item[name] for item in items]))
        out["hold_pre"] = float(
            np.mean([item["hold_pre"] for item in items])
        )
        return out

    overall = summarise(windows)
    overall["hold_pre_fallback_windows"] = fallbacks
    median_per_window = {
        name: float(np.median([item[name] for item in windows]))
        for name in model_names
    }
    median_per_window["hold_pre"] = float(
        np.median([item["hold_pre"] for item in windows])
    )

    by_type: dict[str, list[dict]] = {}
    for item in windows:
        by_type.setdefault(item["label"], []).append(item)
    per_type = {label: summarise(items) for label, items in sorted(by_type.items())}

    return overall, median_per_window, per_type


def _residual_sd(prepared: list[dict], coef: dict) -> float:
    residuals = []
    for day in prepared:
        _, model = simulate_day(day["inputs"], coef)
        hr = day["inputs"]["hr"]
        keep = np.isfinite(hr) & np.isfinite(model)
        residuals.append(hr[keep] - model[keep])
    combined = np.concatenate(residuals) if residuals else np.empty(0)
    if combined.size == 0:
        raise ValueError(
            "not enough data to fit: no minute has both a measured and a "
            "modelled heart rate, so residual_sd is undefined."
        )
    return float(np.std(combined))


# ── Guards and reporting ─────────────────────────────────────────────────────


def _default_seed(twin) -> dict:
    seed = {}
    for name in COEFFICIENT_NAMES:
        attr = twin.attributes.get(name)
        if attr is None or attr.baseline is None:
            raise ValueError(
                f"Lamina {twin.lamina_id} declares no baseline for coefficient "
                f"'{name}', so the fit has no starting value."
            )
        seed[name] = float(attr.baseline)
    return seed


def _check_seed(seed_coef: dict) -> None:
    if not isinstance(seed_coef, dict):
        raise ValueError(
            f"seed_coef must be a mapping of coefficient names to values, got "
            f"{type(seed_coef).__name__}."
        )
    missing = [name for name in COEFFICIENT_NAMES if name not in seed_coef]
    if missing:
        raise ValueError(
            f"seed_coef is missing coefficient(s): {', '.join(missing)}. "
            f"Supply all of: {', '.join(COEFFICIENT_NAMES)}."
        )
    bad = [
        name for name in COEFFICIENT_NAMES
        if not is_finite_number(seed_coef[name])
    ]
    if bad:
        raise ValueError(
            f"seed_coef has non-finite value(s) for: {', '.join(bad)}."
        )


def _complete_seed(seed_coef: dict) -> dict:
    """
    Fill missing gain seeds from the lamina's declared baselines.

    The gains were added after callers had already built seed mappings, so a
    seed without them is an old caller, not an error.  Every other coefficient
    must still be supplied.
    """
    if not isinstance(seed_coef, dict):
        raise ValueError(
            f"seed_coef must be a mapping of coefficient names to values, got "
            f"{type(seed_coef).__name__}."
        )
    seed = dict(seed_coef)
    twin = load_twin(WEARABLE_XML)
    for name in GAIN_NAMES:
        if name not in seed:
            attr = twin.attributes.get(name)
            if attr is None or attr.baseline is None:
                raise ValueError(
                    f"Lamina {twin.lamina_id} declares no baseline for "
                    f"coefficient '{name}', so a seed that omits it cannot be "
                    f"completed."
                )
            seed[name] = float(attr.baseline)
    _check_seed(seed)
    return seed


def _check_gain_bounds(coefficients: dict, where: str) -> None:
    for name in GAIN_NAMES:
        value = float(coefficients[name])
        lower, upper = STAGE_B_BOUNDS[name]
        if not math.isfinite(value):
            raise ValueError(
                f"Refusing to use {where}: gain {name} is non-finite "
                f"({value!r})."
            )
        if value < lower or value > upper:
            raise ValueError(
                f"Refusing to use {where}: gain {name}={value!r} is outside "
                f"its bounds [{lower}, {upper}]."
            )


def _compute_hr_max(prepared: list[dict], seed: dict) -> float:
    hrs = [
        day["inputs"]["hr"][np.isfinite(day["inputs"]["hr"])]
        for day in prepared
    ]
    combined = np.concatenate(hrs) if hrs else np.empty(0)
    if combined.size == 0:
        raise ValueError(
            "not enough data to fit: no measured heart rate exists, so HR_max "
            "cannot be estimated."
        )
    attr = load_twin(WEARABLE_XML).attributes["HR_max"]
    value = round(float(np.percentile(combined, 99.9)), 1)
    return float(min(attr.physio_max, max(attr.physio_min, value)))


def _rounded(coefficients: dict) -> dict:
    return {name: round(float(coefficients[name]), 4)
            for name in COEFFICIENT_NAMES}


def _assert_finite(value, where: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _assert_finite(item, f"{where}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_finite(item, f"{where}[{index}]")
        return
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        raise ValueError(
            f"Refusing to write params.json: {where} is non-finite "
            f"({value!r}). The fit did not converge to usable numbers."
        )


POST_HOC_CHOICES = ("full",)


def _all_minutes_mae(day_list: list[dict], coef: dict) -> float:
    """MAE over every minute of these days with both a reading and a model."""
    errors = []
    for day in day_list:
        _, model = simulate_day(day["inputs"], coef)
        hr = day["inputs"]["hr"]
        keep = np.isfinite(hr) & np.isfinite(model)
        errors.append(np.abs(hr[keep] - model[keep]))
    joined = np.concatenate(errors) if errors else np.empty(0)
    return float(joined.mean()) if joined.size else float("nan")


def fit(days: list[dict], seed_coef: dict, post_hoc: str | None = None,
        post_hoc_reason: str | None = None, label: str | None = None) -> dict:
    """
    Fit the four models and return the params dict.

    `post_hoc="full"` ships the full model (lag and gains free) whatever the
    two rules chose, and records that a person overrode them after seeing the
    TEST results, with the reason and both models' scores.  The rules' own
    verdicts stay in params.json untouched: an override is written beside a
    pre-registered result, never over it.
    """
    if post_hoc is not None and post_hoc not in POST_HOC_CHOICES:
        raise ValueError(
            f"post_hoc={post_hoc!r} is not a choice this fitter knows; use "
            f"one of {list(POST_HOC_CHOICES)} or leave it unset."
        )
    if post_hoc is not None and not (post_hoc_reason or "").strip():
        raise ValueError(
            "A post-hoc choice needs a reason: it overrides a pre-registered "
            "rule, and params.json must say why."
        )
    """Fit the four models on `days` and return the params dict."""
    seed_coef = _complete_seed(seed_coef)
    if not days:
        raise ValueError(
            "not enough data to fit: no day bundles were supplied."
        )

    prepared = _prepare(days)
    dense = _dense_workouts(prepared)
    quiet_total = int(sum(int(np.count_nonzero(day["quiet"]))
                          for day in prepared))
    if len(dense) < 5 or quiet_total < 200:
        raise ValueError(
            f"not enough data to fit: found {len(dense)} dense workouts and "
            f"{quiet_total} quiet minutes; need at least 5 dense workouts and "
            f"200 quiet minutes."
        )

    n_fit = int(math.floor(FIT_FRACTION * len(dense)))
    n_fit = max(1, min(n_fit, len(dense) - 1))
    fit_workouts = dense[:n_fit]
    test_workouts = dense[n_fit:]
    split_date = test_workouts[0][0]["date"]

    fit_days = [day for day in prepared if day["date"] < split_date]
    test_days = [day for day in prepared if day["date"] >= split_date]

    quiet_fit = int(sum(int(np.count_nonzero(day["quiet"]))
                        for day in fit_days))
    quiet_test = int(sum(int(np.count_nonzero(day["quiet"]))
                         for day in test_days))
    if quiet_fit == 0:
        raise ValueError(
            "not enough data to fit: no quiet minutes fall before the first "
            "test workout. Add days before split_date."
        )
    if quiet_test == 0:
        raise ValueError(
            "not enough data to fit: no quiet minutes fall on or after "
            "split_date, so Stage A cannot be scored on TEST data."
        )

    for day in prepared:
        mask = np.zeros(day["inputs"]["hr"].size, dtype=bool)
        for other, segment in fit_workouts:
            if other is day:
                mask[_window_slice(segment, day["inputs"]["hr"].size)] = True
        day["fit_window"] = mask
    fit_window_days = [
        day for day in prepared if np.any(day["fit_window"])
    ]

    seed = dict(seed_coef)
    seed["HR_max"] = _compute_hr_max(prepared, seed)

    full, full_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days,
        no_lag=False, gains_free=True
    )
    no_gain, no_gain_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days,
        no_lag=False, gains_free=False
    )
    no_lag, no_lag_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days,
        no_lag=True, gains_free=True
    )
    neither, neither_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days,
        no_lag=True, gains_free=False
    )

    full = _rounded(full)
    no_gain = _rounded(no_gain)
    no_lag = _rounded(no_lag)
    neither = _rounded(neither)
    no_lag["tau_on"] = 0.0
    no_lag["tau_off"] = 0.0
    neither["tau_on"] = 0.0
    neither["tau_off"] = 0.0
    for coef in (full, no_gain, no_lag, neither):
        _check_gain_bounds(coef, "rounded fitted model")

    full_overall, _, _ = _window_metrics(
        prepared, {"full": full}, test_workouts
    )
    no_gain_overall, no_gain_median, no_gain_per_type = _window_metrics(
        prepared, {"no_gain": no_gain}, test_workouts
    )
    with_gains_mae = full_overall["full"]
    without_gains_mae = no_gain_overall["no_gain"]
    if not (math.isfinite(with_gains_mae)
            and math.isfinite(without_gains_mae)):
        raise ValueError(
            "Refusing to write params.json: the TEST workout MAE is "
            "non-finite, so the gain rule cannot be evaluated."
        )
    gains_passed = (
        (without_gains_mae - with_gains_mae) >= GAIN_RULE_BPM
    )

    if gains_passed:
        lagged_candidate = full
        no_lag_candidate = no_lag
        lagged_candidate_rounds = full_rounds
        no_lag_candidate_rounds = no_lag_rounds
        gain_setting = "with_gains"
    else:
        lagged_candidate = no_gain
        no_lag_candidate = neither
        lagged_candidate_rounds = no_gain_rounds
        no_lag_candidate_rounds = neither_rounds
        gain_setting = "without_gains"

    pair_overall, _, _ = _window_metrics(
        prepared,
        {"lagged": lagged_candidate, "no_lag": no_lag_candidate},
        test_workouts,
    )
    lagged_mae = pair_overall["lagged"]
    no_lag_mae = pair_overall["no_lag"]
    if not (math.isfinite(lagged_mae) and math.isfinite(no_lag_mae)):
        raise ValueError(
            "Refusing to write params.json: the TEST workout MAE is "
            "non-finite, so the lag rule cannot be evaluated."
        )
    lag_passed = (no_lag_mae - lagged_mae) >= LAG_RULE_BPM
    shipped = lagged_candidate if lag_passed else no_lag_candidate
    shipped_rounds = (
        lagged_candidate_rounds if lag_passed else no_lag_candidate_rounds
    )

    post_hoc_record = None
    if post_hoc == "full":
        rules_choice = shipped
        post_hoc_record = {
            "shipped": "full (lag free, gains free)",
            "rules_chose": (
                f"{gain_setting}, {'lagged' if lag_passed else 'no_lag'}"
            ),
            "reason": post_hoc_reason.strip(),
            "decided": (
                "by a person after seeing the TEST results, so this is not a "
                "pre-registered choice"
            ),
            "decided_at": datetime.now(timezone.utc).date().isoformat(),
            "all_test_minutes_mae": {
                "rules_choice": _all_minutes_mae(test_days, rules_choice),
                "full": _all_minutes_mae(test_days, full),
            },
            "test_window_mae": {
                "rules_choice": lagged_mae if lag_passed else no_lag_mae,
                "full": with_gains_mae,
            },
            "rules_choice_coefficients": rules_choice,
        }
        shipped = full
        shipped_rounds = full_rounds

    shipped_overall, shipped_median, shipped_per_type = _window_metrics(
        prepared, {"shipped": shipped}, test_workouts
    )

    test_quiet = np.zeros(
        int(sum(day["inputs"]["hr"].size for day in test_days)), dtype=bool
    )
    hr_test: list[np.ndarray] = []
    target_test: list[np.ndarray] = []
    level_test: list[np.ndarray] = []
    offset = 0
    for day in test_days:
        inputs = day["inputs"]
        target, _ = simulate_day(inputs, shipped)
        keep = day["quiet"]
        test_quiet[offset:offset + keep.size] = keep
        offset += keep.size
        hr_test.append(inputs["hr"])
        target_test.append(target)
        level_test.append(inputs["HR_level"])

    hr_all = np.concatenate(hr_test)
    target_all = np.concatenate(target_test)
    level_all = np.concatenate(level_test)
    stage_a_static = _mae(target_all, hr_all, test_quiet)
    stage_a_level = _mae(level_all, hr_all, test_quiet)

    residual_sd = _residual_sd(prepared, shipped)

    subject = days[0]["subject"]
    basal_sources: dict[str, int] = {}
    for day in days:
        source = day["day"].get("basal_source", "unknown")
        basal_sources[source] = basal_sources.get(source, 0) + 1

    params = {
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "applies_to": (
            f"{label or subject} only: fitted on {label or subject}'s "
            f"recordings; not a population value"
        ),
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "lamina": LAMINA_ID,
        "coefficients": shipped,
        "residual_sd": residual_sd,
        "outcome_tolerance": {"target_residual": 2.0 * residual_sd},
        "gain_rule": {
            "threshold_bpm": GAIN_RULE_BPM,
            "with_gains_test_mae": with_gains_mae,
            "without_gains_test_mae": without_gains_mae,
            "passed": bool(gains_passed),
            # What the gain-free-to-move model actually found, whatever was
            # shipped: a rejected gain is still a finding worth reading.
            "gains_fitted": {
                name: full[name] for name in GAIN_NAMES
            },
        },
        "lag_rule": {
            "threshold_bpm": LAG_RULE_BPM,
            "gain_setting": gain_setting,
            "lagged_test_mae": lagged_mae,
            "no_lag_test_mae": no_lag_mae,
            "passed": bool(lag_passed),
            "shipped": "lagged" if lag_passed else "no_lag",
            "lagged_coefficients": lagged_candidate,
        },
        "data": {
            "days": len(days),
            "first_date": days[0]["date"],
            "last_date": days[-1]["date"],
            "split_date": split_date,
            "quiet_minutes_fit": quiet_fit,
            "quiet_minutes_test": quiet_test,
            "workouts_fit": len(fit_workouts),
            "workouts_test": len(test_workouts),
            "basal_sources": basal_sources,
        },
        "metrics": {
            "stage_a": {
                "static_mae": stage_a_static,
                "hr_level_mae": stage_a_level,
            },
            "stage_b": {
                "overall": shipped_overall,
                "median_per_window": shipped_median,
                "per_type": shipped_per_type,
                "shipped": {
                    "overall": shipped_overall,
                    "median_per_window": shipped_median,
                    "per_type": shipped_per_type,
                },
                "no_gain": {
                    "overall": no_gain_overall,
                    "median_per_window": no_gain_median,
                    "per_type": no_gain_per_type,
                },
            },
            "rounds": shipped_rounds,
            # Every TEST minute, not only workout windows: the rules above see
            # the windows, and a model can win there while losing at rest.
            "all_test_minutes_mae": _all_minutes_mae(test_days, shipped),
        },
        "post_hoc": post_hoc_record,
    }

    _assert_finite(params["coefficients"], "coefficients")
    _assert_finite(params["residual_sd"], "residual_sd")
    _assert_finite(params["outcome_tolerance"], "outcome_tolerance")
    _assert_finite(params["gain_rule"], "gain_rule")
    _assert_finite(params["lag_rule"], "lag_rule")
    _assert_finite(params["metrics"], "metrics")
    _assert_finite(params["post_hoc"], "post_hoc")
    return params


def render_report(params: dict, label: str | None = None) -> str:
    # The report names the person by their label (subject.json) when the
    # folder has one, so a published report never shows the folder name.
    subject = label or params["subject"]
    data = params["data"]
    stage_b = params["metrics"]["stage_b"]
    overall = stage_b["overall"]
    median = stage_b["median_per_window"]
    no_gain = stage_b["no_gain"]
    no_gain_overall = no_gain["overall"]
    no_gain_median = no_gain["median_per_window"]
    rule = params["lag_rule"]
    gain_rule = params["gain_rule"]

    def cell(metrics: dict, key: str) -> str:
        value = metrics.get(key)
        return "nan" if value is None else f"{value:.2f}"

    lines = [
        f"# Wearable fit — subject {subject} (these coefficients apply to "
        f"{subject} only)",
        "",
        f"{params['applies_to']}.",
        "",
        f"Date range: {data['first_date']} to {data['last_date']} "
        f"({data['days']} days). These are one person's data, not a clinical "
        f"validation.",
        "",
        "## Stage B — workout windows (TEST)",
        "",
        "| window | n | shipped | no_gain | hold pre |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| overall mean | {overall['n']} | {cell(overall, 'shipped')} | "
        f"{cell(no_gain_overall, 'no_gain')} | "
        f"{cell(overall, 'hold_pre')} |",
        f"| median per window | {overall['n']} | {cell(median, 'shipped')} | "
        f"{cell(no_gain_median, 'no_gain')} | "
        f"{cell(median, 'hold_pre')} |",
    ]
    labels = sorted(
        set(stage_b["per_type"]) | set(no_gain["per_type"])
    )
    for label in labels:
        shipped_metrics = stage_b["per_type"].get(label)
        no_gain_metrics = no_gain["per_type"].get(label)
        n = (
            shipped_metrics["n"] if shipped_metrics is not None
            else no_gain_metrics["n"]
        )
        lines.append(
            f"| {label} | {n} | "
            f"{cell(shipped_metrics or {}, 'shipped')} | "
            f"{cell(no_gain_metrics or {}, 'no_gain')} | "
            f"{cell(shipped_metrics or no_gain_metrics or {}, 'hold_pre')} |"
        )
    lines.extend([
        "",
        f"Hold-pre baseline fell back to that day's quiet median on "
        f"{overall['hold_pre_fallback_windows']} window(s).",
        "",
        "## Stage A — quiet minutes (TEST)",
        "",
        f"Static model MAE {params['metrics']['stage_a']['static_mae']:.2f} "
        f"bpm; HR_level alone {params['metrics']['stage_a']['hr_level_mae']:.2f} "
        f"bpm.",
        "",
        "## Gain rule",
        "",
        f"TEST workout MAE without gains {gain_rule['without_gains_test_mae']:.2f} "
        f"bpm vs with gains {gain_rule['with_gains_test_mae']:.2f} bpm; the "
        f"rule required at least {gain_rule['threshold_bpm']:.1f} bpm "
        f"improvement, so "
        f"{'it passed and the fitted per-type gains shipped' if gain_rule['passed'] else 'it did not pass and every gain shipped as 1.0'}.",
        "",
        "## Lag rule",
        "",
        f"Evaluated with the gains "
        f"{'free' if gain_rule['passed'] else 'held at 1.0'} "
        f"({rule['gain_setting']}): lagged TEST MAE "
        f"{rule['lagged_test_mae']:.2f} bpm vs no-lag "
        f"{rule['no_lag_test_mae']:.2f} bpm; the rule required at least "
        f"{rule['threshold_bpm']:.1f} bpm improvement, so "
        f"{'it passed and the lagged coefficients' if rule['passed'] else 'it did not pass and the no-lag coefficients, both taus zero,'} "
        f"{'were the rules choice (overridden below)' if params.get('post_hoc') else 'shipped'}.",
        "",
    ])
    post_hoc = params.get("post_hoc")
    if post_hoc:
        minutes = post_hoc["all_test_minutes_mae"]
        windows = post_hoc["test_window_mae"]
        lines.extend([
            "## Post-hoc choice",
            "",
            f"The rules chose {post_hoc['rules_chose']}; the "
            f"{post_hoc['shipped']} model shipped instead, decided "
            f"{post_hoc['decided']}, on {post_hoc['decided_at']}. Reason: "
            f"{post_hoc['reason']}",
            "",
            f"Every TEST minute: rules' choice {minutes['rules_choice']:.2f} bpm, "
            f"shipped {minutes['full']:.2f} bpm. TEST workout windows: rules' "
            f"choice {windows['rules_choice']:.2f} bpm, shipped "
            f"{windows['full']:.2f} bpm.",
            "",
        ])
    lines.extend([
        "## Shipped coefficients",
        "",
        f"| coefficient | {subject}'s value |",
        "| --- | ---: |",
    ])
    for name in COEFFICIENT_NAMES:
        lines.append(f"| {name} | {params['coefficients'][name]:.4f} |")
    lines.extend([
        "",
        f"Fitted rounds: {params['metrics']['rounds']}. "
        f"Residual SD {params['residual_sd']:.2f} bpm.",
        "",
    ])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Fit one subject's wearable-lamina coefficients."
    )
    parser.add_argument("--bundle-dir", required=True,
                        help="Directory holding <subject>/<date>.json bundles.")
    parser.add_argument("--subject", required=True,
                        help="Subject folder name to fit.")
    parser.add_argument("--post-hoc", choices=list(POST_HOC_CHOICES),
                        help="Override the pre-registered rules and ship this "
                             "model; recorded in params.json as post-hoc.")
    parser.add_argument("--post-hoc-reason",
                        help="Why the rules are overridden (required with "
                             "--post-hoc).")
    args = parser.parse_args(argv)
    if args.post_hoc and not (args.post_hoc_reason or "").strip():
        parser.error("--post-hoc needs --post-hoc-reason: say why the "
                     "pre-registered rules are overridden.")

    days = load_days(Path(args.bundle_dir), args.subject)
    target = Path(args.bundle_dir) / args.subject
    label = read_subject_label(target, args.subject)
    seed = _default_seed(load_twin(WEARABLE_XML))
    params = fit(days, seed, post_hoc=args.post_hoc,
                 post_hoc_reason=args.post_hoc_reason, label=label)

    params_path = target / "params.json"
    report_path = target / "fit_report.md"
    report = render_report(params, label=label)

    params_path.write_text(
        json.dumps(params, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report_path.write_text(
        report + "\n", encoding="utf-8", newline="\n"
    )
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
