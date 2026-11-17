"""
Plan options — everything the "Plan a day" editor draws.

A lamina's optional ``<plan_view>`` block names the roles a plan screen
reads: the session's intensity, where the model settles under it, the count
it accumulates, the ambient context, the person's baseline level and the
clock.  A ``<day_view>`` block names the kinds of session.  A subject's
``templates.json`` says what those kinds cost, how the quiet hours look, the
awake window, and the ranges the resting level and apparent temperature
covered in that person's recordings.

Nothing here names an attribute id or a workout type of its own.  The roles
come from the lamina, the kinds from its day view, and every number about the
person from their own templates.  The settle table is computed by running the
lamina itself, one pass per (hour, intensity) point, so the editor draws the
model's own answer rather than a second implementation of its arithmetic.

The result is cached on the lamina, the subject, the requested level and
ambient, and both source files' modification times: editing either file on
disk makes the next request recompute.
"""
from __future__ import annotations

import contextlib
import functools
import json
import math
from datetime import date
from pathlib import Path

import universal_twin
from bundles import (
    bundle_roots,
    is_finite_number,
    load_params,
    read_subject_label,
)
from laminae import load_twin, resolve_lamina
from signal_source import _validated_coefficient_overrides
from universal_twin import parse_replay_field

#: How many intensity points the settle table is sampled at, inclusive ends.
SETTLE_POINTS = 21
#: Points either side of the templates level median to offer.
LEVEL_SPAN = 10.0
#: Step the outside-session count axis is rounded to.
COUNT_STEP = 100

_REQUIRED_TEMPLATE_KEYS = (
    "groups",
    "level",
    "t_app",
    "awake",
    "steps_outside",
)


class NoPlanView(ValueError):
    """A lamina declares no ``<plan_view>``, so there is no plan to draw."""

    def __init__(self, lamina_id: str) -> None:
        self.lamina_id = lamina_id
        super().__init__(
            f"Lamina '{lamina_id}' declares no <plan_view>, so there is no "
            f"plan screen to draw. Add a <plan_view> block to that lamina."
        )


class UnknownSubject(ValueError):
    """A request named a subject that has no templates to plan from."""

    def __init__(self, subject: str, available: list[str]) -> None:
        self.subject = subject
        self.available = list(available)
        listing = ", ".join(self.available) or "(none)"
        super().__init__(
            f"Unknown subject '{subject}' for planning. Subjects with "
            f"templates.json: {listing}."
        )


class NoTemplates(ValueError):
    """A known subject has no ``templates.json`` beside their bundles."""

    def __init__(self, subject: str) -> None:
        self.subject = subject
        super().__init__(
            f"Subject '{subject}' has no templates.json, so there are no "
            f"activity templates to plan a day from. Run "
            f"tools/make_activity_templates.py for that subject."
        )


def kind_groups(twin) -> dict[str, dict]:
    """
    The lamina's workout groups: group id -> indicator, label and labels.

    Each <event> in the lamina's <day_view> names an indicator whose
    replay_field is a membership field.  Its labels are the workouts in that
    group.  A lamina without a day view, or an indicator without a membership
    field, is refused by name rather than producing empty groups.
    """
    day_view = getattr(twin, "day_view", None)
    if not day_view:
        raise ValueError(
            f"Lamina {twin.lamina_id} declares no <day_view>, so its workout "
            f"groups cannot be read. Add a <day_view> block with one <event> "
            f"per group."
        )

    groups: dict[str, dict] = {}
    for event in day_view["events"]:
        indicator = event["indicator"]
        group_id = event["group"]
        attr = twin.attributes.get(indicator)
        field = None if attr is None else attr.replay_field
        if field is None:
            raise ValueError(
                f"Lamina {twin.lamina_id}: indicator '{indicator}' for group "
                f"'{group_id}' declares no replay_field. An event indicator "
                f"must read a membership field 'sample.<field> in A, B'."
            )
        _path, labels = parse_replay_field(field)
        if labels is None:
            raise ValueError(
                f"Lamina {twin.lamina_id}: indicator '{indicator}' for group "
                f"'{group_id}' has replay_field '{field}', which is not a "
                f"membership field. Use 'sample.<field> in A, B'."
            )
        groups[group_id] = {
            "indicator": indicator,
            "label": event["label"],
            "workouts": sorted(labels),
        }
    return groups


