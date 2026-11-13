"""
Day-bundle discovery and validation.

The committed demo day must always be loadable and always come from this
repository.  A configured bundle directory adds recorded subjects without
being able to replace the demo.  Every structural rule is exercised by
corrupting one copy of the demo, so a bad file fails by name and row instead
of replaying as a day that never happened.
"""
import json
import math
from pathlib import Path

import pytest

from bundles import (
    BUNDLE_DIR,
    UnknownBundle,
    bundle_roots,
    list_bundles,
    load_bundle,
)

DEMO_FILE = BUNDLE_DIR / "demo" / "2025-06-01.json"


def _demo() -> dict:
    return json.loads(DEMO_FILE.read_text(encoding="utf-8"))


def _write(directory: Path, subject: str, date: str, data: dict) -> Path:
    path = Path(directory) / subject / f"{date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_valid(directory: Path, subject: str, date: str) -> Path:
    data = _demo()
    data["subject"] = subject
    data["date"] = date
    return _write(directory, subject, date, data)


# ── The committed demo ────────────────────────────────────────────────

def test_the_demo_day_is_always_offered():
    assert list_bundles()["demo"] == ["2025-06-01"]


def test_the_demo_day_loads_as_1440_samples():
    bundle = load_bundle("demo", "2025-06-01")
    assert len(bundle["samples"]) == 1440
    assert bundle["subject"] == "demo"
    assert bundle["date"] == "2025-06-01"


# ── A configured directory ────────────────────────────────────────────

def test_env_directory_adds_subjects_and_cannot_replace_the_demo(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))

    _write_valid(tmp_path, "s9", "2025-01-02")

    fake_demo = _demo()
    fake_demo["subject"] = "demo"
    fake_demo["date"] = "2025-09-09"
    _write(tmp_path, "demo", "2025-09-09", fake_demo)

    listing = list_bundles()
    assert listing["s9"] == ["2025-01-02"]
    assert listing["demo"] == ["2025-06-01"]
    assert "2025-09-09" not in listing["demo"]
    assert load_bundle("s9", "2025-01-02")["subject"] == "s9"


def test_the_environment_is_read_at_call_time(tmp_path, monkeypatch):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    _write_valid(tmp_path, "s1", "2025-02-03")
    assert "s1" in bundle_roots()
    assert list_bundles()["s1"] == ["2025-02-03"]


def test_a_file_that_is_not_a_date_is_not_listed(tmp_path, monkeypatch):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    (tmp_path / "s1").mkdir()
    (tmp_path / "s1" / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "s1" / "2025-02-30.json").write_text("{}", encoding="utf-8")
    _write_valid(tmp_path, "s1", "2025-02-03")
    assert list_bundles()["s1"] == ["2025-02-03"]


# ── Refused identifiers ───────────────────────────────────────────────

@pytest.mark.parametrize("subject", ["../x", "S2", "a/b", "", "a" * 33, "a-b"])
def test_bad_subjects_are_refused(subject):
    with pytest.raises(ValueError):
        load_bundle(subject, "2025-06-01")


@pytest.mark.parametrize("date", ["2025-13-01", "2025-1-1", "1900-02-29", ""])
def test_bad_dates_are_refused(date):
    with pytest.raises(ValueError):
        load_bundle("demo", date)


def test_an_unknown_date_raises_unknown_bundle():
    with pytest.raises(UnknownBundle) as exc:
        load_bundle("demo", "2025-06-02")
    assert "2025-06-01" in str(exc.value)


def test_an_unknown_subject_raises_unknown_bundle():
    with pytest.raises(UnknownBundle) as exc:
        load_bundle("nobody", "2025-06-01")
    assert "demo" in str(exc.value)


# ── Structural rules, each on a corrupted copy of the demo ───────────

def _t_gap(data):
    data["samples"][5]["t"] += 1


def _hr_as_string(data):
    data["samples"][10]["hr"] = "70"


def _hr_with_zero_count(data):
    data["samples"][10]["hr"] = 70.0
    data["samples"][10]["hr_n"] = 0


def _count_without_hr(data):
    data["samples"][10]["hr"] = None
    data["samples"][10]["hr_n"] = 3


def _nan_through_json(data):
    data["samples"][10]["t_app_c"] = float("nan")


def _wrong_n_minutes(data):
    data["day"]["n_minutes"] = 1439


def _grid_of_30(data):
    data["grid_s"] = 30


def _bool_as_hr(data):
    data["samples"][10]["hr"] = True
    data["samples"][10]["hr_n"] = 1


def _hr_out_of_range(data):
    data["samples"][10]["hr"] = 300.0
    data["samples"][10]["hr_n"] = 1


def _hr_disagrees_with_count(data):
    data["samples"][10]["hr"] = None
    data["samples"][10]["hr_n"] = 0
    data["samples"][20]["hr"] = 70.0
    data["samples"][20]["hr_n"] = 0


@pytest.mark.parametrize(
    "corrupt",
    [
        _t_gap,
        _hr_as_string,
        _hr_with_zero_count,
        _count_without_hr,
        _nan_through_json,
        _wrong_n_minutes,
        _grid_of_30,
        _bool_as_hr,
        _hr_out_of_range,
        _hr_disagrees_with_count,
    ],
    ids=[
        "t-gap",
        "hr-string",
        "hr-set-hr_n-zero",
        "hr-null-hr_n-three",
        "nan-through-json",
        "wrong-n-minutes",
        "grid-30",
        "bool-as-hr",
        "hr-out-of-range",
        "hr-and-count-disagree",
    ],
)
def test_a_corrupted_demo_bundle_is_refused(tmp_path, monkeypatch, corrupt):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    data = _demo()
    data["subject"] = "s1"
    corrupt(data)
    path = _write(tmp_path, "s1", "2025-06-01", data)

    with pytest.raises(ValueError) as exc:
        load_bundle("s1", "2025-06-01")
    assert path.name in str(exc.value)


def test_a_bad_row_names_the_file_and_the_row(tmp_path, monkeypatch):
    monkeypatch.setenv("CARDIOTWIN_BUNDLE_DIR", str(tmp_path))
    data = _demo()
    data["subject"] = "s1"
    data["samples"][10]["t_app_c"] = float("inf")
    _write(tmp_path, "s1", "2025-06-01", data)

    with pytest.raises(ValueError) as exc:
        load_bundle("s1", "2025-06-01")
    message = str(exc.value)
    assert "2025-06-01.json" in message
    assert "sample row 10" in message


def test_nan_really_is_encoded_as_the_nonstandard_json_literal():
    data = _demo()
    data["samples"][3]["rh_pct"] = float("nan")
    encoded = json.dumps(data)
    assert "NaN" in encoded
    assert not math.isfinite(json.loads(encoded)["samples"][3]["rh_pct"])
