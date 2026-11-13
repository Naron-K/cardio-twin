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


def test_the_schema_reports_the_mapping_so_a_control_can_show_a_readout():
    import main

    body = TestClient(main.app).get(
        "/api/schema", params={"lamina": "lamina_wearable"}
    ).json()
    by_id = body["attributes"]          # keyed by attribute id
    assert {k: by_id[k]["replay_field"] for k in EXPECTED} == EXPECTED
    assert by_id["k_I"]["replay_field"] is None
