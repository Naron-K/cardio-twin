"""
<day_view>: a lamina declares which attributes play which role on a day screen.

The block names roles, never ids: the frontend asks this lamina what its
"measured", "modelled", "rates", "events" and "worn" attributes are.  A role
that names an unknown attribute, the wrong source or a misspelt child would
leave the day view quietly missing a quantity, so it is refused at load time.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

EXPECTED_WEARABLE = {
    "pair": {
        "measured": "HR_measured",
        "modelled": "HR_model",
        "label": "Heart rate",
    },
    "rates": [
        {"attribute": "AE_rate", "label": "Active energy"},
        {"attribute": "step_rate", "label": "Steps"},
    ],
    "events": [
        {"indicator": "is_walk", "group": "walk", "label": "Walk"},
        {"indicator": "is_strength", "group": "strength", "label": "Strength"},
        {"indicator": "is_cardio", "group": "cardio", "label": "Cardio"},
    ],
    "event_field": "sample.workout",
    "worn": "AE_rate",
}

BASE_ATTRIBUTES = """
    <attribute id="measured_hr">
      <name>Heart Rate Measured</name><unit>bpm</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>220</physio_max>
    </attribute>
    <attribute id="model_hr">
      <name>Heart Rate Modelled</name><unit>bpm</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>220</physio_max>
    </attribute>
    <attribute id="energy_rate">
      <name>Energy Rate</name><unit>kcal/min</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>30</physio_max>
      <replay_field>sample.ae</replay_field>
    </attribute>
    <attribute id="step_rate">
      <name>Step Rate</name><unit>steps/min</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>250</physio_max>
      <replay_field>sample.steps</replay_field>
    </attribute>
    <attribute id="is_walk">
      <name>Walk</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.workout in Walking</replay_field>
    </attribute>
    <attribute id="is_run">
      <name>Run</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.workout in Running</replay_field>
    </attribute>
    <attribute id="is_cycle">
      <name>Cycle</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.activity in Cycling</replay_field>
    </attribute>
    <attribute id="plain">
      <name>Plain</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.hr</replay_field>
    </attribute>
    <attribute id="worn_attr">
      <name>Worn</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.ae</replay_field>
    </attribute>
"""

VALID_DAY_VIEW = """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="energy_rate" label="Energy"/>
  <event indicator="is_walk" group="walk" label="Walk"/>
  <worn attribute="worn_attr"/>
</day_view>
"""


def _lamina(day_view: str, attr_xml: str = BASE_ATTRIBUTES) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{attr_xml}</attributes>
  <functions/>
  <segments/>
  {day_view}
</lamina>"""


def _load(tmp_path: Path, day_view: str) -> UniversalTwin:
    path = tmp_path / "probe_lamina.xml"
    path.write_text(_lamina(day_view), encoding="utf-8")
    return UniversalTwin(str(path))


def _refused(tmp_path: Path, day_view: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, day_view)


def test_the_wearable_lamina_declares_the_day_view_roles():
    assert load_twin(WEARABLE).day_view == EXPECTED_WEARABLE


def test_the_schema_serves_the_roles_and_a_lamina_without_one_gets_none():
    import main

    client = TestClient(main.app)

    wearable = client.get(
        "/api/schema", params={"lamina": "lamina_wearable"}
    ).json()
    assert wearable["day_view"] == EXPECTED_WEARABLE

    circulatory = client.get(
        "/api/schema", params={"lamina": "lamina_circulatory"}
    ).json()
    assert circulatory["day_view"] is None


def test_a_missing_label_falls_back_to_the_attribute_name(tmp_path):
    twin = _load(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr"/>
  <rate attribute="energy_rate"/>
  <event indicator="is_walk" group="walk"/>
  <worn attribute="worn_attr"/>
</day_view>""")
    assert twin.day_view["pair"]["label"] == "Heart Rate Measured"
    assert twin.day_view["rates"][0]["label"] == "Energy Rate"
    assert twin.day_view["events"][0]["label"] == "Walk"


def test_zero_events_is_allowed_and_leaves_no_event_field(tmp_path):
    twin = _load(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="energy_rate" label="Energy"/>
  <worn attribute="worn_attr"/>
</day_view>""")
    assert twin.day_view["events"] == []
    assert twin.day_view["event_field"] is None


def test_a_missing_pair_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <rate attribute="energy_rate" label="Energy"/>
  <worn attribute="worn_attr"/>
</day_view>""", "exactly one <pair>")


def test_two_pairs_are_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <worn attribute="worn_attr"/>
</day_view>""", "exactly one <pair>")


def test_a_measured_attribute_that_is_not_preliminary_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="energy_rate" modelled="model_hr" label="Heart rate"/>
  <worn attribute="worn_attr"/>
</day_view>""", "PRELIMINARY")


def test_measured_and_modelled_must_differ(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="measured_hr" label="Heart rate"/>
  <worn attribute="worn_attr"/>
</day_view>""", "must differ")


def test_an_unknown_rate_attribute_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="nope" label="Nothing"/>
  <worn attribute="worn_attr"/>
</day_view>""", "unknown attribute 'nope'")


def test_a_rate_on_a_preliminary_attribute_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="model_hr" label="Modelled"/>
  <worn attribute="worn_attr"/>
</day_view>""", "a rate must be SENSOR")


def test_the_same_rate_twice_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="energy_rate" label="Energy"/>
  <rate attribute="energy_rate" label="Energy again"/>
  <worn attribute="worn_attr"/>
</day_view>""", "more than once among the rates")


def test_an_event_indicator_without_a_membership_field_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <event indicator="plain" group="walk" label="Walk"/>
  <worn attribute="worn_attr"/>
</day_view>""", "membership field")


def test_two_events_on_different_paths_are_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <event indicator="is_walk" group="walk" label="Walk"/>
  <event indicator="is_cycle" group="cycle" label="Cycle"/>
  <worn attribute="worn_attr"/>
</day_view>""", "share one recorded path")


def test_a_duplicate_group_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <event indicator="is_walk" group="walk" label="Walk"/>
  <event indicator="is_run" group="walk" label="Run"/>
  <worn attribute="worn_attr"/>
</day_view>""", "used by more than one event")


def test_a_bad_group_name_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <event indicator="is_walk" group="Walk" label="Walk"/>
  <worn attribute="worn_attr"/>
</day_view>""", "must match")


def test_the_same_event_indicator_twice_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <event indicator="is_walk" group="walk" label="Walk"/>
  <event indicator="is_walk" group="walk_again" label="Walk again"/>
  <worn attribute="worn_attr"/>
</day_view>""", "indicator 'is_walk' is used more than once")


def test_a_missing_worn_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <rate attribute="energy_rate" label="Energy"/>
</day_view>""", "exactly one <worn>")


def test_a_worn_attribute_that_is_not_a_sensor_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <worn attribute="model_hr"/>
</day_view>""", "worn attribute must be SENSOR")


def test_an_unknown_child_element_is_refused(tmp_path):
    _refused(tmp_path, """
<day_view>
  <pair measured="measured_hr" modelled="model_hr" label="Heart rate"/>
  <colour attribute="energy_rate"/>
  <worn attribute="worn_attr"/>
</day_view>""", "unknown child <colour>")
