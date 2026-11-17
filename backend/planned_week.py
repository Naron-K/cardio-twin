"""
A planned week — a day's plan repeated, read beside the recorded week.

A person's recorded week already says how much activity they get outside
sessions: ``templates.json`` carries the median of their counted weeks in
MET-min per day.  A plan says what one day of sessions would add.  This
module multiplies the session part by the number of session days a week,
adds the person's own recorded everyday part over seven days, and reports the
result in MET-h/week.

The everyday part is the person's own recorded median, the same basis as
``current``, so the two are comparable: ``current`` is the median of the
weeks the recordings counted, and ``planned`` is that same everyday habit
plus the planned sessions.  Nothing here invents an activity level, names an
attribute id or caches anything across requests.
"""
from __future__ import annotations

from bundles import bundle_roots
from plan_options import (
    NoTemplates,
    UnknownSubject,
    _subjects_with_templates,
    load_templates,
)
from planned_day import PlanRefused, planned_day

#: The unit both the recorded week and the planned week are reported in.
UNIT = "MET-h/week"

#: Minutes in an hour, and days in a week.
_MINUTES_PER_HOUR = 60.0
_DAYS_PER_WEEK = 7.0

#: Decimal places for the computed MET-h/week values.  Two places would
#: erase the session part when it is small, so the same six-place discipline
#: the rest of the package uses for derived numbers is kept to eight.
_DOSE_PLACES = 8


def _round(value: float) -> float:
    """A computed MET-h/week value rounded to a stable number of places."""
    return round(float(value), _DOSE_PLACES)


def _days(value) -> int:
    """A whole number of session days from 0 to 7; a bool is refused."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanRefused(
            "days_per_week",
            f"must be an integer from 0 to 7, got {value!r}.",
        )
    if value < 0 or value > 7:
        raise PlanRefused(
            "days_per_week",
            f"must be from 0 to 7, got {value}.",
        )
    return value


def _current(habit: dict | None) -> dict | None:
    """The recorded-week block as the response reads it, or None."""
    if habit is None:
        return None
    total = habit["total"]
    return {
        "p10": total["p10"],
        "p50": total["p50"],
        "p90": total["p90"],
        "weeks": habit["weeks"],
        "rule": habit["rule"],
    }


def _fitness(templates: dict) -> dict:
    """The subject's recorded fitness medians, or {} when none were built."""
    block = templates.get("fitness")
    if not isinstance(block, dict):
        return {}
    values = block.get("values")
    if not isinstance(values, dict):
        return {}
    return {
        key: entry["median"]
        for key, entry in values.items()
        if isinstance(entry, dict) and "median" in entry
    }


def _reason(day: dict, habit: dict | None) -> str | None:
    """The sentence naming what is missing, or None when both are present."""
    if "dose" in day and habit is not None:
        return None
    missing = []
    if "dose" not in day:
        missing.append("no basal rate in the templates")
    if habit is None:
        missing.append("no counted week in the recordings")
    return (
        "A weekly dose cannot be planned: " + " and ".join(missing) + "."
    )


def week_dose(lamina_id: str, plan: dict, days_per_week: int) -> dict:
    """
    Run one plan and read its weekly dose beside the recorded week.

    ``days_per_week`` is how many days a week the plan is repeated; it must
    be a whole number from 0 to 7, so a bool, a fraction or a value outside a
    week is refused by field.  The day itself is ``planned_day``'s answer, so
    the session dose is the lamina's own arithmetic.  The planned weekly dose
    is ``(days_per_week * in_sessions + 7 * outside_median) / 60`` in
    MET-h/week.

    The everyday part is the person's own recorded median from the counted
    weeks, not another estimate, so ``planned`` and ``current`` share a basis
    and can be compared: ``current`` is that median week and ``planned`` is
    the same everyday habit plus the planned sessions.  When either half is
    absent the planned value is None and ``reason`` names which one, rather
    than treating a missing recording as a zero.
    """
    days = _days(days_per_week)

    day = planned_day(lamina_id, plan)
    subject = day["subject"]
    templates = load_templates(subject)
    if templates is None:
        raise NoTemplates(subject)
    habit = templates.get("habit")

    current = _current(habit)
    reason = _reason(day, habit)
    planned = None
    if reason is None:
        in_sessions = float(day["dose"]["in_sessions"])
        outside_p50 = float(habit["outside_sessions_per_day"]["p50"])
        from_sessions = _round(days * in_sessions / _MINUTES_PER_HOUR)
        from_everyday = _round(
            _DAYS_PER_WEEK * outside_p50 / _MINUTES_PER_HOUR
        )
        planned = {
            "value": _round(from_sessions + from_everyday),
            "from_sessions": from_sessions,
            "from_everyday": from_everyday,
            "days_per_week": days,
            "session_day": _round(in_sessions / _MINUTES_PER_HOUR),
        }

    return {
        "unit": UNIT,
        "fitness": _fitness(templates),
        "current": current,
        "planned": planned,
        "reason": reason,
        "day": day,
    }


def habit_only(subject: str) -> dict:
    """
    The recorded-week block for a subject with no plan to add.

    ``planned`` is None and ``reason`` says no plan was given, so a caller
    can show the person's current dose without pretending it is a proposed
    one.  An unknown subject and one without templates raise the same
    exceptions ``plan_options`` raises, so the endpoint can answer 404 by
    name rather than with a missing number.
    """
    if not isinstance(subject, str) or not subject:
        raise ValueError("subject must be a non-empty string.")

    roots = bundle_roots()
    if subject not in roots:
        raise UnknownSubject(subject, _subjects_with_templates())
    templates = load_templates(subject)
    if templates is None:
        raise NoTemplates(subject)
    habit = templates.get("habit")

    return {
        "unit": UNIT,
        "fitness": _fitness(templates),
        "current": _current(habit),
        "planned": None,
        "reason": "no plan given",
        "day": None,
    }
