"""
Tests for the composite STATE VALUE — the single scalar that summarises a
composite as a weighted mean of its normalised attribute values, the
absorption vector acting as the weight matrix.

Covered here:
  - Composite.state_value: hand-computed weighted mean, every guard, and
    the equal-weight fallback used when the absorption vector is None or
    the wrong length (the same fallback apply_absorption uses).
  - UniversalTwin.get_composite_state: None-dropping, the None answer when
    nothing readable is left, and the KeyError for an unknown composite.
  - UniversalTwin.get_all_composite_states: mirrors get_all_vectors.
  - The [0, 1] invariant: normalised values and positive weights can only
    produce a state value that is itself in [0, 1].
"""

import numpy as np
import pytest

from universal_twin import Composite, UniversalTwin


# ── Composite.state_value — unit level ───────────────────────────────

def _comp(weights=None):
    c = Composite(
        id="grp",
        name="Group",
        attribute_ids=["A", "B", "C"],
    )
    if weights is not None:
        c.absorption_vector = np.asarray(weights, dtype=float)
    return c


def test_state_value_weighted_mean_hand_computed():
    c = _comp(weights=[0.5, 1.0, 0.25])
    # Σ(v·w) = 0.2·0.5 + 0.8·1.0 + 0.6·0.25 = 1.05
    # Σw     = 1.75                      →  1.05 / 1.75 = 0.6
    assert c.state_value([0.2, 0.8, 0.6]) == pytest.approx(0.6)


def test_state_value_equal_weight_fallback_when_vector_none():
    c = _comp(weights=None)
    vals = [0.2, 0.8, 0.6]
    assert c.state_value(vals) == pytest.approx(np.mean(vals))


def test_state_value_equal_weight_fallback_when_vector_wrong_length():
    c = _comp(weights=[0.9])  # one weight, three values → no match
    vals = [0.2, 0.8, 0.6]
    assert c.state_value(vals) == pytest.approx(np.mean(vals))


def test_state_value_empty_values_raise():
    c = _comp(weights=[0.5, 1.0, 0.25])
    with pytest.raises(ValueError):
        c.state_value([])


def test_state_value_nan_value_raises():
    c = _comp(weights=[0.5, 1.0, 0.25])
    with pytest.raises(ValueError):
        c.state_value([0.2, np.nan, 0.6])


def test_state_value_infinite_value_raises():
    c = _comp(weights=[0.5, 1.0, 0.25])
    with pytest.raises(ValueError):
        c.state_value([0.2, np.inf, 0.6])


def test_state_value_nan_weight_raises():
    c = _comp(weights=[0.5, np.nan, 0.25])
    with pytest.raises(ValueError):
        c.state_value([0.2, 0.8, 0.6])


def test_state_value_infinite_weight_raises():
    c = _comp(weights=[0.5, np.inf, 0.25])
    with pytest.raises(ValueError):
        c.state_value([0.2, 0.8, 0.6])


def test_state_value_zero_weight_sum_raises():
    c = _comp(weights=[0.0, 0.0, 0.0])
    with pytest.raises(ValueError):
        c.state_value([0.2, 0.8, 0.6])


def test_state_value_negative_weight_sum_raises():
    c = _comp(weights=[-0.5, -1.0, -0.5])
    with pytest.raises(ValueError):
        c.state_value([0.2, 0.8, 0.6])


def test_state_value_out_of_range_value_raises():
    c = _comp(weights=[0.5, 1.0, 0.25])
    with pytest.raises(ValueError):
        c.state_value([1.2, 0.8, 0.6])
    with pytest.raises(ValueError):
        c.state_value([-0.1, 0.8, 0.6])


def test_state_value_ragged_input_raises():
    c = _comp(weights=[0.5, 1.0, 0.25])
    with pytest.raises(ValueError):
        c.state_value([[0.2, 0.8], [0.6]])


def test_state_value_numerical_invariant_in_unit_interval():
    rng = np.random.default_rng(0)
    c = _comp(weights=None)
    for _ in range(200):
        vals = rng.random(5)
        w = rng.random(5) + 1e-6          # strictly positive weights
        c.absorption_vector = w
        s = c.state_value(vals.tolist())
        assert 0.0 <= s <= 1.0


