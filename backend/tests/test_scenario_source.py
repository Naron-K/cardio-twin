"""
Scenario presets and ScenarioSource.

Every preset used here is written into tmp_path; these tests never read the
real presets directory.  The wearable lamina is the worked example because it
is the one with a declared observed measurement (`HR_obs`) and a set of
coefficients, which are the two cases a scenario has to get right.
"""
import math
from pathlib import Path

import pytest

from laminae import LAMINA_DIR, load_twin
from scenario_presets import UnknownPreset, list_presets, load_preset
from session import Session
from signal_source import ScenarioSource

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"


def _write_preset(
    directory: Path,
    stem: str,
    values: dict,
    *,
    lamina: str | None = "lamina_wearable",
    label: str | None = None,
    description: str = "",
    subject: str | None = None,
    order: int | None = None,
    nested: str = "",
) -> Path:
    path = Path(directory) / nested / f"{stem}.xml"
    path.parent.mkdir(parents=True, exist_ok=True)

    metadata = [f"    <name>{label or stem.title()}</name>"]
    if lamina is not None:
        metadata.append(f"    <lamina>{lamina}</lamina>")
    if subject is not None:
        metadata.append(f"    <subject>{subject}</subject>")
    if order is not None:
        metadata.append(f"    <order>{order}</order>")
    if description:
        metadata.append(f"    <description>{description}</description>")

    sensors = [
        f"    <{attr_id}>{value}</{attr_id}>"
        for attr_id, value in values.items()
    ]
    path.write_text(
        "<patient>\n"
        "  <metadata>\n"
        + "\n".join(metadata)
        + "\n  </metadata>\n"
        "  <sensor_data>\n"
        + "\n".join(sensors)
        + "\n  </sensor_data>\n"
        "</patient>\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def presets(tmp_path):
    _write_preset(
        tmp_path,
        "rest",
        {"AE_rate": 0.31, "step_rate": 0, "hour_local": 17.7},
        label="Rest",
        order=1,
    )
    _write_preset(
        tmp_path,
        "walk",
        {"AE_rate": 3.22, "step_rate": 106, "hour_local": 17.1},
        label="Walk",
        subject="s2",
        order=2,
        description="Walking home",
    )
    return tmp_path


def _load(tmp_path: Path, name: str) -> dict:
    return load_preset("lamina_wearable", name, tmp_path)


def _target(twin, values: dict) -> float:
    """The hand-computed HR_target for a scenario's inputs and coefficients."""
    def coefficient(name: str) -> float:
        return float(twin.attributes[name].baseline)

    hour = values.get("hour_local", twin.attributes["hour_local"].baseline)
    ae_rate = values.get("AE_rate", twin.attributes["AE_rate"].baseline)
    t_app = values.get("T_app", twin.attributes["T_app"].baseline)

    total = (
        coefficient("HR_level")
        + coefficient("HR_offset")
        + coefficient("A_circ")
        * math.cos(2.0 * math.pi * (hour - coefficient("phi_circ")) / 24.0)
        + coefficient("k_T") * max(0.0, t_app - coefficient("T_ref"))
        + coefficient("k_I") * ae_rate ** coefficient("p_I")
    )
    return max(35.0, min(coefficient("HR_max"), total))


# ── list_presets ─────────────────────────────────────────────────────

def test_list_presets_returns_only_this_lamina_sorted(tmp_path):
    _write_preset(tmp_path, "rest", {"AE_rate": 0.31}, label="Rest", order=2)
    _write_preset(tmp_path, "walk", {"AE_rate": 3.22}, label="Walk", order=1)
    _write_preset(
        tmp_path, "other", {"AE_rate": 1.0},
        lamina="lamina_metabolic", label="Other", order=0,
    )
    _write_preset(tmp_path, "normal", {"HR": 72}, lamina=None, label="Normal")
    (tmp_path / "broken.xml").write_text(
        "<patient><metadata>", encoding="utf-8"
    )

    listed = list_presets("lamina_wearable", tmp_path)

    assert [preset["name"] for preset in listed] == ["walk", "rest"]
    assert listed[0]["label"] == "Walk"
    assert listed[0]["order"] == 1
    assert listed[0]["subject"] is None
    assert listed[1]["label"] == "Rest"


def test_list_presets_still_lists_the_rest_when_one_file_is_malformed(tmp_path):
    _write_preset(tmp_path, "walk", {"AE_rate": 3.22}, order=1)
    _write_preset(tmp_path, "bad_order", {"AE_rate": 1.0}, order="soon")
    (tmp_path / "not_xml.xml").write_text("not xml at all", encoding="utf-8")

    assert [preset["name"] for preset in list_presets(
        "lamina_wearable", tmp_path
    )] == ["walk"]


# ── load_preset guards ───────────────────────────────────────────────

def test_load_preset_returns_metadata_and_values(tmp_path):
    _write_preset(
        tmp_path,
        "walk",
        {"AE_rate": 3.22, "step_rate": 106, "hour_local": 17.1},
        label="Walk",
        subject="s2",
        order=4,
        description="Walking home",
    )

    preset = load_preset("lamina_wearable", "walk", tmp_path)

    assert preset["name"] == "walk"
    assert preset["label"] == "Walk"
    assert preset["description"] == "Walking home"
    assert preset["subject"] == "s2"
    assert preset["order"] == 4
    assert preset["values"] == {
        "AE_rate": 3.22,
        "step_rate": 106.0,
        "hour_local": 17.1,
    }


@pytest.mark.parametrize("name", ["../walk", "Walk", "a/b", ""])
def test_load_preset_refuses_a_name_that_is_not_an_identifier(tmp_path, name):
    _write_preset(tmp_path, "walk", {"AE_rate": 3.22})

    with pytest.raises(ValueError):
        load_preset("lamina_wearable", name, tmp_path)


def test_an_unknown_name_lists_the_names_that_exist(tmp_path):
    _write_preset(tmp_path, "walk", {"AE_rate": 3.22})
    _write_preset(tmp_path, "rest", {"AE_rate": 0.31})

    with pytest.raises(UnknownPreset) as caught:
        load_preset("lamina_wearable", "nope", tmp_path)

    message = str(caught.value)
    assert "nope" in message
    assert "walk" in message
    assert "rest" in message


def test_another_lamina_s_preset_is_unknown_here(tmp_path):
    _write_preset(
        tmp_path, "other", {"AE_rate": 1.0}, lamina="lamina_metabolic"
    )

    with pytest.raises(UnknownPreset):
        load_preset("lamina_wearable", "other", tmp_path)


def test_load_preset_refuses_nan_and_names_the_file_and_element(tmp_path):
    path = _write_preset(tmp_path, "bad", {"AE_rate": float("nan")})

    with pytest.raises(ValueError) as caught:
        load_preset("lamina_wearable", "bad", tmp_path)

    message = str(caught.value)
    assert str(path) in message
    assert "AE_rate" in message


def test_load_preset_refuses_empty_sensor_data(tmp_path):
    path = _write_preset(tmp_path, "empty", {})

    with pytest.raises(ValueError) as caught:
        load_preset("lamina_wearable", "empty", tmp_path)

    message = str(caught.value)
    assert str(path) in message
    assert "sensor_data" in message


# ── ScenarioSource ───────────────────────────────────────────────────

def test_observed_measurement_is_omitted_and_named(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "walk"))

    readings = source.next()

    assert "HR_obs" not in readings
    assert "HR_obs" in source.last_missing
    assert readings["AE_rate"] == pytest.approx(3.22)
    assert readings["step_rate"] == pytest.approx(106.0)
    assert readings["hour_local"] == pytest.approx(17.1)


