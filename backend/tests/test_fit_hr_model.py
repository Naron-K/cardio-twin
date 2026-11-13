"""
Fitting the wearable lamina's coefficients from synthetic day bundles.

All data here is generated in tmp_path; no real person's recordings are used.
The parity tests replay the committed demo bundle (and one copy with a gap in
active energy) through a Session and check that simulate_day reproduces the
lamina minute for minute.
"""
import copy
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("scipy")

from bundles import load_bundle, validate_bundle  # noqa: E402
from laminae import LAMINA_DIR, load_twin  # noqa: E402
from session import Session  # noqa: E402
from signal_source import ReplaySource  # noqa: E402
from tools.fit_hr_model import (  # noqa: E402
    COEFFICIENT_NAMES,
    LAG_RULE_BPM,
    day_inputs,
    fit,
    load_days,
    main,
    simulate_day,
)

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"
DEMO = load_bundle("demo", "2025-06-01")

TRUE = {
    "HR_offset": -8.0,
    "A_circ": 5.0,
    "phi_circ": 16.0,
    "k_T": 0.3,
    "T_ref": 22.0,
    "k_I": 14.0,
    "p_I": 0.8,
    "tau_on": 40.0,
    "tau_off": 100.0,
    "HR_max": 200.0,
}

N_DAYS = 12
T_APP_DAYS = (15.0, 35.0, 20.0, 30.0, 17.0, 33.0,
              22.0, 28.0, 16.0, 34.0, 19.0, 31.0)
WORKOUT_LABELS = (
    "Walking",
    "Running",
    "Cycling",
    "TraditionalStrengthTraining",
)


def _seed_from_twin() -> dict:
    twin = load_twin(WEARABLE)
    return {
        name: float(twin.attributes[name].baseline)
        for name in COEFFICIENT_NAMES
    }


def _replay_series(bundle: dict):
    session = Session(lamina=WEARABLE)
    feed = ReplaySource(session.twin, bundle)
    n = len(bundle["samples"])
    target = np.full(n, np.nan)
    model = np.full(n, np.nan)
    target_stale = np.zeros(n, dtype=bool)
    model_stale = np.zeros(n, dtype=bool)

    for index in range(n):
        snapshot = session.tick(feed.next(), missing=feed.last_missing)
        target_entry = snapshot["computed"]["HR_target"]
        model_entry = snapshot["computed"]["HR_model"]
        target_stale[index] = target_entry["stale"]
        model_stale[index] = model_entry["stale"]
        if not target_entry["stale"]:
            target[index] = target_entry["value"]
        if not model_entry["stale"]:
            model[index] = model_entry["value"]

    return target, model, target_stale, model_stale


def _assert_parity(bundle: dict) -> None:
    twin = load_twin(WEARABLE)
    defaults = {
        name: float(twin.attributes[name].baseline)
        for name in COEFFICIENT_NAMES
    }
    inputs = day_inputs(bundle)
    target, model = simulate_day(inputs, defaults)
    replayed_target, replayed_model, target_stale, model_stale = (
        _replay_series(bundle)
    )

    assert np.array_equal(np.isnan(target), target_stale)
    assert np.array_equal(np.isnan(model), model_stale)
    np.testing.assert_allclose(
        target[~target_stale], replayed_target[~target_stale], atol=1e-9
    )
    np.testing.assert_allclose(
        model[~model_stale], replayed_model[~model_stale], atol=1e-9
    )


def test_simulate_day_matches_session_on_demo_bundle():
    _assert_parity(DEMO)


def test_simulate_day_matches_session_when_ae_is_missing():
    bundle = copy.deepcopy(DEMO)
    for row in bundle["samples"][600:660]:
        row["ae_kcal_min"] = None
    validate_bundle(bundle, label="demo-with-gap")
    _assert_parity(bundle)


# ── Synthetic day generation (same shape as tools/make_demo_bundle.py) ──────