def _templates_path(subject: str) -> Path | None:
    """The subject's templates.json path, or None when the subject is absent."""
    directory = bundle_roots().get(subject)
    if directory is None:
        return None
    return directory / "templates.json"


def _finite_field(mapping: dict, key: str, path: Path, where: str) -> float:
    """One finite number from a templates mapping, refused by file and key."""
    if key not in mapping:
        raise ValueError(
            f"{path}: templates {where} is missing required field '{key}'."
        )
    value = mapping[key]
    if not is_finite_number(value):
        raise ValueError(
            f"{path}: templates {where}['{key}']={value!r} is not a finite "
            f"number."
        )
    return float(value)


def _habit_block(data: dict, path: Path) -> None:
    """Validate templates['habit'] when an upgraded file carries one."""
    if "habit" not in data or data["habit"] is None:
        return
    habit = data["habit"]
    if not isinstance(habit, dict):
        raise ValueError(
            f"{path}: templates['habit'] must be a JSON object or null, got "
            f"{type(habit).__name__}."
        )
    weeks = _finite_field(habit, "weeks", path, "habit")
    if weeks < 0.0 or weeks != int(weeks):
        raise ValueError(
            f"{path}: templates habit['weeks']={weeks!r} must be a "
            f"non-negative integer."
        )
    for key in ("unit", "first_week", "last_week", "rule"):
        value = habit.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(
                f"{path}: templates habit['{key}']={value!r} must be a "
                f"non-empty string."
            )
    for block in ("total", "in_sessions", "outside_sessions_per_day"):
        entry = habit.get(block)
        if not isinstance(entry, dict):
            raise ValueError(
                f"{path}: templates habit['{block}'] must be a JSON object, "
                f"got {type(entry).__name__}."
            )
        for key in ("p10", "p50", "p90"):
            value = _finite_field(entry, key, path, f"habit {block}")
            if value < 0.0:
                raise ValueError(
                    f"{path}: templates habit {block}['{key}']={value:g} "
                    f"must not be negative."
                )


def _fitness_block(data: dict, path: Path) -> None:
    """Validate templates['fitness'] when a file built from recordings has it."""
    if "fitness" not in data or data["fitness"] is None:
        return
    fitness = data["fitness"]
    if not isinstance(fitness, dict):
        raise ValueError(
            f"{path}: templates['fitness'] must be a JSON object or null, got "
            f"{type(fitness).__name__}."
        )
    period = fitness.get("period")
    if (
        not isinstance(period, list)
        or len(period) != 2
        or not all(isinstance(item, str) and item for item in period)
    ):
        raise ValueError(
            f"{path}: templates fitness['period'] must be a [first, last] "
            f"list of YYYY-MM-DD strings, got {period!r}."
        )
    try:
        first = date.fromisoformat(period[0])
        last = date.fromisoformat(period[1])
    except ValueError as exc:
        raise ValueError(
            f"{path}: templates fitness['period'] must be YYYY-MM-DD dates, "
            f"got {period!r}."
        ) from exc
    if first > last:
        raise ValueError(
            f"{path}: templates fitness['period'] starts {period[0]} after "
            f"it ends {period[1]}."
        )
    rule = fitness.get("rule")
    if not isinstance(rule, str) or not rule:
        raise ValueError(
            f"{path}: templates fitness['rule']={rule!r} must be a non-empty "
            f"string."
        )
    values = fitness.get("values")
    if not isinstance(values, dict):
        raise ValueError(
            f"{path}: templates fitness['values'] must be a JSON object, got "
            f"{type(values).__name__}."
        )
    for key, entry in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError(
                f"{path}: templates fitness['values'] keys must be non-empty "
                f"strings, got {key!r}."
            )
        if not isinstance(entry, dict):
            raise ValueError(
                f"{path}: templates fitness values['{key}'] must be a JSON "
                f"object, got {type(entry).__name__}."
            )
        where = f"fitness values['{key}']"
        median = _finite_field(entry, "median", path, where)
        p10 = _finite_field(entry, "p10", path, where)
        p90 = _finite_field(entry, "p90", path, where)
        days = _finite_field(entry, "days", path, where)
        if days < 3.0 or days != int(days):
            raise ValueError(
                f"{path}: templates {where}['days']={days:g} must be an "
                f"integer of at least 3."
            )
        if not p10 <= median <= p90:
            raise ValueError(
                f"{path}: templates {where} has p10={p10:g}, median={median:g}, "
                f"p90={p90:g}; p10 <= median <= p90 is required."
            )
        unit = entry.get("unit")
        if not isinstance(unit, str) or not unit:
            raise ValueError(
                f"{path}: templates {where}['unit']={unit!r} must be a "
                f"non-empty string."
            )


