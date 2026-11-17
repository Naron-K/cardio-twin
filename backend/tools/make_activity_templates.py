"""
Turn one subject's recorded days into activity templates.

A template is a summary of the minutes this person actually recorded: what one
minute of each workout label costs in active energy and steps, what the quiet
hours outside sessions look like, when they are awake, and the range their
resting level and apparent temperature cover.  Nothing here is a population
value; every number is this subject's own recording, and the written file says
so in "applies_to".

The workout groups are read from the lamina's <day_view>: this tool names no
workout type and no attribute id itself.  A group is whatever the wearable
lamina declares an <event> for, and its workouts are the labels that event's
indicator reads.

DEFINITIONS

  * A minute is WORN when its bundle row has ae_kcal_min not null.
  * A SESSION is a maximal run of consecutive minutes carrying the same
    non-null workout label.
  * A day is USED when it has at least one worn minute.
  * A qualifying session lasts at least 5 minutes and has at least 3 worn
    minutes; its activity is the mean AE_rate over those worn minutes.

OUTPUT

``<bundle-dir>/<subject>/templates.json`` (or --out) holds, in addition to the
identity fields, the per-workout, per-group and all-session summaries, 24
hourly rates (with a fallback when an hour is thinly recorded), the daily steps
outside sessions, the awake window, the resting level range and the apparent
temperature range.  It also holds, when a full week qualifies, the current
weekly activity dose.  Floats are rounded to four decimals; the resting level
and the temperature use one decimal because that is how they are read.

Run from backend/:

    python tools/make_activity_templates.py --bundle-dir bundles --subject subject_demo

or from the repository root:

    python backend/tools/make_activity_templates.py --bundle-dir backend/bundles --subject subject_demo
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from bundles import (  # noqa: E402
    load_params,
    read_subject_label,
)
from day_summary import summarise_bundle  # noqa: E402
from plan_options import _quiet, kind_groups  # noqa: E402
from tools.export_fitness_records import CHANNELS  # noqa: E402
from tools.fit_hr_model import (  # noqa: E402
    WEARABLE_XML,
    day_inputs,
    load_days,
    load_twin,
)

SCHEMA_VERSION = 1
LAMINA_ID = "lamina_wearable"

SESSION_MIN_MINUTES = 5
SESSION_MIN_WORN = 3
WORKOUT_DIRECT_MINUTES = 30
GROUP_MIN_MINUTES = 10
OFFERED_SESSIONS = 5
HOURLY_MIN_MINUTES = 30
USED_DAY_MIN_WORN = 720
AWAKE_ROUND_MINUTES = 5
ROUND_DECIMALS = 4
LEVEL_DECIMALS = 1

HABIT_START_DATE = _date(2025, 1, 1)
HABIT_MIN_WORN_MINUTES = 300
HABIT_MIN_WORN_DAYS = 5
HABIT_WEEK_DAYS = 7

#: A fitness series needs at least this many recorded days to be summarised.
FITNESS_MIN_DAYS = 3
#: Fitness values are reported to the two decimals the recordings carry.
FITNESS_DECIMALS = 2
#: The plausible range of each fitness series, from the exporter that writes
#: ``fitness_records.json``, so a unit error is refused here as it is there.
_FITNESS_RANGES = {
    key: plausible for key, _unit, plausible in CHANNELS.values()
}


def _r4(value) -> float:
    return round(float(value), ROUND_DECIMALS)


def _r1(value) -> float:
    return round(float(value), LEVEL_DECIMALS)


def _nearest(value, step: int) -> int:
    return int(round(float(value) / step) * step)


def _empty_acc() -> dict:
    return {
        "minutes": 0,
        "ae": 0.0,
        "steps": 0.0,
        "sessions": 0,
        "session_ae": [],
    }


def _stats(acc: dict) -> dict:
    minutes = int(acc["minutes"])
    if minutes > 0:
        ae_mean = _r4(acc["ae"] / minutes)
        steps_mean = _r4(acc["steps"] / minutes)
    else:
        ae_mean = None
        steps_mean = None

    sessions = int(acc["sessions"])
    if sessions > 0:
        p10, p50, p90 = np.percentile(acc["session_ae"], [10, 50, 90])
        session_ae = {
            "p10": _r4(p10),
            "p50": _r4(p50),
            "p90": _r4(p90),
        }
    else:
        session_ae = None

    return {
        "minutes": minutes,
        "ae_mean": ae_mean,
        "steps_mean": steps_mean,
        "sessions": sessions,
        "session_ae": session_ae,
    }


def _session_runs(labels) -> list[dict]:
    runs: list[dict] = []
    n = len(labels)
    index = 0
    while index < n:
        raw = labels[index]
        if raw is None:
            index += 1
            continue
        label = str(raw)
        end = index + 1
        while (
            end < n
            and labels[end] is not None
            and str(labels[end]) == label
        ):
            end += 1
        runs.append({
            "label": label,
            "start": index,
            "end": end,
            "length": end - index,
        })
        index = end
    return runs


def _steps_of(row: dict) -> float:
    value = row.get("steps_min")
    return 0.0 if value is None else float(value)


def _check_non_negative(value, field: str, date: str, index: int) -> None:
    if value is None:
        return
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(
            f"{date}: sample row {index} has {field}={value!r}. Activity "
            f"templates need null or a non-negative finite number; fix the "
            f"bundle or leave that day out."
        )


def build_templates(days: list[dict], groups: dict[str, dict]) -> dict:
    """
    Summarise the worn minutes of these validated day bundles.

    Only worn minutes inside sessions feed the workout, group and all-session
    summaries.  Hours, daily step totals and the awake window are measured
    outside sessions, where the day is not already explained by a workout.
    Every group in `groups` appears even when it has no minutes.
    """
    if not days:
        raise ValueError(
            "No day bundles were supplied, so no activity templates can be "
            "built. Pass at least one <subject>/<date>.json bundle."
        )

    subjects = {bundle.get("subject") for bundle in days}
    if len(subjects) != 1:
        shown = ", ".join(sorted(str(name) for name in subjects))
        raise ValueError(
            f"Activity templates are built for one subject, but these days "
            f"belong to: {shown}. Load the days of a single subject."
        )

    label_group: dict[str, str] = {}
    for group_id, spec in groups.items():
        for workout in spec["workouts"]:
            label_group.setdefault(workout, group_id)

    label_acc: dict[str, dict] = {}
    group_acc = {group_id: _empty_acc() for group_id in groups}
    all_acc = _empty_acc()

    hourly_minutes = [0] * 24
    hourly_ae = [0.0] * 24
    hourly_steps = [0.0] * 24
    outside_minutes = 0
    outside_ae = 0.0
    outside_steps = 0.0

    outside_day_steps: list[float] = []
    awake_starts: list[int] = []
    awake_ends: list[int] = []
    level_values: list[float] = []
    t_app_values: list[float] = []
    used_days = 0

    for bundle in days:
        date = bundle["date"]
        samples = bundle["samples"]
        for index, row in enumerate(samples):
            _check_non_negative(
                row.get("ae_kcal_min"), "ae_kcal_min", date, index
            )
            _check_non_negative(row.get("steps_min"), "steps_min", date, index)

        inputs = day_inputs(bundle)
        labels = inputs["workout"]
        hours = inputs["hour_local"]
        ae_rate = inputs["AE_rate"]
        n = len(samples)

        worn = np.array(
            [row.get("ae_kcal_min") is not None for row in samples],
            dtype=bool,
        )
        in_session = np.array(
            [label is not None for label in labels], dtype=bool
        )
        worn_count = int(worn.sum())
        if worn_count > 0:
            used_days += 1

        for run in _session_runs(labels):
            label = run["label"]
            label_acc.setdefault(label, _empty_acc())
            worn_indices = [
                minute
                for minute in range(run["start"], run["end"])
                if worn[minute]
            ]
            ae_values = [float(ae_rate[minute]) for minute in worn_indices]
            step_values = [
                _steps_of(samples[minute]) for minute in worn_indices
            ]

            targets = [label_acc[label], all_acc]
            group_id = label_group.get(label)
            if group_id is not None:
                targets.append(group_acc[group_id])

            for acc in targets:
                acc["minutes"] += len(worn_indices)
                acc["ae"] += float(sum(ae_values))
                acc["steps"] += float(sum(step_values))

            qualifies = (
                run["length"] >= SESSION_MIN_MINUTES
                and len(worn_indices) >= SESSION_MIN_WORN
            )
            if qualifies:
                mean_ae = float(sum(ae_values)) / len(worn_indices)
                for acc in targets:
                    acc["sessions"] += 1
                    acc["session_ae"].append(mean_ae)

        outside = worn & ~in_session
        # A day's steps outside sessions count every minute that is not in a
        # session, worn or not: steps can be recorded while the watch is off
        # (by the phone), and a planned day sets its total, not its wear.
        outside_day_total = float(sum(
            _steps_of(samples[minute])
            for minute in range(n)
            if not in_session[minute]
        ))
        for minute in np.nonzero(outside)[0]:
            minute = int(minute)
            hour_value = float(hours[minute])
            if not math.isfinite(hour_value):
                continue
            hour = int(hour_value) % 24
            ae_value = float(ae_rate[minute])
            step_value = _steps_of(samples[minute])
            hourly_minutes[hour] += 1
            hourly_ae[hour] += ae_value
            hourly_steps[hour] += step_value
            outside_minutes += 1
            outside_ae += ae_value
            outside_steps += step_value

        if worn_count >= USED_DAY_MIN_WORN:
            outside_day_steps.append(outside_day_total)
            first = int(np.argmax(worn))
            last = n - 1 - int(np.argmax(worn[::-1]))
            awake_starts.append(
                int(round(float(hours[first]) * 60.0))
            )
            awake_ends.append(
                int(round(float(hours[last]) * 60.0)) + 1
            )

        level = bundle["day"].get("hr_level_rts")
        if level is not None:
            level_values.append(float(level))

        for minute in range(n):
            if not worn[minute]:
                continue
            raw = samples[minute].get("t_app_c")
            if raw is not None:
                t_app_values.append(float(raw))

    if used_days == 0:
        raise ValueError(
            "None of these days has a worn minute (ae_kcal_min not null), so "
            "there is nothing to build activity templates from. Add a day the "
            "watch recorded something for."
        )

    workouts: dict[str, dict] = {}
    for label, acc in label_acc.items():
        entry = _stats(acc)
        entry["group"] = label_group.get(label)
        workouts[label] = entry

    group_entries: dict[str, dict] = {}
    for group_id, spec in groups.items():
        entry = _stats(group_acc[group_id])
        entry["label"] = spec["label"]
        entry["offered"] = entry["sessions"] >= OFFERED_SESSIONS
        group_entries[group_id] = entry

    hourly: list[dict] = []
    for hour in range(24):
        count = hourly_minutes[hour]
        if count >= HOURLY_MIN_MINUTES:
            ae_mean = _r4(hourly_ae[hour] / count)
            steps_mean = _r4(hourly_steps[hour] / count)
            fallback = False
        else:
            if outside_minutes > 0:
                ae_mean = _r4(outside_ae / outside_minutes)
                steps_mean = _r4(outside_steps / outside_minutes)
            elif all_acc["minutes"] > 0:
                ae_mean = _r4(all_acc["ae"] / all_acc["minutes"])
                steps_mean = _r4(all_acc["steps"] / all_acc["minutes"])
            else:
                ae_mean = 0.0
                steps_mean = 0.0
            fallback = True
        hourly.append({
            "hour": hour,
            "ae_mean": ae_mean,
            "steps_mean": steps_mean,
            "minutes": int(count),
            "fallback": fallback,
        })

    if outside_day_steps:
        p10, p50, p90 = np.percentile(outside_day_steps, [10, 50, 90])
        steps_outside = {
            "p10": int(round(float(p10))),
            "p50": int(round(float(p50))),
            "p90": int(round(float(p90))),
            "days": len(outside_day_steps),
        }
    else:
        steps_outside = {"p10": 0, "p50": 0, "p90": 0, "days": 0}

    if awake_starts:
        awake = {
            "start": _nearest(np.median(awake_starts), AWAKE_ROUND_MINUTES),
            "end": _nearest(np.median(awake_ends), AWAKE_ROUND_MINUTES),
            "days": len(awake_starts),
        }
    else:
        awake = {"start": 0, "end": 0, "days": 0}

    if level_values:
        median = _r1(np.median(level_values))
        p5, p95 = np.percentile(level_values, [5, 95])
        recorded = [
            int(math.floor(float(p5))),
            int(math.ceil(float(p95))),
        ]
    else:
        median = 0.0
        recorded = [0, 0]
    level = {
        "median": median,
        "recorded": recorded,
        "days": len(level_values),
    }

    if t_app_values:
        p5, p50, p95 = np.percentile(t_app_values, [5, 50, 95])
        t_app = {"p5": _r1(p5), "p50": _r1(p50), "p95": _r1(p95)}
    else:
        t_app = {"p5": 0.0, "p50": 0.0, "p95": 0.0}

    return {
        "workouts": workouts,
        "groups": group_entries,
        "all_sessions": _stats(all_acc),
        "hourly": hourly,
        "steps_outside": steps_outside,
        "awake": awake,
        "level": level,
        "t_app": t_app,
        "days": len(days),
        "first_date": days[0]["date"],
        "last_date": days[-1]["date"],
    }


def _worn_minutes(bundle: dict) -> int:
    """Minutes on which the bundle has ae_kcal_min, the tool's worn minute."""
    return sum(
        1 for row in bundle["samples"] if row.get("ae_kcal_min") is not None
    )