def _make_day(day_index: int, lagged: bool) -> dict:
    rng = random.Random(20250601 + day_index)
    n = 1440
    minutes = np.arange(n)
    hour = minutes / 60.0
    t_app_daily = T_APP_DAYS[day_index]
    t_app = t_app_daily + 1.0 * np.cos(2.0 * math.pi * (hour - 15.0) / 24.0)

    ae = np.array([rng.uniform(0.05, 0.45) for _ in range(n)])
    labels = [None] * n
    start = 470 + rng.randint(0, 40)
    for _ in range(rng.randint(2, 3)):
        length = rng.randint(20, 40)
        if start + length > 1180:
            break
        intensity = rng.uniform(1.2, 3.0)
        label = rng.choice(WORKOUT_LABELS)
        for offset in range(length):
            phase = (offset // 6) % 2
            ae[start + offset] = intensity * (1.6 if phase == 0 else 0.4)
            labels[start + offset] = label
        start += length + rng.randint(70, 120)

    circadian = TRUE["A_circ"] * np.cos(
        2.0 * math.pi * (hour - TRUE["phi_circ"]) / 24.0
    )
    thermal = TRUE["k_T"] * np.maximum(0.0, t_app - TRUE["T_ref"])
    drive = TRUE["k_I"] * np.power(ae, TRUE["p_I"])
    target = np.clip(
        62.0 + TRUE["HR_offset"] + circadian + thermal + drive,
        35.0,
        TRUE["HR_max"],
    )

    if lagged:
        course = [float(target[0])]
        for value in target[1:]:
            previous = course[-1]
            tau = TRUE["tau_on"] if value > previous else TRUE["tau_off"]
            alpha = 1.0 - math.exp(-60.0 / tau)
            course.append(previous + alpha * (value - previous))
        course = np.asarray(course)
    else:
        course = target

    measured = np.clip(
        np.round(course + rng.gauss(0.0, 2.0), 1), 20.0, 240.0
    )

    samples = []
    for minute in range(n):
        label = labels[minute]
        if label is not None:
            hr = float(measured[minute])
            hr_n = 12
        elif minute % 4 == 0:
            hr = float(measured[minute])
            hr_n = 1
        else:
            hr = None
            hr_n = 0
        samples.append({
            "t": minute * 60,
            "hr": hr,
            "hr_n": hr_n,
            "ae_kcal_min": round(float(ae[minute]), 4),
            "be_kcal_min": 1.1,
            "steps_min": 0.0,
            "t_app_c": round(float(t_app[minute]), 1),
            "rh_pct": 60.0,
            "workout": label,
        })

    minutes_with_hr = sum(1 for row in samples if row["hr"] is not None)
    dense_minutes = sum(1 for row in samples if row["hr_n"] >= 6)
    bundle = {
        "schema_version": 1,
        "subject": "s2",
        "date": (date(2025, 7, 1) + timedelta(days=day_index)).isoformat(),
        "timezone": "UTC",
        "grid_s": 60,
        "synthetic": True,
        "samples": samples,
        "day": {
            "hr_level_rts": 62.0,
            "n_minutes": n,
            "minutes_with_hr": minutes_with_hr,
            "coverage_hr_min_frac": round(minutes_with_hr / n, 3),
            "coverage_hr_hours": len(
                {row["t"] // 3600 for row in samples if row["hr"] is not None}
            ),
            "dense_minutes": dense_minutes,
            "basal_source": "synthetic",
        },
    }
    validate_bundle(bundle, label=f"synthetic day {day_index}")
    return bundle


def _write_bundle(root: Path, bundle: dict) -> Path:
    path = Path(root) / bundle["subject"] / f"{bundle['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _write_synthetic(root: Path, subject: str, lagged: bool) -> None:
    for day_index in range(N_DAYS):
        bundle = _make_day(day_index, lagged=lagged)
        bundle["subject"] = subject
        _write_bundle(root, bundle)


@pytest.fixture(scope="module")
def lagged_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("lagged")
    _write_synthetic(root, "s2", lagged=True)
    assert main(["--bundle-dir", str(root), "--subject", "s2"]) == 0
    params = json.loads(
        (root / "s2" / "params.json").read_text(encoding="utf-8")
    )
    return root, params


@pytest.fixture(scope="module")
def no_lag_run(tmp_path_factory):
    root = tmp_path_factory.mktemp("no_lag")
    _write_synthetic(root, "s2", lagged=False)
    assert main(["--bundle-dir", str(root), "--subject", "s2"]) == 0
    params = json.loads(
        (root / "s2" / "params.json").read_text(encoding="utf-8")
    )
    return root, params


def test_recovers_true_coefficients(lagged_run):
    _, params = lagged_run
    coef = params["coefficients"]

    assert abs(coef["HR_offset"] - TRUE["HR_offset"]) <= 2.0
    assert abs(coef["k_I"] - TRUE["k_I"]) / TRUE["k_I"] <= 0.25
    assert abs(coef["tau_on"] - TRUE["tau_on"]) / TRUE["tau_on"] <= 0.30
    assert abs(coef["tau_off"] - TRUE["tau_off"]) / TRUE["tau_off"] <= 0.30
    assert params["lag_rule"]["passed"] is True
    assert params["lag_rule"]["shipped"] == "lagged"
    assert params["lag_rule"]["lagged_test_mae"] <= (
        params["lag_rule"]["no_lag_test_mae"] - LAG_RULE_BPM
    )


def test_no_lag_data_ships_zero_taus(no_lag_run):
    _, params = no_lag_run
    assert params["lag_rule"]["passed"] is False
    assert params["lag_rule"]["shipped"] == "no_lag"
    assert params["coefficients"]["tau_on"] == 0.0
    assert params["coefficients"]["tau_off"] == 0.0


def _dense_starts(days: list[dict]) -> list[tuple[str, int]]:
    starts = []
    for bundle in days:
        inputs = day_inputs(bundle)
        labels = inputs["workout"]
        hr_n = inputs["hr_n"]
        index = 0
        while index < labels.size:
            label = labels[index]
            if label is None:
                index += 1
                continue
            end = index + 1
            while end < labels.size and labels[end] == label:
                end += 1
            length = end - index
            if length >= 10 and float(np.mean(hr_n[index:end])) >= 6.0:
                starts.append((bundle["date"], index))
            index = end
    starts.sort()
    return starts


def test_split_leaves_all_test_workouts_after_fit(lagged_run):
    root, _ = lagged_run
    days = load_days(root, "s2")
    starts = _dense_starts(days)
    n_fit = max(1, min(int(math.floor(0.70 * len(starts))), len(starts) - 1))
    assert starts[n_fit - 1] < starts[n_fit]


def test_params_json_is_complete_and_usable(lagged_run):
    root, params = lagged_run
    written = json.loads(
        (root / "s2" / "params.json").read_text(encoding="utf-8")
    )
    assert written == params

    assert params["schema_version"] == 1
    assert params["subject"] == "s2"
    assert params["lamina"] == "lamina_wearable"
    for name in COEFFICIENT_NAMES:
        assert name in params["coefficients"]
    for key in ("residual_sd", "outcome_tolerance", "lag_rule", "data",
                "metrics"):
        assert key in params
    for key in ("threshold_bpm", "lagged_test_mae", "no_lag_test_mae",
                "passed", "shipped", "lagged_coefficients"):
        assert key in params["lag_rule"]
    for key in ("days", "first_date", "last_date", "split_date",
                "quiet_minutes_fit", "quiet_minutes_test", "workouts_fit",
                "workouts_test", "basal_sources"):
        assert key in params["data"]
    assert "overall" in params["metrics"]["stage_b"]
    assert "median_per_window" in params["metrics"]["stage_b"]
    assert "per_type" in params["metrics"]["stage_b"]
    assert "rounds" in params["metrics"]
    assert len(params["lag_rule"]["lagged_coefficients"]) == len(
        COEFFICIENT_NAMES
    )

    def walk(node):
        if isinstance(node, dict):
            for item in node.values():
                walk(item)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)):
            assert math.isfinite(float(node))

    walk(params)

    ReplaySource(
        load_twin(WEARABLE), DEMO, params=params["coefficients"]
    )