# ── UniversalTwin.get_composite_state — integration level ───────────

def _twin(tmp_path, absorption_text):
    xml = tmp_path / "twin.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<lamina name="Twin" id="twin" level="1">'
        "  <attributes>"
        '    <attribute id="A"><source>SENSOR</source>'
        "<physio_min>0</physio_min><physio_max>100</physio_max></attribute>"
        '    <attribute id="B"><source>SENSOR</source>'
        "<physio_min>0</physio_min><physio_max>100</physio_max></attribute>"
        '    <attribute id="C"><source>SENSOR</source>'
        "<physio_min>0</physio_min><physio_max>100</physio_max></attribute>"
        "  </attributes>"
        "  <composites>"
        '    <composite id="grp"><attributes>A, B, C</attributes>'
        f"{absorption_text}"
        "    </composite>"
        "  </composites>"
        "</lamina>"
    )
    return UniversalTwin(str(xml))


def test_get_composite_state_weighted_mean(tmp_path):
    t = _twin(
        tmp_path,
        "<absorption_vector>"
        '<weight attribute="A">0.5</weight>'
        '<weight attribute="B">1.0</weight>'
        '<weight attribute="C">0.5</weight>'
        "</absorption_vector>",
    )
    t.set_sensor("A", 50)   # normalised 0.5
    t.set_sensor("B", 80)   # normalised 0.8
    t.set_sensor("C", 20)   # normalised 0.2
    # Σ(v·w) = 0.25 + 0.8 + 0.1 = 1.15 over Σw = 2.0 → 0.575
    assert t.get_composite_state("grp") == pytest.approx(0.575)


def test_get_composite_state_drops_none_attributes_with_their_weights(tmp_path):
    t = _twin(
        tmp_path,
        "<absorption_vector>"
        '<weight attribute="A">0.5</weight>'
        '<weight attribute="B">1.0</weight>'
        '<weight attribute="C">0.5</weight>'
        "</absorption_vector>",
    )
    t.set_sensor("A", 50)   # normalised 0.5
    t.set_sensor("B", 80)   # normalised 0.8
    # C unset → normalised None → dropped together with its 0.5 weight.
    # Σ(v·w) = 0.25 + 0.8 = 1.05 over Σw = 1.5 → 0.7
    assert t.get_composite_state("grp") == pytest.approx(0.7)


def test_get_composite_state_all_none_returns_none(tmp_path):
    t = _twin(
        tmp_path,
        "<absorption_vector>"
        '<weight attribute="A">0.5</weight>'
        '<weight attribute="B">1.0</weight>'
        '<weight attribute="C">0.5</weight>'
        "</absorption_vector>",
    )
    assert t.get_composite_state("grp") is None


def test_get_composite_state_plain_mean_without_absorption_vector(tmp_path):
    t = _twin(tmp_path, "")
    t.set_sensor("A", 50)   # normalised 0.5
    t.set_sensor("B", 100)  # normalised 1.0
    t.set_sensor("C", 0)    # normalised 0.0
    assert t.get_composite_state("grp") == pytest.approx((0.5 + 1.0 + 0.0) / 3)


def test_get_composite_state_unknown_composite_raises(tmp_path):
    t = _twin(tmp_path, "")
    with pytest.raises(KeyError) as exc:
        t.get_composite_state("does_not_exist")
    assert "Composite 'does_not_exist' not defined in XML" in str(exc.value)


def test_get_all_composite_states_matches_vectors_shape(tmp_path):
    t = _twin(
        tmp_path,
        "<absorption_vector>"
        '<weight attribute="A">0.5</weight>'
        '<weight attribute="B">1.0</weight>'
        '<weight attribute="C">0.5</weight>'
        "</absorption_vector>",
    )
    t.set_sensor("A", 50)
    t.set_sensor("B", 80)
    states = t.get_all_composite_states()
    assert set(states) == set(t.get_all_vectors())
    for comp_id, state in states.items():
        assert state == t.get_composite_state(comp_id)
