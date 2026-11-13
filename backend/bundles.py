"""
Day bundles — recorded days the replay feed can read.

A "day bundle" is one recorded day, one JSON row per minute.  The format is
declared in `bundles/bundle.schema.json`; this module is the reader that makes
the schema true without requiring `jsonschema`, which is not a backend
dependency.

Two jobs, kept apart:

  * discovery — which subjects and dates exist.  The committed demo day is
    always offered; a deployment may point `CARDIOTWIN_BUNDLE_DIR` at a
    directory of per-subject folders to add recorded subjects.
  * validation — a bundle that does not hold what it claims is refused by
    name and row rather than replayed as a day that never happened.

Replay itself lives in `signal_source.ReplaySource`; this module knows nothing
about laminae or twins.
"""
from __future__ import annotations

import json
import math
import os
import re
from datetime import date as _date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

BUNDLE_DIR = Path(__file__).parent / "bundles"

_SUBJECT_PATTERN = re.compile(r"^[a-z0-9_]{1,32}$")
_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: Fields every sample row carries when they hold a number.  `t` and `hr_n`
#: are checked separately because their rules are structural rather than
#: merely numeric.
_NUMERIC_FIELDS = (
    "hr",
    "ae_kcal_min",
    "be_kcal_min",
    "steps_min",
    "t_app_c",
    "rh_pct",
)

_REQUIRED_TOP_LEVEL = (
    "schema_version",
    "subject",
    "date",
    "timezone",
    "grid_s",
    "synthetic",
    "samples",
    "day",
)


class UnknownBundle(LookupError):
    """A request named a subject or date that is not on disk."""

    def __init__(self, subject: str, date: str, available: dict[str, list[str]]) -> None:
        self.subject = subject
        self.date = date
        self.available = available
        listing = "; ".join(
            f"{name}: {', '.join(dates) if dates else '(no bundles)'}"
            for name, dates in sorted(available.items())
        ) or "(no bundles)"
        super().__init__(
            f"No bundle '{date}' for subject '{subject}'. Available: {listing}"
        )


