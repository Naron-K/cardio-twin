"""
<replay_field>: a lamina says which recorded field feeds each measured input.

The mapping lives in the XML so that the replay code names no attribute.  A
field that could never resolve would replay as a gap on every row, so a bad
one is refused at load time rather than discovered as missing data.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

EXPECTED = {
    "HR_obs": "sample.hr",
    "AE_rate": "sample.ae_kcal_min",
    "BE_rate": "sample.be_kcal_min",
    "step_rate": "sample.steps_min",
    "T_app": "sample.t_app_c",
    "hour_local": "clock.hour",
    "dt_s": "clock.dt_s",
    "HR_level": "day.hr_level_rts",
    # The kind of workout, as 0/1 indicators read from the recorded label.
    "is_walk": "sample.workout in Walking",
    "is_strength": "sample.workout in TraditionalStrengthTraining, FunctionalStrengthTraining, CoreTraining",
    "is_cardio": "sample.workout in StairClimbing, Elliptical, Running, Cycling, HighIntensityIntervalTraining, Rowing",
}


def _lamina(attr_xml: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{attr_xml}</attributes>
  <functions/>
  <segments/>
</lamina>"""


def _load(tmp_path: Path, attr_xml: str) -> UniversalTwin:
    path = tmp_path / "probe_lamina.xml"
    path.write_text(_lamina(attr_xml), encoding="utf-8")
    return UniversalTwin(str(path))


def test_the_wearable_lamina_maps_its_measured_inputs_and_no_coefficient():
    twin = load_twin(WEARABLE)
    mapped = {
        a: twin.attributes[a].replay_field
        for a in twin.list_attributes("SENSOR")
        if twin.attributes[a].replay_field is not None
    }
    assert mapped == EXPECTED


@pytest.mark.parametrize("name", ["circulatory", "respiratory", "metabolic"])
def test_laminae_that_replay_nothing_declare_nothing(name):
    twin = load_twin(LAMINA_DIR / f"{name}_lamina.xml")
    assert all(a.replay_field is None for a in twin.attributes.values())


def test_a_replay_field_on_a_computed_attribute_is_refused(tmp_path):
    with pytest.raises(ValueError, match="Only a SENSOR"):
        _load(tmp_path, """
    <attribute id="x"><name>X</name><unit>1</unit><source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.x</replay_field></attribute>""")


@pytest.mark.parametrize("field", ["hr", "samples.hr", "sample.HR", "clock.minute", "day."])
def test_a_field_that_could_never_resolve_is_refused(tmp_path, field):
    with pytest.raises(ValueError, match="replay_field"):
        _load(tmp_path, f"""
    <attribute id="x"><name>X</name><unit>1</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>{field}</replay_field></attribute>""")


def test_a_membership_field_names_its_labels():
    from universal_twin import parse_replay_field

    assert parse_replay_field("sample.hr") == ("sample.hr", None)
    assert parse_replay_field("sample.workout in Walking, Running") == (
        "sample.workout", frozenset({"Walking", "Running"})
    )


@pytest.mark.parametrize(
    "field",
    [
        "sample.workout in",                 # no labels
        "sample.workout in Walking,,Run",    # empty label
        "sample.workout in Walk ing",        # space inside a label
        "sample.workout in Run, Run",        # repeated
        "clock.hour in Morning",             # the clock has no labels
        "samples.workout in Walking",        # unknown source
    ],
)
def test_a_malformed_membership_field_is_refused(tmp_path, field):
    with pytest.raises(ValueError, match="replay_field"):
        _load(tmp_path, f"""
    <attribute id="x"><name>X</name><unit>1</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>{field}</replay_field></attribute>""")


def test_a_membership_field_replays_as_one_or_zero(tmp_path):
    # The demo day walks 08:00-08:30 and lifts 17:30-18:15; nothing at 10:00.
    import json

    from signal_source import ReplaySource

    twin = _load(tmp_path, """
    <attribute id="walking"><name>W</name><unit>1</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.workout in Walking</replay_field></attribute>
    <attribute id="lifting"><name>L</name><unit>1</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.workout in TraditionalStrengthTraining, CoreTraining</replay_field></attribute>""")
    bundle = json.loads(
        (LAMINA_DIR / "bundles" / "demo" / "2025-06-01.json").read_text()
    )
    source = ReplaySource(twin, bundle)
    seen = {}
    for minute in range(1440):
        readings = source.next()
        if minute in (8 * 60 + 10, 10 * 60, 17 * 60 + 40):
            seen[minute] = (readings["walking"], readings["lifting"])
        assert "walking" not in source.last_missing  # a label is never a gap
    assert seen == {490: (1.0, 0.0), 600: (0.0, 0.0), 1060: (0.0, 1.0)}


def test_only_the_measured_heart_rate_is_observed():
    # An observation is what a scenario leaves unset: inventing it would give
    # the model a reading to be compared against that nobody measured.
    twin = load_twin(WEARABLE)
    assert [a for a, v in twin.attributes.items() if v.observed] == ["HR_obs"]
    for name in ("circulatory", "respiratory", "metabolic"):
        other = load_twin(LAMINA_DIR / f"{name}_lamina.xml")
        assert not any(v.observed for v in other.attributes.values())


@pytest.mark.parametrize(
    "source, value, match",
    [("PRELIMINARY", "true", "Only a SENSOR"), ("SENSOR", "yes", "observed")],
)
def test_a_bad_observed_flag_is_refused(tmp_path, source, value, match):
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, f"""
    <attribute id="x"><name>X</name><unit>1</unit><source>{source}</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <observed>{value}</observed></attribute>""")


def test_the_schema_reports_the_mapping_so_a_control_can_show_a_readout():
    import main

    body = TestClient(main.app).get(
        "/api/schema", params={"lamina": "lamina_wearable"}
    ).json()
    by_id = body["attributes"]          # keyed by attribute id
    assert {k: by_id[k]["replay_field"] for k in EXPECTED} == EXPECTED
    assert by_id["k_I"]["replay_field"] is None
    assert by_id["HR_obs"]["observed"] is True
    assert by_id["AE_rate"]["observed"] is False
