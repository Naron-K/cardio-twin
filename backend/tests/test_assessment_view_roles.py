"""
<assessment_view>: a lamina declares what a person enters and what follows.

The block names declared attributes as entries, links, a range, paired
results, flags and an invented example.  Every id must already exist, every
entry must be a sensor with no baseline, every choice value must lie inside
its attribute's range, and an answer that was not given must stay absent.
Each refusal names the lamina and the element.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

HEALTH = LAMINA_DIR / "health_lamina.xml"
WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

BASE_ATTRIBUTES = """
    <attribute id="age">
      <name>Age</name><unit>years</unit>
      <source>SENSOR</source>
      <physio_min>18</physio_min><physio_max>100</physio_max>
    </attribute>
    <attribute id="sex">
      <name>Sex</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
    </attribute>
    <attribute id="smoker">
      <name>Smokes</name><unit>1</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
    </attribute>
    <attribute id="baseline_entry">
      <name>Already answered</name><unit>years</unit>
      <source>SENSOR</source>
      <physio_min>18</physio_min><physio_max>100</physio_max>
      <baseline>50</baseline>
    </attribute>
    <attribute id="dose_a">
      <name>Dose now</name><unit>MET-h/week</unit>
      <source>INTER_LAMINA</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
    </attribute>
    <attribute id="dose_b">
      <name>Dose planned</name><unit>MET-h/week</unit>
      <source>INTER_LAMINA</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
    </attribute>
    <attribute id="low">
      <name>Low end</name><unit>MET-h/week</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <baseline>10</baseline>
    </attribute>
    <attribute id="high">
      <name>High end</name><unit>MET-h/week</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <baseline>20</baseline>
    </attribute>
    <attribute id="risk_now">
      <name>Outcome now</name><unit>%</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn</computed_by>
    </attribute>
    <attribute id="risk_plan">
      <name>Outcome with the plan</name><unit>%</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn</computed_by>
    </attribute>
    <attribute id="flag_a">
      <name>Flag</name><unit>1</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>1</physio_max>
      <computed_by>fn</computed_by>
    </attribute>
"""

VALID_GROUPS = """
<group id="about" label="About">
  <entry attribute="age" kind="number" why="Age matters."/>
  <entry attribute="sex" kind="choice" options="0:Female,1:Male" why="Sex matters."/>
  <entry attribute="smoker" kind="yesno" why="Smoking matters."/>
</group>
"""

VALID_TAIL = """
<link attribute="dose_a" role="current" label="Now"/>
<link attribute="dose_b" role="planned" label="Planned"/>
<range low="low" high="high" label="Guideline"/>
<result id="r1" label="Outcome" period="over 10 years" now="risk_now" planned="risk_plan"/>
<flag attribute="flag_a" topic="Topic" label="Raised" text="Text."/>
<example label="Example">
  <value attribute="age">40</value>
  <value attribute="sex">1</value>
  <value attribute="smoker">0</value>
</example>
"""

TAIL_NO_RESULT = """
<link attribute="dose_a" role="current" label="Now"/>
<range low="low" high="high" label="Guideline"/>
<flag attribute="flag_a" topic="Topic" label="Raised" text="Text."/>
"""


def _view(groups: str = VALID_GROUPS, tail: str = VALID_TAIL) -> str:
    return f"<assessment_view>{groups}{tail}</assessment_view>"


def _lamina(view: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{BASE_ATTRIBUTES}</attributes>
  <functions/>
  <segments/>
  {view}
</lamina>"""


def _load(tmp_path: Path, view: str) -> UniversalTwin:
    path = tmp_path / "probe_lamina.xml"
    path.write_text(_lamina(view), encoding="utf-8")
    return UniversalTwin(str(path))