# ── Guards ──────────────────────────────────────────────────────────────────


def test_empty_folder_raises(tmp_path):
    (tmp_path / "s2").mkdir()
    with pytest.raises(ValueError, match="No day bundles"):
        load_days(tmp_path, "s2")


def test_bundle_of_another_subject_raises(tmp_path):
    bundle = _make_day(0, lagged=True)
    bundle["subject"] = "other"
    path = tmp_path / "s2" / f"{bundle['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    with pytest.raises(ValueError, match="bundle subject"):
        load_days(tmp_path, "s2")


def test_too_few_workouts_raises(tmp_path):
    bundle = _make_day(0, lagged=True)
    for row in bundle["samples"]:
        if row["workout"] is not None:
            row["workout"] = None
            if not row["t"] // 60 % 4 == 0:
                row["hr"] = None
                row["hr_n"] = 0
            else:
                row["hr_n"] = 1
    bundle["day"]["dense_minutes"] = 0
    validate_bundle(bundle, label="no-workouts")
    days = [bundle]
    with pytest.raises(ValueError, match="not enough data to fit"):
        fit(days, _seed_from_twin())


def test_missing_seed_coefficient_raises():
    seed = _seed_from_twin()
    del seed["tau_on"]
    with pytest.raises(ValueError, match="missing coefficient"):
        fit([_make_day(0, lagged=True)], seed)
