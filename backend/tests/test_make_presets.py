"""
Scenario presets derived from synthetic day bundles.

Every bundle here is a copy of the committed demo day with its samples edited
in tmp_path; no real person's recordings are used.  The tests pin the
pre-registered proxy rules, their boundaries, the data-driven caveats, the
written XML and the output-directory guard.
"""
import copy
import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from bundles import load_bundle, validate_bundle
from tools.make_presets import (
    classify_minutes,
    main,
    summarise,
    write_presets,
)
from xml_converter import patient_xml_to_dict

DEMO = load_bundle("demo", "2025-06-01")
MONDAY = "2025-06-02"
SATURDAY = "2025-06-07"
WEEKDAYS = (
    "2025-06-02",
    "2025-06-03",
    "2025-06-04",
    "2025-06-05",
    "2025-06-06",
)


def _clean_bundle(date: str = MONDAY, subject: str = "s2") -> dict:
    """A copy of the demo day with every sample made non-qualifying."""
    bundle = copy.deepcopy(DEMO)
    bundle["subject"] = subject
    bundle["date"] = date
    for row in bundle["samples"]:
        row["hr"] = None
        row["hr_n"] = 0
        row["ae_kcal_min"] = None
        row["steps_min"] = 0.0
        row["workout"] = None
        row["t_app_c"] = 20.0
        row["be_kcal_min"] = 1.1
    bundle["day"]["hr_level_rts"] = 62.0
    bundle["day"]["minutes_with_hr"] = 0
    bundle["day"]["coverage_hr_min_frac"] = 0.0
    bundle["day"]["coverage_hr_hours"] = 0
    bundle["day"]["dense_minutes"] = 0
    return bundle


def _add(
    bundle: dict,
    hour: float,
    minute: int = 0,
    *,
    ae=0.05,
    steps=0.0,
    workout=None,
    hr=None,
) -> int:
    index = int(round(hour * 60.0)) + minute
    row = bundle["samples"][index]
    row["ae_kcal_min"] = ae
    row["steps_min"] = steps
    row["workout"] = workout
    row["hr"] = hr
    row["hr_n"] = 0 if hr is None else 1
    return index


def _write_bundle(root: Path, bundle: dict) -> Path:
    validate_bundle(bundle, label=f"synthetic {bundle['date']}")
    path = Path(root) / bundle["subject"] / f"{bundle['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _all_states_bundle(
    date: str = MONDAY,
    *,
    sleep_ae: float = 1.0,
    rest_ae: float = 0.1,
    walk_ae: float = 2.0,
    vigorous_ae: float = 2.05,
    walk_steps: float = 20.0,
    vigorous_steps: float = 20.0,
) -> dict:
    bundle = _clean_bundle(date)
    for hour in (0, 1, 2, 3, 4, 5):
        _add(bundle, hour, ae=sleep_ae, steps=0.0)
    for hour in (7, 8, 18, 19):
        _add(bundle, hour, ae=rest_ae, steps=0.0)
    for hour in (9, 10, 11):
        _add(bundle, hour, ae=0.1, steps=0.0)
    _add(
        bundle, 12, ae=walk_ae, steps=walk_steps, workout="Walking"
    )
    _add(
        bundle, 13, ae=vigorous_ae, steps=vigorous_steps, workout="Running"
    )
    return bundle


# ── Precedence and boundaries ───────────────────────────────────────────────


def test_walking_at_three_is_walk_not_sleep():
    bundle = _clean_bundle()
    _add(bundle, 3.0, workout="Walking", ae=2.0, steps=80.0)

    states = classify_minutes([bundle])

    assert (2.0, 80.0, 3.0) in states["walk"]
    assert states["sleep"] == []


def test_a_day_without_a_level_still_classifies():
    # Real exports have days the pipeline gave no resting level.  A minute
    # with a heart rate cannot be shown to sit at or below a level that does
    # not exist, so it is not sleep; one without a heart rate still can be.
    bundle = _clean_bundle()
    bundle["day"]["hr_level_rts"] = None
    _add(bundle, 2.0, hr=50.0)
    _add(bundle, 3.0)

    states = classify_minutes([bundle])

    assert [entry[2] for entry in states["sleep"]] == [3.0]


def test_hour_six_is_not_sleep():
    bundle = _clean_bundle()
    _add(bundle, 6.0)

    states = classify_minutes([bundle])

    assert states["sleep"] == []
    assert all(entry[2] != 6.0 for entries in states.values() for entry in entries)