def _refused(tmp_path: Path, view: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        _load(tmp_path, view)


# ── The health lamina's own block ─────────────────────────────────────

def test_the_health_lamina_assessment_view_parses():
    view = load_twin(HEALTH).assessment_view
    assert view is not None

    assert [group["id"] for group in view["groups"]] == [
        "about", "tests", "history",
    ]
    about = view["groups"][0]
    assert about["label"] == "About you"
    assert about["entries"][0] == {
        "attribute": "age",
        "label": "Age",
        "unit": "years",
        "kind": "number",
        "why": "Risk rises with age in every model.",
        "min": 18.0,
        "max": 100.0,
        "options": None,
    }
    assert about["entries"][1]["options"] == [
        {"value": 0.0, "label": "Female"},
        {"value": 1.0, "label": "Male"},
    ]

    assert view["links"] == {
        "current": {
            "attribute": "dose_current",
            "label": "Activity now",
            "unit": "MET-h/week",
        },
        "planned": {
            "attribute": "dose_planned",
            "label": "Activity with this plan",
            "unit": "MET-h/week",
        },
    }
    assert view["range"] == {
        "low": "dose_guideline_low",
        "high": "dose_guideline_high",
        "label": "Guideline range",
        "unit": "MET-h/week",
    }

    results = {result["id"]: result for result in view["results"]}
    assert results["cvd"] == {
        "id": "cvd",
        "label": "Cardiovascular disease",
        "period": "over 10 years",
        "now": "cvd_risk_now",
        "planned": "cvd_risk_at",
        "unit": "%",
        "not_applicable_when": None,
        "not_applicable_text": None,
    }
    assert results["diabetes"]["not_applicable_when"] == "diabetes"
    assert results["diabetes"]["not_applicable_text"] == (
        "Not shown: diabetes is already diagnosed."
    )

    flags = {flag["attribute"]: flag for flag in view["flags"]}
    assert flags["flag_bp"] == {
        "attribute": "flag_bp",
        "topic": "Resting blood pressure",
        "label": "Resting blood pressure is high",
        "text": (
            "The blood pressure you entered is at or above the level at "
            "which guidance advises seeing a doctor before starting or "
            "increasing exercise."
        ),
    }

    assert view["example"]["label"] == "Low risk · invented example"
    assert view["example"]["values"]["age"] == 38.0
    assert view["example"]["values"]["sex_male"] == 0.0
    assert view["example"]["values"]["family_diabetes"] == 0.0


def test_every_attribute_named_in_the_health_view_exists():
    twin = load_twin(HEALTH)
    view = twin.assessment_view
    named = set()

    for group in view["groups"]:
        for entry in group["entries"]:
            named.add(entry["attribute"])
    for link in view["links"].values():
        named.add(link["attribute"])
    if view["range"] is not None:
        named.add(view["range"]["low"])
        named.add(view["range"]["high"])
    for result in view["results"]:
        named.add(result["now"])
        named.add(result["planned"])
        if result["not_applicable_when"] is not None:
            named.add(result["not_applicable_when"])
    for flag in view["flags"]:
        named.add(flag["attribute"])
    if view["example"] is not None:
        named.update(view["example"]["values"])

    assert named <= set(twin.attributes)


def test_a_lamina_without_the_block_has_assessment_view_none():
    assert load_twin(WEARABLE).assessment_view is None


def test_the_schema_serves_the_assessment_view():
    import main

    client = TestClient(main.app)
    body = client.get(
        "/api/schema", params={"lamina": "lamina_health"}
    ).json()

    view = body["assessment_view"]
    assert view["groups"][0]["id"] == "about"
    assert view["groups"][0]["entries"][0]["attribute"] == "age"
    assert view["links"]["current"]["attribute"] == "dose_current"
    assert view["flags"][0]["attribute"] == "flag_bp"
    assert view["example"]["values"]["age"] == 38


# ── The valid probe, so a refusal is about the one changed thing ──────

def test_the_probe_assessment_view_parses(tmp_path):
    view = _load(tmp_path, _view()).assessment_view
    assert view["range"] == {
        "low": "low", "high": "high", "label": "Guideline",
        "unit": "MET-h/week",
    }
    assert view["results"][0]["now"] == "risk_now"
    assert view["example"]["values"] == {
        "age": 40.0, "sex": 1.0, "smoker": 0.0,
    }


# ── Top-level shape ──────────────────────────────────────────────────

def test_an_unknown_child_element_is_refused(tmp_path):
    _refused(tmp_path, _view()[:-len("</assessment_view>")] + """
<colour label="nope"/>
</assessment_view>""", "unknown child <colour>")


def test_a_missing_group_is_refused(tmp_path):
    _refused(tmp_path, _view(groups=""), "at least one <group>")


def test_a_missing_result_is_refused(tmp_path):
    _refused(tmp_path, _view(tail=TAIL_NO_RESULT), "at least one <result>")


# ── Groups and entries ───────────────────────────────────────────────

def test_an_unknown_entry_attribute_is_refused(tmp_path):
    groups = VALID_GROUPS.replace('attribute="age"', 'attribute="nope"', 1)
    _refused(tmp_path, _view(groups), "unknown attribute 'nope'")


def test_an_entry_that_is_not_a_sensor_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'attribute="age"', 'attribute="risk_now"', 1)
    _refused(tmp_path, _view(groups), "an entry must be SENSOR")


