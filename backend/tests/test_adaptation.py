"""
Phase 1 tests — Adaptive Feedback Loop scaffolding (universal layer).

These lock the parent-level mechanism the spec calls for:
  - a sixth `adaptation_kernel` registry parallel to the gate kernel
  - a PERSISTENT per-outcome meta-state store that survives the fast
    loop's transient reset (the two-timescale invariant)
  - model_free registered as the default kernel, rls as a deferred stub
  - the slow loop ships INERT (cadence 0) so pre-adaptive laminas are
    unchanged

No domain math is touched — these only exercise UniversalTwin.
"""

import pytest

from circulatory_lamina import CirculatoryLamina
from universal_twin import MetaState
from feedback_controller import FeedbackController

XML = "circulatory_lamina.xml"


@pytest.fixture
def twin():
    return CirculatoryLamina(XML)


# ── Registry ─────────────────────────────────────────────────────────

def test_adaptation_registry_has_default_kernels(twin):
    assert "model_free" in twin._adaptation_kernel_registry
    assert "rls" in twin._adaptation_kernel_registry


def test_rls_is_a_deferred_stub(twin):
    rls = twin._adaptation_kernel_registry["rls"]
    with pytest.raises(NotImplementedError):
        rls(MetaState(), {}, {})


def test_framework_default_is_inert(tmp_path):
    """A lamina that omits the <adaptation> block inherits the universal
    mechanism (registry + meta-state) but ships with the slow loop OFF —
    pre-adaptive behaviour is unchanged.  This is also a mini acceptance
    check: the parent provides the loop with zero lamina code."""
    from universal_twin import UniversalTwin
    xml = tmp_path / "bare.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<lamina name="Bare" id="bare" level="1"></lamina>'
    )
    bare = UniversalTwin(str(xml))
    assert bare.slow_loop_cadence == 0                      # inert
    assert "model_free" in bare._adaptation_kernel_registry  # mechanism inherited
    assert "rls" in bare._adaptation_kernel_registry
    assert bare._meta_state == {}


def test_xml_opts_into_slow_loop(twin):
    """Phase 5: circulatory_lamina.xml now declares <adaptation>, so the
    lamina opts into the slow loop with the configured numbers."""
    assert twin.slow_loop_cadence == 20
    assert twin.adaptation_kernel_type == "model_free"
    # A few param overrides must have come through from the XML.
    assert twin.adaptation_params["gain_max"] == 1.20
    assert twin.adaptation_params["op_max"] == 0.30
    assert twin.adaptation_params["settle_band"] == 0.50


# ── Persistent meta-state store ──────────────────────────────────────

def test_meta_state_lazily_created(twin):
    assert twin._meta_state == {}
    ms = twin.get_meta_state("target_co")
    assert isinstance(ms, MetaState)
    # Same object returned on second access (not recreated).
    assert twin.get_meta_state("target_co") is ms


def test_meta_state_survives_fast_loop_reset(twin):
    """The core two-timescale invariant: transient state is wiped, the
    persistent meta-state is not."""
    ms = twin.get_meta_state("target_co")
    ms.gain = 0.9
    ms.perf_ewma = 0.42

    fc = FeedbackController(twin)
    fc._kernel_state[("CO_DEV", "SV")] = {"x_pp": 0.123}
    fc.reset_kernel_state()

    assert fc._kernel_state == {}                      # transient wiped
    survived = twin.get_meta_state("target_co")        # persistent kept
    assert survived is ms
    assert survived.gain == 0.9
    assert survived.perf_ewma == 0.42


def test_explicit_meta_reset_clears_store(twin):
    twin.get_meta_state("target_co").gain = 1.1
    twin.reset_meta_state()
    assert twin._meta_state == {}


# ── model_free kernel behaviour ──────────────────────────────────────

def test_model_free_returns_frozen_contract_shape(twin):
    mf = twin._adaptation_kernel_registry["model_free"]
    ms = twin.get_meta_state("target_co")
    out = mf(ms, {"perf": 0.3, "settled": False,
                  "sustained_correction": 0.0}, twin.adaptation_params)
    assert set(out) == {"gain", "operating_point", "op_delta",
                        "direction", "consolidated"}


def test_model_free_does_not_mutate_meta(twin):
    """Kernel is pure w.r.t. meta — the controller owns write-back."""
    mf = twin._adaptation_kernel_registry["model_free"]
    ms = twin.get_meta_state("target_co")
    ms.gain = 0.6
    mf(ms, {"perf": 0.3, "settled": True,
            "sustained_correction": 0.5}, twin.adaptation_params)
    assert ms.gain == 0.6            # unchanged
    assert ms.operating_point == 0.0


