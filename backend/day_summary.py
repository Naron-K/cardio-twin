"""
Day summary — one person's whole day, computed from a lamina's roles.

The day view names no attribute of its own.  A lamina's optional
``<day_view>`` block declares which attributes are the measured/modelled
pair, which are the rates worth a strip, which indicators colour a session
and which attribute says the device was worn.  This module reads those
roles, replays the recorded day through the lamina once, and returns the
per-minute series plus the sessions, gaps, KPIs and verdicts a specialist
reads.

Replay, bundle validation and session stepping are the existing pieces:
``bundles.load_bundle`` / ``load_params``, ``signal_source.ReplaySource``
and ``session.Session``.  The only work done here is the day-level reading
of what that replay produced.

Nothing here promises a clinical result.  A missing measurement stays a
missing value; a KPI with no data behind it reports ``None`` and says so.
"""
from __future__ import annotations

import functools
import json
import math
import re
import statistics
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from bundles import (
    bundle_roots,
    is_finite_number,
    list_bundles,
    load_bundle,
    load_params,
    subject_labels,
)
from laminae import load_twin, resolve_lamina
from session import Session
from signal_source import ReplayExhausted, ReplaySource
from universal_twin import parse_replay_field

#: A watch that records nothing for this many consecutive minutes was off.
_GAP_MINUTES = 20
#: Shorter than this is a moment in a workout, not a session worth a row.
_SESSION_MINUTES = 5
#: Quiet heart rate excludes every session and this margin either side.
_MARGIN_MINUTES = 30
#: Usual error when neither a fitted value nor enough pairs exist.
_DEFAULT_SD = 5.0


def _r(value: float | None) -> float | None:
    """A returned float, rounded to two decimal places; None stays None."""
    if value is None:
        return None
    return round(float(value), 2)


def _plain(value: float) -> str:
    """A compact number for a sentence, without a trailing ``.0``."""
    return f"{round(float(value), 2):g}"


