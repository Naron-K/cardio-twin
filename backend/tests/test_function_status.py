"""
A function's provenance: its optional status, source and reviewer.

The status is optional so every pre-existing lamina loads exactly as before,
but when it is declared it must be one of three words, and a review must name
who signed it.  The schema serves all three keys additively.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

HEALTH = LAMINA_DIR / "health_lamina.xml"
WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

OLD_SCHEMA_KEYS = {
    "lamina_name", "lamina_id", "lamina_level", "upper_lamina_id",
    "lower_lamina_id", "attributes", "composites", "functions", "segments",
    "day_view", "plan_view", "channel_mappings", "feedback_config", "tags",
    "gates", "registries",
}
OLD_FUNCTION_KEYS = {
    "id", "name", "step", "formula", "inputs", "output", "description",
    "state",
}
ADDED_FUNCTION_KEYS = {"status", "source", "reviewed_by"}

BASE_ATTRIBUTES = """
    <attribute id="a_one">
      <name>One</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
    </attribute>
    <attribute id="a_out">
      <name>Out</name><unit>1</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <computed_by>fn</computed_by>
    </attribute>
"""


def _lamina(function_attrs: str = "", extra: str = "") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{BASE_ATTRIBUTES}</attributes>
  <functions>
    <function id="fn" step="1" {function_attrs}>
      <formula>a_out = a_one</formula>
      <inputs>a_one</inputs>
      <output>a_out</output>
      <description>A probe function.</description>
      {extra}
    </function>
  </functions>
  <segments/>
</lamina>"""


def _load(tmp_path: Path, function_attrs: str = "",
          extra: str = "") -> UniversalTwin:
    path = tmp_path / "probe_lamina.xml"
    path.write_text(_lamina(function_attrs, extra), encoding="utf-8")
    return UniversalTwin(str(path))


def _refused(tmp_path: Path, function_attrs: str, extra: str,
             match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, function_attrs, extra)


def test_the_health_lamina_declares_function_provenance():
    twin = load_twin(HEALTH)

    body_mass_index = twin.functions["body_mass_index"]
    assert body_mass_index.status == "draft"
    assert body_mass_index.source == "Standard definition."
    assert body_mass_index.reviewed_by == ""

    assert twin.functions["cvd_score"].status == "placeholder"
    assert twin.functions["flag_medicine"].status == "draft"


def test_an_existing_lamina_without_statuses_loads_as_before():
    twin = load_twin(WEARABLE)

    assert twin.functions
    for function in twin.functions.values():
        assert function.status is None
        assert function.source == ""
        assert function.reviewed_by == ""


def test_the_three_provenance_children_parse(tmp_path):
    twin = _load(
        tmp_path,
        function_attrs='status="reviewed"',
        extra="<source>A named paper.</source>"
              "<reviewed_by>Dr Reviewer</reviewed_by>",
    )
    function = twin.functions["fn"]
    assert function.status == "reviewed"
    assert function.source == "A named paper."
    assert function.reviewed_by == "Dr Reviewer"


def test_no_status_attribute_means_none(tmp_path):
    function = _load(tmp_path).functions["fn"]
    assert function.status is None
    assert function.source == ""
    assert function.reviewed_by == ""


def test_a_status_outside_the_allowed_set_is_refused(tmp_path):
    _refused(
        tmp_path, 'status="approved"', "",
        r"Function 'fn' declares status 'approved'\..*placeholder, draft, "
        r"reviewed",
    )


def test_a_review_without_a_reviewer_is_refused(tmp_path):
    _refused(
        tmp_path, 'status="reviewed"', "",
        r"Function 'fn' declares status 'reviewed' but names no reviewer",
    )


def test_the_schema_serves_function_provenance_and_the_assessment_view():
    import main

    client = TestClient(main.app)
    health = client.get(
        "/api/schema", params={"lamina": "lamina_health"}
    ).json()

    assert health["assessment_view"] is not None
    functions = {f["id"]: f for f in health["functions"]}
    assert functions["body_mass_index"]["status"] == "draft"
    assert functions["body_mass_index"]["source"] == "Standard definition."
    assert functions["body_mass_index"]["reviewed_by"] == ""
    assert functions["cvd_score"]["status"] == "placeholder"


def test_the_wearable_schema_only_gains_the_additive_keys():
    import main

    client = TestClient(main.app)
    body = client.get(
        "/api/schema", params={"lamina": "lamina_wearable"}
    ).json()

    assert set(body) == OLD_SCHEMA_KEYS | {"assessment_view"}
    assert body["assessment_view"] is None

    for function in body["functions"]:
        assert set(function) == OLD_FUNCTION_KEYS | ADDED_FUNCTION_KEYS
        assert function["status"] is None
        assert function["source"] == ""
        assert function["reviewed_by"] == ""