def test_hour_seventeen_is_not_desk_but_is_awake_rest():
    bundle = _clean_bundle()
    _add(bundle, 17.0)

    states = classify_minutes([bundle])

    assert states["desk_work"] == []
    assert (0.05, 0.0, 17.0) in states["rest_awake"]


def test_saturday_is_not_desk():
    bundle = _clean_bundle(SATURDAY)
    _add(bundle, 10.0)

    states = classify_minutes([bundle])

    assert states["desk_work"] == []
    assert (0.05, 0.0, 10.0) in states["rest_awake"]


def test_steps_eleven_is_not_desk_but_ten_is():
    eleven = _clean_bundle()
    _add(eleven, 10.0, steps=11.0)
    states = classify_minutes([eleven])
    assert states["desk_work"] == []
    assert states["rest_awake"] == []

    ten = _clean_bundle()
    _add(ten, 10.0, steps=10.0)
    states = classify_minutes([ten])
    assert (0.05, 10.0, 10.0) in states["desk_work"]


def test_null_steps_count_as_zero():
    bundle = _clean_bundle()
    _add(bundle, 10.0, steps=None)

    states = classify_minutes([bundle])

    assert (0.05, 0.0, 10.0) in states["desk_work"]


def test_null_ae_is_excluded():
    bundle = _clean_bundle()
    _add(bundle, 10.0, ae=None, steps=0.0)

    states = classify_minutes([bundle])

    assert all(not entries for entries in states.values())


# ── Caveats ─────────────────────────────────────────────────────────────────


def test_weak_caveat_appears_only_below_1000_minutes(tmp_path):
    days = []
    for date in WEEKDAYS:
        bundle = _clean_bundle(date)
        for index in range(9 * 60, 17 * 60):
            _add(bundle, index // 60, index % 60, ae=0.1, steps=0.0)
        _add(bundle, 0.0, ae=0.05, steps=0.0)
        _add(bundle, 7.0, ae=0.1, steps=0.0)
        _add(bundle, 12.0, ae=2.0, steps=20.0, workout="Walking")
        _add(bundle, 13.0, ae=2.2, steps=20.0, workout="Running")
        _write_bundle(tmp_path, bundle)
        days.append(bundle)

    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes(days), days)
    }

    assert summaries["desk_work"]["n_minutes"] >= 1000
    assert not any(
        caveat.startswith("Only")
        for caveat in summaries["desk_work"]["caveats"]
    )
    assert any(
        caveat.startswith("Only")
        for caveat in summaries["sleep"]["caveats"]
    )


def test_sleep_caveat_appears_when_sleep_activity_is_not_lower():
    bundle = _all_states_bundle(sleep_ae=1.0, rest_ae=0.1)

    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes([bundle]), [bundle])
    }

    expected = (
        "Median activity here is not lower than awake rest, so these minutes "
        "are probably not sleep: the watch is rarely worn at night."
    )
    assert expected in summaries["sleep"]["caveats"]
    assert all(
        expected not in summaries[name]["caveats"]
        for name in ("rest_awake", "desk_work", "walk", "vigorous")
    )


def test_sleep_caveat_absent_when_sleep_activity_is_lower():
    bundle = _all_states_bundle(sleep_ae=0.05, rest_ae=0.2)

    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes([bundle]), [bundle])
    }

    expected = (
        "Median activity here is not lower than awake rest, so these minutes "
        "are probably not sleep: the watch is rarely worn at night."
    )
    assert expected not in summaries["sleep"]["caveats"]


def test_indistinguishable_caveat_appears_for_close_medians_and_equal_steps():
    bundle = _all_states_bundle(
        walk_ae=2.0,
        vigorous_ae=2.05,
        walk_steps=20.0,
        vigorous_steps=20.0,
    )

    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes([bundle]), [bundle])
    }

    assert (
        "Indistinguishable from Vigorous in this data."
        in summaries["walk"]["caveats"]
    )
    assert (
        "Indistinguishable from Walk in this data."
        in summaries["vigorous"]["caveats"]
    )


def test_indistinguishable_caveat_absent_when_ae_or_steps_differ():
    far_ae = _all_states_bundle(
        walk_ae=2.0,
        vigorous_ae=2.2,
        walk_steps=20.0,
        vigorous_steps=20.0,
    )
    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes([far_ae]), [far_ae])
    }
    assert not any(
        "Vigorous" in caveat for caveat in summaries["walk"]["caveats"]
    )

    far_steps = _all_states_bundle(
        walk_ae=2.0,
        vigorous_ae=2.05,
        walk_steps=20.0,
        vigorous_steps=21.0,
    )
    summaries = {
        item["name"]: item
        for item in summarise(classify_minutes([far_steps]), [far_steps])
    }
    assert not any(
        "Vigorous" in caveat for caveat in summaries["walk"]["caveats"]
    )


