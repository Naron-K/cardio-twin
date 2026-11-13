"""
Derive five wearable-lamina scenario presets from one subject's day bundles.

The presets are proxies, not labelled states.  Each one summarises the minutes
of a recorded day that a pre-registered rule selects, and writes one XML file
in the same shape as ``presets/normal.xml``.  The rules below were fixed before
any code was written; they are not tuned per subject.

PRE-REGISTERED PROXY RULES
==========================

Only minutes with a non-null AE_rate count.  Null steps count as zero.  The
rules are applied top to bottom and a minute takes the first state it qualifies
for:

  walk       workout label "Walking".
  vigorous   workout label in {"Running", "HighIntensityIntervalTraining",
             "StairClimbing", "Elliptical", "Cycling"}.
  (any other workout label: the minute is excluded)
  sleep      no workout, hour_local < 6, steps 0, and hr null or
             hr <= that day's hr_level_rts.
  desk_work  no workout, Monday-Friday, 9 <= hour_local < 17, steps <= 10.
  rest_awake no workout, 7 <= hour_local < 23, AE_rate <= 0.5, steps <= 5.

Labels and order: Sleep 1, Rest (awake) 2, Desk work 3, Walk 4, Vigorous 5.
Medians are rounded to 2 dp for AE_rate, 0 dp for step_rate and 1 dp for
hour_local.

CAVEATS
=======

Caveats are computed from the data, never typed in as facts:

  * fewer than 1000 qualifying minutes: "Only <n> minutes qualify, so this
    median is weak."
  * sleep's AE median at least rest_awake's: "Median activity here is not lower
    than awake rest, so these minutes are probably not sleep: the watch is
    rarely worn at night."
  * any two states whose AE medians differ by less than 0.1 kcal/min and whose
    step medians are equal: on each, "Indistinguishable from <other label> in
    this data."

Run from the repository root:

    python backend/tools/make_presets.py --bundle-dir DIR --subject s2

or from backend/:

    python tools/make_presets.py --bundle-dir DIR --subject s2

The output directory must be named ``wearable`` so a typo cannot overwrite the
patient presets in ``presets/``.
"""
from __future__ import annotations

import argparse
import math
import sys
from datetime import date as _date
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tools.fit_hr_model import day_inputs, load_days  # noqa: E402

# ── Pre-registered proxy definitions (do not tune per subject) ───────────────

STATE_ORDER = ("sleep", "rest_awake", "desk_work", "walk", "vigorous")

STATE_LABELS = {
    "sleep": "Sleep",
    "rest_awake": "Rest (awake)",
    "desk_work": "Desk work",
    "walk": "Walk",
    "vigorous": "Vigorous",
}

STATE_ORDERS = {
    "sleep": 1,
    "rest_awake": 2,
    "desk_work": 3,
    "walk": 4,
    "vigorous": 5,
}

RULE_TEXT = {
    "sleep": (
        "there is no workout, the local hour is before 6, steps are zero and "
        "heart rate is missing or no higher than the day's resting level"
    ),
    "rest_awake": (
        "there is no workout, the local hour is from 7 to before 23, activity "
        "is at most 0.5 kcal/min and steps are at most 5"
    ),
    "desk_work": (
        "there is no workout, it is a Monday-to-Friday working hour from 9 to "
        "before 17, and steps are at most 10"
    ),
    "walk": "the workout label is Walking",
    "vigorous": (
        "the workout label is one of Running, "
        "HighIntensityIntervalTraining, StairClimbing, Elliptical or Cycling"
    ),
}

WALK_LABEL = "Walking"
VIGOROUS_LABELS = frozenset({
    "Running",
    "HighIntensityIntervalTraining",
    "StairClimbing",
    "Elliptical",
    "Cycling",
})

SLEEP_HOUR_END = 6.0

DESK_WEEKDAY_MAX = 4  # Monday = 0, Friday = 4
DESK_HOUR_START = 9.0
DESK_HOUR_END = 17.0
DESK_MAX_STEPS = 10.0

REST_HOUR_START = 7.0
REST_HOUR_END = 23.0
REST_AE_MAX = 0.5
REST_MAX_STEPS = 5.0

WEAK_MINUTES = 1000
INDISTINGUISHABLE_AE = 0.1

AE_DECIMALS = 2
STEP_DECIMALS = 0
HOUR_DECIMALS = 1


