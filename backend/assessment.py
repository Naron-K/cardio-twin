"""
Enter what is known, read what follows — a generic assessment evaluator.

A lamina's optional ``<assessment_view>`` block declares the roles an
assessment screen needs: the groups of entries a person fills in, the values
that arrive from another lamina, a range those values are read against, the
paired results the screen reports, the 0-or-1 outputs it raises as flags and
an invented example that fills the form.  This module reads only that block.

Nothing here names an attribute id, a unit, a disease or a model.  The
entries, links, outputs, labels, ranges and units all come from the view, and
the arithmetic comes from the lamina itself: ``assess`` builds a fresh twin,
seeds the declared baselines, writes the given entries and links, runs the
lamina's own ``compute_all`` and reads the results back.  A dependency walk
over the declared functions says which models, entries and links stand behind
each result and flag, so the ``needs`` messages and the placeholder notice
follow from the XML rather than from a table kept here.

A wrong input is refused by field, with the allowed range in the message, so
it can never turn into a confident-looking answer.
"""
from __future__ import annotations

import re

from bundles import is_finite_number
from day_summary import _r
from laminae import load_twin, resolve_lamina
from plan_options import _quiet
from universal_twin import PRELIMINARY, SENSOR

#: The sentence shown when a chain still contains an unvalidated model.
PLACEHOLDER_NOTICE = (
    "Placeholder models: the figures below are not validated and are not "
    "medical advice."
)

#: A value that is absent although nothing is missing: the model refused it.
_REFUSED_REASON = (
    "The model refused its inputs, so no value was reported."
)

#: Weakest first: a chain is no stronger than its least reviewed model.
_STATUS_RANK = {"placeholder": 0, "draft": 1, "reviewed": 2}


class NoAssessmentView(ValueError):
    """A lamina declares no ``<assessment_view>``, so there is nothing to draw."""

    def __init__(self, lamina_id: str) -> None:
        self.lamina_id = lamina_id
        super().__init__(
            f"Lamina '{lamina_id}' declares no <assessment_view>, so there is "
            f"no assessment screen to draw. Add an <assessment_view> block to "
            f"that lamina."
        )


class EntryRefused(ValueError):
    """An entry or link the view cannot accept, naming the field refused."""

    def __init__(self, field: str, message: str) -> None:
        self.field = field
        super().__init__(f"{field}: {message}")


def _step_key(step: str) -> tuple[int, str]:
    """Order a declared step like ``2``, ``6a``, ``10`` numerically."""
    text = str(step or "")
    match = re.match(r"^(\d+)(.*)$", text)
    if match is None:
        return (10**9, text)
    return (int(match.group(1)), match.group(2))


def _view_indexes(view: dict) -> tuple[dict, list, dict, list]:
    """
    The view's entries and links, by id and in the order the view declares.

    The orders are what makes ``needs`` deterministic: a missing entry is
    listed where the form lists it, not where a set happened to iterate.
    """
    entries: dict[str, dict] = {}
    entry_order: list[str] = []
    for group in view["groups"]:
        for entry in group["entries"]:
            entries[entry["attribute"]] = entry
            entry_order.append(entry["attribute"])
    link_by_attribute = {
        link["attribute"]: role for role, link in view["links"].items()
    }
    link_order = list(view["links"])
    return entries, entry_order, link_by_attribute, link_order