def load_templates(subject: str) -> dict | None:
    """
    Read and shape-check a subject's ``templates.json``, when it exists.

    None means the subject has no templates file.  A file that is not a JSON
    object with the keys the plan editor reads is refused by path and key, so
    a typo surfaces here rather than as a missing number on screen.
    """
    path = _templates_path(subject)
    if path is None or not path.is_file():
        return None

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"{path}: cannot read templates: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ValueError(f"{path}: invalid JSON in templates: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"{path}: templates must be a JSON object with "
            f"{', '.join(_REQUIRED_TEMPLATE_KEYS)}, got "
            f"{type(data).__name__}."
        )
    missing = [key for key in _REQUIRED_TEMPLATE_KEYS if key not in data]
    if missing:
        raise ValueError(
            f"{path}: templates is missing required field(s): "
            f"{', '.join(missing)}."
        )
    for key in _REQUIRED_TEMPLATE_KEYS:
        if not isinstance(data[key], dict):
            raise ValueError(
                f"{path}: templates['{key}'] must be a JSON object, got "
                f"{type(data[key]).__name__}."
            )

    _finite_field(data["level"], "median", path, "level")
    for key in ("p5", "p50", "p95"):
        _finite_field(data["t_app"], key, path, "t_app")
    for key in ("p10", "p50", "p90"):
        _finite_field(data["steps_outside"], key, path, "steps_outside")
    for key in ("start", "end"):
        _finite_field(data["awake"], key, path, "awake")

    _habit_block(data, path)
    _fitness_block(data, path)

    for group_id, entry in data["groups"].items():
        if not isinstance(group_id, str) or not isinstance(entry, dict):
            raise ValueError(
                f"{path}: templates['groups'] must map group ids to JSON "
                f"objects, got {group_id!r}: {type(entry).__name__}."
            )
    return data


def _subjects_with_templates() -> list[str]:
    """Subjects that can be planned, in bundle_roots order."""
    return [
        subject
        for subject, directory in bundle_roots().items()
        if (directory / "templates.json").is_file()
    ]


def _sample(values: list[float]) -> None:
    """Validate a settle table's intensity points before running the twin."""
    if not values:
        raise ValueError(
            "The settle table needs at least one intensity point, got none."
        )
    for value in values:
        if not is_finite_number(value):
            raise ValueError(
                f"Intensity point {value!r} is not a finite number; the "
                f"settle table needs finite intensity values."
            )


@contextlib.contextmanager
def _quiet():
    """
    Silence the twin's per-pass echo while the settle table runs.

    ``_log`` appends every pass to the in-memory computation log and echoes
    it to stdout when ``_ECHO_LOG`` is set.  Hundreds of passes are expected
    here, so the echo is switched off and restored afterwards; the log is
    still rebuilt by every ``compute_all`` call.
    """
    previous = universal_twin._ECHO_LOG
    universal_twin._ECHO_LOG = False
    try:
        yield
    finally:
        universal_twin._ECHO_LOG = previous


