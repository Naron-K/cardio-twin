"""
Plan a day — run a plan through the lamina and answer in the /api/day shape.

A plan names the waking hours, the day's ambient context and resting level,
the steps outside sessions, and up to six sessions.  This module turns that
plan into an ordinary schema-1 day bundle and replays it, so the plan's answer
is the lamina's own arithmetic rather than a second implementation of it.

Nothing here names an attribute id or a workout type: the roles come from the
lamina's ``<plan_view>`` and ``<day_view>`` (through ``plan_options`` and
``kind_groups``), and the kinds' costs come from the subject's own templates.
Nothing is cached and nothing is written to disk.
"""
from __future__ import annotations

from bundles import is_finite_number, load_params, validate_bundle
from day_summary import summarise_bundle
from laminae import load_twin, resolve_lamina
from plan_options import OutOfRange, kind_groups, load_templates, plan_options
from tools.make_activity_templates import hour_rate

#: One row per minute, the bundle grid every replay reads.
DAY_MINUTES = 1440

_ALLOWED_PLAN_KEYS = (
    "subject",
    "awake",
    "ambient",
    "level",
    "count_outside",
    "sessions",
)
_ALLOWED_SESSION_KEYS = ("kind", "start", "minutes", "intensity", "count",
                         "target")


class PlanRefused(ValueError):
    """A plan the options cannot accept, naming the field that was refused."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


def _finite(value, field: str) -> float:
    """A finite number from a plan, refusing bools and non-numbers by field."""
    if not is_finite_number(value):
        raise PlanRefused(field, f"must be a finite number, got {value!r}.")
    return float(value)


def validate_plan(plan: dict, options: dict) -> dict:
    """
    Return a cleaned copy of a plan, or refuse by field and allowed range.

    Every number is checked for being finite (a bool is not a number), every
    range against what this subject's options offer, and the sessions against
    the waking window and each other.  Unknown top-level keys are refused so a
    misspelt field is not silently ignored.
    """
    if not isinstance(plan, dict):
        raise PlanRefused("plan", "must be a JSON object.")

    unknown = [key for key in plan if key not in _ALLOWED_PLAN_KEYS]
    if unknown:
        raise PlanRefused(
            unknown[0],
            f"unknown plan field; allowed: {', '.join(_ALLOWED_PLAN_KEYS)}.",
        )

    subject = plan.get("subject")
    if not isinstance(subject, str) or not subject:
        raise PlanRefused("subject", "must be a non-empty string.")

    awake = plan.get("awake")
    if not isinstance(awake, (list, tuple)) or len(awake) != 2:
        raise PlanRefused("awake", "must be [start, end] in minutes.")
    start_minute, end_minute = awake
    for field, value in (("awake[0]", start_minute), ("awake[1]", end_minute)):
        if isinstance(value, bool) or not isinstance(value, int):
            raise PlanRefused(
                field,
                f"must be an integer minute from 0 to {DAY_MINUTES}, got "
                f"{value!r}.",
            )
    if not (0 <= start_minute < end_minute <= DAY_MINUTES):
        raise PlanRefused(
            "awake",
            f"must satisfy 0 <= start < end <= {DAY_MINUTES}, got "
            f"[{start_minute}, {end_minute}].",
        )

    ambient = _finite(plan.get("ambient"), "ambient")
    level = _finite(plan.get("level"), "level")

    count_outside = _finite(plan.get("count_outside"), "count_outside")
    max_outside = float(options["day"]["count_outside"]["max"])
    if count_outside < 0 or count_outside > max_outside:
        raise PlanRefused(
            "count_outside",
            f"must be from 0 to {max_outside:g}, got {count_outside:g}.",
        )

    raw_sessions = plan.get("sessions")
    if not isinstance(raw_sessions, list):
        raise PlanRefused("sessions", "must be a list of sessions.")
    max_sessions = int(options["limits"]["max_sessions"])
    if len(raw_sessions) > max_sessions:
        raise PlanRefused(
            "sessions",
            f"at most {max_sessions} sessions, got {len(raw_sessions)}.",
        )

    min_minutes, max_minutes = options["limits"]["session_minutes"]
    kinds = {kind["id"]: kind for kind in options["kinds"]}

    sessions: list[dict] = []
    for index, raw in enumerate(raw_sessions):
        where = f"sessions[{index}]"
        if not isinstance(raw, dict):
            raise PlanRefused(where, "must be a JSON object.")

        unknown = [key for key in raw if key not in _ALLOWED_SESSION_KEYS]
        if unknown:
            raise PlanRefused(
                f"{where}.{unknown[0]}",
                f"unknown session field; allowed: "
                f"{', '.join(_ALLOWED_SESSION_KEYS)}.",
            )

        kind_id = raw.get("kind")
        if not isinstance(kind_id, str) or kind_id not in kinds:
            offered = ", ".join(kinds) or "(none)"
            raise PlanRefused(
                f"{where}.kind",
                f"unknown kind {kind_id!r}; offered: {offered}.",
            )
        kind = kinds[kind_id]

        start = raw.get("start")
        if isinstance(start, bool) or not isinstance(start, int):
            raise PlanRefused(
                f"{where}.start",
                f"must be an integer minute from {start_minute} to "
                f"{end_minute - 1}, got {start!r}.",
            )
        if start < start_minute or start >= end_minute:
            raise PlanRefused(
                f"{where}.start",
                f"must be from {start_minute} to {end_minute - 1} (inside the "
                f"awake hours {start_minute}..{end_minute}), got {start}.",
            )

        minutes = raw.get("minutes")
        if isinstance(minutes, bool) or not isinstance(minutes, int):
            raise PlanRefused(
                f"{where}.minutes",
                f"must be an integer from {min_minutes} to {max_minutes}, got "
                f"{minutes!r}.",
            )
        if minutes < min_minutes or minutes > max_minutes:
            raise PlanRefused(
                f"{where}.minutes",
                f"must be from {min_minutes} to {max_minutes}, got {minutes}.",
            )
        if start + minutes > end_minute:
            raise PlanRefused(
                f"{where}.minutes",
                f"{minutes} minutes from {start} ends at {start + minutes}, "
                f"after the awake end {end_minute}; at most "
                f"{end_minute - start} minutes fit.",
            )

        p10 = float(kind["intensity"]["p10"])
        p90 = float(kind["intensity"]["p90"])
        intensity = raw.get("intensity")
        if not is_finite_number(intensity):
            raise PlanRefused(
                f"{where}.intensity",
                f"must be a finite number from {p10:g} to {p90:g}, got "
                f"{intensity!r}.",
            )
        intensity = float(intensity)
        if intensity < p10 - 1e-6 or intensity > p90 + 1e-6:
            raise PlanRefused(
                f"{where}.intensity",
                f"must be from {p10:g} to {p90:g}, got {intensity:g}.",
            )

        max_count = float(kind["steps_per_min"]) * 180 * 1.5
        count = raw.get("count")
        if not is_finite_number(count):
            raise PlanRefused(
                f"{where}.count",
                f"must be a finite number from 0 to {max_count:g}, got "
                f"{count!r}.",
            )
        count = float(count)
        if count < 0 or count > max_count:
            raise PlanRefused(
                f"{where}.count",
                f"must be from 0 to {max_count:g}, got {count:g}.",
            )

        target = raw.get("target")
        if target is not None:
            target = _finite(target, f"{where}.target")

        sessions.append({
            "kind": kind_id,
            "start": start,
            "minutes": minutes,
            "intensity": intensity,
            "count": count,
            "target": target,
        })

    ordered = sorted(
        range(len(sessions)), key=lambda i: sessions[i]["start"]
    )
    for previous_index, index in zip(ordered, ordered[1:]):
        previous = sessions[previous_index]
        current = sessions[index]
        if current["start"] < previous["start"] + previous["minutes"]:
            raise PlanRefused(
                f"sessions[{index}].start",
                f"overlaps the session at {previous['start']} for "
                f"{previous['minutes']} minutes; start at or after "
                f"{previous['start'] + previous['minutes']}.",
            )

    return {
        "subject": subject,
        "awake": [start_minute, end_minute],
        "ambient": ambient,
        "level": level,
        "count_outside": count_outside,
        "sessions": sessions,
    }


def _representative_workout(templates: dict, groups: dict) -> dict[str, str]:
    """
    Group id -> the recorded workout label with the most minutes behind it.

    A planned session has to carry a recorded label for the lamina's event
    indicators to colour it.  The label with the most minutes is the one this
    person's templates describe best; a tie breaks alphabetically so the
    choice is deterministic.
    """
    workouts = templates.get("workouts") or {}
    chosen: dict[str, str] = {}
    for group_id, spec in groups.items():
        candidates = sorted(
            label for label in spec["workouts"] if label in workouts
        )
        if candidates:
            chosen[group_id] = max(
                candidates, key=lambda label: workouts[label]["minutes"]
            )
    return chosen


def build_planned_bundle(plan: dict, templates: dict, groups: dict) -> dict:
    """
    A schema-1 day bundle drawn from a plan.

    Inside a session the intensity and steps are the plan's; outside, energy
    is the template's hourly mean and the planned steps are spread over the
    waking hours in proportion to the template's hourly step rate.  Outside
    the waking hours nothing is recorded, as on a real night.  No measured
    value exists anywhere, which is what makes this a plan rather than a day.
    """
    subject = plan["subject"]
    ambient = float(plan["ambient"])
    level = float(plan["level"])
    count_outside = float(plan["count_outside"])
    start_minute, end_minute = (int(value) for value in plan["awake"])
    if not 0 <= start_minute < end_minute <= DAY_MINUTES:
        raise ValueError(
            f"awake must satisfy 0 <= start < end <= {DAY_MINUTES}, got "
            f"[{start_minute}, {end_minute}]."
        )

    representative = _representative_workout(templates, groups)

    ae: list[float | None] = [None] * DAY_MINUTES
    steps: list[float | None] = [None] * DAY_MINUTES
    workout: list[str | None] = [None] * DAY_MINUTES

    for session in plan["sessions"]:
        start = int(session["start"])
        minutes = int(session["minutes"])
        end = start + minutes
        if start < 0 or end > DAY_MINUTES:
            raise ValueError(
                f"session {session['kind']!r} at {start} for {minutes} minutes "
                f"does not fit inside a {DAY_MINUTES}-minute day."
            )
        rate = float(session["intensity"])
        per_minute = float(session["count"]) / minutes
        label = representative.get(session["kind"])
        for minute in range(start, end):
            ae[minute] = rate
            steps[minute] = per_minute
            workout[minute] = label

    outside: list[int] = [
        minute
        for minute in range(start_minute, end_minute)
        if workout[minute] is None
    ]
    weights: list[float] = []
    for minute in outside:
        hourly_ae, hourly_steps = hour_rate(templates, minute // 60)
        ae[minute] = hourly_ae
        weights.append(hourly_steps)

    if outside:
        total_weight = float(sum(weights))
        if total_weight > 0.0:
            for minute, weight in zip(outside, weights):
                steps[minute] = count_outside * weight / total_weight
        else:
            uniform = count_outside / len(outside)
            for minute in outside:
                steps[minute] = uniform

    samples = [
        {
            "t": 60 * minute,
            "hr": None,
            "hr_n": 0,
            "ae_kcal_min": ae[minute],
            "be_kcal_min": None,
            "steps_min": steps[minute],
            "t_app_c": ambient,
            "rh_pct": None,
            "workout": workout[minute],
        }
        for minute in range(DAY_MINUTES)
    ]

    bundle = {
        "schema_version": 1,
        "subject": subject,
        "date": "2000-01-01",
        "timezone": "UTC",
        "grid_s": 60,
        "synthetic": True,
        "samples": samples,
        "day": {
            "hr_level_rts": level,
            "n_minutes": DAY_MINUTES,
            "minutes_with_hr": 0,
            "coverage_hr_min_frac": 0.0,
            "coverage_hr_hours": 0,
            "dense_minutes": 0,
            "basal_source": "synthetic",
        },
    }
    validate_bundle(bundle, label=f"planned day for {subject}")
    return bundle


def planned_day(lamina_id: str, plan: dict) -> dict:
    """
    Run one plan through the lamina and return it in the /api/day shape.

    The options are built from the plan's own level and ambient, so the settle
    targets the response carries are the ones this plan asks of the model.
    The result is the recorded day's shape plus ``planned``, the projection
    error, the limit lines, and per-session settings beside what was reached.
    """
    if not isinstance(plan, dict):
        raise PlanRefused("plan", f"must be a JSON object, got {type(plan).__name__}.")
    for key in ("subject", "level", "ambient"):
        if key not in plan:
            raise PlanRefused(key, "is required.")
    if not isinstance(plan["subject"], str):
        raise PlanRefused("subject", f"must be a string, got {plan['subject']!r}.")
    try:
        options = plan_options(
            lamina_id,
            plan["subject"],
            level=plan["level"],
            ambient=plan["ambient"],
        )
    except OutOfRange as exc:
        # A level or temperature outside the subject's range is a refused
        # field like any other, so the editor can show it under its slider.
        raise PlanRefused(exc.field, str(exc)) from exc
    cleaned = validate_plan(plan, options)
    subject = cleaned["subject"]

    templates = load_templates(subject)
    if templates is None:
        raise ValueError(
            f"Subject '{subject}' has no activity templates to plan from."
        )
    groups = kind_groups(load_twin(resolve_lamina(lamina_id)))
    bundle = build_planned_bundle(cleaned, templates, groups)

    params = load_params(subject)
    result = summarise_bundle(
        lamina_id,
        bundle,
        params,
        options["subject_label"],
        planned=True,
    )

    projection = options["projection_error"]
    result["planned"] = True
    result["projection_error"] = projection
    result["limits_text"] = options["limits_text"]
    result["summary"] = None

    kind_labels = {kind["id"]: kind["label"] for kind in options["kinds"]}
    by_start = {spec["start"]: spec for spec in cleaned["sessions"]}
    modelled = result["pair"]["modelled"]
    for session in result["sessions"]:
        spec = by_start.get(session["start"])
        if spec is None:
            continue
        label = kind_labels[spec["kind"]]
        session["label"] = label
        session["group_label"] = label
        session["group"] = spec["kind"]
        session["target_set"] = spec["target"]
        session["intensity_set"] = spec["intensity"]
        session["count_set"] = spec["count"]
        run = [
            value
            for value in modelled[session["start"]:session["end"]]
            if value is not None
        ]
        session["peak_modelled"] = max(run) if run else None

    if projection is not None:
        result["model"]["sd"] = projection["hr_mae"]
        result["model"]["sd_source"] = "projection"

    roles = options["roles"]
    intensity_id = roles["intensity"]["attribute"]
    count_id = roles["count"]["attribute"]
    rates = {entry["attribute"]: entry for entry in result["rates"]}
    previous = {entry["key"]: entry for entry in result["kpis"]}

    intensity_rate = rates.get(intensity_id)
    intensity_kpi = previous.get(intensity_id)
    energy_unit = intensity_rate["unit"] if intensity_rate else ""
    energy_label = (
        intensity_rate["label"] if intensity_rate else "Active energy"
    )
    if projection is not None:
        mae = projection["energy_mae"]
        energy_note = (
            f"± {mae:g} {energy_unit}".strip()
            if energy_unit
            else f"± {mae:g}"
        )
    else:
        energy_note = ""

    count_rate = rates.get(count_id)
    count_kpi = previous.get(count_id)
    steps_label = count_rate["label"] if count_rate else "Steps"
    steps_unit = count_rate["unit"] if count_rate else ""

    total_session_minutes = sum(item["minutes"] for item in result["sessions"])

    peak_index = None
    peak_value = None
    for index, value in enumerate(modelled):
        if value is not None and (peak_value is None or value > peak_value):
            peak_value = value
            peak_index = index
    peak_note = (
        f"at {peak_index // 60:02d}:{peak_index % 60:02d}"
        if peak_index is not None
        else ""
    )

    result["kpis"] = [
        {
            "key": intensity_id,
            "label": energy_label,
            "value": intensity_kpi["value"] if intensity_kpi else None,
            "unit": energy_unit,
            "note": energy_note,
        },
        {
            "key": count_id,
            "label": steps_label,
            "value": count_kpi["value"] if count_kpi else None,
            "unit": steps_unit,
            "note": "as set",
        },
        {
            "key": "sessions",
            "label": "In sessions",
            "value": total_session_minutes,
            "unit": "min",
            "note": f"{len(result['sessions'])} sessions",
        },
        {
            "key": "peak_modelled",
            "label": "Highest heart rate",
            "value": peak_value,
            "unit": result["pair"]["unit"],
            "note": peak_note,
        },
    ]
    return result
