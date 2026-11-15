"""
Score a day projected from its schedule alone against what was recorded.

A plan knows the date, the clock hours and the workout labels of a day, but not
the minute-by-minute active energy or steps it will cost.  This tool builds
this subject's activity templates from the FIT days only, projects every TEST
day from its schedule, and compares the projection with the recording.  Two
projections are scored:

  * ``schedule``          each minute gets the hour's background rate or the
                          workout's session rate from the FIT templates.
  * ``stated_intensity``  the same, then every session's worn minutes are
                          given the session's own recorded mean AE, as a
                          planner who states an intensity would.

The report is written as ``projection_report`` into
``<bundle-dir>/<subject>/templates.json``; every other key is left untouched.
Nothing here is a population value: the templates and coefficients are this
subject's own recordings.

Run from backend/:

    python tools/backtest_planned_day.py --bundle-dir bundles --subject subject_demo
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import numpy as np  # noqa: E402

from tools.fit_hr_model import (  # noqa: E402
    WEARABLE_XML,
    day_inputs,
    load_days,
    load_twin,
    simulate_day,
)
from tools.make_activity_templates import (  # noqa: E402
    build_templates,
    hour_rate,
    kind_groups,
    session_rate,
)

SCHEMA_VERSION = 1

ENERGY_BEATS_BASELINE = 0.25
HR_WITHIN_BPM = 2.0

SESSION_MIN_MINUTES = 5
SESSION_MIN_HR_MINUTES = 3
ROUND_DECIMALS = 2

REQUIRED_COEFFICIENTS = (
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


def _minute_array(bundle: dict, key: str, fill: float) -> np.ndarray:
    values = np.empty(len(bundle["samples"]), dtype=float)
    for index, row in enumerate(bundle["samples"]):
        value = row.get(key)
        values[index] = fill if value is None else float(value)
    return values


def _runs(labels) -> list[tuple[int, int, str]]:
    runs: list[tuple[int, int, str]] = []
    index = 0
    count = len(labels)
    while index < count:
        raw = labels[index]
        if raw is None:
            index += 1
            continue
        label = str(raw)
        end = index + 1
        while (
            end < count
            and labels[end] is not None
            and str(labels[end]) == label
        ):
            end += 1
        runs.append((index, end, label))
        index = end
    return runs


def _label_groups(groups: dict) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for group_id, spec in groups.items():
        for workout in spec["workouts"]:
            mapping.setdefault(str(workout), group_id)
    return mapping


def _pearson(prediction: np.ndarray, actual: np.ndarray) -> float:
    if prediction.size < 2 or actual.size < 2:
        return float("nan")
    if float(np.std(prediction)) == 0.0 or float(np.std(actual)) == 0.0:
        return float("nan")
    return float(np.corrcoef(prediction, actual)[0, 1])


def _mean_abs(values: np.ndarray) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.mean(np.abs(values)))


def _prepare(days: list[dict]) -> list[dict]:
    records: list[dict] = []
    for bundle in days:
        inputs = day_inputs(bundle)
        ae = _minute_array(bundle, "ae_kcal_min", np.nan)
        steps = _minute_array(bundle, "steps_min", 0.0)
        records.append({
            "date": bundle["date"],
            "bundle": bundle,
            "inputs": inputs,
            "ae": ae,
            "steps": steps,
            "worn": np.isfinite(ae),
            "labels": inputs["workout"],
            "level": bundle["day"].get("hr_level_rts"),
            "has_hr": bool(np.isfinite(inputs["hr"]).any()),
        })
    return records


def _project(record: dict, mode: str, templates: dict, level_med: float,
             coef: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    inputs = record["inputs"]
    worn = record["worn"]
    labels = record["labels"]
    count = worn.size

    ae = np.full(count, np.nan, dtype=float)
    steps = np.zeros(count, dtype=float)
    for minute in range(count):
        if not worn[minute]:
            continue
        raw = labels[minute]
        if raw is None:
            hour_value = float(inputs["hour_local"][minute])
            hour = (
                int(hour_value) % 24
                if math.isfinite(hour_value)
                else (minute // 60) % 24
            )
            ae_rate, step_rate = hour_rate(templates, hour)
        else:
            ae_rate, step_rate = session_rate(templates, str(raw))
        ae[minute] = ae_rate
        steps[minute] = step_rate

    if mode == "stated_intensity":
        for start, end, _label in _runs(labels):
            worn_indices = np.nonzero(worn[start:end])[0] + start
            if worn_indices.size:
                mean_ae = float(np.nanmean(record["ae"][start:end]))
                ae[worn_indices] = mean_ae

    projected = dict(inputs)
    projected["AE_rate"] = ae
    projected["HR_level"] = np.where(
        np.isfinite(inputs["HR_level"]), level_med, np.nan
    )
    _, hr = simulate_day(projected, coef)
    return ae, steps, hr


def _empty_group() -> dict:
    return {
        "energy_pred": [],
        "energy_act": [],
        "steps_pred": [],
        "steps_act": [],
        "hr_err": [],
        "replay_err": [],
        "peak": [],
    }


def _score(records: list[dict], coef: dict, templates: dict,
           level_med: float, mode: str, base_energy: float, base_steps: float,
           groups: dict, label_groups: dict[str, str]) -> tuple[dict, int, int]:
    energy_pred: list[float] = []
    energy_act: list[float] = []
    steps_pred: list[float] = []
    steps_act: list[float] = []
    hr_pred: list[np.ndarray] = []
    hr_obs: list[np.ndarray] = []
    hr_replay: list[np.ndarray] = []

    group_stats = {group_id: _empty_group() for group_id in groups}
    test_sessions = 0
    test_sessions_with_hr = 0

    for record in records:
        proj_ae, proj_steps, proj_hr = _project(
            record, mode, templates, level_med, coef
        )
        recorded_ae = record["ae"]
        recorded_steps = record["steps"]
        energy_pred.append(float(np.nansum(proj_ae)))
        energy_act.append(float(np.nansum(recorded_ae)))
        steps_pred.append(float(np.nansum(proj_steps)))
        steps_act.append(float(np.nansum(recorded_steps)))

        observed = record["inputs"]["hr"]
        replay = record["replay_hr"]
        ok_all = (
            np.isfinite(observed) & np.isfinite(proj_hr) & np.isfinite(replay)
        )
        hr_pred.append(proj_hr[ok_all])
        hr_obs.append(observed[ok_all])
        hr_replay.append(replay[ok_all])

        for start, end, label in _runs(record["labels"]):
            if end - start < SESSION_MIN_MINUTES:
                continue
            test_sessions += 1
            group_id = label_groups.get(label, "other")
            bucket = group_stats.setdefault(group_id, _empty_group())
            ok = ok_all[start:end]
            ok_count = int(ok.sum())
            if ok_count >= SESSION_MIN_HR_MINUTES:
                test_sessions_with_hr += 1

            bucket["energy_pred"].append(
                float(np.nansum(proj_ae[start:end]))
            )
            bucket["energy_act"].append(
                float(np.nansum(recorded_ae[start:end]))
            )
            bucket["steps_pred"].append(
                float(np.nansum(proj_steps[start:end]))
            )
            bucket["steps_act"].append(
                float(np.nansum(recorded_steps[start:end]))
            )

            if ok_count >= SESSION_MIN_HR_MINUTES:
                session_pred = proj_hr[start:end][ok]
                session_obs = observed[start:end][ok]
                session_replay = replay[start:end][ok]
                bucket["hr_err"].append(abs(
                    float(np.mean(session_pred)) - float(np.mean(session_obs))
                ))
                bucket["replay_err"].append(abs(
                    float(np.mean(session_replay))
                    - float(np.mean(session_obs))
                ))
                bucket["peak"].append(
                    float(np.nanmax(proj_hr[start:end]))
                    - float(np.max(session_obs))
                )

    predicted_energy = np.asarray(energy_pred, dtype=float)
    actual_energy = np.asarray(energy_act, dtype=float)
    predicted_steps = np.asarray(steps_pred, dtype=float)
    actual_steps = np.asarray(steps_act, dtype=float)

    def day_metrics(predicted: np.ndarray, actual: np.ndarray,
                    baseline: float) -> dict:
        error = predicted - actual
        return {
            "mae": _mean_abs(error),
            "bias": float(np.mean(error)),
            "mape_median_pct": float(
                np.median(np.abs(error) / np.maximum(actual, 1e-9)) * 100.0
            ),
            "r": _pearson(predicted, actual),
            "actual_median": float(np.median(actual)),
            "baseline_mae": float(np.mean(np.abs(baseline - actual))),
            "n_days": int(actual.size),
        }

    projected_all = (
        np.concatenate(hr_pred) if hr_pred else np.empty(0, dtype=float)
    )
    observed_all = (
        np.concatenate(hr_obs) if hr_obs else np.empty(0, dtype=float)
    )
    replay_all = (
        np.concatenate(hr_replay) if hr_replay else np.empty(0, dtype=float)
    )
    if observed_all.size:
        hr_minute = {
            "mae": _mean_abs(projected_all - observed_all),
            "mae_replay": _mean_abs(replay_all - observed_all),
            "mae_constant": _mean_abs(level_med - observed_all),
            "n_minutes": int(observed_all.size),
        }
    else:
        hr_minute = {
            "mae": None,
            "mae_replay": None,
            "mae_constant": None,
            "n_minutes": 0,
        }

    sessions: dict[str, dict] = {}
    for group_id, bucket in group_stats.items():
        n_sessions = len(bucket["energy_act"])
        n_hr = len(bucket["hr_err"])
        entry: dict = {"n": n_sessions}
        if n_sessions:
            entry["energy_mae"] = _mean_abs(
                np.asarray(bucket["energy_pred"], dtype=float)
                - np.asarray(bucket["energy_act"], dtype=float)
            )
            entry["energy_actual_median"] = float(
                np.median(bucket["energy_act"])
            )
            entry["steps_mae"] = _mean_abs(
                np.asarray(bucket["steps_pred"], dtype=float)
                - np.asarray(bucket["steps_act"], dtype=float)
            )
            entry["steps_actual_median"] = float(
                np.median(bucket["steps_act"])
            )
        else:
            entry["energy_mae"] = None
            entry["energy_actual_median"] = None
            entry["steps_mae"] = None
            entry["steps_actual_median"] = None
        entry["n_hr"] = n_hr
        if n_hr:
            entry["mean_hr_abs_error"] = float(np.mean(bucket["hr_err"]))
            entry["mean_hr_abs_error_replay"] = float(
                np.mean(bucket["replay_err"])
            )
            entry["peak_bias"] = float(np.mean(bucket["peak"]))
        else:
            entry["mean_hr_abs_error"] = None
            entry["mean_hr_abs_error_replay"] = None
            entry["peak_bias"] = None
        sessions[group_id] = entry

    return (
        {
            "energy_day": day_metrics(
                predicted_energy, actual_energy, base_energy
            ),
            "steps_day": day_metrics(
                predicted_steps, actual_steps, base_steps
            ),
            "hr_minute": hr_minute,
            "sessions": sessions,
        },
        test_sessions,
        test_sessions_with_hr,
    )


def _round_value(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, dict):
        return {key: _round_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round_value(item) for item in value]
    if isinstance(value, (int, np.integer)):
        return int(value)
    number = float(value)
    if not math.isfinite(number):
        return None
    return round(number, ROUND_DECIMALS)


def _coefficients(params: dict) -> dict:
    coefficients = params.get("coefficients")
    if not isinstance(coefficients, dict):
        raise ValueError(
            "params.json has no 'coefficients' mapping. Run "
            "tools/fit_hr_model.py --bundle-dir <bundle-dir> --subject "
            "<subject> first to fit them."
        )
    missing = [
        name for name in REQUIRED_COEFFICIENTS if name not in coefficients
    ]
    if missing:
        raise ValueError(
            f"params.json coefficients are missing {', '.join(missing)}, "
            f"which simulate_day needs. Refit with "
            f"tools/fit_hr_model.py --bundle-dir <bundle-dir> --subject "
            f"<subject>."
        )
    return coefficients


def backtest(days: list[dict], params: dict, groups: dict) -> dict:
    """Score the two schedule projections of every TEST day."""
    coef = _coefficients(params)

    data = params.get("data")
    if not isinstance(data, dict) or not data.get("split_date"):
        raise ValueError(
            "params.json has no data.split_date, so FIT and TEST days cannot "
            "be separated. Run tools/fit_hr_model.py --bundle-dir "
            "<bundle-dir> --subject <subject> first."
        )
    split = str(data["split_date"])

    if not days:
        raise ValueError(
            "No day bundles were supplied. Pass the subject's <date>.json "
            "files or load them with load_days()."
        )

    records = _prepare(days)
    fit = [
        record for record in records
        if record["date"] < split and bool(record["worn"].any())
    ]
    test = [
        record for record in records
        if record["date"] >= split and record["has_hr"]
    ]

    if not fit:
        raise ValueError(
            f"No FIT day: no day before split_date {split} has a worn minute "
            f"(ae_kcal_min not null), so there are no activity templates to "
            f"project from. Add days before {split} or refit with an earlier "
            f"split using tools/fit_hr_model.py."
        )
    if not test:
        raise ValueError(
            f"No TEST day: no day on or after split_date {split} has a "
            f"recorded heart rate, so a projection cannot be scored. Add days "
            f"on or after {split} with hr readings."
        )

    levels = [
        float(record["level"]) for record in fit
        if record["level"] is not None
    ]
    if not levels:
        raise ValueError(
            "No FIT day carries hr_level_rts, so level_median is undefined. "
            "Add a FIT day with a resting level or rebuild the bundles with "
            "one."
        )
    level_med = float(np.median(levels))

    templates = build_templates(
        [record["bundle"] for record in fit], groups
    )

    for record in test:
        record["replay_hr"] = simulate_day(record["inputs"], coef)[1]

    fit_energy = [
        float(np.nansum(record["ae"])) for record in fit
    ]
    fit_steps = [
        float(np.nansum(record["steps"])) for record in fit
    ]
    base_energy = float(np.median(fit_energy))
    base_steps = float(np.median(fit_steps))

    label_groups = _label_groups(groups)

    schedule, test_sessions, test_sessions_with_hr = _score(
        test, coef, templates, level_med, "schedule",
        base_energy, base_steps, groups, label_groups,
    )
    stated, _, _ = _score(
        test, coef, templates, level_med, "stated_intensity",
        base_energy, base_steps, groups, label_groups,
    )

    schedule = _round_value(schedule)
    stated = _round_value(stated)
    level_median = round(level_med, ROUND_DECIMALS)

    rules = {
        "ENERGY_BEATS_BASELINE": ENERGY_BEATS_BASELINE,
        "HR_WITHIN_BPM": HR_WITHIN_BPM,
    }

    energy_mae = schedule["energy_day"]["mae"]
    energy_baseline = schedule["energy_day"]["baseline_mae"]
    energy_reliable = bool(
        energy_mae is not None
        and energy_baseline is not None
        and energy_mae <= (1.0 - ENERGY_BEATS_BASELINE) * energy_baseline
    )

    hr_mae = schedule["hr_minute"]["mae"]
    hr_replay = schedule["hr_minute"]["mae_replay"]
    hr_rough = bool(
        hr_mae is not None
        and hr_replay is not None
        and (hr_mae - hr_replay) > HR_WITHIN_BPM
    )

    return {
        "split_date": split,
        "fit_days": len(fit),
        "test_days": len(test),
        "level_median": level_median,
        "rules": rules,
        "schedule": schedule,
        "stated_intensity": stated,
        "energy_reliable": energy_reliable,
        "hr_rough": hr_rough,
        "test_sessions": int(test_sessions),
        "test_sessions_with_hr": int(test_sessions_with_hr),
    }


def _number(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    return f"{float(value):.2f}"


def _render(report: dict, subject: str) -> str:
    lines = [
        f"Projected day backtest - {subject}",
        f"split_date {report['split_date']} | fit days {report['fit_days']}"
        f" | test days {report['test_days']}"
        f" | level median {_number(report['level_median'])}",
        "",
        f"rules: ENERGY_BEATS_BASELINE "
        f"{report['rules']['ENERGY_BEATS_BASELINE']:.2f}, HR_WITHIN_BPM "
        f"{report['rules']['HR_WITHIN_BPM']:.2f}",
        f"energy_reliable {_number(report['energy_reliable'])} "
        f"(schedule energy MAE {_number(report['schedule']['energy_day']['mae'])}"
        f" vs baseline {_number(report['schedule']['energy_day']['baseline_mae'])})",
        f"hr_rough {_number(report['hr_rough'])} "
        f"(schedule HR MAE {_number(report['schedule']['hr_minute']['mae'])}"
        f" vs replay {_number(report['schedule']['hr_minute']['mae_replay'])})",
        f"test sessions {report['test_sessions']} "
        f"(with HR: {report['test_sessions_with_hr']})",
    ]

    for mode in ("schedule", "stated_intensity"):
        section = report[mode]
        energy = section["energy_day"]
        steps = section["steps_day"]
        hr = section["hr_minute"]
        lines.extend([
            "",
            f"=== {mode} ===",
            f"energy per day: n={energy['n_days']} actual median "
            f"{_number(energy['actual_median'])} | MAE {_number(energy['mae'])}"
            f" bias {_number(energy['bias'])} MAPE "
            f"{_number(energy['mape_median_pct'])}% r {_number(energy['r'])}"
            f" | baseline MAE {_number(energy['baseline_mae'])}",
            f"steps per day: n={steps['n_days']} actual median "
            f"{_number(steps['actual_median'])} | MAE {_number(steps['mae'])}"
            f" bias {_number(steps['bias'])} MAPE "
            f"{_number(steps['mape_median_pct'])}% r {_number(steps['r'])}"
            f" | baseline MAE {_number(steps['baseline_mae'])}",
            f"heart rate per minute: n={hr['n_minutes']} forecast "
            f"{_number(hr['mae'])} | replay {_number(hr['mae_replay'])} | "
            f"constant {_number(hr['mae_constant'])}",
            "sessions >=5 min:",
            "  group     n  energy MAE (median)   steps MAE (median)   "
            "HR abs err forecast/replay (n_hr)   peak bias",
        ])
        for group_id, entry in section["sessions"].items():
            lines.append(
                f"  {group_id:<9} {entry['n']:>2}  "
                f"{_number(entry['energy_mae'])} "
                f"({_number(entry['energy_actual_median'])})  "
                f"{_number(entry['steps_mae'])} "
                f"({_number(entry['steps_actual_median'])})  "
                f"{_number(entry['mean_hr_abs_error'])} / "
                f"{_number(entry['mean_hr_abs_error_replay'])} "
                f"(n={entry['n_hr']})  "
                f"{_number(entry['peak_bias'])}"
            )
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Score a schedule-only projection of each TEST day."
    )
    parser.add_argument(
        "--bundle-dir", required=True,
        help="Directory holding <subject>/<date>.json bundles.",
    )
    parser.add_argument(
        "--subject", required=True,
        help="Subject folder name to backtest.",
    )
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle_dir)
    subject_dir = bundle_dir / args.subject
    params_path = subject_dir / "params.json"
    templates_path = subject_dir / "templates.json"

    if not params_path.is_file():
        raise ValueError(
            f"Missing {params_path}: run "
            f"tools/fit_hr_model.py --bundle-dir {bundle_dir} --subject "
            f"{args.subject} first."
        )
    if not templates_path.is_file():
        raise ValueError(
            f"Missing {templates_path}: run "
            f"tools/make_activity_templates.py --bundle-dir {bundle_dir} "
            f"--subject {args.subject} first."
        )

    days = load_days(bundle_dir, args.subject)
    params = json.loads(params_path.read_text(encoding="utf-8"))
    stored = json.loads(templates_path.read_text(encoding="utf-8"))

    groups = kind_groups(load_twin(WEARABLE_XML))
    report = backtest(days, params, groups)
    report["made_at"] = datetime.now(timezone.utc).isoformat()

    stored["projection_report"] = report
    templates_path.write_text(
        json.dumps(stored, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(_render(report, stored.get("label") or args.subject))
    return 0


if __name__ == "__main__":
    sys.exit(main())
