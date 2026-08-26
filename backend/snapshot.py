"""
Shared snapshot + kernel-state helpers.

Extracted from main.py so Session (session.py) and the Phase 3
WebSocket layer can reuse them without importing the full FastAPI app.
"""
from __future__ import annotations

from typing import Any, Dict

from universal_twin import INTER_LAMINA, PRELIMINARY, SENSOR

# Wire-format separator for kernel_state keys.  Tuples don't survive
# JSON, so "(tag_id, attr_id)" becomes "tag_id|attr_id" on the wire.
# Pipe is safe because neither tag ids nor attribute ids contain it.
_KSTATE_SEP = "|"

# What the snapshot says about an INTER_LAMINA attribute nothing has
# coupled to yet (G9).  The value beside it is the baseline the domain
# expert declared, and it is indistinguishable from a live coupled value
# unless the payload says which it is — the same failure mode as a stale
# computed value looking live, one layer up.
_UNCOUPLED = {"state": "uncoupled", "detail": "baseline (uncoupled)"}


def _attr_entry(attr) -> Dict[str, Any]:
    """The value columns every attribute carries, whatever its source."""
    return {
        "value":          attr.value,
        "value_external": attr.value_external,
        "value_feedback": attr.value_feedback,
        "normalised":     attr.normalised,
        "unit":           attr.unit,
        "name":           attr.name,
    }


def _simulation_snapshot(twin) -> Dict[str, Any]:
    """
    Return the same payload shape as /api/compute — attribute split,
    composite vectors, outcomes, feedback_norm, warnings.
    """
    sensors_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes(SENSOR):
        sensors_out[attr_id] = _attr_entry(twin.attributes[attr_id])

    # Inter-lamina inputs get their own section rather than joining
    # `sensors`.  Both are X' this lamina did not compute, but "sensor"
    # carries a specific claim — measured, from a device, sacred because
    # it is ground truth — and widening it to mean "anything I did not
    # compute" would erase the distinction the whole coupling design is
    # built on (G1).  A consumer that wants every input reads both keys;
    # one that wants readings reads `sensors` and still gets readings.
    inbound_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes(INTER_LAMINA):
        attr = twin.attributes[attr_id]
        entry = _attr_entry(attr)
        entry["provenance"] = (
            {"state": "coupled", **attr.provenance}
            if attr.provenance else dict(_UNCOUPLED)
        )
        inbound_out[attr_id] = entry

    # `stale` and `error` are the other half of the fix the warnings list
    # started.  A warning says something went wrong somewhere; these say
    # WHICH number you should stop believing, which is what a value
    # renderer needs in order to draw it differently.  stale is True when
    # this attribute did not compute on the last pass — the value beside
    # it is either last cycle's or absent, never this cycle's.
    failed = twin.failed_attributes
    computed_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes(PRELIMINARY):
        attr = twin.attributes[attr_id]
        entry = _attr_entry(attr)
        entry["stale"] = attr_id in failed
        entry["error"] = failed.get(attr_id)
        computed_out[attr_id] = entry

    # `ERROR computing` matters as much as a gate here, and used to be dropped.
    # When a function raises, `_resolve` logs and moves on: the attribute keeps
    # whatever it held last cycle and every consumer — the visualiser included —
    # sees a number that looks live and is not being computed. The log line is
    # what tells a reader what broke; the per-attribute `stale` flag above is
    # what tells the screen which value to stop drawing as live.
    warnings = [line for line in twin.get_log()
                if "GATE FAIL" in line
                or "GATE SOFT" in line
                or "ERROR computing" in line
                or "No function registered" in line]
    return {
        # Which lamina produced these numbers.  A page fetches its structure
        # once and then reads values off a socket forever; without this the two
        # halves cannot be checked against each other, and a stream that starts
        # sending another lamina's values looks exactly like the one that was
        # asked for.  One line here is what makes that detectable at all.
        "lamina_id":     twin.lamina_id,
        "sensors":       sensors_out,
        "inbound":       inbound_out,
        "computed":      computed_out,
        "vectors":       twin.get_all_vectors(),
        "absorption":    twin.get_all_absorbed_vectors(),
        "outcomes":      twin.evaluate_all_outcomes(),
        "feedback_norm": twin.feedback_norm(),
        "warnings":      warnings,
    }


