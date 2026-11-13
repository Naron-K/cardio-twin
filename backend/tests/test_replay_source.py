"""
ReplaySource — a recorded day fed through a lamina.

The committed demo day is the worked example: 1440 minutes, a gap where the
watch recorded no heart rate, and a walking block at 08:10.  Small bundles in
tmp_path cover the wall-clock arithmetic around a daylight-saving transition.
Nothing here uses a real person's data.
"""
import json
from pathlib import Path

import pytest

from bundles import load_bundle
from laminae import LAMINA_DIR, load_twin
from session import Session
from signal_source import (
    REPLAY_SPEEDS,
    ReplayExhausted,
    ReplaySource,
)

WEARABLE = LAMINA_DIR / "wearable_lamina.xml"
CIRCULATORY = LAMINA_DIR / "circulatory_lamina.xml"


@pytest.fixture
def twin():
    return load_twin(WEARABLE)


@pytest.fixture
def bundle():
    return load_bundle("demo", "2025-06-01")


@pytest.fixture
def source(twin, bundle):
    return ReplaySource(twin, bundle)


def _day_bundle(subject, date, timezone_name, n_minutes):
    samples = [
        {
            "t": index * 60,
            "hr": 70.0,
            "hr_n": 1,
            "ae_kcal_min": 0.05,
            "be_kcal_min": 1.1,
            "steps_min": 0.0,
            "t_app_c": 20.0,
            "rh_pct": 60.0,
            "workout": None,
        }
        for index in range(n_minutes)
    ]
    return {
        "schema_version": 1,
        "subject": subject,
        "date": date,
        "timezone": timezone_name,
        "grid_s": 60,
        "synthetic": False,
        "samples": samples,
        "day": {
            "hr_level_rts": 62.0,
            "n_minutes": n_minutes,
            "minutes_with_hr": n_minutes,
            "coverage_hr_min_frac": 1.0,
            "coverage_hr_hours": 24,
            "dense_minutes": 0,
            "basal_source": "measured",
        },
    }


def _write(directory: Path, subject: str, date: str, data: dict) -> Path:
    path = Path(directory) / subject / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ── The demo day ──────────────────────────────────────────────────────

def test_exactly_1440_rows_then_exhausted(source):
    for _ in range(1440):
        source.next()
    assert source.exhausted is True
    assert source.index == 1440
    with pytest.raises(ReplayExhausted):
        source.next()


def test_row_zero_is_local_midnight_and_the_declared_day_values(source):
    readings = source.next()
    assert readings["hour_local"] == pytest.approx(0.0)
    assert readings["dt_s"] == 60
    assert readings["HR_level"] == pytest.approx(62.0)
    assert readings["AE_rate"] == pytest.approx(0.05)


def test_the_walking_minute_at_0810_replays_as_recorded(source):
    for _ in range(491):
        readings = source.next()
    assert readings["hour_local"] == pytest.approx(8.1667, abs=1e-3)
    assert readings["AE_rate"] == pytest.approx(4.5)
    assert readings["step_rate"] == pytest.approx(110.0)


def test_a_null_heart_rate_is_omitted_and_named(source):
    source.next()
    readings = source.next()
    assert "HR_obs" not in readings
    assert "HR_obs" in source.last_missing
    assert "AE_rate" in readings
    assert "BE_rate" in readings


def test_coefficients_do_not_move_over_the_day(source, twin):
    coefficient_ids = [
        attr_id
        for attr_id in twin.list_attributes("SENSOR")
        if twin.attributes[attr_id].replay_field is None
    ]
    assert coefficient_ids
    first = source.next()
    last = first
    for _ in range(1439):
        last = source.next()
    for attr_id in coefficient_ids:
        assert first[attr_id] == last[attr_id]


def test_rewind_returns_to_row_zero(source):
    source.next()
    source.next()
    source.rewind()
    assert source.index == 0
    assert source.next()["hour_local"] == pytest.approx(0.0)