def _habit_percentiles(values: list[float]) -> dict:
    """The 10th, 50th and 90th percentile, rounded like the other tables."""
    p10, p50, p90 = np.percentile(values, [10, 50, 90])
    return {
        "p10": _r4(p10),
        "p50": _r4(p50),
        "p90": _r4(p90),
    }


def _fitness_period(days: list[dict]) -> tuple[str, str]:
    """The habit's period: its own start date to the last recorded day."""
    if not isinstance(days, list) or not days:
        raise ValueError(
            "Fitness values need the subject's day bundles, but none were "
            "supplied."
        )
    last = days[-1]
    if not isinstance(last, dict) or not isinstance(last.get("date"), str):
        raise ValueError(
            f"The last day bundle must declare a YYYY-MM-DD 'date', got "
            f"{last!r}."
        )
    try:
        last_date = _date.fromisoformat(last["date"])
    except ValueError as exc:
        raise ValueError(
            f"The last bundle date {last['date']!r} is not a YYYY-MM-DD date."
        ) from exc
    if last_date < HABIT_START_DATE:
        raise ValueError(
            f"The last bundle date {last_date.isoformat()} is before the "
            f"habit's start {HABIT_START_DATE.isoformat()}, so no fitness "
            f"period can run from the habit's start to it."
        )
    return HABIT_START_DATE.isoformat(), last_date.isoformat()