def settle_table(
    twin,
    coefficients: dict,
    kind: dict,
    intensity_points: list[float],
    level: float,
    ambient: float,
) -> dict:
    """
    Where the lamina settles at every clock hour and intensity point.

    Every SENSOR is set for the plan: an observed measurement is cleared (a
    plan has no recording to offer), a coefficient takes the subject's fitted
    value when present and its declared starting value otherwise, and every
    other input takes its declared starting value.  The kind's indicator is
    set and every other event indicator cleared, the level and ambient roles
    are set to the request, and the clock and intensity roles are stepped
    through the table.  Each point is one full ``compute_all`` pass, and the
    settles attribute is read from the lamina's own result.
    """
    plan_view = getattr(twin, "plan_view", None)
    if not plan_view:
        raise NoPlanView(twin.lamina_id)
    day_view = getattr(twin, "day_view", None)
    if not day_view:
        raise ValueError(
            f"Lamina {twin.lamina_id} declares no <day_view>, so the kinds "
            f"of session cannot be set for a settle table."
        )
    indicator = kind.get("indicator") if isinstance(kind, dict) else None
    if not isinstance(indicator, str):
        raise ValueError(
            f"kind must carry an 'indicator' (as kind_groups returns), got "
            f"{kind!r}."
        )

    _sample(intensity_points)
    for name, value in (("level", level), ("ambient", ambient)):
        if not is_finite_number(value):
            raise ValueError(
                f"{name}={value!r} is not a finite number; a settle table "
                f"needs finite plan values."
            )

    sensor_ids = twin.list_attributes("SENSOR")
    coefficient_ids = [
        attr_id
        for attr_id in sensor_ids
        if twin.attributes[attr_id].replay_field is None
    ]
    overrides = _validated_coefficient_overrides(
        twin,
        coefficients,
        coefficient_ids,
        {},
        mapped_reason="",
        only_clause=(
            "Only a SENSOR without a replay_field is a coefficient and may "
            "be set from fitted parameters."
        ),
    )

    roles = plan_view
    settles_id = roles["settles"]["attribute"]
    clock_id = roles["clock"]["attribute"]
    intensity_id = roles["intensity"]["attribute"]
    level_id = roles["level"]["attribute"]
    ambient_id = roles["ambient"]["attribute"]
    event_indicators = [event["indicator"] for event in day_view["events"]]

    with _quiet():
        for attr_id in sensor_ids:
            attr = twin.attributes[attr_id]
            if attr.observed:
                twin.clear_sensor(attr_id)
                continue
            if attr_id in overrides:
                value = overrides[attr_id]
            elif attr.baseline is not None:
                value = float(attr.baseline)
            else:
                value = (attr.physio_min + attr.physio_max) / 2.0
            twin.set_sensor(attr_id, value)

        for event_indicator in event_indicators:
            twin.set_sensor(
                event_indicator, 1.0 if event_indicator == indicator else 0.0
            )
        twin.set_sensor(level_id, float(level))
        twin.set_sensor(ambient_id, float(ambient))

        values: list[list[float]] = []
        for hour in range(24):
            twin.set_sensor(clock_id, float(hour))
            row: list[float] = []
            for point in intensity_points:
                twin.set_sensor(intensity_id, float(point))
                twin.compute_all()
                if settles_id in twin.failed_attributes:
                    reason = twin.failed_attributes[settles_id]
                    raise ValueError(
                        f"Lamina {twin.lamina_id} could not compute the "
                        f"settles attribute '{settles_id}' at hour {hour} "
                        f"and intensity {point}: {reason}."
                    )
                value = twin.attributes[settles_id].value
                if value is None or not is_finite_number(value):
                    raise ValueError(
                        f"Lamina {twin.lamina_id} left the settles attribute "
                        f"'{settles_id}' unset or non-finite at hour {hour} "
                        f"and intensity {point} (got {value!r})."
                    )
                row.append(round(float(value), 4))
            values.append(row)

    return {
        "hours": list(range(24)),
        "intensities": [float(point) for point in intensity_points],
        "values": values,
    }


def _spread(low: float, high: float, count: int) -> list[float]:
    """`count` evenly spaced points from `low` to `high`, inclusive."""
    if count < 2:
        return [float(low)]
    step = (float(high) - float(low)) / float(count - 1)
    return [float(low) + step * index for index in range(count)]


