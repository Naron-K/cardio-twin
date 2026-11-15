"""
Plan options and GET /api/plan/options.

The settle table is the acceptance test of this phase: it must be the
lamina's own answer, not a second implementation.  The independent model in
tools/fit_hr_model is run on a one-minute input built from the same role
values and the two are compared.  The remaining tests pin the defaults, the
shape, the monotonicity of intensity, the +5 level invariant, and the
endpoint's status codes.
"""
import pytest
from fastapi.testclient import TestClient

from bundles import load_params
from laminae import load_twin
from main import app
import plan_options as po
from tools.fit_hr_model import (
    HR_TARGET_FLOOR,
    WEARABLE_XML,
    simulate_day,
)
from tools.make_activity_templates import kind_groups

SUBJECT = "subject_demo"
LAMINA = "lamina_wearable"
HOURS = (0, 7, 12, 18)


@pytest.fixture(scope="module")
def templates() -> dict:
    data = po.load_templates(SUBJECT)
    assert data is not None
    return data


@pytest.fixture(scope="module")
def options() -> dict:
    po.plan_options.cache_clear()
    return po.plan_options(LAMINA, SUBJECT)


@pytest.fixture(scope="module")
def groups() -> dict:
    return kind_groups(load_twin(WEARABLE_XML))


def _one_minute(options: dict, indicator: str, hour: int, intensity: float,
                level: float, ambient: float) -> dict:
    """The same values the settle table sets, in simulate_day's input shape."""
    roles = options["roles"]
    twin = load_twin(WEARABLE_XML)
    inputs = {
        roles["clock"]["attribute"]: [float(hour)],
        "dt_s": [60.0],
        roles["level"]["attribute"]: [float(level)],
        roles["intensity"]["attribute"]: [float(intensity)],
        roles["ambient"]["attribute"]: [float(ambient)],
    }
    for event in twin.day_view["events"]:
        inputs[event["indicator"]] = [
            1.0 if event["indicator"] == indicator else 0.0
        ]
    return inputs