def _dependency_chain(
    twin,
    entry_by_id: dict,
    link_by_attribute: dict,
    start_ids: list[str],
    measured_by_attribute: dict | None = None,
) -> tuple[dict, set, set, set]:
    """
    The functions, entries, link roles and measured inputs behind outputs.

    Each PRELIMINARY attribute contributes its ``computed_by`` function and
    that function's declared inputs, recursively.  A sensor, an inter-lamina
    value, a coefficient or any other external input ends that branch; when
    it is a view entry, a view link or a measured link it is remembered as a
    dependency.
    """
    measured_by_attribute = measured_by_attribute or {}
    functions: dict[str, object] = {}
    entries: set[str] = set()
    roles: set[str] = set()
    measured: set[str] = set()
    seen: set[str] = set()
    pending = list(start_ids)

    while pending:
        attribute_id = pending.pop()
        if attribute_id in seen:
            continue
        seen.add(attribute_id)

        if attribute_id in entry_by_id:
            entries.add(attribute_id)
        if attribute_id in measured_by_attribute:
            measured.add(attribute_id)
        role = link_by_attribute.get(attribute_id)
        if role is not None:
            roles.add(role)

        attribute = twin.attributes.get(attribute_id)
        if attribute is None or attribute.source != PRELIMINARY:
            continue
        function_id = attribute.computed_by
        function = twin.functions.get(function_id) if function_id else None
        if function is None:
            continue
        functions[function.id] = function
        pending.extend(function.inputs)

    return functions, entries, roles, measured


def _ordered_models(functions: dict) -> list[object]:
    """The chain's functions in declared step order, without duplicates."""
    return [
        functions[function_id]
        for function_id in sorted(
            functions, key=lambda item: _step_key(functions[item].step)
        )
    ]


def _weakest_status(functions) -> str | None:
    """The least reviewed status in a chain, or None when none declares one."""
    declared = [
        function.status
        for function in functions
        if function.status in _STATUS_RANK
    ]
    if not declared:
        return None
    return min(declared, key=lambda status: _STATUS_RANK[status])


def _model(function) -> dict:
    """One function as the options screen reads it."""
    return {
        "id": function.id,
        "name": function.name,
        "status": function.status,
        "source": function.source,
        "reviewed_by": function.reviewed_by,
    }


def _range_view(twin, view: dict) -> dict | None:
    """The declared range with its two endpoints read from their baselines."""
    declared = view.get("range")
    if declared is None:
        return None
    low = twin.attributes.get(declared["low"])
    high = twin.attributes.get(declared["high"])
    if low is None or high is None:
        raise ValueError(
            f"Lamina '{twin.lamina_id}' <assessment_view><range> names an "
            f"attribute that is not declared."
        )
    if low.baseline is None or high.baseline is None:
        raise ValueError(
            f"Lamina '{twin.lamina_id}' <assessment_view><range> names an "
            f"endpoint with no <baseline>; both endpoints must declare one."
        )
    return {
        "label": declared["label"],
        "unit": declared["unit"],
        "low": float(low.baseline),
        "high": float(high.baseline),
    }


