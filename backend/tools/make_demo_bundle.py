"""
Synthetic demo day bundle generator.

This module invents one plausible day and writes it as a "day bundle"
(backend/bundles/demo/2025-06-01.json).  It is a SYNTHETIC generator: every
number here is made up from the schedule declared below, and no real person's
data is involved.

The heart-rate signal comes from the wearable lamina's HR_target.  The
measurement noise that turns that target into something a wrist-worn watch
would actually record lives HERE, in this script, and not in the lamina.  The
lamina now models the same first-order lag this generator applies, with the
same constants it uses (tau_on 30 s, tau_off 90 s), so the two describe the
same day.  The lag constants and the RNG seed are arguments to
make_demo_bundle so a caller can reproduce a day exactly.

Run from the repository root:

    python backend/tools/make_demo_bundle.py

or from backend/:

    python tools/make_demo_bundle.py
"""
from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from laminae import load_twin  # noqa: E402
from signal_source import SimulatedSource  # noqa: E402

LAMINA_FILE = BACKEND_DIR / "wearable_lamina.xml"
BUNDLE_FILE = BACKEND_DIR / "bundles" / "demo" / "2025-06-01.json"

SCHEMA_VERSION = 1
SUBJECT = "demo"
DATE = "2025-06-01"
TIMEZONE = "UTC"
GRID_S = 60
MINUTES = 1440
HR_LEVEL_RTS = 62.0
BE_KCAL_MIN = 1.1
RH_PCT = 60.0
HR_LEVEL = 62.0

TAU_ON_S = 30.0
TAU_OFF_S = 90.0
NOISE_SIGMA = 2.0
DT_S = 60.0

HR_FLOOR = 20.0
HR_CEILING = 240.0

_SCHEDULE = (
    (0, 390, 0.05, 0, None),
    (390, 480, 0.4, 3, None),
    (480, 510, 4.5, 110, "Walking"),
    (510, 540, 0.4, 3, None),
    (540, 735, 0.3, 2, None),
    (735, 755, 3.5, 95, "Walking"),
    (755, 1050, 0.3, 2, None),
    (1050, 1095, 3.0, 10, "TraditionalStrengthTraining"),
    (1095, 1350, 0.4, 3, None),
    (1350, 1440, 0.05, 0, None),
)


def _schedule_at(minute: int) -> tuple:
    for start, end, ae_rate, steps, workout in _SCHEDULE:
        if start <= minute < end:
            return ae_rate, steps, workout
    raise ValueError(f"minute {minute} is outside the declared schedule")


def _t_app_c(t_seconds: int) -> float:
    hour = t_seconds / 3600.0
    return round(14.0 + 8.0 * math.cos(2.0 * math.pi * (hour - 15.0) / 24.0), 1)


def _lagged_targets(targets: list, dt_s: float,
                    tau_on_s: float, tau_off_s: float) -> list:
    lagged = [targets[0]]
    for target in targets[1:]:
        previous = lagged[-1]
        tau = tau_on_s if target > previous else tau_off_s
        alpha = 1.0 - math.exp(-dt_s / tau)
        lagged.append(previous + alpha * (target - previous))
    return lagged


def _validate_rows(samples: list, n_minutes: int) -> None:
    if len(samples) != n_minutes:
        raise ValueError(
            f"expected {n_minutes} rows, got {len(samples)}. "
            f"A day bundle is one row per minute with no gaps."
        )
    for row in samples:
        hr, hr_n = row["hr"], row["hr_n"]
        if hr is not None:
            if not isinstance(hr, (int, float)) or not math.isfinite(hr):
                raise ValueError(
                    f"sample t={row['t']} has non-finite hr {hr!r}"
                )
            if not HR_FLOOR <= hr <= HR_CEILING:
                raise ValueError(
                    f"sample t={row['t']} has hr={hr} outside "
                    f"[{HR_FLOOR}, {HR_CEILING}]"
                )
            if hr_n == 0:
                raise ValueError(
                    f"sample t={row['t']} has hr set but hr_n=0"
                )
        elif hr_n > 0:
            raise ValueError(
                f"sample t={row['t']} has hr null but hr_n={hr_n}"
            )


