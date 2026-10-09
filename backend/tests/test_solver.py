"""
The behaviour solver — and the first one that can express a closed loop.

`compute_all()` walks the function chain ONCE in declared step order.
That is enough for any chain shaped like a DAG, and every lamina shipped
so far is one.  It is not enough for a body that feeds back on itself:
raise cardiac output and mean arterial pressure rises, raise mean
arterial pressure and afterload lowers stroke volume, which lowers
cardiac output.  `_resolve` meets that cycle, logs
"Circular dependency detected. Halting", and returns — leaving the
attribute holding whatever it held before.

Measured on the two-attribute cycle below, whose true fixed point is
p = 20/3 = 6.6667:

    compute_all() alone   p = 5.0    failed_attributes = {}
    fixed_point           p = 6.666666667

The first line is the problem.  Not that it is wrong — that it is wrong
with an empty `failed_attributes`, which is this project's oldest
failure mode: a number that is stale or unconverged and reads as live.

So the three properties here are:

  IT CONVERGES.  On a real cycle, to the real fixed point.
  IT NEVER LIES.  A loop that ran out of passes records every attribute
  still moving, with its residual, so a value it returns is either
  converged or marked.
  IT REFUSES A LOOP IT CANNOT MEASURE.  max_iter=1 is one pass, which is
  algebraic_chain wearing an iterative name — and it returned the first
  estimate with a clean bill of health, so it is refused.

Nothing shipped uses it yet: both laminae declare
`<behaviour_solver type="algebraic_chain"/>` and still do.  The solver
is here so that a domain expert who adds afterload gets a body that
solves rather than one that silently halts.
"""
import math

import pytest

from universal_twin import PRELIMINARY, UniversalTwin

# ══════════════════════════════════════════════════════════════════════
# A lamina with a genuine cycle
# ══════════════════════════════════════════════════════════════════════
#
#     p = seed + 0.5·q          q = 0.5·p          seed = 5
#
# Substituting: p = 5 + 0.25p → p = 20/3, q = 10/3.  Chosen because the
# iteration is a geometric walk of ratio 0.25, so how many passes it
# needs is arithmetic rather than luck.

TRUE_P = 20 / 3
TRUE_Q = 10 / 3

_CYCLIC = """<?xml version="1.0" encoding="UTF-8"?>
<lamina id="lamina_cyc" name="Cyc" level="0">
  {solver}
  <attributes>
    <attribute id="seed"><name>Seed</name><unit>u</unit><source>SENSOR</source>
      <physio_min>0</physio_min><physio_max>10</physio_max>
      <baseline>5</baseline></attribute>
    <attribute id="p"><name>P</name><unit>u</unit><source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>f_p</computed_by><depends_on>seed, q</depends_on></attribute>
    <attribute id="q"><name>Q</name><unit>u</unit><source>PRELIMINARY</source>
      <physio_min>0</physio_min><physio_max>100</physio_max>
      <computed_by>f_q</computed_by><depends_on>p</depends_on></attribute>
  </attributes>
  <functions>
    <function id="f_p" step="1"><name>P</name>
      <formula>p = seed + 0.5*q</formula>
      <inputs>seed, q</inputs><output>p</output></function>
    <function id="f_q" step="2"><name>Q</name>
      <formula>q = 0.5*p</formula>
      <inputs>p</inputs><output>q</output></function>
  </functions>
</lamina>
"""


@pytest.fixture
def make_twin(tmp_path):
    """A twin on the cyclic lamina, with its two functions registered."""
    def build(solver='<behaviour_solver type="fixed_point"'
                     ' max_iter="60" tol="1e-9"/>'):
        path = tmp_path / "cyc_lamina.xml"
        path.write_text(_CYCLIC.format(solver=solver), encoding="utf-8")
        twin = UniversalTwin(str(path))
        twin._function_registry["f_p"] = \
            lambda i: (i[0] or 0.0) + 0.5 * (i[1] or 0.0)
        twin._function_registry["f_q"] = lambda i: 0.5 * (i[0] or 0.0)
        twin.set_sensor("seed", 5.0)
        return twin
    return build


def _solve(twin, params=None):
    fn = twin._solver_registry[twin.behaviour_solver_type]
    fn(twin, twin.behaviour_solver_params if params is None else params)
    return twin


# ══════════════════════════════════════════════════════════════════════
# The gap it exists to close
# ══════════════════════════════════════════════════════════════════════

def test_one_pass_gets_a_cycle_wrong_and_does_not_say_so(make_twin):
    """
    The measurement the solver was written for.  Not a test of desired
    behaviour — a record of why the desired behaviour is needed.
    """
    twin = make_twin()
    twin.compute_all()

    assert twin.get("p").value == pytest.approx(5.0)
    assert abs(twin.get("p").value - TRUE_P) > 1.5
    assert twin.failed_attributes == {}, (
        "this is the failure: wrong, and carrying no mark that says so"
    )
    assert any("Circular dependency" in line for line in twin.get_log()), (
        "the cycle IS detected — it is only detected somewhere nobody reads"
    )