def _flat_outcomes(outcome_evaluations: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten {segment_id: [feedback_obj]} → {outcome_id: feedback_obj}."""
    flat: Dict[str, Any] = {}
    for seg_outcomes in outcome_evaluations.values():
        for fb in seg_outcomes:
            flat[fb["outcome_id"]] = fb
    return flat


def before_after_outcomes(twin) -> Dict[str, Any]:
    """
    Shadow-pass baseline: for every behavioural outcome, return the value
    WITH the feedback loop ("after") alongside the value the chain would
    have produced WITHOUT any feedback ("before", X'' = 0 everywhere).

    The before/after difference is exactly what the loop achieved this
    tick — the same framing as DEMO.md's before/after table.  Because the
    whole chain is recomputed with feedback zeroed, coupling such as
    CO = HR·SV is reflected: a correction that lands on SV shows up in the
    CO row too, which a per-attribute value_external diff cannot capture.

    Pure with respect to twin state: the feedback channel is saved, zeroed,
    used for one recompute, then restored and recomputed, so the twin is
    byte-for-byte where it started when this returns.  Cost is two extra
    compute_all() passes per tick — cheap at streaming cadence.

    Payload is self-contained (target, tolerance, physio range) so the
    frontend panel needs nothing from the schema endpoint.
    """
    # AFTER = current settled state (feedback applied).
    after = _flat_outcomes(twin.evaluate_all_outcomes())

    # Snapshot then zero the X'' channel on every attribute (D12 keeps
    # sensors at 0 anyway; saving/restoring them is harmless).
    saved = {aid: a.value_feedback for aid, a in twin.attributes.items()}
    for a in twin.attributes.values():
        a.value_feedback = 0.0
        a.normalise()
    twin.compute_all()
    before = _flat_outcomes(twin.evaluate_all_outcomes())

    # Restore the exact feedback channel and re-derive the chain.
    for aid, a in twin.attributes.items():
        a.value_feedback = saved[aid]
        a.normalise()
    twin.compute_all()

    out: Dict[str, Any] = {}
    for seg in twin.segments.values():
        for outcome in seg.behavioural_outcomes:
            oid = outcome.id
            attr = twin.attributes.get(outcome.attribute_id)
            fb_after = after.get(oid)
            fb_before = before.get(oid)
            if attr is None or fb_after is None or fb_before is None:
                continue
            out[oid] = {
                "attribute_id":  outcome.attribute_id,
                "unit":          outcome.unit,
                "target":        outcome.target_value,
                "tolerance":     outcome.tolerance,
                "physio_min":    attr.physio_min,
                "physio_max":    attr.physio_max,
                "before":        fb_before["actual"],
                "after":         fb_after["actual"],
                "x_pp":          round(attr.value_feedback, 4),
                "within_after":  fb_after["within_tolerance"],
            }
    return out


def _serialize_kernel_state(controller) -> Dict[str, Dict[str, float]]:
    """Convert controller._kernel_state to a JSON-serialisable dict."""
    out: Dict[str, Dict[str, float]] = {}
    for (tag_id, attr_id), state in controller._kernel_state.items():
        if not state:
            continue  # skip empty slots (post-snap reset)
        key = f"{tag_id}{_KSTATE_SEP}{attr_id}"
        out[key] = {k: float(v) for k, v in state.items()}
    return out


def _restore_kernel_state(controller, wire: Dict[str, Dict[str, float]]) -> None:
    """
    Inject client-supplied state back into the controller dict and
    reconstruct value_feedback on every targeted attribute so the twin
    picks up exactly where the previous cycle left off.

    Per D11, value_feedback equals the sum of x_pp across all tags
    targeting that attribute — exactly what the wire format carries.
    """
    feedback_sum: Dict[str, float] = {}
    for key, state in wire.items():
        if _KSTATE_SEP not in key:
            continue
        tag_id, attr_id = key.split(_KSTATE_SEP, 1)
        controller._kernel_state[(tag_id, attr_id)] = dict(state)
        feedback_sum[attr_id] = (
            feedback_sum.get(attr_id, 0.0) + float(state.get("x_pp", 0.0))
        )

    for attr_id, total in feedback_sum.items():
        attr = controller.twin.attributes.get(attr_id)
        if attr is not None:
            attr.apply_feedback(total)

    # Re-derive PRELIMINARY so the chain reflects the restored X''.
    controller.twin.compute_all()