# ── Daylight saving ──────────────────────────────────────────────────

def test_local_clock_jumps_back_when_daylight_saving_ends(
    tmp_path, monkeypatch, twin
):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    _write(
        tmp_path,
        "s2",
        "2025-04-06",
        _day_bundle("s2", "2025-04-06", "Australia/Adelaide", 1500),
    )
    day = load_bundle("s2", "2025-04-06")
    source = ReplaySource(twin, day)

    for _ in range(180):
        readings = source.next()
    assert readings["hour_local"] == pytest.approx(2.9833, abs=1e-3)

    readings = source.next()
    assert readings["hour_local"] == pytest.approx(2.0)

    status = source.status()
    assert status["position_s"] == 180 * 60
    assert status["data_time"].endswith("+09:30")


# ── The Session pipeline ─────────────────────────────────────────────

def test_session_carries_each_recorded_heart_rate(bundle):
    session = Session(lamina=WEARABLE)
    source = ReplaySource(session.twin, bundle)
    session.seed(source.starting_state())

    for row in bundle["samples"]:
        snapshot = session.tick(source.next())
        if row["hr"] is not None:
            assert snapshot["computed"]["HR_measured"]["value"] == pytest.approx(
                row["hr"]
            )


# ── Parameters, baselines and speed ──────────────────────────────────

def test_a_coefficient_override_and_a_later_baseline_are_used(twin, bundle):
    source = ReplaySource(twin, bundle, params={"k_I": 10.0})
    assert source.next()["k_I"] == pytest.approx(10.0)
    source.set_baseline("k_I", 5.0)
    assert source.next()["k_I"] == pytest.approx(5.0)


def test_an_unknown_baseline_is_ignored_like_simulated_source(source):
    source.set_baseline("not_an_attribute", 1.0)


def test_speed_validation_happens_at_both_doors(twin, bundle):
    with pytest.raises(ValueError):
        ReplaySource(twin, bundle, speed=3600)
    source = ReplaySource(twin, bundle)
    with pytest.raises(ValueError):
        source.set_speed(3600)
    source.set_speed(600)
    assert source.speed == 600
    assert "x600" in source.describe()


def test_at_least_one_available_speed_is_a_plain_int_tuple():
    assert REPLAY_SPEEDS == (60, 120, 600)


# ── Guards ───────────────────────────────────────────────────────────

def test_params_may_not_address_recorded_or_unknown_sensors(twin, bundle):
    with pytest.raises(ValueError, match="recorded day"):
        ReplaySource(twin, bundle, params={"HR_obs": 70.0})
    with pytest.raises(ValueError, match="not a coefficient"):
        ReplaySource(twin, bundle, params={"nope": 1})
    with pytest.raises(ValueError, match="not a finite number"):
        ReplaySource(twin, bundle, params={"k_I": float("nan")})


def test_a_recorded_sensor_cannot_be_rebaselined(source):
    with pytest.raises(ValueError, match="recorded day"):
        source.set_baseline("HR_obs", 70.0)


def test_a_lamina_with_no_replay_field_cannot_replay(bundle):
    twin = load_twin(CIRCULATORY)
    with pytest.raises(ValueError, match="declares no replay_field"):
        ReplaySource(twin, bundle)


def test_status_reports_the_last_emitted_row_and_advances_by_one_minute(
    source,
):
    status = source.status()
    assert status["kind"] == "replay"
    for key in (
        "detail",
        "subject",
        "date",
        "synthetic",
        "data_time",
        "position_s",
        "duration_s",
        "speed",
        "ended",
    ):
        assert key in status
    assert status["subject"] == "demo"
    assert status["date"] == "2025-06-01"
    assert status["synthetic"] is True
    assert status["duration_s"] == 1440 * 60
    assert status["ended"] is False
    assert status["position_s"] == 0

    source.next()
    assert source.status()["position_s"] == 0
    source.next()
    assert source.status()["position_s"] == 60
