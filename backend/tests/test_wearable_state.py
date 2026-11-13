"""
The wearable lamina's two stateful steps, and replay clearing missing readings.

HR_model now lags its target with tau_on / tau_off, and kcal_active_cum
accumulates the day's active energy.  The engine commits both once per tick,
so these probes check the step response against the closed-form curve, check
that a replayed day reproduces itself after reset, check that a null reading
marks the measured chain stale without marking the model stale, and check the
guards on the two new callables.

The demo bundle is synthetic and is the only recording used here.
"""
import math
import statistics

import pytest
from fastapi.testclient import TestClient

import signal_source
from bundles import load_bundle
from laminae import LAMINA_DIR, load_twin
from main import app
from session import Session
from signal_source import ReplaySource, SimulatedSource

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"

FAST_SPEEDS = (60, 120, 600, 60000)
DEMO = (
    "/ws/feedback?lamina=lamina_wearable&source=replay"
    "&subject=demo&date=2025-06-01&speed=60000"
)


@pytest.fixture
def bundle():
    return load_bundle("demo", "2025-06-01")


@pytest.fixture
def fast_speeds(monkeypatch):
    monkeypatch.setattr(signal_source, "REPLAY_SPEEDS", FAST_SPEEDS)


def _new_session():
    twin = load_twin(WEARABLE)
    session = Session(lamina=WEARABLE)
    session.seed(SimulatedSource(twin).starting_state())
    return session


def _replay_row(snapshot):
    computed = snapshot["computed"]
    residual = computed["HR_residual"]
    return (
        computed["HR_model"]["value"],
        computed["kcal_active_cum"]["value"],
        None if residual["stale"] else residual["value"],
    )


def _replay(session, feed):
    rows = []
    while not feed.exhausted:
        readings = feed.next()
        rows.append(_replay_row(
            session.tick(readings, missing=feed.last_missing)
        ))
    return rows


# ══════════════════════════════════════════════════════════════════════
# Step response: tau_on while rising, tau_off while falling
# ══════════════════════════════════════════════════════════════════════

def test_hr_model_rises_with_tau_on_and_falls_with_tau_off():
    session = _new_session()

    for _ in range(5):
        session.tick({})

    before = session.twin.get("HR_model").value

    for n in range(1, 11):
        session.tick({"AE_rate": 4.5})
        target = session.twin.get("HR_target").value
        expected = target + (before - target) * math.exp(-n * 60.0 / 30.0)
        assert session.twin.get("HR_model").value == pytest.approx(
            expected, abs=0.01 * abs(target - before)
        ), f"rise tick {n}"

    before_fall = session.twin.get("HR_model").value

    for n in range(1, 11):
        session.tick({"AE_rate": 0.3})
        target = session.twin.get("HR_target").value
        expected = target + (before_fall - target) * math.exp(-n * 60.0 / 90.0)
        assert session.twin.get("HR_model").value == pytest.approx(
            expected, abs=0.01 * abs(target - before_fall)
        ), f"fall tick {n}"


def test_zero_time_constants_make_hr_model_equal_its_target():
    session = _new_session()

    for ae_rate in (0.3, 4.5, 0.3, 5.0, 0.0, 3.0, 0.3):
        session.tick({"AE_rate": ae_rate, "tau_on": 0.0, "tau_off": 0.0})
        assert session.twin.get("HR_model").value == pytest.approx(
            session.twin.get("HR_target").value
        )


# ══════════════════════════════════════════════════════════════════════
# Replay, reset, replay
# ══════════════════════════════════════════════════════════════════════

def test_replay_reset_replay_reproduces_the_same_series(bundle):
    session = Session(lamina=WEARABLE)
    feed = ReplaySource(session.twin, bundle)
    session.seed(feed.starting_state())
    first = _replay(session, feed)

    session.reset()
    feed.rewind()
    session.seed(feed.starting_state())
    second = _replay(session, feed)

    assert first == second


# ══════════════════════════════════════════════════════════════════════
# A null minute
# ══════════════════════════════════════════════════════════════════════

