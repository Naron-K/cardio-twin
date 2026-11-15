"""
Activity templates from generated day bundles.

The days are written by test_fit_hr_model's generator into tmp_path, so no real
person's recordings are used.  Every expected number is recomputed here from
the bundle rows, never read back out of the tool's own summary.
"""
import copy
import json

import numpy as np

import pytest

from laminae import load_twin
from tools.fit_hr_model import WEARABLE_XML, day_inputs, load_days
from tools.make_activity_templates import (
    build_templates,
    hour_rate,
    kind_groups,
    main,
    session_rate,
)
from tests.test_fit_hr_model import _write_synthetic


def _groups() -> dict:
    return kind_groups(load_twin(WEARABLE_XML))


def _worn_values(days: list[dict], labels: set) -> list[float]:
    values = []
    for bundle in days:
        for row in bundle["samples"]:
            if row["workout"] in labels and row["ae_kcal_min"] is not None:
                values.append(row["ae_kcal_min"])
    return values


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    root = tmp_path_factory.mktemp("activity_templates")
    _write_synthetic(root, "s7", lagged=False)
    return root, load_days(root, "s7")


def test_kind_groups_reads_the_real_lamina():
    groups = _groups()

    assert set(groups) == {"walk", "strength", "cardio"}
    assert groups["walk"]["indicator"] == "is_walk"
    assert groups["walk"]["label"] == "Walk"
    assert groups["walk"]["workouts"] == ["Walking"]
    assert groups["strength"]["indicator"] == "is_strength"
    assert groups["strength"]["label"] == "Strength"
    assert groups["strength"]["workouts"] == sorted(
        groups["strength"]["workouts"]
    )
    assert "TraditionalStrengthTraining" in groups["strength"]["workouts"]
    assert groups["cardio"]["indicator"] == "is_cardio"
    assert "Running" in groups["cardio"]["workouts"]
    assert "Cycling" in groups["cardio"]["workouts"]


def test_kind_groups_refuses_a_lamina_without_a_day_view_and_a_plain_field():
    class NoDayView:
        lamina_id = "lamina_no_day"
        day_view = None
        attributes = {}

    with pytest.raises(ValueError, match="lamina_no_day"):
        kind_groups(NoDayView())

    class PlainAttr:
        replay_field = "sample.hr"

    class PlainIndicator:
        lamina_id = "lamina_plain"
        day_view = {
            "events": [
                {"indicator": "plain", "group": "walk", "label": "Walk"}
            ]
        }
        attributes = {"plain": PlainAttr()}

    with pytest.raises(ValueError, match="lamina_plain"):
        kind_groups(PlainIndicator())


def test_workout_minutes_equal_the_bundles_worn_minutes(synthetic):
    _, days = synthetic
    templates = build_templates(days, _groups())

    assert templates["workouts"]
    for label, stats in templates["workouts"].items():
        expected = sum(
            1
            for bundle in days
            for row in bundle["samples"]
            if row["workout"] == label and row["ae_kcal_min"] is not None
        )
        assert stats["minutes"] == expected
        assert stats["minutes"] > 0


def test_group_ae_mean_equals_the_bundles_own_mean(synthetic):
    _, days = synthetic
    groups = _groups()
    templates = build_templates(days, groups)

    for group_id in ("walk", "strength", "cardio"):
        values = _worn_values(days, set(groups[group_id]["workouts"]))
        entry = templates["groups"][group_id]
        assert values
        expected = sum(values) / len(values)
        assert entry["ae_mean"] == pytest.approx(expected, abs=1e-4)


def test_group_minutes_are_the_sum_of_their_workouts(synthetic):
    _, days = synthetic
    templates = build_templates(days, _groups())

    for group_id, entry in templates["groups"].items():
        total = sum(
            stats["minutes"]
            for stats in templates["workouts"].values()
            if stats["group"] == group_id
        )
        assert entry["minutes"] == total
        assert entry["offered"] is (entry["sessions"] >= 5)