def load_fitness_records(path: Path) -> dict | None:
    """
    Read and shape-check a subject's ``fitness_records.json``, when it exists.

    None means no recordings file.  A file that is not the exported shape, a
    day that is not a date, a value that is not finite or one outside the
    exporter's plausible range is refused by path and key, so a unit error
    surfaces here rather than as a confident-looking median.
    """
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(
            f"{path}: cannot read fitness records: {exc}"
        ) from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(
            f"{path}: invalid JSON in fitness records: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: fitness records must be a JSON object, got "
            f"{type(data).__name__}."
        )
    series = data.get("series")
    if not isinstance(series, dict):
        raise ValueError(
            f"{path}: fitness records must hold a 'series' object, got "
            f"{type(series).__name__}."
        )
    for key, block in series.items():
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"{path}: a fitness series key must be a non-empty string, "
                f"got {key!r}."
            )
        if not isinstance(block, dict):
            raise ValueError(
                f"{path}: fitness series '{key}' must be a JSON object, got "
                f"{type(block).__name__}."
            )
        unit = block.get("unit")
        if not isinstance(unit, str) or not unit:
            raise ValueError(
                f"{path}: fitness series '{key}' must declare a non-empty "
                f"'unit' string, got {unit!r}."
            )
        days = block.get("days")
        if not isinstance(days, list):
            raise ValueError(
                f"{path}: fitness series '{key}' must hold a 'days' list, "
                f"got {type(days).__name__}."
            )
        plausible = _FITNESS_RANGES.get(key)
        for index, row in enumerate(days):
            if not isinstance(row, (list, tuple)) or len(row) != 2:
                raise ValueError(
                    f"{path}: fitness series '{key}' day {index} must be "
                    f"[date, value], got {row!r}."
                )
            day_text, value = row
            try:
                _date.fromisoformat(day_text)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}: fitness series '{key}' day {index} has date "
                    f"{day_text!r}; expected YYYY-MM-DD."
                ) from exc
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path}: fitness series '{key}' value on {day_text} is "
                    f"{value!r}, not a number."
                ) from exc
            if not math.isfinite(number):
                raise ValueError(
                    f"{path}: fitness series '{key}' value on {day_text} is "
                    f"{value!r}, not a finite number."
                )
            if plausible is not None:
                low, high = plausible
                if number < low or number > high:
                    raise ValueError(
                        f"{path}: fitness series '{key}' value {number:g} on "
                        f"{day_text} lies outside the plausible {low:g}.."
                        f"{high:g}; check the unit."
                    )
    return data


