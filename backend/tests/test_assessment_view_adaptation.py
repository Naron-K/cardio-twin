"""
<assessment_view>'s adaptation roles: examples, measured links, horizons
and mediators.

Examples may be declared several times, each with its own id.  A measured
link names the key its value is read from.  Horizons name the elapsed-time
attribute and the values the view is read at.  A mediator pairs a factor's
value now (entered or measured) with the value the plan tends to, and must
be reachable from that projection through the function inputs.
"""
from pathlib import Path

import pytest

from laminae import LAMINA_DIR, load_twin
from universal_twin import UniversalTwin

HEALTH = LAMINA_DIR / "health_lamina.xml"

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
    <attribute id="glucose">
      <name>Glucose</name><unit>mmol/L</unit>
      <source>SENSOR</source>
      <physio_min>2.5</physio_min><physio_max>25</physio_max>
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
    <attribute id="meas_a">
      <name>Measured A</name><unit>bpm</unit>
      <source>INTER_LAMINA</source>
      <physio_min>25</physio_min><physio_max>140</physio_max>
    </attribute>
    <attribute id="meas_b">
      <name>Measured B</name><unit>mL/kg/min</unit>
      <source>INTER_LAMINA</source>
      <physio_min>8</physio_min><physio_max>95</physio_max>
    </attribute>
    <attribute id="weeks">
      <name>Weeks</name><unit>weeks</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1000</physio_max>
    </attribute>
    <attribute id="baselined_weeks">
      <name>Weeks with baseline</name><unit>weeks</unit>
      <source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>1000</physio_max>
      <baseline>4</baseline>
    </attribute>
    <attribute id="risk_now">
      <name>Outcome now</name><unit>%</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn_now</computed_by>
    </attribute>
    <attribute id="risk_plan">
      <name>Outcome with the plan</name><unit>%</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn_plan</computed_by>
    </attribute>
    <attribute id="at_ok">
      <name>Factor with the plan</name><unit>mmol/L</unit>
      <source>PRELIMINARY</source>
      <physio_min>2.5</physio_min><physio_max>25</physio_max>
      <computed_by>fn_at</computed_by>
    </attribute>
    <attribute id="at_no_now">
      <name>Projection that misses now</name><unit>1</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn_bad</computed_by>
    </attribute>
    <attribute id="at_no_horizon">
      <name>Projection that misses horizons</name><unit>1</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn_no_weeks</computed_by>
    </attribute>
    <attribute id="plan_no_horizon">
      <name>Plan that misses horizons</name><unit>%</unit>
      <source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>fn_no_weeks</computed_by>
    </attribute>
"""

FUNCTIONS = """
    <function id="fn_now">
      <inputs>age, sex, smoker, glucose, meas_a, meas_b</inputs>
      <output>risk_now</output>
    </function>
    <function id="fn_plan">
      <inputs>risk_now, at_ok, weeks</inputs>
      <output>risk_plan</output>
    </function>
    <function id="fn_at">
      <inputs>glucose, meas_a, weeks</inputs>
      <output>at_ok</output>
    </function>
    <function id="fn_bad">
      <inputs>weeks</inputs>
      <output>at_no_now</output>
    </function>
    <function id="fn_no_weeks">
      <inputs>glucose</inputs>
      <output>at_no_horizon</output>
    </function>
"""

VALID_GROUPS = """
<group id="about" label="About">
  <entry attribute="age" kind="number" why="Age matters."/>
  <entry attribute="sex" kind="choice" options="0:Female,1:Male" why="Sex matters."/>
  <entry attribute="smoker" kind="yesno" why="Smoking matters."/>
  <entry attribute="glucose" kind="number" why="Glucose matters."/>
</group>
"""

VALID_TAIL = """
<link attribute="dose_a" role="current" label="Now"/>
<link attribute="dose_b" role="planned" label="Planned"/>
<link attribute="meas_a" role="measured" key="resting" label="Measured A, from your recordings"/>
<link attribute="meas_b" role="measured" key="vo2" label="Measured B, from your recordings"/>
<horizons attribute="weeks" values="0,4,8,12" settled="1000" settled_label="Settled"/>
<mediator now="glucose" at="at_ok"/>
<mediator now="meas_a" at="at_ok" still="Held still."/>
<result id="r1" label="Outcome" period="over 10 years" now="risk_now" planned="risk_plan"/>
<example id="one" label="One">
  <value attribute="age">40</value>
