"""
The committed synthetic demo day bundle.

The file under bundles/demo/2025-06-01.json is the contract the frontend and
the streaming runtime read.  These tests pin it to the schema, to the shape a
watch would actually deliver, and to the generator that produced it: if the
generator and the committed file ever disagree, a reader is looking at a day
nobody can reproduce.
"""
import json
import math
from pathlib import Path

import pytest

from tools.make_demo_bundle import make_demo_bundle

BUNDLE_FILE = (
    Path(__file__).resolve().parents[1] / "bundles" / "demo" / "2025-06-01.json"
)
SCHEMA_FILE = Path(__file__).resolve().parents[1] / "bundles" / "bundle.schema.json"

SCHEDULE = (
    (0, 390, 0.05),
    (390, 480, 0.4),
    (480, 510, 4.5),
    (510, 540, 0.4),
    (540, 735, 0.3),
    (735, 755, 3.5),
    (755, 1050, 0.3),
    (1050, 1095, 3.0),
    (1095, 1350, 0.4),
    (1350, 1440, 0.05),
)


@pytest.fixture(scope="module")
def committed() -> dict:
    return json.loads(BUNDLE_FILE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def generated() -> dict:
    return make_demo_bundle(seed=0)


def test_committed_bundle_validates_against_the_schema(committed):
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_FILE.read_text(encoding="utf-8"))
    jsonschema.validate(instance=committed, schema=schema)


def test_the_day_is_one_row_per_minute_and_synthetic(committed):
    assert committed["synthetic"] is True
    assert committed["grid_s"] == 60
    assert len(committed["samples"]) == 1440


def test_there_is_no_heart_rate_between_one_and_five(committed):
    for sample in committed["samples"]:
        if 3600 <= sample["t"] < 18000:
            assert sample["hr"] is None, sample["t"]


def test_every_workout_minute_has_a_heart_rate(committed):
    workout_minutes = [s for s in committed["samples"] if s["workout"] is not None]
    assert workout_minutes
    for sample in workout_minutes:
        assert sample["hr"] is not None, sample["t"]


def test_the_day_block_counts_what_the_samples_hold(committed):
    samples = committed["samples"]
    day = committed["day"]
    with_hr = [s for s in samples if s["hr"] is not None]
    assert day["minutes_with_hr"] == len(with_hr)
    assert day["dense_minutes"] == sum(s["hr_n"] >= 6 for s in samples)
    # Hours holding at least one reading -- 20 here: every hour but 01-05.
    assert day["coverage_hr_hours"] == len({s["t"] // 3600 for s in with_hr}) == 20


def test_the_generator_is_deterministic():
    assert make_demo_bundle(seed=0) == make_demo_bundle(seed=0)


def test_the_generator_reproduces_the_committed_file(committed, generated):
    assert generated == committed


def test_the_days_active_energy_matches_the_schedule(committed):
    expected = sum(
        (end - start) * ae_rate for start, end, ae_rate in SCHEDULE
    )
    actual = sum(sample["ae_kcal_min"] for sample in committed["samples"])
    assert actual == pytest.approx(expected, abs=1e-6)
    assert math.isfinite(actual)