# ── XML output ──────────────────────────────────────────────────────────────


def test_written_xml_round_trips_with_the_medians(tmp_path):
    bundle = _all_states_bundle()
    days = [bundle]
    summaries = summarise(classify_minutes(days), days)
    out_dir = tmp_path / "wearable"

    paths = write_presets(summaries, "s2", out_dir)

    assert {path.name for path in paths} == {
        "sleep.xml",
        "rest_awake.xml",
        "desk_work.xml",
        "walk.xml",
        "vigorous.xml",
    }

    for summary in summaries:
        path = out_dir / f"{summary['name']}.xml"
        text = path.read_text(encoding="utf-8")

        sensors = patient_xml_to_dict(text)
        assert sensors["AE_rate"] == pytest.approx(summary["ae"])
        assert sensors["step_rate"] == pytest.approx(summary["steps"])
        assert sensors["hour_local"] == pytest.approx(summary["hour"])
        # The subject's resting level travels with every preset, so a
        # scenario rests where this person does (the clean bundle is 62).
        assert sensors["HR_level"] == pytest.approx(62.0)
        assert summary["hr_level"] == pytest.approx(62.0)
        # A workout state carries its kind, so a scenario applies that
        # kind's activity gain; rest states carry none.
        expected = {"walk": "is_walk", "vigorous": "is_cardio"}.get(summary["name"])
        for indicator in ("is_walk", "is_strength", "is_cardio"):
            if indicator == expected:
                assert sensors[indicator] == pytest.approx(1.0)
            else:
                assert indicator not in sensors

        root = ET.fromstring(text)
        metadata = root.find("metadata")
        assert metadata.findtext("name") == summary["label"]
        assert metadata.findtext("lamina") == "lamina_wearable"
        assert metadata.findtext("subject") == "s2"
        assert metadata.findtext("order") == str(summary["order"])
        description = metadata.findtext("description")
        assert f"A proxy for {summary['label']}, not a labelled state." in description
        for caveat in summary["caveats"]:
            assert caveat in description


def test_out_directory_must_be_named_wearable(tmp_path):
    bundle = _all_states_bundle()
    summaries = summarise(classify_minutes([bundle]), [bundle])

    with pytest.raises(ValueError, match="named 'wearable'"):
        write_presets(summaries, "s2", tmp_path / "presets")


def test_main_refuses_out_not_named_wearable(tmp_path):
    bundle = _all_states_bundle()
    _write_bundle(tmp_path / "bundles", bundle)

    with pytest.raises(ValueError, match="named 'wearable'"):
        main([
            "--bundle-dir", str(tmp_path / "bundles"),
            "--subject", "s2",
            "--out", str(tmp_path / "presets"),
        ])


def test_main_writes_one_preset_per_state(tmp_path, capsys):
    bundle = _all_states_bundle()
    _write_bundle(tmp_path / "bundles", bundle)
    out_dir = tmp_path / "wearable"

    assert main([
        "--bundle-dir", str(tmp_path / "bundles"),
        "--subject", "s2",
        "--out", str(out_dir),
    ]) == 0

    lines = [line for line in capsys.readouterr().out.splitlines() if line]
    assert len(lines) == 5
    assert {path.name for path in out_dir.iterdir()} == {
        "sleep.xml",
        "rest_awake.xml",
        "desk_work.xml",
        "walk.xml",
        "vigorous.xml",
    }


# ── Guards ──────────────────────────────────────────────────────────────────


def test_zero_minute_state_raises():
    bundle = _clean_bundle()
    _add(bundle, 12.0, ae=2.0, steps=20.0, workout="Walking")
    _add(bundle, 13.0, ae=3.0, steps=25.0, workout="Running")

    states = classify_minutes([bundle])

    with pytest.raises(
        ValueError, match=r"no minutes qualify for sleep under rule"
    ):
        summarise(states, [bundle])


def test_no_bundles_load_raises(tmp_path):
    with pytest.raises(ValueError, match="No bundle folder"):
        main([
            "--bundle-dir", str(tmp_path),
            "--subject", "s2",
            "--out", str(tmp_path / "wearable"),
        ])