def test_an_entry_with_a_baseline_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'attribute="age"', 'attribute="baseline_entry"', 1)
    _refused(tmp_path, _view(groups), "declares a <baseline>")


def test_an_unknown_entry_kind_is_refused(tmp_path):
    groups = VALID_GROUPS.replace('kind="number"', 'kind="slider"', 1)
    _refused(tmp_path, _view(groups), "kind 'slider' is not one of")


def test_a_choice_without_options_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        ' kind="choice" options="0:Female,1:Male"', ' kind="choice"', 1)
    _refused(tmp_path, _view(groups), "must declare options")


def test_options_on_a_non_choice_are_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'attribute="age" kind="number" why="Age matters."',
        'attribute="age" kind="number" why="Age matters." '
        'options="1:One,2:Two"', 1)
    _refused(tmp_path, _view(groups), "only allowed on a choice entry")


def test_options_not_in_value_label_form_are_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'options="0:Female,1:Male"', 'options="Female,Male"', 1)
    _refused(tmp_path, _view(groups), "not in the form value:Label")


def test_a_non_numeric_option_value_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'options="0:Female,1:Male"', 'options="a:Female,b:Male"', 1)
    _refused(tmp_path, _view(groups), "not a number")


def test_a_choice_with_fewer_than_two_options_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'options="0:Female,1:Male"', 'options="0:Female"', 1)
    _refused(tmp_path, _view(groups), "at least two options")


def test_a_duplicate_option_value_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'options="0:Female,1:Male"', 'options="0:Female,0:Male"', 1)
    _refused(tmp_path, _view(groups), "declared more than once")


def test_a_choice_value_outside_the_attribute_range_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'options="0:Female,1:Male"', 'options="0:Female,2:Male"', 1)
    _refused(tmp_path, _view(groups), "lies outside attribute 'sex' range")


def test_a_yesno_entry_on_a_wider_range_is_refused(tmp_path):
    groups = VALID_GROUPS.replace(
        'attribute="smoker" kind="yesno"',
        'attribute="age" kind="yesno"', 1)
    _refused(tmp_path, _view(groups), "range is exactly 0..1")


def test_an_attribute_that_is_an_entry_twice_is_refused(tmp_path):
    groups = VALID_GROUPS + """
<group id="again" label="Again">
  <entry attribute="age" kind="number" why="Once more."/>
</group>
"""
    _refused(tmp_path, _view(groups), "already an entry")


def test_a_duplicate_group_id_is_refused(tmp_path):
    _refused(tmp_path, _view(VALID_GROUPS + VALID_GROUPS),
             "group ids must be unique")


def test_a_group_with_no_entries_is_refused(tmp_path):
    groups = VALID_GROUPS + """
<group id="empty" label="Empty"></group>
"""
    _refused(tmp_path, _view(groups), "at least one <entry>")


# ── Links ────────────────────────────────────────────────────────────

def test_an_unknown_link_role_is_refused(tmp_path):
    tail = VALID_TAIL.replace('role="current"', 'role="now"', 1)
    _refused(tmp_path, _view(tail=tail), "allowed roles are current, planned")


def test_a_link_role_declared_twice_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<link attribute="dose_b" role="planned" label="Planned"/>',
        '<link attribute="dose_b" role="current" label="Again"/>', 1)
    _refused(tmp_path, _view(tail=tail),
             "role 'current' is declared more than once")


def test_an_unknown_link_attribute_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'attribute="dose_a"', 'attribute="nope"', 1)
    _refused(tmp_path, _view(tail=tail), "unknown attribute 'nope'")


def test_a_link_that_is_not_inter_lamina_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'attribute="dose_a"', 'attribute="age"', 1)
    _refused(tmp_path, _view(tail=tail), "a link must be INTER_LAMINA")


# ── Range ────────────────────────────────────────────────────────────

def test_a_second_range_is_refused(tmp_path):
    tail = VALID_TAIL + '<range low="low" high="high" label="Again"/>'
    _refused(tmp_path, _view(tail=tail), "at most one is allowed")


def test_an_unknown_range_endpoint_is_refused(tmp_path):
    tail = VALID_TAIL.replace('low="low"', 'low="nope"', 1)
    _refused(tmp_path, _view(tail=tail), "unknown attribute 'nope'")


def test_a_range_endpoint_that_is_not_a_sensor_is_refused(tmp_path):
    tail = VALID_TAIL.replace('low="low"', 'low="risk_now"', 1)
    _refused(tmp_path, _view(tail=tail), "the low attribute must be SENSOR")