def test_model_free_gain_clamped_to_bounds(twin):
    mf = twin._adaptation_kernel_registry["model_free"]
    ms = MetaState(gain=10.0, last_direction=1.0, prev_perf=0.5)
    out = mf(ms, {"perf": 0.1, "settled": False,
                  "sustained_correction": 0.0}, twin.adaptation_params)
    assert out["gain"] <= twin.adaptation_params["gain_max"]


def test_model_free_consolidates_only_when_settled(twin):
    mf = twin._adaptation_kernel_registry["model_free"]
    ms = twin.get_meta_state("target_co")
    # Mid-transient: no operating-point movement.
    moving = mf(ms, {"perf": 0.3, "settled": False,
                     "sustained_correction": 0.8}, twin.adaptation_params)
    assert moving["op_delta"] == 0.0
    assert moving["consolidated"] is False
    # Settled: residual folds into the operating point.
    settled = mf(ms, {"perf": 0.3, "settled": True,
                      "sustained_correction": 0.8}, twin.adaptation_params)
    assert settled["op_delta"] != 0.0
    assert settled["consolidated"] is True


def test_model_free_mit_rule_reverses_on_worse_perf(twin):
    """If the last nudge made performance worse, flip direction."""
    mf = twin._adaptation_kernel_registry["model_free"]
    ms = MetaState(gain=0.6, last_direction=1.0, prev_perf=0.20)
    out = mf(ms, {"perf": 0.35, "settled": False,     # got worse (0.20→0.35)
                  "sustained_correction": 0.0}, twin.adaptation_params)
    assert out["direction"] == -1.0


# ── Phase 2 — performance accumulator (EWMA per outcome) ─────────────

NORMAL_SENSORS = {
    "SBP": 120, "DBP": 80, "HR": 72, "eta": 3.5, "L": 20, "r": 0.4,
    "EDV": 120, "r_m": 5000, "r_i": 200, "r_e": 300,
}


def _running_twin(enable=True, cadence=20):
    """A circulatory twin with sensors set and the slow loop forced on/off.

    The XML now opts into the slow loop (cadence 20), so disabling means
    explicitly zeroing the cadence; enabling overrides it to the value the
    test wants.
    """
    t = CirculatoryLamina(XML)
    for k, v in NORMAL_SENSORS.items():
        t.set_sensor(k, v)
    t.compute_all()
    t.slow_loop_cadence = cadence if enable else 0
    return t


def test_update_performance_seeds_then_ewma(twin):
    """Deterministic EWMA check, domain-free: feed hand-built deviations."""
    twin.slow_loop_cadence = 20
    fc = FeedbackController(twin)
    alpha = twin.adaptation_params["perf_alpha"]
    tol = 1.5  # target_co tolerance from the XML

    # deviation 3.0 → normalised 2.0 → seeds the EWMA.
    evals = {"seg": [{"outcome_id": "target_co", "attribute_id": "CO",
                      "deviation": 3.0}]}
    fc._update_performance(evals)
    assert twin.get_meta_state("target_co").perf_ewma == pytest.approx(3.0 / tol)

    # deviation 0.0 → normalised 0.0 → EWMA decays toward 0.
    evals0 = {"seg": [{"outcome_id": "target_co", "attribute_id": "CO",
                       "deviation": 0.0}]}
    fc._update_performance(evals0)
    expected = (1 - alpha) * (3.0 / tol) + alpha * 0.0
    assert twin.get_meta_state("target_co").perf_ewma == pytest.approx(expected)


def test_perf_accumulator_inert_when_disabled():
    """cadence 0 → no meta-state touched, report['perf'] empty."""
    t = _running_twin(enable=False)
    fc = FeedbackController(t)
    report = fc.step()
    assert report["perf"] == {}
    assert t._meta_state == {}            # nothing created


def test_perf_accumulator_populates_when_enabled():
    t = _running_twin(enable=True)
    fc = FeedbackController(t)
    report = fc.step()
    # Every tagged outcome that has a positive tolerance is tracked.
    assert report["perf"]                 # non-empty
    for outcome_id in report["perf"]:
        assert t.get_meta_state(outcome_id).perf_ewma is not None


def test_perf_tracks_only_tagged_outcomes():
    t = _running_twin(enable=True)
    fc = FeedbackController(t)
    fc.step()
    assert set(t._meta_state).issubset(fc._tagged_outcomes)


def test_perf_survives_dead_zone_snap():
    """The accumulator lives in persistent meta-state, so the snap that
    wipes the fast loop's transient store must not erase it."""
    t = _running_twin(enable=True)
    fc = FeedbackController(t)
    fc.step()
    tracked = dict(
        (oid, t.get_meta_state(oid).perf_ewma) for oid in t._meta_state
    )
    assert tracked
    # Force a snap of all transient state.
    fc.reset_kernel_state()
    for oid, ewma in tracked.items():
        assert t.get_meta_state(oid).perf_ewma == ewma