def test_hourly_has_24_entries_with_the_fallback_rule(synthetic):
    _, days = synthetic
    templates = build_templates(days, _groups())

    counts = [0] * 24
    ae = [0.0] * 24
    steps = [0.0] * 24
    for bundle in days:
        inputs = day_inputs(bundle)
        for minute, row in enumerate(bundle["samples"]):
            if row["ae_kcal_min"] is None or row["workout"] is not None:
                continue
            hour = int(inputs["hour_local"][minute]) % 24
            counts[hour] += 1
            ae[hour] += row["ae_kcal_min"]
            steps[hour] += (
                0.0 if row["steps_min"] is None else row["steps_min"]
            )

    total = sum(counts)
    assert total > 0
    overall_ae = sum(ae) / total
    overall_steps = sum(steps) / total

    hourly = templates["hourly"]
    assert len(hourly) == 24
    assert [item["hour"] for item in hourly] == list(range(24))
    for hour, item in enumerate(hourly):
        assert item["minutes"] == counts[hour]
        if counts[hour] >= 30:
            assert item["fallback"] is False
            assert item["ae_mean"] == pytest.approx(
                ae[hour] / counts[hour], abs=1e-4
            )
            assert item["steps_mean"] == pytest.approx(
                steps[hour] / counts[hour], abs=1e-4
            )
        else:
            assert item["fallback"] is True
            assert item["ae_mean"] == pytest.approx(overall_ae, abs=1e-4)
            assert item["steps_mean"] == pytest.approx(
                overall_steps, abs=1e-4
            )


def _entry(minutes, ae, steps) -> dict:
    return {
        "minutes": minutes,
        "ae_mean": ae,
        "steps_mean": steps,
        "sessions": 0,
        "session_ae": None,
    }


def _hand_templates() -> dict:
    return {
        "workouts": {
            "long": {**_entry(30, 2.0, 10.0), "group": "walk"},
            "short": {**_entry(29, 3.0, 11.0), "group": "walk"},
            "tiny": {**_entry(5, 4.0, 12.0), "group": "cardio"},
        },
        "groups": {
            "walk": {**_entry(10, 1.5, 8.0), "label": "Walk", "offered": True},
            "cardio": {
                **_entry(9, 0.5, 2.0), "label": "Cardio", "offered": False
            },
        },
        "all_sessions": _entry(100, 1.0, 5.0),
        "hourly": [
            {
                "hour": hour,
                "ae_mean": 1.25,
                "steps_mean": 2.5,
                "minutes": 40,
                "fallback": False,
            }
            for hour in range(24)
        ],
    }


def test_session_rate_falls_back_from_label_to_group_to_all_sessions():
    templates = _hand_templates()

    assert session_rate(templates, "long") == (2.0, 10.0)
    assert session_rate(templates, "short") == (1.5, 8.0)
    assert session_rate(templates, "tiny") == (1.0, 5.0)
    assert session_rate(templates, "absent") == (1.0, 5.0)

    empty = {
        "workouts": {"none": {**_entry(0, None, None), "group": None}},
        "groups": {},
        "all_sessions": _entry(0, None, None),
    }
    with pytest.raises(ValueError, match="No recorded minutes"):
        session_rate(empty, "none")


def test_hour_rate_reads_the_hour_and_refuses_outside_0_to_23():
    templates = _hand_templates()

    assert hour_rate(templates, 0) == (1.25, 2.5)
    assert hour_rate(templates, 23) == (1.25, 2.5)
    with pytest.raises(ValueError):
        hour_rate(templates, -1)
    with pytest.raises(ValueError):
        hour_rate(templates, 24)


def test_build_templates_refuses_no_days():
    with pytest.raises(ValueError, match="No day bundles"):
        build_templates([], {})