def build_fitness(days: list[dict], subject_dir: Path) -> dict | None:
    """
    The person's measured fitness over the same days as their habit.

    Reads ``<subject_dir>/fitness_records.json``; None when that file does
    not exist.  Each series' daily values between the habit's own start date
    and the last recorded day are summarised by their median and 10th/90th
    percentiles.  A series with fewer than three values in that period is
    left out rather than reported from too little.
    """
    records = load_fitness_records(Path(subject_dir) / "fitness_records.json")
    if records is None:
        return None

    first, last = _fitness_period(days)
    values: dict[str, dict] = {}
    for key, block in records["series"].items():
        in_period = [
            float(value)
            for day_text, value in block["days"]
            if first <= day_text <= last
        ]
        if len(in_period) < FITNESS_MIN_DAYS:
            continue
        p10, p50, p90 = np.percentile(in_period, [10, 50, 90])
        values[key] = {
            "median": round(float(p50), FITNESS_DECIMALS),
            "p10": round(float(p10), FITNESS_DECIMALS),
            "p90": round(float(p90), FITNESS_DECIMALS),
            "days": len(in_period),
            "unit": block["unit"],
        }

    return {
        "period": [first, last],
        "rule": (
            f"Days from {first} to {last}; each value is that series' median "
            f"over those days, with the 10th and 90th percentiles."
        ),
        "values": values,
    }


