"""
The wearable lamina's per-workout-kind activity gain.

The workout categories live in the XML: each indicator replays as 1 on a
minute the recording labels as that kind of workout and 0 otherwise, and each
gain is a personal coefficient.  These probes check the selection, the guards
that refuse a nonsensical minute or indicator, and that a fitted gain reaches
HR_drive on the committed demo day without disturbing the minutes it should
not touch.
"""
import pytest

from bundles import load_bundle
from laminae import LAMINA_DIR, load_twin
from session import Session
from signal_source import ReplaySource

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"
DEMO = ("demo", "2025-06-01")


def _activity_gain(twin, *inputs):
    return twin._function_registry["activity_gain"](list(inputs))


def test_activity_gain_returns_the_strength_gain_when_strength_is_the_workout():
    twin = load_twin(WEARABLE)
    gain = _activity_gain(twin, 0.0, 1.0, 0.0, 1.2, 1.7, 0.8)
    assert gain == pytest.approx(1.7)


def test_no_workout_at_all_leaves_the_gain_at_one():
    twin = load_twin(WEARABLE)
    gain = _activity_gain(twin, 0.0, 0.0, 0.0, 1.5, 2.0, 0.5)
    assert gain == pytest.approx(1.0)


def test_two_indicators_at_once_are_refused():
    twin = load_twin(WEARABLE)
    with pytest.raises(ValueError,
                       match="a minute cannot be two kinds of workout"):
        _activity_gain(twin, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0)


def test_an_indicator_above_one_is_refused():
    twin = load_twin(WEARABLE)
    with pytest.raises(ValueError):
        _activity_gain(twin, 1.5, 0.0, 0.0, 1.0, 1.0, 1.0)


def test_a_nan_indicator_is_refused():
    twin = load_twin(WEARABLE)
    with pytest.raises(ValueError):
        _activity_gain(twin, float("nan"), 0.0, 0.0, 1.0, 1.0, 1.0)


def test_a_fitted_walk_gain_scales_only_the_walking_minutes():
    bundle = load_bundle(*DEMO)
    session = Session(lamina=WEARABLE)
    source = ReplaySource(session.twin, bundle, params={"g_walk": 1.5})
    session.seed(source.starting_state())

    snapshots = {}
    for index in range(1061):
        readings = source.next()
        snapshot = session.tick(readings, missing=source.last_missing)
        if index in (490, 600, 1060):
            snapshots[index] = snapshot

    walking = snapshots[490]
    k_i = walking["sensors"]["k_I"]["value"]
    ae_rate = walking["sensors"]["AE_rate"]["value"]
    p_i = walking["sensors"]["p_I"]["value"]
    assert walking["computed"]["g_activity"]["value"] == pytest.approx(1.5)
    assert walking["computed"]["HR_drive"]["value"] == pytest.approx(
        1.5 * k_i * ae_rate ** p_i
    )

    quiet = snapshots[600]
    assert quiet["computed"]["g_activity"]["value"] == pytest.approx(1.0)

    strength = snapshots[1060]
    assert strength["sensors"]["is_strength"]["value"] == pytest.approx(1.0)
    assert strength["computed"]["g_activity"]["value"] == pytest.approx(1.0)