def assessment_options(lamina_id: str) -> dict:
    """
    Everything an assessment form needs for one lamina.

    The groups, links, range, results, flags and example come from the
    lamina's own ``<assessment_view>``.  Each result and flag carries the
    weakest status in its dependency chain, the functions behind it in step
    order, and the view entries and link roles its chain reaches.  The
    placeholder notice is present when any chain contains a placeholder
    model.
    """
    with _quiet():
        twin = load_twin(resolve_lamina(lamina_id))
        view = twin.assessment_view
        if view is None:
            raise NoAssessmentView(lamina_id)
        entry_by_id, entry_order, link_by_attribute, link_order = (
            _view_indexes(view)
        )

    chain_functions: dict[str, object] = {}
    measured_by_attribute = {
        entry["attribute"]: entry for entry in view["measured"]
    }

    results = []
    for result in view["results"]:
        functions, entries, roles, _measured = _dependency_chain(
            twin,
            entry_by_id,
            link_by_attribute,
            [result["now"], result["planned"]],
            measured_by_attribute,
        )
        chain_functions.update(functions)
        results.append({
            "id": result["id"],
            "label": result["label"],
            "period": result["period"],
            "unit": result["unit"],
            "status": _weakest_status(functions.values()),
            "models": [_model(function)
                       for function in _ordered_models(functions)],
            "entries": [item for item in entry_order if item in entries],
            "links": [role for role in link_order if role in roles],
        })

    flags = []
    for flag in view["flags"]:
        functions, entries, roles, _measured = _dependency_chain(
            twin,
            entry_by_id,
            link_by_attribute,
            [flag["attribute"]],
            measured_by_attribute,
        )
        chain_functions.update(functions)
        flags.append({
            "attribute": flag["attribute"],
            "topic": flag["topic"],
            "label": flag["label"],
            "text": flag["text"],
            "status": _weakest_status(functions.values()),
            "entries": [item for item in entry_order if item in entries],
            "links": [role for role in link_order if role in roles],
        })

    mediators = []
    for mediator in view["mediators"]:
        functions, _entries, _roles, _measured = _dependency_chain(
            twin,
            entry_by_id,
            link_by_attribute,
            [mediator["at"]],
            measured_by_attribute,
        )
        chain_functions.update(functions)
        mediators.append({
            "now": mediator["now"],
            "at": mediator["at"],
            "label": mediator["label"],
            "unit": mediator["unit"],
            "source": mediator["source"],
            "key": mediator["key"],
            "still": mediator["still"],
            "status": _weakest_status(functions.values()),
            "models": [_model(function)
                       for function in _ordered_models(functions)],
        })

    notice = (
        PLACEHOLDER_NOTICE
        if any(function.status == "placeholder"
               for function in chain_functions.values())
        else None
    )

    return {
        "lamina": twin.lamina_id,
        "name": twin.lamina_name,
        "groups": view["groups"],
        "links": view["links"],
        "range": _range_view(twin, view),
        "results": results,
        "flags": flags,
        "examples": view["examples"],
        "measured": view["measured"],
        "horizons": view["horizons"],
        "mediators": mediators,
        "example": view["example"],
        "notice": notice,
    }


def _check_entry(attribute_id: str, entry: dict, value) -> float:
    """One entry value, refused by field and allowed range."""
    field = f"entries.{attribute_id}"
    low = entry["min"]
    high = entry["max"]
    if not is_finite_number(value):
        raise EntryRefused(
            field,
            f"must be a finite number from {low:g} to {high:g}, got "
            f"{value!r}.",
        )
    number = float(value)
    if number < low or number > high:
        raise EntryRefused(
            field,
            f"must be from {low:g} to {high:g}, got {number:g}.",
        )
    kind = entry["kind"]
    if kind == "yesno" and number not in (0.0, 1.0):
        raise EntryRefused(
            field,
            f"must be 0 or 1 for a yes/no answer, got {number:g}.",
        )
    if kind == "choice":
        options = entry.get("options") or []
        allowed = [option["value"] for option in options]
        if number not in allowed:
            listing = ", ".join(
                f"{option['value']:g} ({option['label']})"
                for option in options
            ) or "(none)"
            raise EntryRefused(
                field,
                f"must be one of the declared options: {listing}; got "
                f"{number:g}.",
            )
    return number


def _clean_entries(
    entries, entry_by_id: dict, entry_order: list[str]
) -> dict[str, float]:
    """Validate an entries mapping, dropping absent and null answers."""
    if not isinstance(entries, dict):
        raise EntryRefused(
            "entries",
            f"must be an object mapping entry attributes to numbers, got "
            f"{type(entries).__name__}.",
        )
    cleaned: dict[str, float] = {}
    for attribute_id, value in entries.items():
        if attribute_id not in entry_by_id:
            listing = ", ".join(entry_order) or "(none)"
            raise EntryRefused(
                f"entries.{attribute_id}",
                f"is not an entry in this lamina's assessment view; allowed "
                f"entries: {listing}.",
            )
        if value is None:
            continue
        cleaned[attribute_id] = _check_entry(
            attribute_id, entry_by_id[attribute_id], value
        )
    return cleaned