def build_habit(
    days: list[dict],
    params: dict | None,
    subject_label: str,
    lamina_id: str = LAMINA_ID,
) -> dict | None:
    """
    The current weekly activity, from the recordings' own day dose.

    Days dated 2025-01-01 or later are grouped by ISO week.  A week counts
    when all seven of its days are present as bundles and at least five of
    them have more than 300 worn minutes.  Each counted day's dose is the
    one ``day_summary.summarise_bundle`` returns, so this is the lamina's
    arithmetic rather than a second copy of it.  With no counted week the
    answer is None.
    """
    if not isinstance(days, list):
        raise ValueError(
            f"days must be a list of day bundles, got "
            f"{type(days).__name__}."
        )
    if not isinstance(subject_label, str) or not subject_label:
        raise ValueError(
            f"subject_label must be a non-empty string, got "
            f"{subject_label!r}."
        )
    if params is not None:
        if not isinstance(params, dict):
            raise ValueError(
                f"params must be a mapping or None, got "
                f"{type(params).__name__}."
            )
        if "coefficients" not in params:
            raise ValueError(
                "params has no 'coefficients'; load it with "
                "bundles.load_params before building the habit."
            )

    weeks: dict[tuple[int, int], dict[_date, dict]] = {}
    for bundle in days:
        if not isinstance(bundle, dict) or "date" not in bundle:
            raise ValueError(
                "Every habit day must be a bundle object with a 'date', got "
                f"{bundle!r}."
            )
        try:
            day = _date.fromisoformat(bundle["date"])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Bundle date {bundle['date']!r} is not a YYYY-MM-DD date."
            ) from exc
        if day < HABIT_START_DATE:
            continue
        iso = day.isocalendar()
        weeks.setdefault((iso.year, iso.week), {})[day] = bundle

    counted: list[tuple[tuple[int, int], list[dict]]] = []
    for key in sorted(weeks):
        week = weeks[key]
        if len(week) != HABIT_WEEK_DAYS:
            continue
        worn_days = sum(
            1
            for bundle in week.values()
            if _worn_minutes(bundle) > HABIT_MIN_WORN_MINUTES
        )
        if worn_days < HABIT_MIN_WORN_DAYS:
            continue
        counted.append((key, [week[day] for day in sorted(week)]))

    if not counted:
        return None

    weekly_total: list[float] = []
    weekly_in_sessions: list[float] = []
    outside_per_day: list[float] = []
    with _quiet():
        for _key, week in counted:
            total = 0.0
            in_sessions = 0.0
            for bundle in week:
                summary = summarise_bundle(
                    lamina_id,
                    bundle,
                    params,
                    subject_label,
                    planned=True,
                )
                if "dose" not in summary:
                    raise ValueError(
                        f"Lamina '{lamina_id}' has no <dose> role, so a "
                        f"weekly habit cannot be built from day_summary."
                    )
                dose = summary["dose"]
                total += float(dose["total"])
                in_sessions += float(dose["in_sessions"])
                outside_per_day.append(float(dose["outside_sessions"]))
            weekly_total.append(total / 60.0)
            weekly_in_sessions.append(in_sessions / 60.0)

    first = counted[0][0]
    last = counted[-1][0]
    return {
        "unit": "MET-h/week",
        "weeks": len(counted),
        "first_week": f"{first[0]:04d}-W{first[1]:02d}",
        "last_week": f"{last[0]:04d}-W{last[1]:02d}",
        "total": _habit_percentiles(weekly_total),
        "in_sessions": _habit_percentiles(weekly_in_sessions),
        "outside_sessions_per_day": _habit_percentiles(outside_per_day),
        "rule": (
            "Days dated 2025-01-01 or later; an ISO week counts when all 7 "
            "of its days are recorded and at least 5 of them have more than "
            "300 worn minutes."
        ),
    }