def _file_mtimes(subject: str, date: str) -> tuple[float, float]:
    """
    The bundle's and the subject's params file's modification times.

    They are part of the cache key: editing either file on disk must make
    the next request recompute rather than serve a summary of the old day.
    A missing file is 0, which lets the loader produce the real error with
    the subject and date the caller asked for.
    """
    directory = bundle_roots().get(subject)
    if directory is None:
        return 0.0, 0.0

    def mtime(path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return mtime(directory / f"{date}.json"), mtime(directory / "params.json")


class NoReadings(ValueError):
    """A recorded day on which nothing the day view draws was measured."""


def _observed_fields(twin) -> tuple[str, ...]:
    """The bundle sample fields the lamina's observed attributes read."""
    fields = []
    for attr in twin.attributes.values():
        if not attr.observed or not attr.replay_field:
            continue
        path, _labels = parse_replay_field(attr.replay_field)
        if path.startswith("sample."):
            fields.append(path[len("sample."):])
    return tuple(sorted(set(fields)))


@functools.lru_cache(maxsize=4096)
def _has_observed(path: str, mtime: float, fields: tuple[str, ...]) -> bool:
    """True when any sample row holds a number in one of ``fields``."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # An unreadable file is the loader's error to report, not "empty".
        return True
    rows = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return True
    return any(
        isinstance(row, dict) and is_finite_number(row.get(field))
        for row in rows
        for field in fields
    )


def days_without_readings(lamina_id: str) -> dict[str, list[str]]:
    """
    Subject -> recorded days on which the lamina's observed attributes never
    have a reading.

    Without a measured value there is nothing to set the model against, and
    on Subject demo's days without one the model has no resting level to run from
    either, so such a day has nothing to show.  A lamina with no observed
    attribute judges no day empty.  Each file is read once per modification
    time.
    """
    twin = load_twin(resolve_lamina(lamina_id))
    fields = _observed_fields(twin)
    if not fields:
        return {}
    empty: dict[str, list[str]] = {}
    roots = bundle_roots()
    for subject, dates in list_bundles().items():
        directory = roots.get(subject)
        if directory is None:
            continue
        missing = []
        for date in dates:
            path = directory / f"{date}.json"
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if not _has_observed(str(path), mtime, fields):
                missing.append(date)
        if missing:
            empty[subject] = missing
    return empty


def _clock_label(minute: int, bundle: dict) -> str:
    """HH:MM in the bundle's own time zone, matching the replay's clock."""
    tz = (
        timezone.utc
        if bundle["timezone"] == "UTC"
        else ZoneInfo(bundle["timezone"])
    )
    local_day = _date.fromisoformat(bundle["date"])
    midnight = datetime(
        local_day.year, local_day.month, local_day.day, tzinfo=tz
    )
    instant = midnight.astimezone(timezone.utc) + timedelta(minutes=minute)
    local = instant.astimezone(tz)
    return f"{local.hour:02d}:{local.minute:02d}"


def _words(raw: str) -> str:
    """
    A recording's own label as words: ``FunctionalStrengthTraining`` becomes
    ``Functional strength training``.  The recording's wording is kept; only
    the case and the missing spaces are the summary's.
    """
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", raw)
    return spaced.capitalize()


def _verdict(n_paired: int, difference: float | None, sd: float) -> str:
    """
    Section 3 of DAY_VIEW_PLAN.md, in one place.

    Three levels around the model's own usual error.  A difference of zero
    is always as expected, which also keeps the degenerate ``sd == 0`` case
    from reporting a perfect match as slightly high.
    """
    if n_paired < 3 or difference is None:
        return "too_few"
    if difference == 0.0:
        return "as_expected"
    magnitude = abs(difference)
    if magnitude < sd / 2.0:
        return "as_expected"
    if magnitude <= sd:
        return "slightly_higher" if difference > 0 else "slightly_lower"
    return "higher" if difference > 0 else "lower"


def _event_labels(bundle: dict, event_field: str | None) -> list:
    """
    The raw recorded label for every minute, at the lamina's own field.

    The path is parsed with the same helper the replay uses, so a field the
    lamina declared as ``sample.workout`` is read from each row and a
    ``day.`` field is one value for the whole day.
    """
    samples = bundle["samples"]
    if not event_field:
        return [None] * len(samples)
    path, _labels = parse_replay_field(event_field)
    source, key = path.split(".", 1)
    if source == "day":
        value = bundle["day"].get(key)
        return [value] * len(samples)
    return [row.get(key) for row in samples]


def _sum_rate(values: list, label: str, where: str) -> float | None:
    """Sum a rate's recorded minutes, refusing a negative total."""
    recorded = [float(v) for v in values if v is not None]
    if not recorded:
        return None
    total = sum(recorded)
    if total < 0.0:
        raise ValueError(
            f"{where}: total {label} is negative ({total:g}); a day cannot "
            f"record negative {label.lower()}. Check the bundle's units."
        )
    return total


def _assert_finite(node, path: str) -> None:
    """Refuse to return a summary carrying NaN or infinity anywhere."""
    if isinstance(node, bool):
        return
    if isinstance(node, float):
        if not math.isfinite(node):
            raise ValueError(
                f"day summary produced a non-finite number at {path} "
                f"({node!r}); refusing to return it as a reading."
            )
    elif isinstance(node, dict):
        for key, value in node.items():
            _assert_finite(value, f"{path}.{key}")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _assert_finite(value, f"{path}[{index}]")


def summarise_bundle(
    lamina_id: str,
    bundle: dict,
    params: dict | None,
    subject_label: str,
    *,
    planned: bool = False,
) -> dict:
    """
    Replay one bundle and return the finished day summary.

    ``_build`` loads a recorded day and calls this; ``planned_day`` builds a
    bundle from a plan and calls it with ``planned=True``.  A planned bundle
    has no measured value by construction, so the "nothing was measured"
    refusal is skipped and every session's verdict is ``None``.
    """
    path = resolve_lamina(lamina_id)
    twin = load_twin(path)
    day_view = twin.day_view
    if not day_view:
        raise ValueError(
            f"lamina {twin.lamina_id} declares no <day_view>; there is no "
            f"day to describe. Add a <day_view> block to that lamina."
        )

    subject = bundle["subject"]
    date = bundle["date"]

    attrs = twin.attributes
    pair = day_view["pair"]
    measured_id = pair["measured"]
    modelled_id = pair["modelled"]
    pair_unit = attrs[measured_id].unit
    rate_specs = list(day_view.get("rates", []))
    event_specs = list(day_view.get("events", []))
    worn_id = day_view["worn"]

    session = Session(lamina=path)
    coefficients = params["coefficients"] if params else None
    source = ReplaySource(
        session.twin, bundle, params=coefficients, speed=600
    )
    session.seed(source.starting_state())

    samples = bundle["samples"]
    labels = _event_labels(bundle, day_view.get("event_field"))
    n_minutes = len(samples)

    measured: list = []
    modelled: list = []
    rate_values: dict[str, list] = {
        spec["attribute"]: [] for spec in rate_specs
    }
    indicators: list[set] = []
    worn_present: list[bool] = []

    index = 0
    while True:
        try:
            readings = source.next()
        except ReplayExhausted:
            break
        missing = set(source.last_missing)
        session.tick(readings, missing=source.last_missing)

        twin = session.twin
        failed = twin.failed_attributes
        measured.append(
            None if measured_id in failed
            else twin.attributes[measured_id].value
        )
        modelled.append(
            None if modelled_id in failed
            else twin.attributes[modelled_id].value
        )
        for spec in rate_specs:
            attr_id = spec["attribute"]
            rate_values[attr_id].append(
                None if attr_id in missing else readings.get(attr_id)
            )
        indicators.append({
            spec["indicator"]
            for spec in event_specs
            if readings.get(spec["indicator"]) == 1.0
        })
        worn_present.append(worn_id not in missing)
        index += 1

    # Without one measured value there is nothing to set the model against,
    # whatever the model drew; the same rule as days_without_readings.
    if not planned and not any(v is not None for v in measured):
        raise NoReadings(
            f"No readings on {date}: {subject_label}'s watch recorded nothing "
            f"the model can be set against that day."
        )

    n_minutes = len(measured)

    # Gaps: 20+ consecutive minutes with no value for the worn attribute.
    gaps: list[list[int]] = []
    index = 0
    while index < n_minutes:
        if not worn_present[index]:
            end = index
            while end < n_minutes and not worn_present[end]:
                end += 1
            if end - index >= _GAP_MINUTES:
                gaps.append([index, end])
            index = end
        else:
            index += 1

    residuals = [
        float(a) - float(b)
        for a, b in zip(measured, modelled)
        if a is not None and b is not None
    ]
    if params is not None and params.get("residual_sd") is not None:
        sd = float(params["residual_sd"])
        sd_source = "fitted"
    elif len(residuals) > 1:
        sd = statistics.pstdev(residuals)
        sd_source = "this day"
    else:
        sd = _DEFAULT_SD
        sd_source = "default"
    if not math.isfinite(sd) or sd < 0.0:
        raise ValueError(
            f"the usual error for {subject_label}/{date} is {sd!r}; a "
            f"standard deviation must be a finite non-negative number."
        )

    sessions: list[dict] = []
    index = 0
    while index < n_minutes:
        raw_label = labels[index]
        if raw_label is None:
            index += 1
            continue
        end = index + 1
        while end < n_minutes and labels[end] == raw_label:
            end += 1
        if end - index >= _SESSION_MINUTES:
            minutes = range(index, end)
            measured_run = [
                measured[k] for k in minutes if measured[k] is not None
            ]
            paired = [
                (measured[k], modelled[k])
                for k in minutes
                if measured[k] is not None and modelled[k] is not None
            ]
            modelled_run = [
                modelled[k] for k in minutes if modelled[k] is not None
            ]
            if planned:
                # A planned session has no measured line to pair with, so the
                # mean and peak the model reached are read from the model
                # alone; there is no difference to judge.
                mean_measured = difference = None
                mean_modelled = (
                    statistics.mean(modelled_run) if modelled_run else None
                )
            elif paired:
                mean_measured = statistics.mean(p[0] for p in paired)
                mean_modelled = statistics.mean(p[1] for p in paired)
                difference = mean_measured - mean_modelled
            else:
                mean_measured = mean_modelled = difference = None

            group = "other"
            group_label = "Other"
            for spec in event_specs:
                if any(spec["indicator"] in indicators[k] for k in minutes):
                    group = spec["group"]
                    group_label = spec["label"]
                    break

            rate_totals = {}
            for spec in rate_specs:
                attr_id = spec["attribute"]
                total = _sum_rate(
                    [rate_values[attr_id][k] for k in minutes],
                    spec["label"],
                    f"session at minute {index}",
                )
                rate_totals[attr_id] = _r(total)

            sessions.append({
                "start": index,
                "end": end,
                "minutes": end - index,
                "label": _words(raw_label),
                "group": group,
                "group_label": group_label,
                "mean_measured": _r(mean_measured),
                "peak_measured": _r(max(measured_run) if measured_run else None),
                "mean_modelled": _r(mean_modelled),
                "n_paired": len(paired),
                "difference": _r(difference),
                "rate_totals": rate_totals,
                "verdict": (
                    None if planned else _verdict(len(paired), difference, sd)
                ),
            })
        index = end

    total_session_minutes = sum(item["minutes"] for item in sessions)

    # Per-day rate totals: what the top row shows for each rate.
    day_rate_totals: dict[str, float | None] = {}
    for spec in rate_specs:
        attr_id = spec["attribute"]
        day_rate_totals[attr_id] = _r(
            _sum_rate(rate_values[attr_id], spec["label"], "the day")
        )

    kpis: list[dict] = []
    for spec in rate_specs:
        attr_id = spec["attribute"]
        total = day_rate_totals[attr_id]
        kpis.append({
            "key": attr_id,
            "label": spec["label"],
            "value": total,
            "unit": attrs[attr_id].unit.replace("/min", "").strip(),
            "note": "",
        })

    kpis.append({
        "key": "sessions",
        "label": "Sessions",
        "value": len(sessions),
        "unit": "",
        "note": f"{total_session_minutes} min",
    })

    excluded: set[int] = set()
    for item in sessions:
        start = max(0, item["start"] - _MARGIN_MINUTES)
        end = min(n_minutes, item["end"] + _MARGIN_MINUTES)
        excluded.update(range(start, end))
    quiet = [
        measured[k]
        for k in range(n_minutes)
        if k not in excluded and measured[k] is not None
    ]
    kpis.append({
        "key": "quiet",
        "label": f"{pair['label']} outside sessions",
        "value": _r(statistics.median(quiet)) if quiet else None,
        "unit": pair_unit,
        "note": f"median, n = {len(quiet)}" if quiet else "",
    })

    peak_minutes = [
        (value, k) for k, value in enumerate(measured) if value is not None
    ]
    if peak_minutes:
        peak_value, peak_index = max(peak_minutes, key=lambda item: item[0])
        peak_note = f"at {_clock_label(peak_index, bundle)}"
    else:
        peak_value, peak_note = None, ""
    kpis.append({
        "key": "peak",
        "label": f"Peak {pair['label'].lower()}",
        "value": _r(peak_value),
        "unit": pair_unit,
        "note": peak_note,
    })

    paired_all = [
        (a, b) for a, b in zip(measured, modelled)
        if a is not None and b is not None
    ]
    if paired_all:
        within = sum(1 for a, b in paired_all if abs(a - b) <= sd)
        as_expected_value = 100.0 * within / len(paired_all)
        as_expected_note = f"SD {_plain(sd)} {pair_unit}".strip()
    else:
        as_expected_value = None
        as_expected_note = ""
    kpis.append({
        "key": "as_expected",
        "label": "Within ±1 SD of model",
        "value": _r(as_expected_value),
        "unit": "%",
        "note": as_expected_note,
    })

    worn_minutes = sum(1 for present in worn_present if present)
    kpis.append({
        "key": "worn",
        "label": "Wear time",
        "value": _r(worn_minutes / 60.0) if worn_minutes else None,
        "unit": "h",
        "note": f"{worn_minutes} / {n_minutes} min" if worn_minutes else "",
    })

    rate_phrases = []
    for spec in rate_specs:
        total = day_rate_totals[spec["attribute"]]
        if total is None:
            continue
        unit = attrs[spec["attribute"]].unit.replace("/min", "").strip()
        label = spec["label"].lower()
        if unit and unit.lower() in label:
            rate_phrases.append(f"{total:,.0f} {label}")
        elif unit:
            rate_phrases.append(f"{total:,.0f} {unit} {label}")
        else:
            rate_phrases.append(f"{total:,.0f} {label}")

    session_word = "session" if len(sessions) == 1 else "sessions"
    if sessions:
        headline = (
            f"{len(sessions)} {session_word} ({total_session_minutes} min)"
        )
        if rate_phrases:
            headline += ", " + ", ".join(rate_phrases)
    else:
        # "0 sessions (0 min)" reads as a fault; say what the day was instead.
        headline = "No session recorded"
        if rate_phrases:
            headline += "; " + ", ".join(rate_phrases)
    headline += "."

    at_third_level = [
        item for item in sessions
        if item["verdict"] in ("higher", "lower")
    ]
    if at_third_level:
        named = []
        for item in at_third_level:
            direction = (
                "higher" if item["difference"] > 0 else "lower"
            )
            named.append(
                f"{item['label']} at "
                f"{_clock_label(item['start'], bundle)}, {direction} by "
                f"{_plain(abs(item['difference']))} {pair_unit}"
            )
        ending = (
            f"{day_view['pair']['label']} differed from the model: "
            + "; ".join(named) + "."
        )
    elif sessions and all(
        item["verdict"] == "as_expected" for item in sessions
    ):
        ending = "Every session was as expected."
    elif sessions:
        ending = "Every session was as expected or only slightly off."
    else:
        ending = ""

    result = {
        "lamina": twin.lamina_id,
        "subject": subject,
        "subject_label": subject_label,
        "date": date,
        "timezone": bundle["timezone"],
        "synthetic": bundle["synthetic"],
        "n_minutes": n_minutes,
        "pair": {
            "label": pair["label"],
            "unit": pair_unit,
            "measured": [_r(value) for value in measured],
            "modelled": [_r(value) for value in modelled],
        },
        "rates": [
            {
                "attribute": spec["attribute"],
                "label": spec["label"],
                "unit": attrs[spec["attribute"]].unit.replace(
                    "/min", ""
                ).strip(),
                "values": [
                    _r(value) for value in rate_values[spec["attribute"]]
                ],
            }
            for spec in rate_specs
        ],
        "events": [dict(spec) for spec in event_specs],
        "gaps": gaps,
        "sessions": sessions,
        "kpis": kpis,
        "summary": f"{headline} {ending}".strip(),
        "model": {
            "sd": _r(sd),
            "sd_source": sd_source,
            "fitted": params is not None,
            "applies_to": (params.get("applies_to") if params else None)
            or None,
        },
    }
    _assert_finite(result, "day_summary")
    return result


def _build(lamina_id: str, subject: str, date: str) -> dict:
    """Load one recorded day and summarise it."""
    twin = load_twin(resolve_lamina(lamina_id))
    if not twin.day_view:
        raise ValueError(
            f"lamina {twin.lamina_id} declares no <day_view>; there is no "
            f"day to describe. Add a <day_view> block to that lamina."
        )

    bundle = load_bundle(subject, date)
    params = load_params(subject)
    subject_label = subject_labels().get(subject, subject)
    return summarise_bundle(lamina_id, bundle, params, subject_label)


@functools.lru_cache(maxsize=32)
def _cached(
    lamina_id: str,
    subject: str,
    date: str,
    bundle_mtime: float,
    params_mtime: float,
) -> dict:
    """The cache body: a second request for the same files is a dict copy."""
    return _build(lamina_id, subject, date)


def day_summary(lamina_id: str, subject: str, date: str) -> dict:
    """
    One person's whole day, computed from the lamina's ``<day_view>`` roles.

    The replay is cached on the lamina, the subject, the date and both
    source files' modification times, so reopening a finished day does not
    replay it again.  Unknown subjects and dates come from ``load_bundle``;
    a lamina without roles raises before any replay starts.
    """
    bundle_mtime, params_mtime = _file_mtimes(subject, date)
    return _cached(lamina_id, subject, date, bundle_mtime, params_mtime)


day_summary.cache_clear = _cached.cache_clear
day_summary.cache_info = _cached.cache_info
