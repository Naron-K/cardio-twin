"""
Fit one subject's wearable coefficients from their day bundles.

This tool reads a subject's recorded days, rebuilds exactly the minute inputs
the wearable lamina sees, and fits the coefficients of

    HR_target = clamp(HR_level + HR_offset
                      + A_circ*cos(2*pi*(hour_local - phi_circ)/24)
                      + k_T*max(0, T_app - T_ref)
                      + k_I*AE_rate**p_I, 35, HR_max)

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
  * MAX_ROUNDS = 4, CONVERGENCE_FRACTION = 0.01.  Stage A and Stage B alternate
    until no free parameter moves by more than 1% of its bound span.

Run from the repository root:

    python backend/tools/fit_hr_model.py --bundle-dir DIR --subject s2

or from backend/:

    python tools/fit_hr_model.py --bundle-dir DIR --subject s2
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

from bundles import is_finite_number, validate_bundle  # noqa: E402
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
)

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
}

_INPUT_FIELDS = ("hour_local", "dt_s", "HR_level", "AE_rate", "T_app")


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

    with np.errstate(invalid="ignore", over="ignore", divide="ignore"):
        circadian = coef["A_circ"] * np.cos(
            2.0 * math.pi * (hour - coef["phi_circ"]) / 24.0
        )
        thermal = coef["k_T"] * np.maximum(0.0, t_app - coef["T_ref"])
        drive = coef["k_I"] * np.power(ae_rate, coef["p_I"])
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
               fit_window_days: list[dict], no_lag: bool) -> tuple[dict, int]:
    coef = dict(seed)
    if no_lag:
        coef["tau_on"] = 0.0
        coef["tau_off"] = 0.0
    free_b = STAGE_B_FREE_NO_LAG if no_lag else STAGE_B_FREE

    rounds = 0
    for _ in range(MAX_ROUNDS):
        rounds += 1
        before = dict(coef)

        coef = _fit_stage_a(prepared, coef, fit_days)
        if no_lag:
            coef["tau_on"] = 0.0
            coef["tau_off"] = 0.0

        coef = _fit_stage_b(
            prepared, coef, fit_window_days, free_b, no_lag=no_lag
        )

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


def _window_metrics(prepared: list[dict], lagged: dict, no_lag: dict,
                    test_workouts: list[tuple[dict, dict]]) -> tuple[dict,
                                                                   dict,
                                                                   dict]:
    lagged_models = _day_models(prepared, lagged)
    no_lag_models = _day_models(prepared, no_lag)

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
        lag_prediction = lagged_models[day["date"]][keep]
        no_lag_prediction = no_lag_models[day["date"]][keep]

        windows.append({
            "label": segment["label"],
            "lagged": _mae(lag_prediction, observed, valid),
            "no_lag": _mae(no_lag_prediction, observed, valid),
            "hold_pre": _mae(np.full(observed.shape, hold), observed, valid),
        })

    def summarise(items: list[dict]) -> dict:
        if not items:
            return {"n": 0, "lagged": float("nan"),
                    "no_lag": float("nan"), "hold_pre": float("nan")}
        return {
            "n": len(items),
            "lagged": float(np.mean([item["lagged"] for item in items])),
            "no_lag": float(np.mean([item["no_lag"] for item in items])),
            "hold_pre": float(np.mean([item["hold_pre"] for item in items])),
        }

    overall = summarise(windows)
    overall["hold_pre_fallback_windows"] = fallbacks
    median_per_window = {
        "lagged": float(np.median([item["lagged"] for item in windows])),
        "no_lag": float(np.median([item["no_lag"] for item in windows])),
        "hold_pre": float(np.median([item["hold_pre"] for item in windows])),
    }

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


def fit(days: list[dict], seed_coef: dict) -> dict:
    """Fit both models on `days` and return the params dict."""
    _check_seed(seed_coef)
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

    lagged, lagged_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days, no_lag=False
    )
    no_lag, no_lag_rounds = _fit_model(
        prepared, seed, fit_days, fit_window_days, no_lag=True
    )

    lagged = _rounded(lagged)
    no_lag = _rounded(no_lag)
    no_lag["tau_on"] = 0.0
    no_lag["tau_off"] = 0.0

    overall, median_per_window, per_type = _window_metrics(
        prepared, lagged, no_lag, test_workouts
    )

    lagged_mae = overall["lagged"]
    no_lag_mae = overall["no_lag"]
    if not (math.isfinite(lagged_mae) and math.isfinite(no_lag_mae)):
        raise ValueError(
            "Refusing to write params.json: the TEST workout MAE is "
            "non-finite, so the lag rule cannot be evaluated."
        )
    passed = (no_lag_mae - lagged_mae) >= LAG_RULE_BPM
    shipped = lagged if passed else no_lag

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

    basal_sources: dict[str, int] = {}
    for day in days:
        source = day["day"].get("basal_source", "unknown")
        basal_sources[source] = basal_sources.get(source, 0) + 1

    params = {
        "schema_version": SCHEMA_VERSION,
        "subject": days[0]["subject"],
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "lamina": LAMINA_ID,
        "coefficients": shipped,
        "residual_sd": residual_sd,
        "outcome_tolerance": {"target_residual": 2.0 * residual_sd},
        "lag_rule": {
            "threshold_bpm": LAG_RULE_BPM,
            "lagged_test_mae": lagged_mae,
            "no_lag_test_mae": no_lag_mae,
            "passed": bool(passed),
            "shipped": "lagged" if passed else "no_lag",
            "lagged_coefficients": lagged,
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
                "overall": overall,
                "median_per_window": median_per_window,
                "per_type": per_type,
            },
            "rounds": lagged_rounds if passed else no_lag_rounds,
        },
    }

    _assert_finite(params["coefficients"], "coefficients")
    _assert_finite(params["residual_sd"], "residual_sd")
    _assert_finite(params["outcome_tolerance"], "outcome_tolerance")
    _assert_finite(params["lag_rule"], "lag_rule")
    _assert_finite(params["metrics"], "metrics")
    return params


def render_report(params: dict) -> str:
    data = params["data"]
    stage_b = params["metrics"]["stage_b"]
    overall = stage_b["overall"]
    median = stage_b["median_per_window"]
    rule = params["lag_rule"]

    lines = [
        f"# Wearable fit — subject {params['subject']}",
        "",
        f"Date range: {data['first_date']} to {data['last_date']} "
        f"({data['days']} days). These are one person's data, not a clinical "
        f"validation.",
        "",
        "## Stage B — workout windows (TEST)",
        "",
        "| window | n | lagged | no-lag | hold pre |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| overall mean | {overall['n']} | {overall['lagged']:.2f} | "
        f"{overall['no_lag']:.2f} | {overall['hold_pre']:.2f} |",
        f"| median per window | {overall['n']} | {median['lagged']:.2f} | "
        f"{median['no_lag']:.2f} | {median['hold_pre']:.2f} |",
    ]
    for label, metrics in stage_b["per_type"].items():
        lines.append(
            f"| {label} | {metrics['n']} | {metrics['lagged']:.2f} | "
            f"{metrics['no_lag']:.2f} | {metrics['hold_pre']:.2f} |"
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
        "## Lag rule",
        "",
        f"Lagged TEST MAE {rule['lagged_test_mae']:.2f} bpm vs no-lag "
        f"{rule['no_lag_test_mae']:.2f} bpm; the rule required at least "
        f"{rule['threshold_bpm']:.1f} bpm improvement, so "
        f"{'it passed and the lagged coefficients shipped' if rule['passed'] else 'it did not pass and the no-lag coefficients shipped with both taus set to zero'}.",
        "",
        "## Shipped coefficients",
        "",
        "| coefficient | value |",
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
    args = parser.parse_args(argv)

    days = load_days(Path(args.bundle_dir), args.subject)
    seed = _default_seed(load_twin(WEARABLE_XML))
    params = fit(days, seed)

    target = Path(args.bundle_dir) / args.subject
    params_path = target / "params.json"
    report_path = target / "fit_report.md"
    report = render_report(params)

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