def classify_minutes(
    days: list[dict],
) -> dict[str, list[tuple[float, float, float]]]:
    """Return state -> [(AE_rate, step_rate, hour_local)] for qualifying minutes."""
    if not days:
        raise ValueError(
            "No day bundles were supplied, so no minute can be classified. "
            "Point --bundle-dir at a folder holding <subject>/<date>.json."
        )

    states: dict[str, list[tuple[float, float, float]]] = {
        name: [] for name in STATE_ORDER
    }

    for bundle in days:
        inputs = day_inputs(bundle)
        samples = bundle["samples"]
        hour = inputs["hour_local"]
        ae_rate = inputs["AE_rate"]
        hr = inputs["hr"]
        labels = inputs["workout"]
        weekday = _date.fromisoformat(bundle["date"]).weekday()
        # A day the pipeline gave no level: a minute WITH a heart rate cannot
        # be shown to sit at or below it, so it cannot qualify as sleep; a
        # minute without one still can, by the same rule as any other day.
        raw_level = bundle["day"].get("hr_level_rts")
        hr_level = None if raw_level is None else float(raw_level)

        n = len(samples)
        if not (
            hour.size == ae_rate.size == hr.size == labels.size == n
        ):
            raise ValueError(
                f"{bundle['date']}: replay produced {hour.size} rows but the "
                f"bundle declares {n} samples."
            )

        for index in range(n):
            ae_value = float(ae_rate[index])
            if not math.isfinite(ae_value):
                continue

            hour_value = float(hour[index])
            if not math.isfinite(hour_value):
                continue

            raw_steps = samples[index].get("steps_min")
            steps = 0.0 if raw_steps is None else float(raw_steps)
            if not math.isfinite(steps):
                continue

            label = labels[index]
            hr_value = float(hr[index])
            hr_missing = not math.isfinite(hr_value)

            if label == WALK_LABEL:
                state = "walk"
            elif label in VIGOROUS_LABELS:
                state = "vigorous"
            elif label is not None:
                continue
            elif (
                hour_value < SLEEP_HOUR_END
                and steps == 0.0
                and (hr_missing or (hr_level is not None and hr_value <= hr_level))
            ):
                state = "sleep"
            elif (
                weekday <= DESK_WEEKDAY_MAX
                and DESK_HOUR_START <= hour_value < DESK_HOUR_END
                and steps <= DESK_MAX_STEPS
            ):
                state = "desk_work"
            elif (
                REST_HOUR_START <= hour_value < REST_HOUR_END
                and ae_value <= REST_AE_MAX
                and steps <= REST_MAX_STEPS
            ):
                state = "rest_awake"
            else:
                continue

            states[state].append((ae_value, steps, hour_value))

    return states


def summarise(states: dict, days: list[dict]) -> list[dict]:
    """Return one summary dict per state, in the pre-registered order."""
    if not days:
        raise ValueError(
            "No day bundles were supplied, so no preset can be summarised. "
            "Point --bundle-dir at a folder holding <subject>/<date>.json."
        )

    n_days_by_state: dict[str, set[str]] = {
        name: set() for name in STATE_ORDER
    }
    for bundle in days:
        per_day = classify_minutes([bundle])
        for name in STATE_ORDER:
            if per_day[name]:
                n_days_by_state[name].add(bundle["date"])

    first_date = days[0]["date"]
    last_date = days[-1]["date"]

    # The subject's resting level travels with every preset.  A scenario that
    # took the fitted offset (relative to THIS person's level) but left
    # HR_level at the lamina's default would rest 15 bpm below them: measured
    # for s2, 61.6 bpm against a daily level near 77.
    levels = [
        float(bundle["day"]["hr_level_rts"])
        for bundle in days
        if bundle["day"].get("hr_level_rts") is not None
    ]
    hr_level = round(float(np.median(levels)), HOUR_DECIMALS) if levels else None
    if hr_level is not None and not math.isfinite(hr_level):
        raise ValueError(
            f"median resting level is not finite ({hr_level!r}); check the "
            f"bundles' day.hr_level_rts values."
        )

    summaries: list[dict] = []
    for name in STATE_ORDER:
        entries = states.get(name, [])
        if not entries:
            raise ValueError(
                f"no minutes qualify for {name} under rule {RULE_TEXT[name]}. "
                f"Add days that contain this state, or check the bundle's "
                f"workout labels, steps and clock."
            )

        aes = [entry[0] for entry in entries]
        steps = [entry[1] for entry in entries]
        hours = [entry[2] for entry in entries]
        ae = round(float(np.median(aes)), AE_DECIMALS)
        step = round(float(np.median(steps)), STEP_DECIMALS)
        hour = round(float(np.median(hours)), HOUR_DECIMALS)

        if not all(math.isfinite(value) for value in (ae, step, hour)):
            raise ValueError(
                f"median for {name} is not finite "
                f"(AE_rate={ae!r}, step_rate={step!r}, hour_local={hour!r}). "
                f"Check the bundles for corrupt numeric values."
            )

        summaries.append({
            "name": name,
            "label": STATE_LABELS[name],
            "order": STATE_ORDERS[name],
            "n_minutes": len(entries),
            "n_days": len(n_days_by_state[name]),
            "ae": ae,
            "steps": step,
            "hour": hour,
            "hr_level": hr_level,
            "n_level_days": len(levels),
            "caveats": [],
            "first_date": first_date,
            "last_date": last_date,
        })

    by_name = {summary["name"]: summary for summary in summaries}

    for summary in summaries:
        caveats: list[str] = []

        if summary["n_minutes"] < WEAK_MINUTES:
            caveats.append(
                f"Only {summary['n_minutes']} minutes qualify, so this median "
                f"is weak."
            )

        if (
            summary["name"] == "sleep"
            and summary["ae"] >= by_name["rest_awake"]["ae"]
        ):
            caveats.append(
                "Median activity here is not lower than awake rest, so these "
                "minutes are probably not sleep: the watch is rarely worn at "
                "night."
            )

        for other in summaries:
            if other["name"] == summary["name"]:
                continue
            if (
                abs(summary["ae"] - other["ae"]) < INDISTINGUISHABLE_AE
                and summary["steps"] == other["steps"]
            ):
                caveats.append(
                    f"Indistinguishable from {other['label']} in this data."
                )

        summary["caveats"] = caveats

    return summaries