def session_rate(templates: dict, workout: str) -> tuple[float, float]:
    """
    The (AE, steps) rate of one minute in a session with this label.

    A well-recorded workout is its own best answer; a thin one borrows its
    group; anything else falls back to all sessions.  The chosen entry must
    have minutes, otherwise there is no rate to return.
    """
    workout_entry = templates.get("workouts", {}).get(workout)
    if (
        workout_entry is not None
        and workout_entry["minutes"] >= WORKOUT_DIRECT_MINUTES
    ):
        chosen = workout_entry
    else:
        group_id = (
            None if workout_entry is None else workout_entry.get("group")
        )
        group_entry = (
            None if group_id is None
            else templates.get("groups", {}).get(group_id)
        )
        if (
            group_entry is not None
            and group_entry["minutes"] >= GROUP_MIN_MINUTES
        ):
            chosen = group_entry
        else:
            chosen = templates["all_sessions"]

    if chosen["minutes"] <= 0:
        raise ValueError(
            f"No recorded minutes exist for workout '{workout}', its group or "
            f"all sessions, so there is no rate to return."
        )
    if chosen["ae_mean"] is None or chosen["steps_mean"] is None:
        raise ValueError(
            f"The chosen template for workout '{workout}' has minutes but no "
            f"activity mean; rebuild the templates."
        )
    return float(chosen["ae_mean"]), float(chosen["steps_mean"])


