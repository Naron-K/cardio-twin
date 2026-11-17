"""
<plan_view>: a lamina declares which attributes play which role on a plan screen.

The block names roles, never ids: the frontend asks this lamina what its
"intensity", "settles", "count", "ambient", "level" and "clock" attributes
are.  A role that names an unknown attribute, the wrong source, a misspelt
child, or a settling value its intensity never reaches would leave the plan
view quietly missing a quantity, so it is refused at load time.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

EXPECTED_WEARABLE = {
    "intensity": {
        "attribute": "AE_rate",
        "label": "Level",
        "unit": "kcal/min",
    },
    "settles": {
        "attribute": "HR_target",
        "label": "Settles near",
        "unit": "bpm",
    },
    "count": {
        "attribute": "step_rate",
        "label": "Steps",
        "unit": "steps/min",
    },
    "ambient": {
        "attribute": "T_app",
        "label": "Outdoor temperature",
        "unit": "degC",
    },
    "level": {
        "attribute": "HR_level",
        "label": "Resting level",
        "unit": "bpm",
    },
    "clock": {
        "attribute": "hour_local",
        "label": "Clock hour",
        "unit": "h",
    },
    "dose": {
        "attribute": "dose_rate",
        "label": "Activity dose",
        "unit": "MET",
    },
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
      <computed_by>model_fn</computed_by>
      <depends_on>energy_rate</depends_on>
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
    <attribute id="temp">
      <name>Outdoor Temperature</name><unit>degC</unit>
      <source>SENSOR</source>
      <physio_min>-10</physio_min><physio_max>50</physio_max>
      <replay_field>sample.t_app_c</replay_field>
    </attribute>
    <attribute id="resting">
      <name>Resting Level</name><unit>bpm</unit>
      <source>SENSOR</source>
      <physio_min>30</physio_min><physio_max>120</physio_max>
      <replay_field>day.hr_level</replay_field>
    </attribute>
    <attribute id="clock_hour">
      <name>Clock Hour</name><unit>h</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>24</physio_max>
      <replay_field>clock.hour</replay_field>
    </attribute>
    <attribute id="alt_sensor">
      <name>Alternative Sensor</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.alt</replay_field>
    </attribute>
    <attribute id="is_walk">
      <name>Walk</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <replay_field>sample.workout in Walking</replay_field>
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

FUNCTIONS = """
<functions>
  <function id="model_fn" step="1">
    <formula>model_hr = energy_rate</formula>
    <inputs>energy_rate</inputs>
    <output>model_hr</output>
  </function>
</functions>
"""

FUNCTIONS_ON_OTHER_SENSOR = """
<functions>
  <function id="model_fn" step="1">
    <formula>model_hr = alt_sensor</formula>
    <inputs>alt_sensor</inputs>
    <output>model_hr</output>
  </function>
</functions>
"""

VALID_PLAN_VIEW = """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
</plan_view>
"""


def _lamina(day_view: str, plan_view: str, attr_xml: str = BASE_ATTRIBUTES,
            functions_xml: str = FUNCTIONS) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{attr_xml}</attributes>
  {functions_xml}
  <segments/>
  {day_view}
  {plan_view}
</lamina>"""


def _load(tmp_path: Path, plan_view: str, day_view: str = VALID_DAY_VIEW,
          functions_xml: str = FUNCTIONS) -> UniversalTwin:
    path = tmp_path / "probe_lamina.xml"
    path.write_text(
        _lamina(day_view, plan_view, functions_xml=functions_xml),
        encoding="utf-8",
    )
    return UniversalTwin(str(path))


def _refused(tmp_path: Path, plan_view: str, match: str,
             day_view: str = VALID_DAY_VIEW,
             functions_xml: str = FUNCTIONS) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, plan_view, day_view=day_view,
              functions_xml=functions_xml)


def test_the_wearable_lamina_declares_the_plan_view_roles():
    assert load_twin(WEARABLE).plan_view == EXPECTED_WEARABLE


def test_the_schema_serves_the_roles_and_a_lamina_without_one_gets_none():
    import main

    client = TestClient(main.app)

    wearable = client.get(
        "/api/schema", params={"lamina": "lamina_wearable"}
    ).json()
    assert wearable["plan_view"] == EXPECTED_WEARABLE

    for lamina_id in ("lamina_circulatory", "lamina_respiratory",
                      "lamina_metabolic"):
        other = client.get(
            "/api/schema", params={"lamina": lamina_id}
        ).json()
        assert other["plan_view"] is None


def test_a_missing_label_falls_back_to_the_attribute_name(tmp_path):
    twin = _load(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate"/>
  <settles attribute="model_hr"/>
  <count attribute="step_rate"/>
  <ambient attribute="temp"/>
  <level attribute="resting"/>
  <clock attribute="clock_hour"/>
</plan_view>""")
    assert twin.plan_view["intensity"]["label"] == "Energy Rate"
    assert twin.plan_view["settles"]["label"] == "Heart Rate Modelled"


def test_an_unknown_child_element_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
  <colour attribute="energy_rate"/>
</plan_view>""", "unknown child <colour>")


def test_a_missing_role_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
</plan_view>""", "exactly one <clock>")


def test_a_role_given_twice_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <intensity attribute="energy_rate" label="Level again"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
</plan_view>""", "exactly one <intensity>")


def test_a_role_without_an_attribute_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock label="Clock hour"/>
</plan_view>""", "must declare an attribute")


def test_an_unknown_attribute_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="nope" label="Clock hour"/>
</plan_view>""", "unknown attribute 'nope'")


def test_a_sensor_role_on_a_preliminary_attribute_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="model_hr" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
</plan_view>""", "intensity attribute must be SENSOR")


def test_settles_on_a_sensor_is_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="energy_rate" label="Settles near"/>
  <count attribute="step_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
</plan_view>""", "settles attribute must be PRELIMINARY")


def test_settles_that_never_reaches_the_intensity_is_refused(tmp_path):
    _refused(tmp_path, VALID_PLAN_VIEW,
             "does not depend on the intensity attribute",
             functions_xml=FUNCTIONS_ON_OTHER_SENSOR)


def test_two_roles_on_the_same_attribute_are_refused(tmp_path):
    _refused(tmp_path, """
<plan_view>
  <intensity attribute="energy_rate" label="Level"/>
  <settles attribute="model_hr" label="Settles near"/>
  <count attribute="energy_rate" label="Steps"/>
  <ambient attribute="temp" label="Outdoor temperature"/>
  <level attribute="resting" label="Resting level"/>
  <clock attribute="clock_hour" label="Clock hour"/>
</plan_view>""", "must name six different attributes")


def test_a_plan_view_without_a_day_view_is_refused(tmp_path):
    _refused(tmp_path, VALID_PLAN_VIEW,
             "declares <plan_view> but no <day_view>",
             day_view="")
