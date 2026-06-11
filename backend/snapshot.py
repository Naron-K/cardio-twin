"""
Shared snapshot + kernel-state helpers.

Extracted from main.py so Session (session.py) and the Phase 3
WebSocket layer can reuse them without importing the full FastAPI app.
"""
from __future__ import annotations

from typing import Any, Dict

# Wire-format separator for kernel_state keys.  Tuples don't survive
# JSON, so "(tag_id, attr_id)" becomes "tag_id|attr_id" on the wire.
# Pipe is safe because neither tag ids nor attribute ids contain it.
_KSTATE_SEP = "|"


def _simulation_snapshot(twin) -> Dict[str, Any]:
    """
    Return the same payload shape as /api/compute — attribute split,
    composite vectors, outcomes, feedback_norm, warnings.
    """
    sensors_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes("SENSOR"):
        attr = twin.attributes[attr_id]
        sensors_out[attr_id] = {
            "value":          attr.value,
            "value_external": attr.value_external,
            "value_feedback": attr.value_feedback,
            "normalised":     attr.normalised,
            "unit":           attr.unit,
            "name":           attr.name,
        }

    computed_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes("PRELIMINARY"):
        attr = twin.attributes[attr_id]
        computed_out[attr_id] = {
            "value":          attr.value,
            "value_external": attr.value_external,
            "value_feedback": attr.value_feedback,
            "normalised":     attr.normalised,
            "unit":           attr.unit,
            "name":           attr.name,
        }

    warnings = [line for line in twin.get_log() if "GATE FAIL" in line]
    return {
        "sensors":       sensors_out,
        "computed":      computed_out,
        "vectors":       twin.get_all_vectors(),
        "absorption":    twin.get_all_absorbed_vectors(),
        "outcomes":      twin.evaluate_all_outcomes(),
        "feedback_norm": twin.feedback_norm(),
        "warnings":      warnings,
    }


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