def hour_rate(templates: dict, hour: int) -> tuple[float, float]:
    """The (AE, steps) rate for a local clock hour from templates["hourly"]."""
    if (
        isinstance(hour, bool)
        or not isinstance(hour, int)
        or hour < 0
        or hour > 23
    ):
        raise ValueError(
            f"hour must be an integer from 0 to 23, got {hour!r}."
        )
    entry = templates["hourly"][hour]
    return float(entry["ae_mean"]), float(entry["steps_mean"])


def _format_number(value) -> str:
    return "None" if value is None else f"{float(value):.4f}"


def _format_session(session_ae) -> str:
    if session_ae is None:
        return "None"
    return (
        f"{session_ae['p10']:.4f}/{session_ae['p50']:.4f}/"
        f"{session_ae['p90']:.4f}"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Build one subject's activity templates from their days."
    )
    parser.add_argument(
        "--bundle-dir", required=True,
        help="Directory holding <subject>/<date>.json bundles.",
    )
    parser.add_argument(
        "--subject", required=True,
        help="Subject folder name to summarise.",
    )
    parser.add_argument(
        "--out", default=None,
        help="Output path (default: <bundle-dir>/<subject>/templates.json).",
    )
    args = parser.parse_args(argv)

    bundle_dir = Path(args.bundle_dir)
    subject_dir = bundle_dir / args.subject
    out_path = (
        Path(args.out) if args.out
        else subject_dir / "templates.json"
    )
    if not out_path.parent.is_dir():
        raise ValueError(
            f"Refusing to write {out_path}: its parent directory "
            f"{out_path.parent} does not exist. Create it first."
        )

    days = load_days(bundle_dir, args.subject)
    twin = load_twin(WEARABLE_XML)
    groups = kind_groups(twin)
    templates = build_templates(days, groups)

    label = read_subject_label(subject_dir, args.subject)
    params = load_params(args.subject)
    habit = build_habit(days, params, label, LAMINA_ID)
    fitness = build_fitness(days, subject_dir)

    dropped = False
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = None
        if isinstance(existing, dict) and "projection_report" in existing:
            dropped = True

    payload = {
        "schema_version": SCHEMA_VERSION,
        "subject": args.subject,
        "label": label,
        "applies_to": (
            f"{label} only: from {label}'s recordings; not a population value"
        ),
        "lamina": LAMINA_ID,
        "made_at": datetime.now(timezone.utc).isoformat(),
        **templates,
        "habit": habit,
        "fitness": fitness,
    }
    out_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    if dropped:
        print(
            "projection_report dropped: rerun "
            "tools/backtest_planned_day.py"
        )

    for group_id, entry in templates["groups"].items():
        print(
            f"{group_id}: sessions {entry['sessions']}, minutes "
            f"{entry['minutes']}, ae_mean {_format_number(entry['ae_mean'])}, "
            f"session_ae {_format_session(entry['session_ae'])}, offered "
            f"{entry['offered']}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