def test_coefficients_rest_at_declared_baselines(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "walk"))

    readings = source.next()

    for coefficient in ("HR_level", "HR_offset", "k_I", "p_I", "tau_on"):
        assert readings[coefficient] == pytest.approx(
            twin.attributes[coefficient].baseline
        )
    assert source.status()["coefficients"] == "declared defaults"
    assert "fitted" not in source.describe()


def test_fitted_params_supply_the_coefficients(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(
        twin, _load(presets, "walk"), params={"k_I": 20.0, "HR_offset": -5.0}
    )

    readings = source.next()

    assert readings["k_I"] == pytest.approx(20.0)
    assert readings["HR_offset"] == pytest.approx(-5.0)
    assert source.status()["coefficients"] == "fitted"
    assert "fitted" in source.describe()


def test_set_baseline_wins_over_the_preset_and_clamps(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "walk"))

    source.set_baseline("AE_rate", 5.0)
    assert source.next()["AE_rate"] == pytest.approx(5.0)

    source.set_baseline("AE_rate", 1000.0)
    assert source.next()["AE_rate"] == pytest.approx(
        twin.attributes["AE_rate"].physio_max
    )

    source.set_baseline("not_an_attribute", 1.0)
    assert source.next()["AE_rate"] == pytest.approx(
        twin.attributes["AE_rate"].physio_max
    )