def _clean_links(links, view: dict, twin) -> dict[str, float]:
    """Validate a links mapping, dropping null roles; unknown roles refused."""
    if links is None:
        return {}
    if not isinstance(links, dict):
        raise EntryRefused(
            "links",
            f"must be an object mapping link roles to numbers or null, got "
            f"{type(links).__name__}.",
        )
    cleaned: dict[str, float] = {}
    for role, value in links.items():
        spec = view["links"].get(role)
        if spec is None:
            listing = ", ".join(view["links"]) or "(none)"
            raise EntryRefused(
                f"links.{role}",
                f"is not a link role in this lamina's assessment view; "
                f"allowed roles: {listing}.",
            )
        if value is None:
            cleaned[role] = None
            continue
        attribute = twin.attributes[spec["attribute"]]
        low = float(attribute.physio_min)
        high = float(attribute.physio_max)
        lowest = max(0.0, low)
        field = f"links.{role}"
        if not is_finite_number(value):
            raise EntryRefused(
                field,
                f"must be a finite number from {lowest:g} to {high:g}, or "
                f"null to leave it unset, got {value!r}.",
            )
        number = float(value)
        if number < 0.0:
            raise EntryRefused(
                field,
                f"must not be negative; give a number from {lowest:g} to "
                f"{high:g}.",
            )
        if number < low or number > high:
            raise EntryRefused(
                field,
                f"must be from {lowest:g} to {high:g}, got {number:g}.",
            )
        cleaned[role] = number
    return cleaned


def _clean_measured(measured, view: dict, twin) -> dict[str, float]:
    """Validate the recorded values, using only the declared measured keys."""
    if measured is None:
        return {}
    if not isinstance(measured, dict):
        raise EntryRefused(
            "measured",
            f"must be an object mapping measured link keys to numbers or be "
            f"absent, got {type(measured).__name__}.",
        )
    by_key = {entry["key"]: entry for entry in view["measured"]}
    cleaned: dict[str, float] = {}
    for key, value in measured.items():
        entry = by_key.get(key)
        if entry is None:
            continue
        attribute = twin.attributes[entry["attribute"]]
        low = float(attribute.physio_min)
        high = float(attribute.physio_max)
        field = f"measured.{key}"
        if not is_finite_number(value):
            raise EntryRefused(
                field,
                f"must be a finite number from {low:g} to {high:g}, got "
                f"{value!r}.",
            )
        number = float(value)
        if number < low or number > high:
            raise EntryRefused(
                field,
                f"must be from {low:g} to {high:g}, got {number:g}.",
            )
        cleaned[key] = number
    return cleaned


def _raw_value(twin, attribute_id: str) -> float | None:
    """The attribute's value, or None when it did not compute finite."""
    attribute = twin.attributes.get(attribute_id)
    if attribute is None or attribute.value is None:
        return None
    value = attribute.value
    if not is_finite_number(value):
        return None
    return float(value)


def _missing(
    chain: tuple[dict, set, set, set],
    given: dict,
    given_links: dict,
    given_measured: dict,
    entry_by_id: dict,
    entry_order: list[str],
    link_order: list[str],
    view: dict,
    include_links: bool,
) -> list[dict]:
    """The chain's view entries, measured links and link roles not supplied."""
    _functions, entries, roles, measured = chain
    needs = [
        {"attribute": attribute_id,
         "label": entry_by_id[attribute_id]["label"]}
        for attribute_id in entry_order
        if attribute_id in entries and attribute_id not in given
    ]
    needs.extend(
        {"measured": entry["key"], "label": entry["label"]}
        for entry in view["measured"]
        if entry["attribute"] in measured
        and entry["key"] not in given_measured
    )
    if include_links:
        needs.extend(
            {"link": role, "label": view["links"][role]["label"]}
            for role in link_order
            if role in roles and given_links.get(role) is None
        )
    return needs


