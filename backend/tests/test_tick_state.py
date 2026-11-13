"""
Stateful functions, missing readings, and stale-input propagation.

A Session.tick() runs compute_all() four times, so a function that advanced
its own state on every call would advance four times per tick.  These probes
pin the contract: compute is read-only, end_tick commits once, and a missing
input makes the whole downstream chain stale instead of quietly recomputing
from last cycle's number.
"""
import pytest
from fastapi.testclient import TestClient

import laminae
from session import Session
from universal_twin import PRELIMINARY, SENSOR, UniversalTwin


def _attr(attr_id, source, computed_by=None, physio_max=1000):
    computed = (f"<computed_by>{computed_by}</computed_by>"
                if computed_by else "")
    return (
        f'<attribute id="{attr_id}">'
        f"<name>{attr_id}</name><unit>u</unit><source>{source}</source>"
        f"<physio_min>0</physio_min><physio_max>{physio_max}</physio_max>"
        f"{computed}</attribute>"
    )


def _func(func_id, inputs, output, step, state=None):
    state_xml = f'<state after_gap="{state}"/>' if state else ""
    return (
        f'<function id="{func_id}" step="{step}">'
        f"<name>{func_id}</name><formula>{func_id}</formula>"
        f"<inputs>{inputs}</inputs><output>{output}</output>"
        f"{state_xml}</function>"
    )


def _write_lamina(tmp_path, name, attrs, funcs,
                  lamina_id="lamina_probe"):
    path = tmp_path / f"{name}.xml"
    path.write_text(
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<lamina id="{lamina_id}" name="Probe" level="1">'
        f"<attributes>{attrs}</attributes>"
        f"<functions>{funcs}</functions>"
        f"<segments/></lamina>",
        encoding="utf-8",
    )
    return path


class ProbeTwin(UniversalTwin):
    """A twin whose functions are supplied by the test, with call counts."""

    def __init__(self, xml_path, funcs):
        self._probe_funcs = funcs
        self.calls: dict[str, int] = {}
        super().__init__(xml_path)

    def _register_functions(self):
        for func_id, fn in self._probe_funcs.items():
            def wrapper(inputs, _fn=fn, _func_id=func_id):
                self.calls[_func_id] = self.calls.get(_func_id, 0) + 1
                return _fn(inputs)
            self._function_registry[func_id] = wrapper


def _probe(tmp_path, attrs, funcs, callables, name="probe"):
    path = _write_lamina(tmp_path, name, attrs, funcs)
    return ProbeTwin(str(path), callables)


ACC_ATTRS = _attr("x", SENSOR) + _attr("acc", PRELIMINARY, "acc")


def _acc(inputs):
    x, prev = inputs
    return (prev or 0.0) + x


def _acc_funcs(state):
    return _func("acc", "x", "acc", "1", state)


# ── Stateful functions ───────────────────────────────────────────────

def test_stateful_function_advances_once_per_tick(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("reseed"), {"acc": _acc})
    twin.set_sensor("x", 1.0)

    values = []
    for _ in range(3):
        # Every pass inside one tick sees the same committed value.
        for _ in range(4):
            twin.compute_all()
            assert twin.attributes["acc"].value == pytest.approx(len(values) + 1)
        values.append(twin.attributes["acc"].value)
        twin.end_tick()

    assert values == pytest.approx([1.0, 2.0, 3.0])


def test_reseed_forgets_state_after_a_failed_tick(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("reseed"), {"acc": _acc})
    twin.set_sensor("x", 1.0)
    twin.compute_all()
    twin.end_tick()
    assert twin._function_state["acc"] == pytest.approx(1.0)

    twin.clear_sensor("x")
    twin.compute_all()
    assert "acc" in twin.failed_attributes
    twin.end_tick()
    assert twin._function_state["acc"] is None

    twin.set_sensor("x", 2.0)
    twin.compute_all()
    assert twin.attributes["acc"].value == pytest.approx(2.0)


def test_hold_keeps_state_after_a_failed_tick(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("hold"), {"acc": _acc})
    twin.set_sensor("x", 1.0)
    twin.compute_all()
    twin.end_tick()
    assert twin._function_state["acc"] == pytest.approx(1.0)

    twin.clear_sensor("x")
    twin.compute_all()
    assert "acc" in twin.failed_attributes
    twin.end_tick()
    assert twin._function_state["acc"] == pytest.approx(1.0)

    twin.set_sensor("x", 2.0)
    twin.compute_all()
    assert twin.attributes["acc"].value == pytest.approx(3.0)


def test_reset_state_makes_the_next_call_receive_none(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("hold"), {"acc": _acc})
    twin.set_sensor("x", 2.0)
    twin.compute_all()
    twin.end_tick()

    twin.reset_state()
    assert twin._function_state == {}

    twin.compute_all()
    assert twin.attributes["acc"].value == pytest.approx(2.0)


# ── Missing readings ─────────────────────────────────────────────────

def test_clear_sensor_leaves_no_value(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("reseed"), {"acc": _acc})
    twin.set_sensor("x", 3.0)
    twin.compute_all()

    twin.clear_sensor("x")

    attr = twin.attributes["x"]
    assert attr.value is None
    assert attr.value_external is None
    assert attr.normalised is None
    assert any("SENSOR CLEARED: x" in line for line in twin.get_log())