class OutOfRange(ValueError):
    """A level or ambient value the subject's templates do not cover."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(message)


def _range(name: str, value: float, low: float, high: float) -> float:
    """Refuse a plan value that is not a finite number inside its range."""
    if not is_finite_number(value):
        raise OutOfRange(name, 
            f"{name}={value!r} is not a finite number; give a number from "
            f"{low:g} to {high:g}."
        )
    value = float(value)
    if value < low or value > high:
        raise OutOfRange(name,
            f"{name}={value:g} is outside the range {low:g}..{high:g} that "
            f"this subject's templates support. Give a number in that range."
        )
    return value


def _projection(templates: dict, path: Path) -> dict | None:
    """
    The projection report as the editor reads it.

    A missing report is None, not an error: a subject may have templates
    before their days have been backtested.  A present report that lacks a
    key this screen shows is refused by file and key.
    """
    report = templates.get("projection_report")
    if report is None:
        return None
    if not isinstance(report, dict):
        raise ValueError(
            f"{path}: templates['projection_report'] must be a JSON object, "
            f"got {type(report).__name__}."
        )

    def field(node: dict, key: str, where: str):
        if not isinstance(node, dict) or key not in node:
            raise ValueError(
                f"{path}: templates['projection_report']{where} is missing "
                f"'{key}'."
            )
        return node[key]

    schedule = field(report, "schedule", "")
    energy = field(schedule, "energy_day", "['schedule']")
    minute = field(schedule, "hr_minute", "['schedule']")
    sessions = field(schedule, "sessions", "['schedule']")

    peak_bias = {}
    for group_id, entry in sessions.items():
        bias = field(entry, "peak_bias", f"['schedule']['sessions']"
                                         f"[{group_id!r}]")
        # The backtest writes null for a kind with no test session that has
        # heart rate: nothing was measured, so there is nothing to report.
        if bias is None:
            peak_bias[group_id] = None
            continue
        if not is_finite_number(bias):
            raise ValueError(
                f"{path}: peak_bias for group '{group_id}' is {bias!r}, "
                f"which is not a finite number."
            )
        peak_bias[group_id] = float(bias)

    result = {
        "test_days": field(report, "test_days", ""),
        "test_sessions": field(report, "test_sessions", ""),
        "energy_reliable": field(report, "energy_reliable", ""),
        "hr_rough": field(report, "hr_rough", ""),
        "energy_mae": field(energy, "mae", "['schedule']['energy_day']"),
        "energy_baseline_mae": field(
            energy, "baseline_mae", "['schedule']['energy_day']"
        ),
        "hr_mae": field(minute, "mae", "['schedule']['hr_minute']"),
        "hr_mae_replay": field(
            minute, "mae_replay", "['schedule']['hr_minute']"
        ),
        "peak_bias": peak_bias,
    }
    return result


def _limits_text(
    label: str,
    fitted: bool,
    projection: dict | None,
    kind_labels: dict[str, str],
) -> list[str]:
    """
    The editor's caution lines, in the order the screen shows them.

    The peak line names each kind, because the kinds miss by very different
    amounts (on Subject demo: walk 20, strength 4, cardio 34 bpm) and a
    single range would hide which is which.
    """
    lines = [
        (
            f"Fitted on {label}'s recordings only"
            if fitted
            else f"Default coefficients, not fitted to {label}"
        ),
    ]
    if projection is not None:
        short = [
            f"{kind_labels.get(group, group)} {int(round(-bias))}"
            for group, bias in (projection.get("peak_bias") or {}).items()
            if bias is not None and bias < 0 and group in kind_labels
        ]
        if short:
            lines.append(
                "Session peaks too low on test sessions: "
                + ", ".join(short) + " bpm"
            )
    lines.extend([
        "Steps outside sessions: as set",
        "No fatigue, recovery, sleep or night",
    ])
    if projection is not None:
        lines.append(
            f"Tested on {projection['test_days']} days, "
            f"{projection['test_sessions']} sessions"
        )
    return lines


def _interpolate(x: float, xs: list[float], ys: list[float]) -> float:
    """Linear interpolation of ``ys`` over increasing ``xs``, clamped at the ends."""
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    for index in range(1, len(xs)):
        if x <= xs[index]:
            span = xs[index] - xs[index - 1]
            weight = (x - xs[index - 1]) / span if span else 0.0
            return float(ys[index - 1] + weight * (ys[index] - ys[index - 1]))
    return float(ys[-1])


def _default_plan(
    kinds: list[dict],
    awake: list[int],
    ambient: float,
    level: float,
    count_outside: float,
    step_minutes: int,
) -> dict:
    """
    The plan the editor opens on: one typical walk and one typical strength
    session, when the lamina offers two kinds and they fit the waking hours.

    Each session's target is the settle table's value at the session's
    middle hour, interpolated at the kind's typical (50th percentile) level.
    The table's middle point is the midpoint of the 10th-90th range, which
    is not the typical level (for Subject demo's strength it is 1.3 kcal/min
    below it), so it must not be read off directly.
    """
    start_minute, end_minute = awake

    def snapped(value: float) -> int:
        return int(round(value / step_minutes) * step_minutes)

    candidates = []
    if kinds:
        candidates.append((kinds[0], snapped(start_minute + 70), 30))
    if len(kinds) > 1:
        candidates.append((kinds[1], snapped(end_minute - 265), 45))

    sessions: list[dict] = []
    for kind, start, minutes in candidates:
        end = start + minutes
        if start < start_minute or end > end_minute:
            continue
        if any(
            not (end <= item["start"] or start >= item["start"] + item["minutes"])
            for item in sessions
        ):
            continue
        settle = kind["settle"]
        hour = int((start + minutes / 2) // 60) % 24
        typical = kind["intensity"]["p50"]
        sessions.append({
            "kind": kind["id"],
            "start": start,
            "minutes": minutes,
            "intensity": kind["intensity"]["p50"],
            "count": round(kind["steps_per_min"] * minutes),
            "target": round(_interpolate(
                typical, settle["intensities"], settle["values"][hour]
            )),
        })

    return {
        "awake": [start_minute, end_minute],
        "ambient": ambient,
        "level": level,
        "count_outside": count_outside,
        "sessions": sessions,
    }


def _build(
    lamina_id: str,
    subject: str,
    level: float | None,
    ambient: float | None,
) -> dict:
    """Build one subject's plan options for one lamina."""
    twin = load_twin(resolve_lamina(lamina_id))
    if twin.plan_view is None:
        raise NoPlanView(twin.lamina_id)

    roots = bundle_roots()
    if subject not in roots:
        raise UnknownSubject(subject, _subjects_with_templates())

    path = roots[subject] / "templates.json"
    templates = load_templates(subject)
    if templates is None:
        raise NoTemplates(subject)

    params = load_params(subject)
    coefficients = params["coefficients"] if params else {}

    level_median = float(templates["level"]["median"])
    ambient_default = float(templates["t_app"]["p50"])
    level_low = math.floor(level_median - LEVEL_SPAN)
    level_high = math.ceil(level_median + LEVEL_SPAN)
    ambient_low = math.floor(float(templates["t_app"]["p5"]))
    ambient_high = math.ceil(float(templates["t_app"]["p95"]))

    level_value = _range(
        "level",
        level_median if level is None else level,
        level_low,
        level_high,
    )
    ambient_value = _range(
        "ambient",
        ambient_default if ambient is None else ambient,
        ambient_low,
        ambient_high,
    )

    subject_label = read_subject_label(roots[subject], subject)
    roles = twin.plan_view
    groups = kind_groups(twin)

    kinds: list[dict] = []
    for group_id, spec in groups.items():
        entry = templates["groups"].get(group_id)
        if not isinstance(entry, dict) or not entry.get("offered"):
            continue
        for key in ("sessions", "minutes", "steps_mean"):
            if key not in entry:
                raise ValueError(
                    f"{path}: templates group '{group_id}' is missing "
                    f"required field '{key}'."
                )
        session_ae = entry.get("session_ae")
        if not isinstance(session_ae, dict):
            raise ValueError(
                f"{path}: templates group '{group_id}' is offered but has no "
                f"'session_ae' object to sample intensity from."
            )
        p10 = _finite_field(
            session_ae, "p10", path, f"group '{group_id}' session_ae"
        )
        p50 = _finite_field(
            session_ae, "p50", path, f"group '{group_id}' session_ae"
        )
        p90 = _finite_field(
            session_ae, "p90", path, f"group '{group_id}' session_ae"
        )
        points = _spread(p10, p90, SETTLE_POINTS)
        kinds.append({
            "id": group_id,
            "label": spec["label"],
            "sessions": entry["sessions"],
            "minutes": entry["minutes"],
            "intensity": {
                "p10": p10,
                "p50": p50,
                "p90": p90,
                "unit": roles["intensity"]["unit"],
            },
            "steps_per_min": entry["steps_mean"],
            "settle": settle_table(
                twin, coefficients, spec, points, level_value, ambient_value
            ),
        })

    steps_outside = templates["steps_outside"]
    count_p10 = steps_outside["p10"]
    count_p50 = steps_outside["p50"]
    count_p90 = steps_outside["p90"]

    projection = _projection(templates, path)
    fitted = params is not None

    return {
        "lamina": twin.lamina_id,
        "subject": subject,
        "subject_label": subject_label,
        "applies_to": templates.get("applies_to"),
        "fitted": fitted,
        "coefficients_applies_to": (
            params.get("applies_to") if params else None
        ),
        "roles": roles,
        "kinds": kinds,
        "day": {
            "awake": {
                "start": templates["awake"]["start"],
                "end": templates["awake"]["end"],
            },
            "ambient": {
                "min": ambient_low,
                "max": ambient_high,
                "default": ambient_default,
                "unit": roles["ambient"]["unit"],
            },
            "level": {
                "min": level_low,
                "max": level_high,
                "default": level_median,
                "recorded": templates["level"].get("recorded"),
                "unit": roles["level"]["unit"],
            },
            "count_outside": {
                "min": 0,
                "max": int(round(count_p90 * 1.5 / COUNT_STEP) * COUNT_STEP),
                "default": count_p50,
                "p10": count_p10,
                "p90": count_p90,
                "unit": "steps",
            },
            "settle_at": {
                "level": level_value,
                "ambient": ambient_value,
            },
        },
        "default_plan": _default_plan(
            kinds,
            [templates["awake"]["start"], templates["awake"]["end"]],
            ambient_value,
            level_value,
            count_p50,
            5,
        ),
        "projection_error": projection,
        "limits": {
            "max_sessions": 6,
            "session_minutes": [5, 180],
            "step_minutes": 5,
        },
        "limits_text": _limits_text(
            subject_label, fitted, projection,
            {kind["id"]: kind["label"] for kind in kinds},
        ),
    }