def assess(
    lamina_id: str,
    entries: dict,
    links: dict | None = None,
    measured: dict | None = None,
) -> dict:
    """
    Run the view's results and flags on the figures a person entered.

    A fresh twin is built for every call: declared baselines are seeded, the
    given entries, links and recorded measurements are written, and the
    lamina's own chain is run with the echo silenced.  Nothing entered or
    measured is printed by this module.

    When the view declares horizons, one fresh twin is run per horizon value
    and one at the settled value: each result carries its series and settled
    value, ``planned`` is the last horizon's value, and the view's mediators
    are reported the same way.  Without horizons the answer is the pair of
    outcomes as before.  Every refusal names the field and the range it
    accepts.
    """
    with _quiet():
        twin = load_twin(resolve_lamina(lamina_id))
        view = twin.assessment_view
        if view is None:
            raise NoAssessmentView(lamina_id)

        entry_by_id, entry_order, link_by_attribute, link_order = (
            _view_indexes(view)
        )
        measured_by_attribute = {
            entry["attribute"]: entry for entry in view["measured"]
        }
        measured_by_key = {
            entry["key"]: entry for entry in view["measured"]
        }
        given = _clean_entries(entries, entry_by_id, entry_order)
        given_links = _clean_links(links, view, twin)
        given_measured = _clean_measured(measured, view, twin)
        horizons = view["horizons"]

        def fresh(weeks_value=None):
            """A fresh, seeded twin at one horizon (or with no horizon)."""
            fresh_twin = load_twin(resolve_lamina(lamina_id))
            for attribute_id in fresh_twin.list_attributes(SENSOR):
                attribute = fresh_twin.attributes[attribute_id]
                if attribute.baseline is not None:
                    fresh_twin.set_sensor(
                        attribute_id, float(attribute.baseline)
                    )
            for attribute_id, value in given.items():
                fresh_twin.set_sensor(attribute_id, value)
            for role, value in given_links.items():
                if value is None:
                    continue
                fresh_twin.set_inter_lamina(
                    view["links"][role]["attribute"],
                    value,
                    provenance={"role": role},
                )
            for key, value in given_measured.items():
                fresh_twin.set_inter_lamina(
                    measured_by_key[key]["attribute"],
                    value,
                    provenance={"measured": key},
                )
            if weeks_value is not None:
                fresh_twin.set_sensor(
                    horizons["attribute"], float(weeks_value)
                )
            fresh_twin.compute_all()
            return fresh_twin

        if horizons is not None:
            horizon_twins = {
                weeks: fresh(weeks) for weeks in horizons["values"]
            }
            settled_twin = fresh(horizons["settled"])
            now_twin = horizon_twins[horizons["values"][0]]
        else:
            horizon_twins = {}
            settled_twin = None
            now_twin = fresh()

        chain_functions: dict[str, object] = {}
        results = []
        for result in view["results"]:
            now_chain = _dependency_chain(
                twin, entry_by_id, link_by_attribute, [result["now"]],
                measured_by_attribute,
            )
            planned_chain = _dependency_chain(
                twin, entry_by_id, link_by_attribute, [result["planned"]],
                measured_by_attribute,
            )
            functions = dict(now_chain[0])
            functions.update(planned_chain[0])
            chain_functions.update(functions)

            not_applicable = None
            when = result.get("not_applicable_when")
            if when is not None and given.get(when) == 1.0:
                not_applicable = result.get("not_applicable_text")

            now_raw = None if not_applicable else _raw_value(
                now_twin, result["now"]
            )
            if horizons is not None:
                series_raw = [
                    None if not_applicable
                    else _raw_value(horizon_twins[weeks], result["planned"])
                    for weeks in horizons["values"]
                ]
                settled_raw = (
                    None if not_applicable
                    else _raw_value(settled_twin, result["planned"])
                )
                planned_raw = series_raw[-1]
            else:
                series_raw = None
                settled_raw = None
                planned_raw = None if not_applicable else _raw_value(
                    now_twin, result["planned"]
                )
            if not_applicable:
                needs_now: list[dict] = []
                needs_planned: list[dict] = []
            else:
                needs_now = _missing(
                    now_chain, given, given_links, given_measured,
                    entry_by_id, entry_order, link_order, view,
                    include_links=False,
                )
                needs_planned = _missing(
                    planned_chain, given, given_links, given_measured,
                    entry_by_id, entry_order, link_order, view,
                    include_links=True,
                )

            refused = (
                (now_raw is None and not needs_now)
                or (planned_raw is None and not needs_planned)
            )
            reason = (
                _REFUSED_REASON
                if refused and not not_applicable
                else None
            )

            change = None
            if (
                now_raw is not None
                and planned_raw is not None
                and now_raw > 0.0
            ):
                change = {
                    "points": _r(planned_raw - now_raw),
                    "relative_pct": _r(
                        100.0 * (planned_raw - now_raw) / now_raw
                    ),
                }

            entry = {
                "id": result["id"],
                "label": result["label"],
                "period": result["period"],
                "unit": result["unit"],
                "status": _weakest_status(functions.values()),
                "models": [_model(function)
                           for function in _ordered_models(functions)],
                "now": _r(now_raw),
                "planned": _r(planned_raw),
                "change": change,
                "not_applicable": not_applicable,
                "needs": {"now": needs_now, "planned": needs_planned},
                "reason": reason,
            }
            if horizons is not None:
                entry["series"] = [
                    {"weeks": weeks, "value": _r(value)}
                    for weeks, value in zip(horizons["values"], series_raw)
                ]
                entry["settled"] = _r(settled_raw)
            results.append(entry)

        flags = []
        for flag in view["flags"]:
            chain = _dependency_chain(
                twin, entry_by_id, link_by_attribute, [flag["attribute"]],
                measured_by_attribute,
            )
            chain_functions.update(chain[0])
            value = _raw_value(now_twin, flag["attribute"])
            if value is None:
                state = "not_answered"
            elif value == 1.0:
                state = "raised"
            else:
                state = "clear"
            flags.append({
                "attribute": flag["attribute"],
                "topic": flag["topic"],
                "label": flag["label"],
                "text": flag["text"],
                "status": _weakest_status(chain[0].values()),
                "state": state,
                "needs": _missing(
                    chain, given, given_links, given_measured, entry_by_id,
                    entry_order, link_order, view, include_links=True,
                ),
            })

        mediators = []
        if horizons is not None:
            for mediator in view["mediators"]:
                chain = _dependency_chain(
                    twin, entry_by_id, link_by_attribute, [mediator["at"]],
                    measured_by_attribute,
                )
                chain_functions.update(chain[0])
                value_now_raw = _raw_value(now_twin, mediator["now"])
                series_raw = [
                    _raw_value(horizon_twins[weeks], mediator["at"])
                    for weeks in horizons["values"]
                ]
                settled_raw = _raw_value(settled_twin, mediator["at"])
                if value_now_raw is None:
                    moves = True
                else:
                    moves = any(
                        value is None
                        or abs(value - value_now_raw) > 1e-9
                        for value in series_raw + [settled_raw]
                    )
                mediators.append({
                    "now": mediator["now"],
                    "label": mediator["label"],
                    "unit": mediator["unit"],
                    "source": mediator["source"],
                    "key": mediator["key"],
                    "still": mediator["still"],
                    "status": _weakest_status(chain[0].values()),
                    "value_now": _r(value_now_raw),
                    "series": [
                        {"weeks": weeks, "value": _r(value)}
                        for weeks, value in zip(
                            horizons["values"], series_raw
                        )
                    ],
                    "settled": _r(settled_raw),
                    "moves": moves,
                    "needs": _missing(
                        chain, given, given_links, given_measured,
                        entry_by_id, entry_order, link_order, view,
                        include_links=False,
                    ),
                })

        notice = (
            PLACEHOLDER_NOTICE
            if any(function.status == "placeholder"
                   for function in chain_functions.values())
            else None
        )

        answer = {
            "lamina": twin.lamina_id,
            "entered": {"given": len(given), "of": len(entry_order)},
            "links": {role: given_links.get(role) for role in link_order},
            "range": _range_view(twin, view),
            "results": results,
            "flags": flags,
            "notice": notice,
        }
        if horizons is not None:
            answer["mediators"] = mediators
            answer["horizons"] = horizons
        return answer