# ══════════════════════════════════════════════════════════════════════
# register_solver
# ══════════════════════════════════════════════════════════════════════

def test_the_two_default_solvers_are_registered(make_twin):
    twin = make_twin()
    assert set(twin._solver_registry) >= {"algebraic_chain", "fixed_point"}


def test_a_solver_can_be_registered_and_replaced(make_twin):
    twin = make_twin()
    calls = []
    twin.register_solver("stub", lambda tw, params: calls.append(params))
    twin._solver_registry["stub"](twin, {"a": "1"})
    assert calls == [{"a": "1"}]

    twin.register_solver("stub", lambda tw, params: calls.append("second"))
    twin._solver_registry["stub"](twin, {})
    assert calls[-1] == "second", "registering again replaces, as documented"


@pytest.mark.parametrize("name", ["", "   ", None, 7, ["x"]])
def test_a_solver_without_a_usable_name_is_refused(make_twin, name):
    with pytest.raises(ValueError) as exc:
        make_twin().register_solver(name, lambda tw, p: None)
    assert "non-empty name" in str(exc.value)


@pytest.mark.parametrize("fn", ["not a function", 3, None, {"a": 1}])
def test_a_solver_that_cannot_be_called_is_refused(make_twin, fn):
    with pytest.raises(ValueError) as exc:
        make_twin().register_solver("x", fn)
    assert "callable" in str(exc.value)


# ══════════════════════════════════════════════════════════════════════
# The params that were declared and never arrived
# ══════════════════════════════════════════════════════════════════════

def test_solver_params_are_parsed_from_the_declaration(make_twin):
    """
    `type`, `dt` and `unit` are the framework's; everything else on the
    element belongs to whichever solver was named and is handed over
    verbatim.
    """
    twin = make_twin(
        '<behaviour_solver type="fixed_point" dt="2.0" unit="minute"'
        ' max_iter="40" tol="1e-8"/>')
    assert twin.behaviour_solver_type == "fixed_point"
    assert twin.behaviour_solver_dt == 2.0
    assert twin.behaviour_solver_unit == "minute"
    assert twin.behaviour_solver_params == {"max_iter": "40", "tol": "1e-8"}


def test_a_declaration_with_no_knobs_hands_over_an_empty_dict(make_twin):
    twin = make_twin('<behaviour_solver type="algebraic_chain" dt="1.0"/>')
    assert twin.behaviour_solver_params == {}


def test_a_lamina_with_no_solver_block_keeps_the_default(make_twin):
    twin = make_twin(solver="")
    assert twin.behaviour_solver_type == "algebraic_chain"
    assert twin.behaviour_solver_params == {}


def test_the_controller_hands_the_params_to_the_solver(make_twin):
    """
    The half that made the declaration inert: the params were parsed and
    then the controller called the solver with a literal `{}`.
    """
    from feedback_controller import FeedbackController

    twin = make_twin('<behaviour_solver type="probe" max_iter="9" tol="1e-3"/>')
    seen = []
    twin.register_solver("probe", lambda tw, params: seen.append(params))
    FeedbackController(twin).step()

    assert seen, "the controller never called the declared solver"
    assert seen[0] == {"max_iter": "9", "tol": "1e-3"}, (
        f"the solver was handed {seen[0]!r} instead of what the file declared"
    )


# ══════════════════════════════════════════════════════════════════════
# fixed_point — the guards
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("max_iter", ["0", "1", "-3"])
def test_a_loop_that_cannot_measure_convergence_is_refused(make_twin, max_iter):
    """
    max_iter=1 is the one worth naming.  It runs, returns the first
    estimate, and leaves failed_attributes empty — measured: p = 5.0
    against a true 6.667, reported as clean.  Convergence is a
    comparison between two passes, so one pass cannot make the claim.
    """
    with pytest.raises(ValueError) as exc:
        _solve(make_twin(), {"max_iter": max_iter, "tol": "1e-9"})
    assert "max_iter" in str(exc.value)


@pytest.mark.parametrize("tol", ["0", "-1", "nan", "inf", "-inf"])
def test_a_tolerance_that_defines_nothing_is_refused(make_twin, tol):
    with pytest.raises(ValueError) as exc:
        _solve(make_twin(), {"max_iter": "10", "tol": tol})
    assert "tol" in str(exc.value)


@pytest.mark.parametrize("params", [
    {"max_iter": "abc", "tol": "1e-9"},
    {"max_iter": "2.5", "tol": "1e-9"},
    {"max_iter": "10", "tol": "abc"},
])
def test_an_unreadable_knob_fails_loudly(make_twin, params):
    with pytest.raises(ValueError):
        _solve(make_twin(), params)


