"""
The day's activity dose, added only when the plan view declares the role.

The bundle's recorded basal energy is irrelevant to the dose.  MET is
1 + AE_rate / BE_ref with the lamina's declared resting rate of 1.1 kcal/min,
so active energy of 5 kcal/min gives MET 1 + 5/1.1 and dose_rate contributes
that many MET-minutes a minute.  Active energy of 1 kcal/min gives MET
1 + 1/1.1, below the declared floor of 3, so those minutes add nothing.
"""
import re

import pytest

import day_summary as ds
from laminae import LAMINA_DIR, load_twin

LAMINA = "lamina_wearable"
BE_KCAL_MIN = 1.0
BE_REF = 1.1
ACTIVE_KCAL_MIN = 5.0
QUIET_KCAL_MIN = 1.0
DOSE_PER_ACTIVE_MINUTE = 1.0 + ACTIVE_KCAL_MIN / BE_REF


def _row(minute: int, ae_kcal_min: float | None, workout: str | None) -> dict:
    return {
        "t": minute * 60,
        "hr": 60.0,
        "hr_n": 1,
        "ae_kcal_min": ae_kcal_min,
        "be_kcal_min": BE_KCAL_MIN,
        "steps_min": 0,
        "t_app_c": 20.0,
        "rh_pct": 50.0,
        "workout": workout,
    }


def _bundle(rows: list[tuple[float | None, str | None]]) -> dict:
    samples = [
        _row(minute, ae, workout)
        for minute, (ae, workout) in enumerate(rows)
    ]
    return {
        "schema_version": 1,
        "subject": "probe",
        "date": "2025-01-01",
        "timezone": "UTC",
        "grid_s": 60,
        "synthetic": True,
        "samples": samples,
        "day": {"n_minutes": len(samples), "hr_level_rts": 60.0},
    }


def _day_rows() -> list[tuple[float | None, str | None]]:
    return (
        [(QUIET_KCAL_MIN, None)] * 5
        + [(ACTIVE_KCAL_MIN, "Walking")] * 5
        + [(QUIET_KCAL_MIN, None)] * 5
        + [(ACTIVE_KCAL_MIN, None)] * 2
        + [(QUIET_KCAL_MIN, None)] * 3
    )


def _role() -> dict:
    return load_twin("wearable_lamina.xml").plan_view["dose"]


def test_the_day_dose_counts_only_the_minutes_at_or_above_the_floor():
    result = ds.summarise_bundle(
        LAMINA, _bundle(_day_rows()), None, "Probe"
    )
    dose = result["dose"]
    role = _role()

    assert dose["attribute"] == role["attribute"]
    assert dose["label"] == role["label"]
    assert dose["unit"] == "MET-min"
    assert dose["total"] == pytest.approx(
        round(7 * DOSE_PER_ACTIVE_MINUTE, 2), abs=1e-6
    )
    assert dose["in_sessions"] == pytest.approx(
        round(5 * DOSE_PER_ACTIVE_MINUTE, 2), abs=1e-6
    )
    assert dose["outside_sessions"] == pytest.approx(
        round(
            round(7 * DOSE_PER_ACTIVE_MINUTE, 2)
            - round(5 * DOSE_PER_ACTIVE_MINUTE, 2),
            2,
        ),
        abs=1e-6,
    )
    assert dose["minutes_counted"] == 7


def test_the_session_and_outside_parts_add_up_to_the_total():
    result = ds.summarise_bundle(
        LAMINA, _bundle(_day_rows()), None, "Probe"
    )
    dose = result["dose"]

    assert dose["in_sessions"] + dose["outside_sessions"] == pytest.approx(
        dose["total"], abs=1e-6
    )
    assert 0.0 <= dose["in_sessions"] <= dose["total"]


def test_a_minute_with_no_active_energy_adds_nothing():
    rows = _day_rows()
    rows[15] = (None, None)

    result = ds.summarise_bundle(LAMINA, _bundle(rows), None, "Probe")
    dose = result["dose"]

    assert dose["total"] == pytest.approx(
        round(6 * DOSE_PER_ACTIVE_MINUTE, 2), abs=1e-6
    )
    assert dose["in_sessions"] == pytest.approx(
        round(5 * DOSE_PER_ACTIVE_MINUTE, 2), abs=1e-6
    )
    assert dose["outside_sessions"] == pytest.approx(
        round(
            round(6 * DOSE_PER_ACTIVE_MINUTE, 2)
            - round(5 * DOSE_PER_ACTIVE_MINUTE, 2),
            2,
        ),
        abs=1e-6,
    )
    assert dose["minutes_counted"] == 6


def test_a_lamina_without_the_dose_role_adds_no_dose_key(
    tmp_path, monkeypatch
):
    bundle = _bundle(_day_rows())
    with_dose = ds.summarise_bundle(LAMINA, bundle, None, "Probe")

    source = (LAMINA_DIR / "wearable_lamina.xml").read_text(encoding="utf-8")
    without = re.sub(r"\s*<dose[^>]*/>\s*\n", "\n", source)
    assert "<dose " not in without
    path = tmp_path / "wearable_lamina.xml"
    path.write_text(without, encoding="utf-8")

    monkeypatch.setattr(ds, "resolve_lamina", lambda _lamina_id: path)
    without_dose = ds.summarise_bundle(LAMINA, bundle, None, "Probe")

    assert "dose" not in without_dose
    assert without_dose == {
        key: value for key, value in with_dose.items() if key != "dose"
    }