def test_clear_sensor_refuses_unknown_and_non_sensor_ids(tmp_path):
    twin = _probe(tmp_path, ACC_ATTRS, _acc_funcs("reseed"), {"acc": _acc})

    with pytest.raises(KeyError, match="nope"):
        twin.clear_sensor("nope")
    with pytest.raises(ValueError, match="not SENSOR"):
        twin.clear_sensor("acc")


# ── Staleness propagates ─────────────────────────────────────────────

CHAIN_ATTRS = (
    _attr("a", SENSOR)
    + _attr("b", PRELIMINARY, "b_fn")
    + _attr("c", PRELIMINARY, "c_fn")
)
CHAIN_FUNCS = (
    _func("b_fn", "a", "b", "1")
    + _func("c_fn", "b", "c", "2")
)


def _double(inputs):
    return inputs[0] * 2.0


def _plus_one(inputs):
    return inputs[0] + 1.0


def test_missing_sensor_makes_the_whole_chain_stale(tmp_path):
    twin = _probe(tmp_path, CHAIN_ATTRS, CHAIN_FUNCS,
                  {"b_fn": _double, "c_fn": _plus_one})
    twin.set_sensor("a", 2.0)
    twin.compute_all()
    assert twin.attributes["b"].value == pytest.approx(4.0)
    assert twin.attributes["c"].value == pytest.approx(5.0)

    twin.calls.clear()
    twin.clear_sensor("a")
    twin.compute_all()

    assert twin.failed_attributes["b"] == "input a not available"
    assert twin.failed_attributes["c"] == "input b not available"
    assert twin.calls.get("b_fn", 0) == 0
    assert twin.calls.get("c_fn", 0) == 0
    # The old values remain, exactly as after a raising function.
    assert twin.attributes["b"].value == pytest.approx(4.0)
    assert twin.attributes["c"].value == pytest.approx(5.0)

    twin.calls.clear()
    twin.set_sensor("a", 3.0)
    twin.compute_all()

    assert "b" not in twin.failed_attributes
    assert "c" not in twin.failed_attributes
    assert twin.calls["b_fn"] == 1
    assert twin.calls["c_fn"] == 1
    assert twin.attributes["b"].value == pytest.approx(6.0)
    assert twin.attributes["c"].value == pytest.approx(7.0)


def _double_or_raise(inputs):
    if inputs[0] < 0.0:
        raise ValueError("negative a")
    return inputs[0] * 2.0


def test_a_raising_function_also_makes_downstream_stale(tmp_path):
    twin = _probe(tmp_path, CHAIN_ATTRS, CHAIN_FUNCS,
                  {"b_fn": _double_or_raise, "c_fn": _plus_one})
    twin.set_sensor("a", -1.0)
    twin.compute_all()

    assert twin.failed_attributes["b"] == "ValueError: negative a"
    assert twin.failed_attributes["c"] == "input b not available"
    assert twin.calls.get("c_fn", 0) == 0

    twin.calls.clear()
    twin.set_sensor("a", 2.0)
    twin.compute_all()

    assert "b" not in twin.failed_attributes
    assert "c" not in twin.failed_attributes
    assert twin.calls["b_fn"] == 1
    assert twin.calls["c_fn"] == 1


# ── Load-time guard ──────────────────────────────────────────────────

def test_unknown_after_gap_fails_at_load(tmp_path):
    path = _write_lamina(
        tmp_path, "bad_state", ACC_ATTRS, _acc_funcs("sometimes")
    )
    with pytest.raises(ValueError) as caught:
        ProbeTwin(str(path), {"acc": _acc})

    message = str(caught.value)
    assert "acc" in message
    assert "reseed" in message
    assert "hold" in message


# ── Session wiring ───────────────────────────────────────────────────

class _SessionProbeTwin(UniversalTwin):
    def _register_functions(self):
        self._function_registry["acc"] = (
            lambda inputs: (inputs[1] or 0.0) + inputs[0]
        )


def test_session_clears_missing_and_reset_clears_committed_state(
        tmp_path, monkeypatch):
    monkeypatch.setitem(laminae._IMPLEMENTATIONS,
                        "lamina_session_probe", _SessionProbeTwin)
    path = _write_lamina(
        tmp_path, "session_probe", ACC_ATTRS, _acc_funcs("hold"),
        lamina_id="lamina_session_probe",
    )

    session = Session(sensor_data={"x": 5.0}, lamina=path)
    assert session.twin._function_state == {}

    session.tick({})
    assert session.twin._function_state["acc"] == pytest.approx(5.0)

    snap = session.tick({}, missing=["x"])
    assert snap["sensors"]["x"]["value"] is None
    assert snap["sensors"]["x"]["value_external"] is None
    assert session.twin._function_state["acc"] == pytest.approx(5.0)

    session.reset()
    assert session.twin._function_state == {}


# ── Schema ───────────────────────────────────────────────────────────

def test_schema_reports_state_for_every_function():
    import main

    response = TestClient(main.app).get(
        "/api/schema", params={"lamina": "lamina_circulatory"}
    )
    assert response.status_code == 200
    functions = response.json()["functions"]
    assert functions
    assert all("state" in f for f in functions)
    assert all(f["state"] is None for f in functions)