</example>
<example id="two" label="Two">
  <value attribute="age">50</value>
</example>
<example id="three" label="Three">
  <value attribute="age">60</value>
</example>
"""


def _view(groups: str = VALID_GROUPS, tail: str = VALID_TAIL) -> str:
    return f"<assessment_view>{groups}{tail}</assessment_view>"


def _lamina(view: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_probe" name="Probe" level="1">
  <attributes>{BASE_ATTRIBUTES}</attributes>
  <functions>{FUNCTIONS}</functions>
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


# ── The rewritten health lamina ───────────────────────────────────────

def test_the_health_examples_and_example_compatibility():
    view = load_twin(HEALTH).assessment_view

    assert [example["id"] for example in view["examples"]] == [
        "low", "borderline", "high_cv",
    ]
    assert view["example"] == {
        "label": view["examples"][0]["label"],
        "values": view["examples"][0]["values"],
    }
    assert view["example"]["label"] == "Low risk · invented example"
    assert view["example"]["values"]["age"] == 38.0


def test_the_health_measured_links():
    view = load_twin(HEALTH).assessment_view

    assert [link["key"] for link in view["measured"]] == [
        "resting_hr", "vo2max",
    ]
    assert view["measured"][0]["attribute"] == "resting_hr"
    assert view["measured"][1]["attribute"] == "vo2max"
    assert set(view["links"]) == {"current", "planned"}


def test_the_health_horizons():
    view = load_twin(HEALTH).assessment_view

    assert view["horizons"] == {
        "attribute": "weeks",
        "unit": "weeks",
        "values": [0.0, 4.0, 8.0, 12.0],
        "settled": 1000.0,
        "settled_label": "Settled",
    }


def test_the_health_mediators():
    view = load_twin(HEALTH).assessment_view

    assert len(view["mediators"]) == 8
    assert [mediator["now"] for mediator in view["mediators"]] == [
        "glucose_fasting", "sbp", "dbp", "chol_hdl", "chol_total",
        "mass_kg", "resting_hr", "vo2max",
    ]
    with_still = [m for m in view["mediators"] if m["still"] is not None]
    assert len(with_still) == 2
    by_now = {mediator["now"]: mediator for mediator in view["mediators"]}
    assert by_now["resting_hr"]["source"] == "measured"
    assert by_now["resting_hr"]["key"] == "resting_hr"
    assert by_now["vo2max"]["source"] == "measured"
    assert by_now["vo2max"]["key"] == "vo2max"
    assert by_now["glucose_fasting"]["source"] == "entered"
    assert by_now["glucose_fasting"]["key"] is None


def test_every_attribute_named_in_the_health_view_exists():
    twin = load_twin(HEALTH)
    view = twin.assessment_view
    named = set()

    for group in view["groups"]:
        for entry in group["entries"]:
            named.add(entry["attribute"])
    for link in view["links"].values():
        named.add(link["attribute"])
    for link in view["measured"]:
        named.add(link["attribute"])
    if view["horizons"] is not None:
        named.add(view["horizons"]["attribute"])
    for mediator in view["mediators"]:
        named.add(mediator["now"])
        named.add(mediator["at"])
    for result in view["results"]:
        named.add(result["now"])
        named.add(result["planned"])
        if result["not_applicable_when"] is not None:
            named.add(result["not_applicable_when"])
    for flag in view["flags"]:
        named.add(flag["attribute"])
    for example in view["examples"]:
        named.update(example["values"])

    assert named <= set(twin.attributes)


# ── The probe, so a refusal is about the one changed thing ────────────

def test_the_probe_adaptation_roles_parse(tmp_path):
    view = _load(tmp_path, _view()).assessment_view

    assert [example["id"] for example in view["examples"]] == [
        "one", "two", "three",
    ]
    assert view["example"]["label"] == "One"
    assert [link["key"] for link in view["measured"]] == ["resting", "vo2"]
    assert view["horizons"]["values"] == [0.0, 4.0, 8.0, 12.0]
    assert view["mediators"][0]["source"] == "entered"
    assert view["mediators"][1]["source"] == "measured"
    assert view["mediators"][1]["key"] == "resting"
    assert view["mediators"][1]["still"] == "Held still."


def test_a_single_example_without_an_id_gets_the_default(tmp_path):
    tail = VALID_TAIL.split('<example id="one"')[0] + (
        '<example label="One"><value attribute="age">40</value></example>'
    )
    view = _load(tmp_path, _view(tail=tail)).assessment_view

    assert [example["id"] for example in view["examples"]] == ["example"]


# ── Examples ─────────────────────────────────────────────────────────

def test_a_duplicate_example_id_is_refused(tmp_path):
    tail = VALID_TAIL + (
        '<example id="one" label="Again">'
        '<value attribute="age">40</value></example>'
    )
    _refused(tmp_path, _view(tail=tail), "example ids must be unique")


def test_an_example_without_a_label_is_refused(tmp_path):
    tail = VALID_TAIL.replace('<example id="one" label="One">',
                              '<example id="one">', 1)
    _refused(tmp_path, _view(tail=tail), "must declare a label")


# ── Measured links ───────────────────────────────────────────────────

def test_a_measured_link_without_a_key_is_refused(tmp_path):
    tail = VALID_TAIL.replace(' key="resting"', "", 1)
    _refused(tmp_path, _view(tail=tail),
             "must declare a non-empty key")


def test_a_duplicate_measured_key_is_refused(tmp_path):
    tail = VALID_TAIL.replace('key="vo2"', 'key="resting"', 1)
    _refused(tmp_path, _view(tail=tail), "declared more than once among "
                                        "measured links")


def test_a_key_on_a_current_link_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<link attribute="dose_a" role="current" label="Now"/>',
        '<link attribute="dose_a" role="current" key="now" label="Now"/>', 1)
    _refused(tmp_path, _view(tail=tail),
             "only allowed on a measured link")


# ── Horizons ─────────────────────────────────────────────────────────

def test_a_horizons_attribute_with_a_baseline_is_refused(tmp_path):
    tail = VALID_TAIL.replace('attribute="weeks"',
                              'attribute="baselined_weeks"', 1)
    _refused(tmp_path, _view(tail=tail), "declares a <baseline>")


def test_horizons_not_starting_at_zero_are_refused(tmp_path):
    tail = VALID_TAIL.replace('values="0,4,8,12"', 'values="1,4,8,12"', 1)
    _refused(tmp_path, _view(tail=tail), "first value must be 0")


def test_horizons_not_increasing_are_refused(tmp_path):
    tail = VALID_TAIL.replace('values="0,4,8,12"', 'values="0,8,4,12"', 1)
    _refused(tmp_path, _view(tail=tail), "strictly increasing")


def test_a_horizon_outside_the_range_is_refused(tmp_path):
    tail = VALID_TAIL.replace('values="0,4,8,12"', 'values="0,4,8,2000"', 1)
    _refused(tmp_path, _view(tail=tail), "lies outside attribute 'weeks' "
                                         "range")


def test_settled_not_above_the_last_horizon_is_refused(tmp_path):
    tail = VALID_TAIL.replace('settled="1000"', 'settled="8"', 1)
    _refused(tmp_path, _view(tail=tail),
             "must be greater than the last horizon value")


# ── Mediators ────────────────────────────────────────────────────────

def test_a_mediator_without_horizons_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<horizons attribute="weeks" values="0,4,8,12" '
        'settled="1000" settled_label="Settled"/>', "", 1)
    _refused(tmp_path, _view(tail=tail), "no <horizons>")


def test_a_mediator_now_that_is_neither_entry_nor_measured_is_refused(
        tmp_path):
    tail = VALID_TAIL.replace(
        '<mediator now="glucose" at="at_ok"/>',
        '<mediator now="dose_a" at="at_ok"/>', 1)
    _refused(tmp_path, _view(tail=tail),
             "neither an entry of a group nor the attribute of a measured "
             "link")


def test_a_mediator_at_that_does_not_reach_now_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<mediator now="glucose" at="at_ok"/>',
        '<mediator now="glucose" at="at_no_now"/>', 1)
    _refused(tmp_path, _view(tail=tail),
             "does not reach the now attribute 'glucose'")


def test_a_mediator_at_that_does_not_reach_horizons_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        '<mediator now="glucose" at="at_ok"/>',
        '<mediator now="glucose" at="at_no_horizon"/>', 1)
    _refused(tmp_path, _view(tail=tail),
             "does not reach the horizons attribute 'weeks'")


# ── Results ──────────────────────────────────────────────────────────

def test_a_result_planned_that_does_not_reach_horizons_is_refused(tmp_path):
    tail = VALID_TAIL.replace(
        'planned="risk_plan"', 'planned="plan_no_horizon"', 1)
    _refused(tmp_path, _view(tail=tail),
             "does not reach the horizons attribute 'weeks'")