def test_the_defaults_apply_when_nothing_is_declared(make_twin):
    """No knobs is not no loop — it is the documented 25 passes at 1e-6."""
    twin = _solve(make_twin('<behaviour_solver type="fixed_point"/>'))
    assert twin.get("p").value == pytest.approx(TRUE_P, abs=1e-5)
    assert twin.failed_attributes == {}


# ══════════════════════════════════════════════════════════════════════
# fixed_point — what it does
# ══════════════════════════════════════════════════════════════════════

def test_it_solves_a_cycle_one_pass_cannot(make_twin):
    twin = _solve(make_twin())
    assert twin.get("p").value == pytest.approx(TRUE_P, abs=1e-8)
    assert twin.get("q").value == pytest.approx(TRUE_Q, abs=1e-8)
    assert twin.failed_attributes == {}


def test_a_chain_with_no_cycle_still_converges(make_twin):
    """
    An acyclic chain is right after the first pass, so the second only
    confirms it. The solver must not need a cycle to be usable.
    """
    twin = make_twin()
    twin._function_registry["f_p"] = lambda i: (i[0] or 0.0) * 2.0
    twin._function_registry["f_q"] = lambda i: 0.5 * (i[0] or 0.0)
    _solve(twin)
    assert twin.get("p").value == pytest.approx(10.0)
    assert twin.get("q").value == pytest.approx(5.0)
    assert twin.failed_attributes == {}


def test_a_loop_that_ran_out_of_passes_says_which_values_are_untrustworthy(
        make_twin):
    """
    The property that makes it safe to leave running: it does not raise
    mid-tick, and it does not pretend either.
    """
    twin = _solve(make_twin(), {"max_iter": "2", "tol": "1e-12"})

    assert twin.failed_attributes, "an unconverged loop must leave a mark"
    assert set(twin.failed_attributes) == {"p", "q"}
    for attr_id, reason in twin.failed_attributes.items():
        assert "did not converge" in reason
        assert attr_id in reason
        assert "residual" in reason
    # The values are still there — marked, not erased.
    assert twin.get("p").value is not None


def test_the_residual_it_reports_is_the_one_it_measured(make_twin):
    """
    p walks 5.0 → 6.25 → 6.5625 …, a geometric approach of ratio 0.25.
    After two passes the last step was 6.25 − 5.0 = 1.25, and that is
    the number the message has to carry — a residual computed from some
    other pair would be a plausible figure attached to nothing.
    """
    twin = _solve(make_twin(), {"max_iter": "2", "tol": "1e-12"})
    assert twin.get("p").value == pytest.approx(6.25)
    assert "1.25" in twin.failed_attributes["p"]
    assert "0.625" in twin.failed_attributes["q"]


def test_more_passes_never_make_it_worse(make_twin):
    """
    The numerical invariant: this iteration is a contraction, so the
    distance to the fixed point falls monotonically with the budget.
    """
    errors = []
    for budget in (2, 4, 8, 16, 40):
        twin = _solve(make_twin(), {"max_iter": str(budget), "tol": "1e-12"})
        errors.append(abs(twin.get("p").value - TRUE_P))
    assert all(math.isfinite(e) for e in errors)
    assert errors == sorted(errors, reverse=True), (
        f"a larger budget has to land at least as close, got {errors}")
    assert errors[-1] < 1e-9


def test_nothing_it_returns_unmarked_is_still_moving(make_twin):
    """
    The invariant stated the other way round, and the one that actually
    matters to a reader: for every budget, an attribute is EITHER inside
    tol of its final value OR named in failed_attributes. Never neither.
    """
    tol = 1e-6
    for budget in (2, 3, 5, 10, 60):
        twin = _solve(make_twin(), {"max_iter": str(budget), "tol": str(tol)})
        for attr_id in ("p", "q"):
            settled = abs(twin.get(attr_id).value
                          - (TRUE_P if attr_id == "p" else TRUE_Q)) < tol
            marked = attr_id in twin.failed_attributes
            assert settled or marked, (
                f"budget {budget}: '{attr_id}' is neither settled nor marked"
            )


# ══════════════════════════════════════════════════════════════════════
# What the shipped bodies do
# ══════════════════════════════════════════════════════════════════════

def test_the_shipped_laminae_still_run_the_single_pass_solver():
    """
    The guardrail this project keeps: a universal mechanism is added
    without moving a shipped number. Both laminae are steady-state
    algebra and say so; the new solver is here for the body that is not.
    """
    from laminae import load_twin

    for path in ("circulatory_lamina.xml", "respiratory_lamina.xml"):
        twin = load_twin(path)
        assert twin.behaviour_solver_type == "algebraic_chain"
        assert twin.behaviour_solver_params == {}