# ── Phase 3 — slow loop (adaptation every N cycles) ──────────────────

def test_slow_loop_fires_only_on_cadence():
    t = _running_twin(enable=True, cadence=3)
    fc = FeedbackController(t)
    r1 = fc.step()
    r2 = fc.step()
    r3 = fc.step()                       # cycle 3 → cadence tick
    assert r1["adaptation"] == {}
    assert r2["adaptation"] == {}
    assert r3["adaptation"]              # populated on the tick


def test_gain_handed_down_to_fast_loop():
    """The one-way 'parameter adjustments down' stream: a learned gain in
    meta-state overrides the static tag/XML gain in the fast loop."""
    t = _running_twin(enable=True)
    fc = FeedbackController(t)
    tag = t.tags["CO_DEVIATION"]
    t.get_meta_state("target_co").gain = 1.23
    params = fc._build_kernel_params(tag, "target_co", "CO", 1.0)
    assert params["gain"] == 1.23


def test_gain_not_handed_down_when_disabled():
    t = _running_twin(enable=False)
    fc = FeedbackController(t)
    tag = t.tags["CO_DEVIATION"]
    t.get_meta_state("target_co").gain = 1.23
    params = fc._build_kernel_params(tag, "target_co", "CO", 1.0)
    assert params["gain"] != 1.23       # falls back to tag/XML default


def test_slow_loop_updates_meta_state():
    t = _running_twin(enable=True, cadence=1)
    fc = FeedbackController(t)
    before = t.get_meta_state("target_co")
    fc.step()  # cadence 1 → ticks every cycle; seeds perf then adapts
    fc.step()
    ms = t.get_meta_state("target_co")
    assert ms.gain is not None          # gain learned
    assert ms.prev_perf is not None     # MIT snapshot taken
    assert ms.updates >= 1


def test_bumpless_transfer_keeps_applied_total_continuous():
    """The core locked design rule: folding the operating point must not
    change the correction applied at the instant of transfer — only the
    split between transient (leaky) and persistent (operating point)."""
    t = _running_twin(enable=True, cadence=1)
    fc = FeedbackController(t)
    attr_id = fc._outcome_attr["target_co"]            # CO

    # Seed a steady transient correction and a settled, populated meta.
    fc._kernel_state[("CO_DEVIATION", attr_id)] = {"x_pp": 2.0}
    ms = t.get_meta_state("target_co")
    ms.perf_ewma = 0.1
    ms.operating_point = 0.0

    # A settled outcome (small deviation) so consolidation triggers.
    evals = {"seg": [{"outcome_id": "target_co", "attribute_id": attr_id,
                      "actual": 5.0, "target": 5.0, "deviation": 0.05}]}

    # Step 4 computes delta_per_attr from the transient BEFORE the slow
    # loop runs — replicate that here.
    transient_before = fc._kernel_state[("CO_DEVIATION", attr_id)]["x_pp"]

    report, op_delta_native = fc._run_slow_loop(evals)

    # Consolidation must actually have happened.
    assert op_delta_native.get(attr_id, 0.0) != 0.0
    assert ms.operating_point != 0.0

    # Replicate step()'s Step 5 arithmetic for this attribute.
    applied = (transient_before
               - op_delta_native.get(attr_id, 0.0)
               + fc._operating_point_per_attr().get(attr_id, 0.0))
    assert applied == pytest.approx(transient_before)   # bumpless

    # …and the transient integrator was genuinely drained for next cycle.
    assert fc._kernel_state[("CO_DEVIATION", attr_id)]["x_pp"] < transient_before


def test_no_consolidation_when_not_settled():
    t = _running_twin(enable=True, cadence=1)
    fc = FeedbackController(t)
    attr_id = fc._outcome_attr["target_co"]
    fc._kernel_state[("CO_DEVIATION", attr_id)] = {"x_pp": 2.0}
    ms = t.get_meta_state("target_co")
    ms.perf_ewma = 3.0
    # Large deviation → not settled → operating point must not move.
    evals = {"seg": [{"outcome_id": "target_co", "attribute_id": attr_id,
                      "actual": 12.0, "target": 5.0, "deviation": 7.0}]}
    fc._run_slow_loop(evals)
    assert ms.operating_point == 0.0


def test_adaptation_run_stays_stable():
    """Integration: many cycles with adaptation on must not diverge and
    the performance accumulator must stay finite and bounded."""
    import math
    t = _running_twin(enable=True, cadence=10)
    fc = FeedbackController(t)
    reports = fc.run(60)
    assert not any(r["diverged"] for r in reports)
    for oid, ms in t._meta_state.items():
        assert ms.perf_ewma is None or math.isfinite(ms.perf_ewma)
        if ms.gain is not None:
            assert (t.adaptation_params["gain_min"]
                    <= ms.gain <= t.adaptation_params["gain_max"])