def is_finite_number(value: object) -> bool:
    """
    True only for a JSON number that is neither a bool nor NaN/infinity.

    `json.loads` accepts the non-standard `NaN` and `Infinity` literals, so a
    corrupt file reaches this code as a float that compares false to every
    range check while still looking like a number.  Booleans are ints in
    Python and would otherwise pass as heart rates.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except (TypeError, OverflowError):
        return False


def _is_calendar_date(text: object) -> bool:
    if not isinstance(text, str) or not _DATE_PATTERN.match(text):
        return False
    try:
        _date.fromisoformat(text)
    except ValueError:
        return False
    return True


def bundle_roots() -> dict[str, Path]:
    """
    Subject name -> directory holding that subject's `<date>.json` files.

    The committed demo always comes from this repository, even when
    `CARDIOTWIN_BUNDLE_DIR` also has a `demo` folder: a demo whose numbers
    change with the deployment's environment is not a reproducible demo.
    Every other immediate subdirectory is a subject.  The environment variable
    is read on every call so a test or a deployment can change it at runtime.
    """
    roots: dict[str, Path] = {"demo": BUNDLE_DIR / "demo"}

    configured = os.environ.get("CARDIOTWIN_BUNDLE_DIR")
    if configured:
        base = Path(configured)
        if base.is_dir():
            for child in sorted(base.iterdir()):
                if child.is_dir() and child.name != "demo":
                    roots[child.name] = child

    return roots


def list_bundles() -> dict[str, list[str]]:
    """Subject -> sorted dates that actually have a `<date>.json` file."""
    found: dict[str, list[str]] = {}
    for subject, directory in bundle_roots().items():
        found[subject] = sorted(
            path.stem
            for path in directory.glob("*.json")
            if path.is_file() and _is_calendar_date(path.stem)
        )
    return found


def _validate_subject(subject: str) -> None:
    """Refuse a subject that could name a path rather than a subject."""
    if not isinstance(subject, str) or not _SUBJECT_PATTERN.match(subject):
        raise ValueError(
            f"Invalid subject {subject!r}: use 1-32 lowercase letters, digits "
            f"or underscores (for example 's9' or 'demo')."
        )


def load_params(subject: str) -> dict | None:
    """
    Read and validate a subject's fitted ``params.json``, when it has one.

    The file lives beside the subject's day bundles, so it is found by the
    same subject discovery as `load_bundle`.  A subject without the file —
    including the committed demo — simply has no fitted parameters and
    returns None; the replay then runs on the lamina's declared defaults.

    Only the file's own shape is checked here: which coefficient ids a
    lamina accepts, and which outcome ids it knows, are facts about the
    lamina and are enforced when the replay is built.
    """
    _validate_subject(subject)

    roots = bundle_roots()
    if subject not in roots:
        return None

    directory = roots[subject]
    path = directory / "params.json"
    resolved = path.resolve()
    try:
        resolved.relative_to(directory.resolve())
    except ValueError as exc:
        raise ValueError(
            f"{resolved}: refusing to read params outside its subject "
            f"directory {directory}."
        ) from exc

    if not resolved.is_file():
        return None

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{resolved}: cannot read params: {exc}") from exc

    validate_params(data, label=str(resolved))
    return data


def validate_params(data: object, label: str = "<params>") -> dict:
    """
    Check a params file by hand and return it unchanged.

    Every failure names the file and the key it is about: this file replaces
    a patient's coefficients, so a typo must be refused before a replay
    starts rather than become a plausible-looking fitted model.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"{label}: params must be a JSON object, got "
            f"{type(data).__name__}."
        )

    if "schema_version" not in data:
        raise ValueError(f"{label}: missing required field 'schema_version'.")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(
            f"{label}: schema_version must be 1, got "
            f"{data['schema_version']!r}."
        )

    if "coefficients" not in data:
        raise ValueError(f"{label}: missing required field 'coefficients'.")
    coefficients = data["coefficients"]
    if not isinstance(coefficients, dict) or not coefficients:
        raise ValueError(
            f"{label}: coefficients must be a non-empty JSON object of "
            f"coefficient id to finite number, got {coefficients!r}."
        )
    for key, value in coefficients.items():
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"{label}: coefficient key {key!r} must be a non-empty string."
            )
        if not is_finite_number(value):
            raise ValueError(
                f"{label}: coefficients['{key}']={value!r} is not a finite "
                f"number."
            )

    if "outcome_tolerance" in data:
        tolerances = data["outcome_tolerance"]
        if not isinstance(tolerances, dict):
            raise ValueError(
                f"{label}: outcome_tolerance must be a JSON object of outcome "
                f"id to positive finite number, got "
                f"{type(tolerances).__name__}."
            )
        for key, value in tolerances.items():
            if not isinstance(key, str) or not key:
                raise ValueError(
                    f"{label}: outcome_tolerance key {key!r} must be a "
                    f"non-empty string."
                )
            if not is_finite_number(value) or value <= 0:
                raise ValueError(
                    f"{label}: outcome_tolerance['{key}']={value!r} must be a "
                    f"finite number greater than 0."
                )

    return data


def load_bundle(subject: str, date: str) -> dict:
    """
    Read, validate and return one day bundle.

    Raises ValueError for an identifier, date or file that is the wrong shape,
    and UnknownBundle when the subject or date simply is not there.  The
    resolved path is checked to stay inside its subject directory even though
    the identifier patterns already forbid separators — a traversal must be
    refused at the boundary that reads the file, not only at the one that
    names it.
    """
    _validate_subject(subject)
    if not _is_calendar_date(date):
        raise ValueError(
            f"Invalid date {date!r}: expected a real calendar date in "
            f"YYYY-MM-DD form (for example '2025-06-01')."
        )

    roots = bundle_roots()
    available = list_bundles()
    if subject not in roots:
        raise UnknownBundle(subject, date, available)

    directory = roots[subject]
    path = directory / f"{date}.json"
    resolved = path.resolve()
    try:
        resolved.relative_to(directory.resolve())
    except ValueError as exc:
        raise ValueError(
            f"{resolved}: refusing to read a bundle outside its subject "
            f"directory {directory}."
        ) from exc

    if not resolved.is_file():
        raise UnknownBundle(subject, date, available)

    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{resolved}: cannot read bundle: {exc}") from exc

    validate_bundle(data, label=str(resolved))

    if data["subject"] != subject:
        raise ValueError(
            f"{resolved}: file subject is {data['subject']!r}, but the request "
            f"asked for {subject!r}."
        )
    if data["date"] != date:
        raise ValueError(
            f"{resolved}: file date is {data['date']!r}, but the request "
            f"asked for {date!r}."
        )
    return data


