"""
A planned week read beside the person's recorded week.

The session part is the lamina's own dose from ``planned_day``, repeated by
the number of session days, and the everyday part is the subject's recorded
median.  These tests pin the arithmetic, the refusal of an impossible number
of days, and the absence of a fabricated planned dose when either half of
the comparison is missing.
"""
import copy

import pytest

from plan_options import load_templates, plan_options
from planned_day import PlanRefused
from planned_week import habit_only, week_dose

LAMINA = "lamina_wearable"
SUBJECT = "subject_demo"


@pytest.fixture(scope="module")
def options() -> dict:
    plan_options.cache_clear()
    return plan_options(LAMINA, SUBJECT)


@pytest.fixture(scope="module")
def habit() -> dict:
    data = load_templates(SUBJECT)
    assert data is not None and data.get("habit") is not None
    return data["habit"]


def _plan(options: dict) -> dict:
    return copy.deepcopy(dict(options["default_plan"], subject=SUBJECT))


@pytest.mark.parametrize("days", [0, 3, 7])
def test_the_planned_week_is_sessions_plus_the_recorded_everyday_part(
    options, habit, days
):
    weekly = week_dose(LAMINA, _plan(options), days)
    in_sessions = weekly["day"]["dose"]["in_sessions"]
    outside_p50 = habit["outside_sessions_per_day"]["p50"]

    expected = (days * in_sessions + 7 * outside_p50) / 60.0
    assert weekly["unit"] == "MET-h/week"
    assert weekly["planned"]["value"] == pytest.approx(expected, abs=1e-6)
    assert weekly["planned"]["from_everyday"] == pytest.approx(
        7 * outside_p50 / 60.0, abs=1e-6
    )
    assert weekly["planned"]["days_per_week"] == days
    assert weekly["planned"]["session_day"] == pytest.approx(
        in_sessions / 60.0, abs=1e-6
    )
    assert weekly["reason"] is None


def test_no_session_days_contribute_no_session_dose(options):
    weekly = week_dose(LAMINA, _plan(options), 0)

    assert weekly["planned"]["from_sessions"] == 0
    assert weekly["planned"]["value"] == pytest.approx(
        weekly["planned"]["from_everyday"], abs=1e-6
    )


@pytest.mark.parametrize("days", [8, -1, 2.5, True])
def test_an_impossible_number_of_days_is_refused(options, days):
    with pytest.raises(PlanRefused) as refused:
        week_dose(LAMINA, _plan(options), days)
    assert refused.value.field == "days_per_week"


def test_a_plan_with_no_sessions_has_no_session_part(options):
    plan = dict(_plan(options), sessions=[])
    weekly = week_dose(LAMINA, plan, 5)

    assert weekly["planned"]["from_sessions"] == 0
    assert weekly["planned"]["value"] == pytest.approx(
        weekly["planned"]["from_everyday"], abs=1e-6
    )


def test_the_current_block_is_the_recorded_weeks_total(habit):
    weekly = habit_only(SUBJECT)

    assert weekly["unit"] == "MET-h/week"
    assert weekly["current"] == {
        "p10": habit["total"]["p10"],
        "p50": habit["total"]["p50"],
        "p90": habit["total"]["p90"],
        "weeks": habit["weeks"],
        "rule": habit["rule"],
    }
    assert weekly["planned"] is None
    assert weekly["day"] is None
    assert weekly["reason"] == "no plan given"
