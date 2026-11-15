"""
Backtesting a day projected from its schedule against generated recordings.

The days are written by test_fit_hr_model's generator into tmp_path, so no real
person's recordings are used.  Expected counts and flags are recomputed here
from the bundles and the returned report, never trusted from the tool alone.
"""
import copy
import json
import shutil

import numpy as np
import pytest

pytest.importorskip("scipy")

from laminae import load_twin  # noqa: E402
from tools.backtest_planned_day import (  # noqa: E402
    ENERGY_BEATS_BASELINE,
    HR_WITHIN_BPM,
    backtest,
    main as backtest_main,
)
from tools.fit_hr_model import (  # noqa: E402
    WEARABLE_XML,
    day_inputs,
    load_days,
    main as fit_main,
)
from tools.make_activity_templates import (  # noqa: E402
    kind_groups,
    main as templates_main,
)
from tests.test_fit_hr_model import _write_synthetic  # noqa: E402


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    root = tmp_path_factory.mktemp("backtest")
    _write_synthetic(root, "s7", lagged=True)
    assert fit_main(["--bundle-dir", str(root), "--subject", "s7"]) == 0
    assert templates_main(["--bundle-dir", str(root), "--subject", "s7"]) == 0

    templates_path = root / "s7" / "templates.json"
    before = json.loads(templates_path.read_text(encoding="utf-8"))
    params = json.loads(
        (root / "s7" / "params.json").read_text(encoding="utf-8")
    )

    assert backtest_main(
        ["--bundle-dir", str(root), "--subject", "s7"]
    ) == 0
    after = json.loads(templates_path.read_text(encoding="utf-8"))
    return {
        "root": root,
        "before": before,
        "after": after,
        "params": params,
    }


def _groups() -> dict:
    return kind_groups(load_twin(WEARABLE_XML))


def _day_and_params(run: dict) -> tuple[list[dict], dict, dict]:
    return (
        load_days(run["root"], "s7"),
        copy.deepcopy(run["params"]),
        _groups(),
    )


def _test_inputs(run: dict) -> list[dict]:
    split = run["params"]["data"]["split_date"]
    selected = []
    for bundle in load_days(run["root"], "s7"):
        if bundle["date"] < split:
            continue
        inputs = day_inputs(bundle)
        if np.isfinite(inputs["hr"]).any():
            selected.append(inputs)
    return selected


def test_main_writes_projection_report_and_keeps_the_other_keys(run):
    after = run["after"]
    assert "projection_report" in after

    report = after["projection_report"]
    assert report["made_at"]
    assert report["rules"]["ENERGY_BEATS_BASELINE"] == ENERGY_BEATS_BASELINE
    assert report["rules"]["HR_WITHIN_BPM"] == HR_WITHIN_BPM
    for key in (
        "split_date", "fit_days", "test_days", "level_median", "rules",
        "schedule", "stated_intensity", "energy_reliable", "hr_rough",
        "test_sessions", "test_sessions_with_hr",
    ):
        assert key in report

    remaining = dict(after)
    del remaining["projection_report"]
    assert remaining == run["before"]


def test_replay_hr_error_is_small(run):
    report = run["after"]["projection_report"]
    assert report["schedule"]["hr_minute"]["mae_replay"] < 4.0


def test_stating_intensity_does_not_make_energy_worse(run):
    report = run["after"]["projection_report"]
    assert (
        report["stated_intensity"]["energy_day"]["mae"]
        <= report["schedule"]["energy_day"]["mae"]
    )


def test_rule_flags_equal_the_formulas_on_the_returned_numbers(run):
    report = run["after"]["projection_report"]
    rules = report["rules"]
    energy = report["schedule"]["energy_day"]
    hr = report["schedule"]["hr_minute"]

    expected_energy = energy["mae"] <= (
        (1.0 - rules["ENERGY_BEATS_BASELINE"]) * energy["baseline_mae"]
    )
    expected_hr = (hr["mae"] - hr["mae_replay"]) > rules["HR_WITHIN_BPM"]

    assert report["energy_reliable"] is expected_energy
    assert report["hr_rough"] is expected_hr


def test_test_sessions_equals_an_independent_count_of_label_runs(run):
    counted = 0
    with_hr = 0
    for inputs in _test_inputs(run):
        labels = inputs["workout"]
        index = 0
        count = labels.size
        while index < count:
            if labels[index] is None:
                index += 1
                continue
            label = labels[index]
            end = index + 1
            while (
                end < count
                and labels[end] is not None
                and labels[end] == label
            ):
                end += 1
            if end - index >= 5:
                counted += 1
            index = end

    report = run["after"]["projection_report"]
    assert report["test_sessions"] == counted
    assert report["test_sessions_with_hr"] <= report["test_sessions"]


def test_no_fit_day_raises(run):
    days, params, groups = _day_and_params(run)
    params["data"]["split_date"] = "1900-01-01"
    with pytest.raises(ValueError, match="No FIT day"):
        backtest(days, params, groups)


def test_no_test_day_raises(run):
    days, params, groups = _day_and_params(run)
    params["data"]["split_date"] = "2999-01-01"
    with pytest.raises(ValueError, match="No TEST day"):
        backtest(days, params, groups)


def test_no_level_on_fit_days_raises(run):
    days, params, groups = _day_and_params(run)
    for bundle in days:
        bundle["day"]["hr_level_rts"] = None
    with pytest.raises(ValueError, match="hr_level_rts"):
        backtest(days, params, groups)


def test_missing_split_date_raises(run):
    days, params, groups = _day_and_params(run)
    del params["data"]["split_date"]
    with pytest.raises(ValueError, match="split_date"):
        backtest(days, params, groups)


def test_missing_simulate_day_coefficient_raises(run):
    days, params, groups = _day_and_params(run)
    del params["coefficients"]["k_I"]
    with pytest.raises(ValueError, match="k_I"):
        backtest(days, params, groups)


def test_main_refuses_a_missing_params_json(tmp_path):
    _write_synthetic(tmp_path, "s7", lagged=True)
    with pytest.raises(ValueError, match="fit_hr_model"):
        backtest_main(["--bundle-dir", str(tmp_path), "--subject", "s7"])


def test_main_refuses_a_missing_templates_json(run, tmp_path):
    shutil.copytree(
        run["root"] / "s7",
        tmp_path / "s7",
        ignore=shutil.ignore_patterns("templates.json"),
    )
    with pytest.raises(ValueError, match="make_activity_templates"):
        backtest_main(["--bundle-dir", str(tmp_path), "--subject", "s7"])