def _validate_structure(bundle: dict) -> None:
    required = {
        "schema_version", "subject", "date", "timezone", "grid_s",
        "synthetic", "samples", "day",
    }
    missing = required - set(bundle)
    if missing:
        raise ValueError(f"bundle is missing keys: {sorted(missing)}")
    samples = bundle["samples"]
    if len(samples) != MINUTES:
        raise ValueError(
            f"bundle has {len(samples)} samples, expected {MINUTES}"
        )
    for row in samples:
        if row["hr"] is not None:
            if not math.isfinite(row["hr"]):
                raise ValueError(f"non-finite hr at t={row['t']}")
            if not HR_FLOOR <= row["hr"] <= HR_CEILING:
                raise ValueError(
                    f"hr={row['hr']} at t={row['t']} outside "
                    f"[{HR_FLOOR}, {HR_CEILING}]"
                )


def make_demo_bundle(seed: int = 0) -> dict:
    """Build the synthetic 2025-06-01 day bundle as a plain dict."""
    twin = load_twin(LAMINA_FILE)
    twin._log = lambda *args, **kwargs: None
    for attr_id, value in SimulatedSource(twin).starting_state().items():
        twin.set_sensor(attr_id, value)
    rng = random.Random(seed)

    samples = []
    targets = []
    for minute in range(MINUTES):
        t = minute * GRID_S
        ae_rate, steps, workout = _schedule_at(minute)
        t_app = _t_app_c(t)

        twin.set_sensor("AE_rate", ae_rate)
        twin.set_sensor("BE_rate", BE_KCAL_MIN)
        twin.set_sensor("T_app", t_app)
        twin.set_sensor("hour_local", t / 3600.0)
        twin.set_sensor("HR_level", HR_LEVEL)
        twin.compute_all()
        targets.append(twin.get("HR_target").value)

        samples.append({
            "t": t,
            "hr": None,
            "hr_n": 0,
            "ae_kcal_min": ae_rate,
            "be_kcal_min": BE_KCAL_MIN,
            "steps_min": steps,
            "t_app_c": t_app,
            "rh_pct": RH_PCT,
            "workout": workout,
        })

    lagged = _lagged_targets(targets, DT_S, TAU_ON_S, TAU_OFF_S)
    measured = [round(value + rng.gauss(0.0, NOISE_SIGMA), 1)
                for value in lagged]
    _validate_rows(
        [{"t": i * GRID_S, "hr": value, "hr_n": 1}
         for i, value in enumerate(measured)],
        MINUTES,
    )

    for minute, row in enumerate(samples):
        t = row["t"]
        workout = row["workout"]

        if workout is not None:
            row["hr"] = measured[minute]
            row["hr_n"] = 12
        elif 3600 <= t < 18000:
            row["hr"] = None
            row["hr_n"] = 0
        elif minute % 6 == 0:
            row["hr"] = measured[minute]
            row["hr_n"] = 1
        else:
            row["hr"] = None
            row["hr_n"] = 0

    _validate_rows(samples, MINUTES)

    minutes_with_hr = sum(1 for row in samples if row["hr"] is not None)
    dense_minutes = sum(1 for row in samples if row["hr_n"] >= 6)

    bundle = {
        "schema_version": SCHEMA_VERSION,
        "subject": SUBJECT,
        "date": DATE,
        "timezone": TIMEZONE,
        "grid_s": GRID_S,
        "synthetic": True,
        "samples": samples,
        "day": {
            "hr_level_rts": HR_LEVEL_RTS,
            "n_minutes": MINUTES,
            "minutes_with_hr": minutes_with_hr,
            "coverage_hr_min_frac": round(minutes_with_hr / MINUTES, 3),
            # Hours holding at least one reading, as the real exporter counts
            # them -- not minutes_with_hr / 60, which reads 5 for a day whose
            # readings are spread across 20 hours.
            "coverage_hr_hours": len(
                {s["t"] // 3600 for s in samples if s["hr"] is not None}
            ),
            "dense_minutes": dense_minutes,
            "basal_source": "synthetic",
        },
    }

    _validate_structure(bundle)
    return bundle


def write_bundle(bundle: dict, path: Path = BUNDLE_FILE) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def main() -> int:
    bundle = make_demo_bundle()
    write_bundle(bundle)
    samples = bundle["samples"]
    hrs = [row["hr"] for row in samples if row["hr"] is not None]
    total_ae = sum(row["ae_kcal_min"] for row in samples)
    print(f"wrote {BUNDLE_FILE}")
    print(f"minutes            {len(samples)}")
    print(f"minutes_with_hr    {bundle['day']['minutes_with_hr']}")
    print(f"total ae kcal      {total_ae:.3f}")
    print(f"hr min             {min(hrs):.1f}")
    print(f"hr max             {max(hrs):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
