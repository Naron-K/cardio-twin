"""
Validate the deterministic gate-trace baseline.

The fixture exists to be replayed against a refactor: if a refactor
changed any number the model produces, the in-memory re-capture stops
matching the file on disk, and that single equality is the whole point
of the file.  Everything else here exists to make sure the file is
complete and well-formed, and that wrong input fails loudly instead of
writing a confident-looking but wrong fixture.
"""
import json

import pytest

from tools.capture_gate_traces import (
    CYCLES,
    DECIMALS,
    FIXTURE_FILE,
    SCENARIOS,
    SCHEMA_VERSION,
    SEED,
    WATCH,
    capture_json,
    capture_run,
    capture_scenario,
    clean_value,
    clean_value_or_none,
)


def _fixture_data():
    assert FIXTURE_FILE.exists(), (
        "tests/fixtures/gate_traces_v1.json is missing — run "
        "`python tools/capture_gate_traces.py` from backend/ to write it."
    )
    return json.loads(FIXTURE_FILE.read_text())


def _cycle_records(scenario_block):
    return scenario_block["cycles"]


# ══════════════════════════════════════════════════════════════════════
# The happy path: the fixture exists, parses, and is complete.
# ══════════════════════════════════════════════════════════════════════

def test_the_fixture_exists_parses_and_covers_every_declared_scenario():
    data = _fixture_data()
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["seed"] == SEED
    assert data["cycles_per_scenario"] == CYCLES

    blocks = data["scenarios"]
    assert len(blocks) == len(SCENARIOS) == 9
    declared = [(name, scenario) for name, scenario, _forcing in SCENARIOS]
    assert [(b["organism"], b["scenario"]) for b in blocks] == declared


def test_the_key_body_and_the_default_body_are_both_represented():
    blocks = {(b["organism"], b["scenario"]): b
              for b in _fixture_data()["scenarios"]}
    assert ("organism.xml", "rest") in blocks
    assert ("organism_key.xml", "rest") in blocks
    assert blocks[("organism_key.xml", "hr150_edv55")]["organism"] == \
        "organism_key.xml"

    default_scenarios = [b for (body, _s), b in blocks.items()
                         if body == "organism.xml"]
    key_scenarios = [b for (body, _s), b in blocks.items()
                     if body == "organism_key.xml"]
    assert len(default_scenarios) == 5
    assert len(key_scenarios) == 4
    assert all(b["controller"] == "threshold" for b in default_scenarios)
    assert all(b["controller"] == "pattern" for b in key_scenarios)


def test_every_scenario_has_forty_cycles_with_the_full_record():
    for block in _fixture_data()["scenarios"]:
        records = _cycle_records(block)
        assert len(records) == CYCLES == 40, (
            f"{block['organism']}/{block['scenario']} must run exactly "
            f"{CYCLES} cycles"
        )
        assert [r["cycle"] for r in records] == list(range(1, CYCLES + 1))

        dest_member = block["dest"].split(":")[1]
        assert block["watch"] == [dest_member] + WATCH[block["organism"]]

        # A pattern trigger records its match and drift; a plain
        # threshold has neither to record.
        is_key = block["controller"] == "pattern"
        for record in records:
            for field in ("cycle", "open_fraction", "transmitted",
                          "provenance_state", *block["watch"]):
                assert field in record, (
                    f"{block['scenario']} cycle {record['cycle']} lost "
                    f"'{field}'"
                )
            assert 0.0 <= record["open_fraction"] <= 1.0
            if is_key:
                assert "match" in record and "drift" in record
            else:
                assert "match" not in record and "drift" not in record


def test_every_recorded_number_is_stable_at_the_rounding_precision():
    """
    The fixture promises floats are rounded to 12 decimals so the file
    is stable; every number already sitting at that precision means a
    rounding change (or a stray unrounded number) shows up here first.
    """
    def _assert_stable(value, where):
        if isinstance(value, float):
            assert round(value, DECIMALS) == value, (
                f"{where} holds {value}, not rounded to {DECIMALS} decimals"
            )
        elif isinstance(value, list):
            for item in value:
                _assert_stable(item, where)

    data = _fixture_data()
    for block in data["scenarios"]:
        for record in _cycle_records(block):
            for field, value in record.items():
                if field in ("provenance_state",):
                    continue
                _assert_stable(value,
                               f"{block['scenario']} cycle "
                               f"{record['cycle']} field '{field}'")


# ══════════════════════════════════════════════════════════════════════
# The guards: wrong input must fail loudly, never write a wrong fixture.
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("organism", [
    "no_such_body.xml",
    "organism.xml.bak",
    "../organism_nope.xml",
])
def test_an_unknown_organism_file_raises(organism):
    with pytest.raises(ValueError):
        capture_scenario(organism, "rest")
    with pytest.raises(ValueError):
        capture_run(organism, "rest", forcing=None)


def test_an_unknown_scenario_name_raises():
    with pytest.raises(ValueError):
        capture_scenario("organism.xml", "not_a_scenario")
    with pytest.raises(ValueError):
        capture_scenario("organism_key.xml", "hr999")


def test_a_scenario_named_for_the_wrong_body_raises():
    # hr150_edv55 belongs to organism_key.xml, not the default body.
    with pytest.raises(ValueError):
        capture_scenario("organism.xml", "hr150_edv55")


def test_a_forcing_that_names_an_undeclared_attribute_raises():
    with pytest.raises(ValueError) as excinfo:
        capture_run("organism_key.xml", "rest", forcing={"QX": 1.0})
    assert "QX" in str(excinfo.value)
    with pytest.raises(ValueError):
        capture_run(None, "rest", forcing={"DO2": 900.0})


@pytest.mark.parametrize("cycles", [0, -1, -40])
def test_a_cycle_count_below_one_raises(cycles):
    with pytest.raises(ValueError):
        capture_run("organism_key.xml", "rest", forcing=None, cycles=cycles)
    with pytest.raises(ValueError):
        capture_scenario("organism.xml", "rest", cycles=cycles)


def test_a_non_cycle_count_raises():
    with pytest.raises(ValueError):
        capture_run("organism_key.xml", "rest", cycles=1.5)


def test_a_non_finite_trace_value_raises():
    with pytest.raises(ValueError):
        clean_value(float("nan"), "open_fraction", "test cycle 1")
    with pytest.raises(ValueError):
        clean_value(float("inf"), "transmitted", "test cycle 1")
    with pytest.raises(ValueError):
        clean_value(-float("inf"), "DO2", "test cycle 1")
    with pytest.raises(ValueError):
        clean_value_or_none(float("nan"), "CO_ref", "test cycle 1")
    # None is a legitimate recorded value (nothing has crossed yet).
    assert clean_value_or_none(None, "transmitted", "test cycle 1") is None


# ══════════════════════════════════════════════════════════════════════
# The numerical invariant the whole file exists to provide.
# ══════════════════════════════════════════════════════════════════════

def test_recapturing_in_memory_reproduces_the_on_disk_fixture_exactly():
    """
    Re-running the capture in memory must reproduce the committed file
    byte for byte.  This is the baseline contract: any refactor that
    changes a number the model produces fails this test.
    """
    assert capture_json() == FIXTURE_FILE.read_text()