def test_build_templates_refuses_days_without_a_worn_minute(synthetic):
    _, days = synthetic
    bundle = copy.deepcopy(days[0])
    for row in bundle["samples"]:
        row["ae_kcal_min"] = None
    with pytest.raises(ValueError, match="worn minute"):
        build_templates([bundle], _groups())


def test_build_templates_refuses_negative_or_non_finite_rates(synthetic):
    _, days = synthetic

    negative = copy.deepcopy(days[0])
    negative["samples"][0]["ae_kcal_min"] = -0.5
    with pytest.raises(ValueError, match="ae_kcal_min"):
        build_templates([negative], _groups())

    non_finite = copy.deepcopy(days[0])
    non_finite["samples"][0]["steps_min"] = float("inf")
    with pytest.raises(ValueError, match="steps_min"):
        build_templates([non_finite], _groups())


def test_build_templates_refuses_mixed_subjects(synthetic):
    _, days = synthetic
    first = copy.deepcopy(days[0])
    second = copy.deepcopy(days[1])
    second["subject"] = "s8"
    with pytest.raises(ValueError, match="one subject"):
        build_templates([first, second], _groups())


def test_main_writes_templates_and_a_second_run_drops_projection_report(
    synthetic, tmp_path, capsys
):
    root, _ = synthetic
    out = tmp_path / "templates.json"
    argv = [
        "--bundle-dir", str(root),
        "--subject", "s7",
        "--out", str(out),
    ]

    assert main(argv) == 0
    capsys.readouterr()

    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["subject"] == "s7"
    assert data["label"] == "s7"
    assert data["lamina"] == "lamina_wearable"
    assert data["applies_to"] == (
        "s7 only: from s7's recordings; not a population value"
    )
    assert "made_at" in data
    for key in (
        "workouts", "groups", "all_sessions", "hourly", "steps_outside",
        "awake", "level", "t_app", "days", "first_date", "last_date",
    ):
        assert key in data

    data["projection_report"] = {"from": "another tool"}
    out.write_text(json.dumps(data, indent=2), encoding="utf-8")

    assert main(argv) == 0
    printed = capsys.readouterr().out
    rewritten = json.loads(out.read_text(encoding="utf-8"))
    assert "projection_report" not in rewritten
    assert (
        "projection_report dropped: rerun tools/backtest_planned_day.py"
        in printed
    )


def test_main_defaults_to_the_subject_folder(synthetic):
    root, _ = synthetic
    assert main(["--bundle-dir", str(root), "--subject", "s7"]) == 0
    assert (root / "s7" / "templates.json").is_file()


def test_main_refuses_an_output_parent_that_does_not_exist(
    synthetic, tmp_path
):
    root, _ = synthetic
    missing = tmp_path / "missing" / "templates.json"
    with pytest.raises(ValueError, match="parent directory"):
        main([
            "--bundle-dir", str(root),
            "--subject", "s7",
            "--out", str(missing),
        ])


def test_steps_outside_counts_every_minute_outside_sessions(synthetic):
    """Steps outside sessions add up every non-session minute, worn or not."""
    _root, loaded = synthetic
    days = copy.deepcopy(loaded)
    # Unworn minutes still carry steps (a phone records them); they count.
    for row in days[0]["samples"][:60]:
        row["ae_kcal_min"] = None
        row["steps_min"] = 10
    for day in days:
        for row in day["samples"]:
            if row["steps_min"] is None:
                row["steps_min"] = 0
    expected = []
    for day in days:
        worn = sum(row["ae_kcal_min"] is not None for row in day["samples"])
        if worn >= 720:
            expected.append(sum(
                (row["steps_min"] or 0)
                for row in day["samples"] if row["workout"] is None
            ))
    templates = build_templates(days, _groups())
    assert templates["steps_outside"]["days"] == len(expected)
    assert templates["steps_outside"]["p50"] == int(round(float(np.percentile(expected, 50))))