def test_settle_values_match_the_independent_model(options, groups):
    coefficients = load_params(SUBJECT)["coefficients"]
    level = options["day"]["settle_at"]["level"]
    ambient = options["day"]["settle_at"]["ambient"]

    for kind in options["kinds"]:
        spec = groups[kind["id"]]
        table = kind["settle"]
        assert table["hours"] == list(range(24))
        last = len(table["intensities"]) - 1
        for hour in HOURS:
            for index in (0, last // 2, last):
                intensity = table["intensities"][index]
                target, _ = simulate_day(
                    _one_minute(
                        options, spec["indicator"], hour, intensity,
                        level, ambient,
                    ),
                    coefficients,
                )
                expected = float(target[0])
                got = table["values"][hour][index]
                assert got == pytest.approx(round(expected, 4), abs=1e-9)
                assert abs(got - expected) <= 1e-4


def test_values_rise_with_intensity_for_every_hour(options):
    for kind in options["kinds"]:
        for hour, row in enumerate(kind["settle"]["values"]):
            assert all(
                later >= earlier for earlier, later in zip(row, row[1:])
            ), f"{kind['id']} does not rise at hour {hour}"
            assert row[-1] > row[0], (
                f"{kind['id']} is flat across intensity at hour {hour}"
            )


def test_moving_level_by_five_moves_every_unclamped_value(options):
    coefficients = load_params(SUBJECT)["coefficients"]
    ceiling = float(coefficients["HR_max"])
    base_level = options["day"]["level"]["default"]
    shifted = po.plan_options(LAMINA, SUBJECT, level=base_level + 5.0)

    for before, after in zip(options["kinds"], shifted["kinds"]):
        assert before["id"] == after["id"]
        for hour, row in enumerate(before["settle"]["values"]):
            for index, value in enumerate(row):
                moved = after["settle"]["values"][hour][index]
                if (
                    value <= HR_TARGET_FLOOR
                    or value >= ceiling
                    or moved <= HR_TARGET_FLOOR
                    or moved >= ceiling
                ):
                    continue
                assert moved - value == pytest.approx(5.0, abs=1e-9)


def test_defaults_shape_and_offered_kinds(options, templates, groups):
    assert options["day"]["level"]["default"] == templates["level"]["median"]
    assert options["day"]["ambient"]["default"] == templates["t_app"]["p50"]
    assert options["day"]["settle_at"] == {
        "level": templates["level"]["median"],
        "ambient": templates["t_app"]["p50"],
    }

    for key in (
        "lamina", "subject", "subject_label", "applies_to", "fitted",
        "coefficients_applies_to", "roles", "kinds", "day",
        "projection_error", "limits", "limits_text",
    ):
        assert key in options
    assert options["subject"] == SUBJECT
    assert options["lamina"] == LAMINA
    assert options["fitted"] is True

    offered = [
        group_id
        for group_id in groups
        if templates["groups"].get(group_id, {}).get("offered")
    ]
    assert [kind["id"] for kind in options["kinds"]] == offered

    for kind in options["kinds"]:
        assert set(kind) == {
            "id", "label", "sessions", "minutes", "intensity",
            "steps_per_min", "settle",
        }
        assert set(kind["intensity"]) == {"p10", "p50", "p90", "unit"}
        assert (
            kind["intensity"]["unit"]
            == options["roles"]["intensity"]["unit"]
        )
        assert kind["steps_per_min"] == (
            templates["groups"][kind["id"]]["steps_mean"]
        )
        table = kind["settle"]
        assert len(table["intensities"]) == po.SETTLE_POINTS
        assert table["intensities"][0] == pytest.approx(
            kind["intensity"]["p10"]
        )
        assert table["intensities"][-1] == pytest.approx(
            kind["intensity"]["p90"]
        )
        assert len(table["values"]) == 24
        assert all(len(row) == po.SETTLE_POINTS for row in table["values"])

    day = options["day"]
    assert set(day) == {"awake", "ambient", "level", "count_outside",
                        "settle_at"}
    assert day["count_outside"]["min"] == 0
    assert day["count_outside"]["default"] == templates["steps_outside"]["p50"]
    assert day["awake"] == {
        "start": templates["awake"]["start"],
        "end": templates["awake"]["end"],
    }


def test_projection_error_is_the_templates_report(options, templates):
    report = templates.get("projection_report")
    if report is None:
        assert options["projection_error"] is None
        return

    error = options["projection_error"]
    schedule = report["schedule"]
    assert error["test_days"] == report["test_days"]
    assert error["test_sessions"] == report["test_sessions"]
    assert error["energy_reliable"] is report["energy_reliable"]
    assert error["hr_rough"] is report["hr_rough"]
    assert error["energy_mae"] == schedule["energy_day"]["mae"]
    assert (
        error["energy_baseline_mae"]
        == schedule["energy_day"]["baseline_mae"]
    )
    assert error["hr_mae"] == schedule["hr_minute"]["mae"]
    assert error["hr_mae_replay"] == schedule["hr_minute"]["mae_replay"]
    assert error["peak_bias"] == {
        group_id: entry["peak_bias"]
        for group_id, entry in schedule["sessions"].items()
    }
    assert any(
        line.startswith("Tested on") for line in options["limits_text"]
    )


def test_api_plan_options_returns_the_same_options(options):
    client = TestClient(app)
    response = client.get(
        "/api/plan/options",
        params={"lamina": LAMINA, "subject": SUBJECT},
    )
    assert response.status_code == 200
    assert response.json() == options


def test_api_plan_options_lamina_without_plan_view_is_400():
    client = TestClient(app)
    response = client.get(
        "/api/plan/options",
        params={"lamina": "lamina_circulatory", "subject": SUBJECT},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["lamina"] == "lamina_circulatory"


def test_api_plan_options_unknown_subject_lists_available():
    client = TestClient(app)
    response = client.get(
        "/api/plan/options",
        params={"lamina": LAMINA, "subject": "nobody_here"},
    )
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["subject"] == "nobody_here"
    assert SUBJECT in detail["available"]


def test_api_plan_options_subject_without_templates_is_404():
    client = TestClient(app)
    response = client.get(
        "/api/plan/options",
        params={"lamina": LAMINA, "subject": "demo"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["subject"] == "demo"


def test_api_plan_options_out_of_range_values_are_422():
    client = TestClient(app)
    for key, value in (("level", 999), ("ambient", -50)):
        response = client.get(
            "/api/plan/options",
            params={"lamina": LAMINA, "subject": SUBJECT, key: value},
        )
        assert response.status_code == 422


def test_kind_groups_is_still_importable_from_the_tool():
    from tools.make_activity_templates import kind_groups as tool_kind_groups

    assert tool_kind_groups is po.kind_groups


def test_a_kind_without_measured_test_sessions_is_left_out_of_the_peaks_line(templates):
    """The backtest writes null peak_bias for a kind with no measured session."""
    import copy
    from pathlib import Path

    from plan_options import _limits_text, _projection

    edited = copy.deepcopy(templates)
    sessions = edited["projection_report"]["schedule"]["sessions"]
    first, *others = list(sessions)
    sessions[first]["peak_bias"] = None
    projection = _projection(edited, Path("templates.json"))
    assert projection["peak_bias"][first] is None
    labels = {group: group.title() for group in sessions}
    peaks = [line for line in _limits_text("Someone", True, projection, labels)
             if line.startswith("Session peaks")]
    assert peaks and first.title() not in peaks[0]
    for group in others:
        if sessions[group]["peak_bias"] is not None and sessions[group]["peak_bias"] < 0:
            assert group.title() in peaks[0]