def test_a_null_minute_marks_measured_and_residual_stale_not_the_model(bundle):
    samples = bundle["samples"]
    null_minute = next(
        index for index in range(1, len(samples))
        if samples[index]["hr"] is None and samples[index - 1]["hr"] is not None
    )

    session = Session(lamina=WEARABLE)
    feed = ReplaySource(session.twin, bundle)
    session.seed(feed.starting_state())

    null_snapshot = None
    for _ in range(null_minute + 1):
        readings = feed.next()
        snapshot = session.tick(readings, missing=feed.last_missing)

    null_snapshot = snapshot
    assert "HR_measured" in session.twin.failed_attributes
    assert "HR_residual" in session.twin.failed_attributes
    assert null_snapshot["computed"]["HR_measured"]["stale"] is True
    assert null_snapshot["computed"]["HR_residual"]["stale"] is True
    assert null_snapshot["computed"]["HR_model"]["stale"] is False

    while not feed.exhausted:
        readings = feed.next()
        snapshot = session.tick(readings, missing=feed.last_missing)
        if snapshot["computed"]["HR_measured"]["stale"] is False:
            break
    else:  # pragma: no cover — the demo day has readings after this gap
        raise AssertionError("no minute with a heart rate followed the null")

    assert "HR_measured" not in session.twin.failed_attributes
    assert snapshot["computed"]["HR_measured"]["value"] == pytest.approx(
        readings["HR_obs"]
    )


# ══════════════════════════════════════════════════════════════════════
# Cumulative active energy
# ══════════════════════════════════════════════════════════════════════

def test_kcal_cumulative_is_the_days_active_energy(bundle):
    session = Session(lamina=WEARABLE)
    feed = ReplaySource(session.twin, bundle)
    session.seed(feed.starting_state())

    first_value = None
    while not feed.exhausted:
        readings = feed.next()
        snapshot = session.tick(readings, missing=feed.last_missing)
        if first_value is None:
            first_value = snapshot["computed"]["kcal_active_cum"]["value"]

    assert first_value == pytest.approx(
        bundle["samples"][0]["ae_kcal_min"], abs=1e-9
    )
    total = sum(row["ae_kcal_min"] for row in bundle["samples"])
    assert session.twin.get("kcal_active_cum").value == pytest.approx(
        total, abs=1e-6
    )


# ══════════════════════════════════════════════════════════════════════
# The model matches the generator's noise
# ══════════════════════════════════════════════════════════════════════

def test_hr_residual_over_recorded_minutes_is_the_demo_noise(bundle):
    session = Session(lamina=WEARABLE)
    feed = ReplaySource(session.twin, bundle)
    session.seed(feed.starting_state())

    residuals = []
    while not feed.exhausted:
        readings = feed.next()
        snapshot = session.tick(readings, missing=feed.last_missing)
        if "HR_obs" in readings:
            residuals.append(snapshot["computed"]["HR_residual"]["value"])

    assert residuals
    assert abs(statistics.fmean(residuals)) <= 0.5
    assert 1.5 <= statistics.pstdev(residuals) <= 2.5


# ══════════════════════════════════════════════════════════════════════
# Guards on the two new callables
# ══════════════════════════════════════════════════════════════════════

def test_guards_on_the_stateful_callables():
    twin = load_twin(WEARABLE)
    hr_model = twin._function_registry["hr_model"]
    kcal = twin._function_registry["kcal_cumulative"]

    with pytest.raises(ValueError):
        hr_model([65.0, 0.0, 30.0, 90.0, None])
    with pytest.raises(ValueError):
        hr_model([65.0, 60.0, -1.0, 90.0, None])
    with pytest.raises(ValueError):
        hr_model([float("nan"), 60.0, 30.0, 90.0, None])
    with pytest.raises(ValueError):
        hr_model([65.0, 60.0, 30.0, 90.0, float("nan")])
    with pytest.raises(ValueError):
        kcal([-0.1, 60.0, 12.0, None])


# ══════════════════════════════════════════════════════════════════════
# The WebSocket replay reproduces itself after a reset
# ══════════════════════════════════════════════════════════════════════

def test_ws_replay_reset_replays_the_same_hr_model_series(fast_speeds):
    with TestClient(app) as client:
        with client.websocket_connect(DEMO) as ws:
            first = [ws.receive_json() for _ in range(1440)]
            notice = ws.receive_json()
            assert notice["code"] == "replay_end"

            ws.send_json({"type": "reset"})
            second = [ws.receive_json() for _ in range(1440)]

    first_series = [frame["computed"]["HR_model"]["value"] for frame in first]
    second_series = [frame["computed"]["HR_model"]["value"] for frame in second]
    assert first_series == second_series