def test_a_range_endpoint_without_a_baseline_is_refused(tmp_path):
    tail = VALID_TAIL.replace('low="low"', 'low="age"', 1)
    _refused(tmp_path, _view(tail=tail), "declares no <baseline>")


# ── Results ──────────────────────────────────────────────────────────

def test_a_duplicate_result_id_is_refused(tmp_path):
    tail = VALID_TAIL + (
        '<result id="r1" label="Again" period="again" '
        'now="risk_now" planned="risk_plan"/>'
    )
    _refused(tmp_path, _view(tail=tail), "result ids must be unique")


def test_an_unknown_result_output_is_refused(tmp_path):
    tail = VALID_TAIL.replace('now="risk_now"', 'now="nope"', 1)
    _refused(tmp_path, _view(tail=tail), "unknown attribute 'nope'")


def test_a_result_output_that_is_not_preliminary_is_refused(tmp_path):
    tail = VALID_TAIL.replace('now="risk_now"', 'now="age"', 1)
    _refused(tmp_path, _view(tail=tail), "the now attribute must be "
                                        "PRELIMINARY")


def test_not_applicable_when_must_name_an_entry(tmp_path):
    tail = VALID_TAIL.replace(
        'now="risk_now" planned="risk_plan"',
        'now="risk_now" planned="risk_plan" '
        'not_applicable_when="mystery" not_applicable_text="Hidden."', 1)
    _refused(tmp_path, _view(tail=tail), "'mystery' is not a declared entry")


def test_not_applicable_when_must_name_a_yesno_entry(tmp_path):
    tail = VALID_TAIL.replace(
        'now="risk_now" planned="risk_plan"',
        'now="risk_now" planned="risk_plan" '
        'not_applicable_when="age" not_applicable_text="Hidden."', 1)
    _refused(tmp_path, _view(tail=tail), "must name a yesno entry")


def test_not_applicable_text_is_required(tmp_path):
    tail = VALID_TAIL.replace(
        'now="risk_now" planned="risk_plan"',
        'now="risk_now" planned="risk_plan" '
        'not_applicable_when="smoker"', 1)
    _refused(tmp_path, _view(tail=tail),
             "must declare a not_applicable_text")


# ── Flags ────────────────────────────────────────────────────────────

def test_an_unknown_flag_attribute_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'attribute="flag_a"', 'attribute="nope"', 1)
    _refused(tmp_path, _view(tail=tail), "unknown attribute 'nope'")


def test_a_flag_that_is_not_preliminary_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'attribute="flag_a"', 'attribute="age"', 1)
    _refused(tmp_path, _view(tail=tail), "a flag must be PRELIMINARY")


def test_a_flag_on_a_wider_range_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'attribute="flag_a"', 'attribute="risk_now"', 1)
    _refused(tmp_path, _view(tail=tail), "range is exactly 0..1")


def test_an_attribute_that_is_a_flag_twice_is_refused(tmp_path):
    tail = VALID_TAIL + (
        '<flag attribute="flag_a" topic="Again" label="Again" text="Again."/>'
    )
    _refused(tmp_path, _view(tail=tail), "already a flag")


# ── Example ──────────────────────────────────────────────────────────

def test_a_duplicate_example_id_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<example label="Example">', '<example id="dup" label="Example">', 1
    )
    tail += (
        '<example id="dup" label="Again">'
        '<value attribute="age">40</value></example>'
    )
    _refused(tmp_path, _view(tail=tail), "example ids must be unique")


def test_an_example_value_must_be_a_declared_entry(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="age">40</value>',
        '<value attribute="nope">40</value>', 1)
    _refused(tmp_path, _view(tail=tail), "'nope' is not a declared entry")


def test_an_example_value_must_be_a_number(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="age">40</value>',
        '<value attribute="age">forty</value>', 1)
    _refused(tmp_path, _view(tail=tail), "not a number")


def test_a_non_finite_example_value_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="age">40</value>',
        '<value attribute="age">nan</value>', 1)
    _refused(tmp_path, _view(tail=tail), "not finite")


def test_an_example_value_outside_the_range_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="age">40</value>',
        '<value attribute="age">5</value>', 1)
    _refused(tmp_path, _view(tail=tail), "lies outside attribute 'age' range")


def test_a_yesno_example_value_that_is_not_zero_or_one_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="smoker">0</value>',
        '<value attribute="smoker">0.5</value>', 1)
    _refused(tmp_path, _view(tail=tail), "is not 0 or 1")


def test_a_choice_example_value_outside_the_options_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<value attribute="sex">1</value>',
        '<value attribute="sex">0.5</value>', 1)
    _refused(tmp_path, _view(tail=tail), "not one of the declared options")