def test_set_preset_drops_overrides_it_sets_and_keeps_the_others(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "rest"))
    source.set_baseline("AE_rate", 5.0)
    source.set_baseline("T_app", 30.0)

    source.set_preset(_load(presets, "walk"))
    readings = source.next()

    assert readings["AE_rate"] == pytest.approx(3.22)
    assert readings["T_app"] == pytest.approx(30.0)


@pytest.mark.parametrize(
    "values",
    [
        {"HR_obs": 70},
        {"HR_model": 70},
        {"not_an_attribute": 1},
    ],
    ids=["observed", "preliminary", "unknown"],
)
def test_scenario_refuses_inputs_it_cannot_set(presets, values):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "rest"))

    with pytest.raises(ValueError):
        ScenarioSource(twin, {"name": "bad", "values": values})
    with pytest.raises(ValueError):
        source.set_preset({"name": "bad", "values": values})


def test_set_baseline_refuses_the_measurement(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "rest"))

    with pytest.raises(ValueError) as caught:
        source.set_baseline("HR_obs", 70.0)

    assert "measurement" in str(caught.value)


def test_status_names_the_preset_and_subject(presets):
    twin = load_twin(WEARABLE)
    source = ScenarioSource(twin, _load(presets, "walk"))

    status = source.status()

    assert status["kind"] == "scenario"
    assert status["preset"] == "walk"
    assert status["label"] == "Walk"
    assert status["subject"] == "s2"
    assert status["detail"] == "Scenario · Walk"


# ── Acceptance: rest → walk → rest through a Session ─────────────────

def test_walk_then_rest_follows_the_declared_time_constants(presets):
    twin = load_twin(WEARABLE)
    rest = _load(presets, "rest")
    walk = _load(presets, "walk")
    source = ScenarioSource(twin, rest)

    session = Session(lamina=WEARABLE)
    session.seed(source.starting_state())
    for _ in range(10):
        session.tick(source.next(), missing=source.last_missing)
        assert "HR_measured" in session.twin.failed_attributes

    before = session.twin.attributes["HR_model"].value
    tau_on = float(twin.attributes["tau_on"].baseline)
    tau_off = float(twin.attributes["tau_off"].baseline)
    dt_s = float(twin.attributes["dt_s"].baseline)
    walk_target = _target(twin, walk["values"])

    source.set_preset(walk)
    snapshot = session.tick(source.next(), missing=source.last_missing)
    assert "HR_measured" in session.twin.failed_attributes
    assert snapshot["computed"]["HR_target"]["value"] == pytest.approx(
        walk_target, abs=1e-9
    )

    for n in range(1, 6):
        if n > 1:
            snapshot = session.tick(source.next(), missing=source.last_missing)
            assert "HR_measured" in session.twin.failed_attributes
        expected = walk_target + (before - walk_target) * math.exp(
            -n * dt_s / tau_on
        )
        assert snapshot["computed"]["HR_model"]["value"] == pytest.approx(
            expected, abs=1e-9
        )

    before_rest = session.twin.attributes["HR_model"].value
    rest_target = _target(twin, rest["values"])
    source.set_preset(rest)

    for n in range(1, 6):
        snapshot = session.tick(source.next(), missing=source.last_missing)
        assert "HR_measured" in session.twin.failed_attributes
        expected = rest_target + (before_rest - rest_target) * math.exp(
            -n * dt_s / tau_off
        )
        assert snapshot["computed"]["HR_model"]["value"] == pytest.approx(
            expected, abs=1e-9
        )