def _format_number(value: float, decimals: int) -> str:
    return f"{float(value):.{decimals}f}"


def write_presets(
    summaries: list[dict], subject: str, out_dir: Path
) -> list[Path]:
    """Write one preset XML per summary and return the paths written."""
    out_dir = Path(out_dir)
    if out_dir.name != "wearable":
        raise ValueError(
            f"Refusing to write presets to {out_dir}: --out must be a "
            f"directory named 'wearable' (for example presets/wearable) so "
            f"the patient presets in presets/ are not overwritten."
        )

    for summary in summaries:
        for key in ("ae", "steps", "hour"):
            if not math.isfinite(float(summary[key])):
                raise ValueError(
                    f"refusing to write {summary['name']}.xml: median "
                    f"'{key}' is not finite ({summary[key]!r})."
                )

    out_dir.mkdir(parents=True, exist_ok=True)

    paths: list[Path] = []
    for summary in sorted(summaries, key=lambda item: item["order"]):
        description = (
            f"{subject}'s median over {summary['n_minutes']} minutes on "
            f"{summary['n_days']} days ({summary['first_date']} to "
            f"{summary['last_date']}) where {RULE_TEXT[summary['name']]}. "
            f"A proxy for {summary['label']}, not a labelled state."
        )
        if summary.get("hr_level") is not None:
            description += (
                f" The resting level, {summary['hr_level']} bpm, is the median "
                f"of the pipeline's daily level over {summary['n_level_days']} "
                f"days."
            )
        if summary["caveats"]:
            description = " ".join([description, *summary["caveats"]])

        root = ET.Element("patient")
        metadata = ET.SubElement(root, "metadata")
        ET.SubElement(metadata, "name").text = str(summary["label"])
        ET.SubElement(metadata, "lamina").text = "lamina_wearable"
        ET.SubElement(metadata, "subject").text = str(subject)
        ET.SubElement(metadata, "order").text = str(summary["order"])
        ET.SubElement(metadata, "description").text = description

        sensor_data = ET.SubElement(root, "sensor_data")
        ET.SubElement(sensor_data, "AE_rate").text = _format_number(
            summary["ae"], AE_DECIMALS
        )
        ET.SubElement(sensor_data, "step_rate").text = _format_number(
            summary["steps"], STEP_DECIMALS
        )
        ET.SubElement(sensor_data, "hour_local").text = _format_number(
            summary["hour"], HOUR_DECIMALS
        )
        if summary.get("hr_level") is not None:
            ET.SubElement(sensor_data, "HR_level").text = _format_number(
                summary["hr_level"], HOUR_DECIMALS
            )

        ET.indent(root, space="  ")
        text = ET.tostring(root, encoding="unicode", xml_declaration=True)

        path = out_dir / f"{summary['name']}.xml"
        path.write_text(text + "\n", encoding="utf-8", newline="\n")
        paths.append(path)

    return paths


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive wearable-lamina scenario presets from day bundles."
    )
    parser.add_argument(
        "--bundle-dir", required=True,
        help="Directory holding <subject>/<date>.json bundles.",
    )
    parser.add_argument(
        "--subject", required=True, help="Subject folder name to summarise.",
    )
    parser.add_argument(
        "--out", default="presets/wearable",
        help="Output directory; its last path component must be 'wearable'.",
    )
    args = parser.parse_args(argv)

    days = load_days(Path(args.bundle_dir), args.subject)
    states = classify_minutes(days)
    summaries = summarise(states, days)
    write_presets(summaries, args.subject, Path(args.out))

    for summary in summaries:
        print(
            f"{summary['name']}: {summary['n_minutes']} minutes on "
            f"{summary['n_days']} days, AE_rate {summary['ae']:.2f} kcal/min, "
            f"step_rate {summary['steps']:.0f} steps/min, "
            f"hour_local {summary['hour']:.1f} h"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