def _file_mtimes(subject: str) -> tuple[float, float]:
    """
    The subject's templates and params file modification times.

    They are part of the cache key: editing either file must make the next
    request recompute rather than serve a plan of the old templates.  A
    missing file is 0, which lets the loader produce the real error with the
    subject the caller asked for.
    """
    directory = bundle_roots().get(subject)
    if directory is None:
        return 0.0, 0.0

    def mtime(path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return (
        mtime(directory / "templates.json"),
        mtime(directory / "params.json"),
    )


@functools.lru_cache(maxsize=64)
def _cached(
    lamina_id: str,
    subject: str,
    level: float | None,
    ambient: float | None,
    templates_mtime: float,
    params_mtime: float,
) -> dict:
    """The cache body: a second request for the same files is a dict reuse."""
    return _build(lamina_id, subject, level, ambient)


def plan_options(
    lamina_id: str,
    subject: str,
    level: float | None = None,
    ambient: float | None = None,
) -> dict:
    """
    Everything the Plan a day editor draws, for one lamina and subject.

    A lamina without ``<plan_view>`` is refused before the subject is looked
    at; an unknown subject and a subject without templates are distinguished
    so the screen can offer the subjects that can be planned.  Out-of-range
    or non-finite level and ambient values are refused.  The result is cached
    on the request and both source files' modification times, like
    ``day_summary``.
    """
    templates_mtime, params_mtime = _file_mtimes(subject)
    return _cached(
        lamina_id, subject, level, ambient, templates_mtime, params_mtime
    )


plan_options.cache_clear = _cached.cache_clear
plan_options.cache_info = _cached.cache_info
