"""
Export a subject's fitness records beside their day bundles.

usage (from backend/):
    python tools/export_fitness_records.py <channels_dir> <subject> [--from YYYY-MM-DD] [--to YYYY-MM-DD]

Reads two channel files a health-data pipeline already wrote,
``resting_hr.parquet`` and ``vo2max.parquet`` (columns ``start``, ``value``;
``start`` carries the local timezone), and writes
``bundles/<subject>/fitness_records.json``:

    {"schema_version": 1, "subject": ..., "made_at": ..., "period": [from, to],
     "series": {"resting_hr": {"unit": "bpm", "days": [[date, value], ...]},
                "vo2max":     {"unit": "mL/kg/min", "days": [[date, value], ...]}},
     "note": ...}

One value per local date: the mean when a date has more than one record.
Only the date and the value are written.  Every other column of the channel
files (the device's name among them, which can hold the person's name) is
left behind on purpose.

The period defaults to the dates of the subject's bundles, so nothing older or
newer than the published days is published with them.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from bundles import BUNDLE_DIR  # noqa: E402

SCHEMA_VERSION = 1

#: channel file stem -> (series key, unit, plausible range).  A value outside
#: the range is a unit or export error, and the export refuses it.
CHANNELS = {
    "resting_hr": ("resting_hr", "bpm", (25.0, 140.0)),
    "vo2max": ("vo2max", "mL/kg/min", (8.0, 95.0)),
}

NOTE = (
    "Watch estimates, as the device reported them: resting heart rate once a "
    "day, VO2max after some outdoor walks and runs. They are estimates, not "
    "laboratory measurements."
)


def _iso(text: str, flag: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{flag} must be a date YYYY-MM-DD, got {text!r}.") from exc


def bundle_period(subject_dir: Path) -> tuple[date, date]:
    """First and last date among a subject folder's day bundles."""
    days = []
    for path in subject_dir.glob("*.json"):
        try:
            days.append(date.fromisoformat(path.stem))
        except ValueError:
            continue
    if not days:
        raise ValueError(
            f"{subject_dir} holds no day bundle (YYYY-MM-DD.json); pass "
            f"--from and --to."
        )
    return min(days), max(days)


def daily_series(frame, key: str, period: tuple[date, date],
                 plausible: tuple[float, float]) -> list[list]:
    """[[date, value], ...] for one channel, one mean value per local date."""
    for column in ("start", "value"):
        if column not in frame.columns:
            raise ValueError(
                f"{key}: the channel file has no '{column}' column; columns "
                f"are {list(frame.columns)}."
            )
    sums: dict[date, list[float]] = {}
    for start, value in zip(frame["start"], frame["value"]):
        if start is None or value is None:
            continue
        if not callable(getattr(start, "date", None)):
            raise ValueError(f"{key}: 'start' must be timestamps, got {start!r}.")
        day = start.date()
        if not (period[0] <= day <= period[1]):
            continue
        number = float(value)
        if not math.isfinite(number):
            raise ValueError(f"{key}: a value on {day} is not finite ({value!r}).")
        low, high = plausible
        if not (low <= number <= high):
            raise ValueError(
                f"{key}: {number:g} on {day} lies outside the plausible "
                f"{low:g}..{high:g}; check the unit of the channel file."
            )
        sums.setdefault(day, []).append(number)
    return [
        [day.isoformat(), round(sum(values) / len(values), 2)]
        for day, values in sorted(sums.items())
    ]


def export(channels_dir: Path, subject: str, period: tuple[date, date] | None = None,
           out_root: Path | None = None) -> Path:
    import pandas as pd

    root = out_root if out_root is not None else BUNDLE_DIR
    subject_dir = Path(root) / subject
    if not subject_dir.is_dir():
        raise ValueError(f"No subject folder {subject_dir}.")
    if period is None:
        period = bundle_period(subject_dir)
    if period[0] > period[1]:
        raise ValueError(f"The period is reversed: {period[0]} after {period[1]}.")

    series = {}
    for stem, (key, unit, plausible) in CHANNELS.items():
        path = Path(channels_dir) / f"{stem}.parquet"
        if not path.is_file():
            raise ValueError(f"Missing channel file {path}.")
        series[key] = {
            "unit": unit,
            "days": daily_series(pd.read_parquet(path), key, period, plausible),
        }

    document = {
        "schema_version": SCHEMA_VERSION,
        "subject": subject,
        "made_at": datetime.now(timezone.utc).isoformat(),
        "period": [period[0].isoformat(), period[1].isoformat()],
        "series": series,
        "note": NOTE,
    }
    out = subject_dir / "fitness_records.json"
    out.write_text(json.dumps(document, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("channels_dir", type=Path)
    parser.add_argument("subject")
    parser.add_argument("--from", dest="start")
    parser.add_argument("--to", dest="end")
    args = parser.parse_args(argv)
    period = None
    if args.start or args.end:
        if not (args.start and args.end):
            parser.error("--from and --to go together.")
        period = (_iso(args.start, "--from"), _iso(args.end, "--to"))
    out = export(args.channels_dir, args.subject, period)
    document = json.loads(out.read_text(encoding="utf-8"))
    for key, block in document["series"].items():
        print(f"{key}: {len(block['days'])} days ({block['unit']})")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