def validate_bundle(data: object, label: str = "<bundle>") -> dict:
    """
    Check a bundle's structure by hand and return it unchanged.

    Every failure names the file (or label) and, where the problem is row
    specific, the row index.  The checks mirror `bundle.schema.json` plus the
    two invariants the schema cannot state: consecutive rows are one minute
    apart, and `hr` is absent exactly when `hr_n` is zero.
    """
    if not isinstance(data, dict):
        raise ValueError(
            f"{label}: a bundle must be a JSON object, got "
            f"{type(data).__name__}."
        )

    for key in _REQUIRED_TOP_LEVEL:
        if key not in data:
            raise ValueError(f"{label}: missing required field '{key}'.")

    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError(
            f"{label}: schema_version must be 1, got "
            f"{data['schema_version']!r}."
        )

    if not isinstance(data["subject"], str) or not data["subject"]:
        raise ValueError(
            f"{label}: subject must be a non-empty string, got "
            f"{data['subject']!r}."
        )

    if not _is_calendar_date(data["date"]):
        raise ValueError(
            f"{label}: date must be a real calendar date in YYYY-MM-DD form, "
            f"got {data['date']!r}."
        )

    timezone_name = data["timezone"]
    if not isinstance(timezone_name, str) or not timezone_name:
        raise ValueError(
            f"{label}: timezone must be a non-empty string, got "
            f"{timezone_name!r}."
        )
    if timezone_name != "UTC":
        try:
            ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
            raise ValueError(
                f"{label}: timezone {timezone_name!r} is neither 'UTC' nor a "
                f"known IANA time zone."
            ) from exc

    if type(data["grid_s"]) is not int or data["grid_s"] != 60:
        raise ValueError(
            f"{label}: grid_s must be 60 (one row per minute), got "
            f"{data['grid_s']!r}."
        )

    if type(data["synthetic"]) is not bool:
        raise ValueError(
            f"{label}: synthetic must be true or false, got "
            f"{data['synthetic']!r}."
        )

    samples = data["samples"]
    if not isinstance(samples, list):
        raise ValueError(
            f"{label}: samples must be a list of rows, got "
            f"{type(samples).__name__}."
        )

    day = data["day"]
    if not isinstance(day, dict):
        raise ValueError(
            f"{label}: day must be a JSON object, got {type(day).__name__}."
        )
    if "n_minutes" not in day:
        raise ValueError(f"{label}: day is missing required field 'n_minutes'.")

    n_minutes = day["n_minutes"]
    if type(n_minutes) is not int or n_minutes < 1:
        raise ValueError(
            f"{label}: day n_minutes must be a positive integer, got "
            f"{n_minutes!r}."
        )
    if len(samples) != n_minutes:
        raise ValueError(
            f"{label}: day n_minutes is {n_minutes}, but samples holds "
            f"{len(samples)} rows."
        )

    for index, row in enumerate(samples):
        _validate_row(row, index, label)

    return data


def _validate_row(row: object, index: int, label: str) -> None:
    where = f"{label}: sample row {index}"

    if not isinstance(row, dict):
        raise ValueError(
            f"{where} must be a JSON object, got {type(row).__name__}."
        )

    if "t" not in row:
        raise ValueError(f"{where} is missing required field 't'.")
    t = row["t"]
    expected_t = index * 60
    if type(t) is not int or t != expected_t:
        raise ValueError(
            f"{where}: t must be {expected_t} (one row per minute), got {t!r}."
        )

    for field in ("hr", "hr_n", *_NUMERIC_FIELDS):
        if field not in row:
            raise ValueError(f"{where} is missing required field '{field}'.")

    hr_n = row["hr_n"]
    if type(hr_n) is not int or hr_n < 0:
        raise ValueError(
            f"{where}: hr_n must be an integer >= 0, got {hr_n!r}."
        )

    hr = row["hr"]
    if hr is not None:
        if not is_finite_number(hr):
            raise ValueError(
                f"{where}: hr must be null or a finite number, got {hr!r}."
            )
        if not 20 <= hr <= 240:
            raise ValueError(
                f"{where}: hr={hr!r} is outside the physiological range "
                f"20..240 bpm."
            )

    if (hr is None) != (hr_n == 0):
        raise ValueError(
            f"{where}: hr and hr_n disagree; hr must be null exactly when "
            f"hr_n is 0 (got hr={hr!r}, hr_n={hr_n})."
        )

    for field in _NUMERIC_FIELDS:
        value = row[field]
        if value is not None and not is_finite_number(value):
            raise ValueError(
                f"{where}: {field} must be null or a finite number, got "
                f"{value!r}."
            )
