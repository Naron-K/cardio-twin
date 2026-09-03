"""
CardioTwin - FastAPI Backend
=============================
Wraps the UniversalTwin simulation engine in a REST API.

Endpoints:
  GET  /health          - Health check
  GET  /api/laminae     - List the laminae this backend can serve
  GET  /api/schema      - Return slider configs from XML schema (?lamina=<id>)
  POST /api/compute     - Run simulation with JSON sensor data
  POST /api/upload      - Upload patient XML file, run simulation
  POST /api/download    - Convert results to downloadable XML
  WS   /ws/feedback     - Stream one lamina (?lamina=<id>)
  WS   /ws/organism     - Stream a whole body (?organism=<file>)

Run:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import os
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure backend package is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from laminae import (
    LAMINA_DIR,
    UnknownLamina,
    available_laminae,
    lamina_path,
    load_twin,
    resolve_lamina,
)
from universal_twin import INTER_LAMINA, UniversalTwin
from feedback_controller import (
    FeedbackController,
    DEFAULT_EPSILON_RATIO,
    DEFAULT_MAX_NORM,
)
from organism import OrganismError, available_organisms, load_organism
from session import OrganismSession, Session
from signal_source import SimulatedSource
from streaming_runtime import StreamingRuntime
from snapshot import (
    _KSTATE_SEP,
    _simulation_snapshot,
    _serialize_kernel_state,
    _restore_kernel_state,
)
from universal_twin import resolve_polarity
from xml_converter import dict_to_patient_xml, patient_xml_to_dict, results_to_xml

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="CardioTwin API",
    description="Cardiovascular physiological digital twin simulation engine",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Path to the XML schema, relative to this file
# Which lamina this process is running.  Overridable via CARDIOTWIN_LAMINA so
# "point the backend at a different lamina and the visualiser follows" is a
# thing anyone can try rather than a claim in a document — the 2D view builds
# itself out of /api/schema and names no attribute of its own.  laminae.py
# pairs the file with the class holding its arithmetic.
SCHEMA_PATH = lamina_path()

# Path to presets folder (one level up from backend/)
PRESETS_PATH = Path(__file__).parent.parent / "presets"

# Serve preset XML files as static files at /presets/<name>.xml
if PRESETS_PATH.exists():
    app.mount("/presets", StaticFiles(directory=str(PRESETS_PATH)), name="presets")


# ── Pydantic Models ───────────────────────────────────────────────────────────

class ComputeRequest(BaseModel):
    sensor_data: Dict[str, float]


class DownloadRequest(BaseModel):
    results: Dict[str, Any]
    name: str = "Patient Scenario"


# ── Feedback loop models (Phase D) ────────────────────────────────────────────
#
# Stateless server contract: the client carries the kernel state and cycle
# counter across requests.  Each /api/feedback/step round-trip returns the
# updated state so the client (or its localStorage) can keep driving.
# /api/feedback/run is the batched alternative — runs N cycles in one shot
# and returns the final state plus a per-cycle trace.
#
# kernel_state on the wire uses "tag_id|attr_id" string keys instead of
# Python tuples so it round-trips through JSON without ceremony.

class TagOverride(BaseModel):
    """Per-tag knobs the client can twiddle without editing the XML."""
    polarity: Optional[Any] = None          # accepts "negative"/"positive"/number
    params:   Optional[Dict[str, float]] = None


class FeedbackConfig(BaseModel):
    """Per-request controller knobs.  All optional — defaults come from the
    feedback_controller module constants."""
    max_norm:      float = Field(default=DEFAULT_MAX_NORM,
                                 description="Circuit breaker — abort cycle when feedback_norm exceeds.")
    epsilon_ratio: float = Field(default=DEFAULT_EPSILON_RATIO,
                                 description="Snap dead-zone as a fraction of physio range (D3).")


class FeedbackStepRequest(BaseModel):
    sensor_data:   Dict[str, float]
    kernel_state:  Dict[str, Dict[str, float]] = Field(default_factory=dict,
                       description='Carry across requests. Keys "tag_id|attr_id".')
    cycle:         int = Field(default=0, description="Cycle counter from the previous response.")
    config:        FeedbackConfig = Field(default_factory=FeedbackConfig)
    tag_overrides: Dict[str, TagOverride] = Field(default_factory=dict)


class FeedbackRunRequest(BaseModel):
    sensor_data:        Dict[str, float]
    kernel_state:       Dict[str, Dict[str, float]] = Field(default_factory=dict)
    cycle:              int = Field(default=0)
    cycles:             int = Field(default=100, ge=1, le=10000,
                                     description="Maximum cycles to run.")
    settled_threshold:  Optional[float] = Field(default=None,
                            description="D14 early stop: norm below this for settled_window cycles.")
    settled_window:     int = Field(default=5, ge=1, le=100)
    config:             FeedbackConfig = Field(default_factory=FeedbackConfig)
    tag_overrides:      Dict[str, TagOverride] = Field(default_factory=dict)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_simulation(sensor_data: Dict[str, float]) -> Dict[str, Any]:
    """
    Initialise a fresh twin for the loaded lamina, feed sensor values,
    run compute_all(), and return a structured results dict.
    """
    twin = load_twin(SCHEMA_PATH)

    # Feed each sensor value
    for attr_id, value in sensor_data.items():
        try:
            twin.set_sensor(attr_id, value)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail={
                "error": str(e),
                "type": type(e).__name__,
                "field": attr_id,
                "timestamp": datetime.now().isoformat(),
            })

    # Run the full computation chain
    twin.compute_all()

    # Collect sensor values (with normalised)
    #
    # Phase A response shape: every attribute now exposes the X = X' + X''
    # decomposition.  `value` stays as the combined view for back-compat
    # with the frontend; `value_external` and `value_feedback` are the
    # two channels per FEEDBACK_LOOP_PLAN.md §2.1.  In Phase A
    # value_feedback is always 0.0 (no kernel runs yet), so the frontend
    # sees identical numbers but can already plan stacked-bar rendering
    # for Phase F.
    sensors_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes("SENSOR"):
        attr = twin.attributes[attr_id]
        sensors_out[attr_id] = {
            "value": attr.value,
            "value_external": attr.value_external,
            "value_feedback": attr.value_feedback,
            "normalised": attr.normalised,
            "unit": attr.unit,
            "name": attr.name,
        }

    # Inter-lamina inputs — X' this lamina did not compute and did not
    # measure either.  Kept out of `sensors` for the reason spelled out in
    # snapshot.py: widening "sensor" to mean "anything I did not compute"
    # erases the distinction the coupling design rests on (G1).
    inbound_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes(INTER_LAMINA):
        attr = twin.attributes[attr_id]
        inbound_out[attr_id] = {
            "value": attr.value,
            "value_external": attr.value_external,
            "value_feedback": attr.value_feedback,
            "normalised": attr.normalised,
            "unit": attr.unit,
            "name": attr.name,
            "provenance": (
                {"state": "coupled", **attr.provenance}
                if attr.provenance
                else {"state": "uncoupled", "detail": "baseline (uncoupled)"}
            ),
        }

    # Collect computed (preliminary) values
    #
    # `stale` / `error` mirror _simulation_snapshot() in snapshot.py — this
    # endpoint builds its own dict rather than sharing that one, so the two
    # have to be kept in step by hand.  Both carry it because a client
    # reading either one has the same problem: a value that failed to
    # compute looks exactly like a value that computed fine (0-C).
    failed = twin.failed_attributes
    computed_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes("PRELIMINARY"):
        attr = twin.attributes[attr_id]
        computed_out[attr_id] = {
            "value": attr.value,
            "value_external": attr.value_external,
            "value_feedback": attr.value_feedback,
            "normalised": attr.normalised,
            "unit": attr.unit,
            "name": attr.name,
            "stale": attr_id in failed,
            "error": failed.get(attr_id),
        }

    # Collect gate warnings (hard fails + soft out-of-range monitors)
    warnings = [line for line in twin.get_log()
                if "GATE FAIL" in line or "GATE SOFT" in line]

    # Collect composite vectors
    vectors = twin.get_all_vectors()

    return {
        "sensors":    sensors_out,
        "inbound":    inbound_out,
        "computed":   computed_out,
        "vectors":    vectors,
        "absorption": twin.get_all_absorbed_vectors(),
        "outcomes":   twin.evaluate_all_outcomes(),
        "warnings":   warnings,
        "log":        twin.get_log(),
    }


# ── Feedback loop helpers (Phase D) ───────────────────────────────────────────
# _KSTATE_SEP, _simulation_snapshot, _serialize_kernel_state, and
# _restore_kernel_state now live in snapshot.py (shared with Session).


def _apply_tag_overrides(twin: UniversalTwin,
                          overrides: Dict[str, "TagOverride"]):
    """
    Mutate the parsed Tag registry in place per client overrides.

    Domain experts can change a tag's polarity or kernel params without
    editing XML — useful for the frontend's "what if I disable Q tag"
    or "what if I bump gain" interactions.  Unknown tag ids are ignored
    (defensive — frontend might still hold stale tag ids while XML
    evolves on the backend).
    """
    for tag_id, ov in overrides.items():
        tag = twin.tags.get(tag_id)
        if tag is None:
            continue
        if ov.polarity is not None:
            try:
                tag.polarity = resolve_polarity(ov.polarity)
            except ValueError as e:
                raise HTTPException(status_code=400, detail={
                    "error": f"tag '{tag_id}': {e}",
                    "type": "ValidationError",
                    "field": f"tag_overrides.{tag_id}.polarity",
                    "timestamp": datetime.now().isoformat(),
                })
        if ov.params:
            # Merge, don't replace — keep XML-defined keys the client
            # didn't touch.
            tag.params = {**tag.params, **ov.params}


def _build_feedback_twin(sensor_data: Dict[str, float],
                          tag_overrides: Dict[str, "TagOverride"]) -> UniversalTwin:
    """
    Fresh twin per request (stateless server).  Applies sensor values
    and any tag overrides before the controller is wired up.
    """
    twin = load_twin(SCHEMA_PATH)
    _apply_tag_overrides(twin, tag_overrides)

    for attr_id, value in sensor_data.items():
        try:
            twin.set_sensor(attr_id, value)
        except (KeyError, ValueError) as e:
            raise HTTPException(status_code=400, detail={
                "error": str(e),
                "type": type(e).__name__,
                "field": attr_id,
                "timestamp": datetime.now().isoformat(),
            })

    # Initial compute_all so PRELIMINARY attributes have a value
    # before the first feedback cycle reads them.
    twin.compute_all()
    return twin


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Health check."""
    return {"status": "ok", "timestamp": datetime.now().isoformat()}


def _resolve_or_400(lamina: Optional[str]) -> Path:
    """
    Turn a requested lamina id into a file, or refuse by name.

    Refusing matters more than it looks.  Falling back to the default for an
    id nobody serves would hand back a schema for a lamina the caller did not
    ask for, which is the exact mismatch this parameter exists to prevent —
    and it would arrive looking like a success.
    """
    try:
        return resolve_lamina(lamina)
    except UnknownLamina as e:
        raise HTTPException(status_code=404, detail={
            "error": str(e),
            "requested": e.lamina_id,
            "available": e.available,
            "timestamp": datetime.now().isoformat(),
        })


@app.get("/api/laminae")
def get_laminae():
    """
    Every lamina this backend can serve, and whether its maths is written.

    The picker in the UI is built from this rather than from a list typed into
    the frontend: adding a lamina is dropping an XML file into `backend/`, and
    it should show up without a second edit somewhere else.  `default` is the
    one a request that names none will get.
    """
    print("[LOG] GET /api/laminae")
    laminae = available_laminae()
    default_id = ""
    for entry in laminae:
        if (LAMINA_DIR / entry["file"]).resolve() == SCHEMA_PATH.resolve():
            default_id = entry["id"]
            break
    return {"laminae": laminae, "default": default_id}


@app.get("/api/organisms")
def get_organisms():
    """
    Every body this backend can serve, and which one a request that names
    none will get.

    The picker is built from this rather than from a list typed into the
    frontend, for the same reason `/api/laminae` exists: adding a body is
    dropping an XML file into `backend/`, and it should show up without a
    second edit somewhere else. Two bodies over the same laminae is the
    normal case rather than an exotic one — organism.xml opens its seam on
    a value leaving its band, organism_key.xml on a recognised state of the
    pump, and comparing them is the point.
    """
    print("[LOG] GET /api/organisms")
    bodies = available_organisms()
    return {
        "organisms": bodies,
        "default": next((b["id"] for b in bodies if b["default"]), ""),
    }


@app.get("/api/organism")
def get_organism(organism: Optional[str] = Query(
        default=None,
        description="Path to an organism file; omit for backend/organism.xml.")):
    """
    The body-level declaration: which laminae, and the seams between them.

    The counterpart of `/api/schema`, one level up.  A page fetches its
    structure here once and then reads live values off `/ws/organism`
    forever, exactly the way a single-lamina page uses `/api/schema` and
    `/ws/feedback`.  Which means this endpoint answers "what is this body
    made of" and never "what is it doing" — every number in the response
    is a declared one.

    Gates come back fully resolved rather than as raw XML attributes,
    including the two boundaries and the transfer settings, because the
    thing that reads this has to draw a valve and label it, and a reader
    that has to re-derive the controller's contract from attribute names
    is a reader that will get it wrong in a different way from the
    backend.

    The laminae are loaded, not merely listed: rules 2 and 3 can only be
    checked against what the laminae actually declare, so an organism
    that names a composite nobody has is refused here rather than at the
    first tick of a socket somebody already opened.
    """
    print(f"[LOG] GET /api/organism  organism={organism or '(default)'}")
    try:
        spec, twins = load_organism(organism)
    except (OrganismError, FileNotFoundError, ET.ParseError) as e:
        raise HTTPException(status_code=404 if isinstance(e, FileNotFoundError)
                            else 400,
                            detail={
                                "error": str(e),
                                "type": type(e).__name__,
                                "requested": organism,
                                "timestamp": datetime.now().isoformat(),
                            })

    return {
        "organism_id": spec.id,
        "version":     spec.version,
        "name":        spec.name,
        "description": spec.description,
        "laminae": [
            {
                "id":         lamina_id,
                "name":       twins[lamina_id].lamina_name,
                "sensors":    twins[lamina_id].list_attributes("SENSOR"),
                "inbound":    twins[lamina_id].list_attributes(INTER_LAMINA),
                "composites": sorted(twins[lamina_id].composites),
            }
            for lamina_id in spec.lamina_ids
        ],
        "gates": [
            {
                "id":          gate.id,
                "from":        str(gate.source),
                "to":          str(gate.dest),
                "from_lamina": gate.source.lamina,
                "from_member": gate.source.member,
                "to_lamina":   gate.dest.lamina,
                "to_member":   gate.dest.member,
                "controller":  gate.controller,
                "extract":     gate.extract,
                "description": gate.description,
                # Rule 1, as a value the reader can show rather than a
                # promise it has to take on trust.
                "starts_closed": gate.starts_closed,
                "controller_params": gate.controller_args(),
                "transfer": {
                    "mode":       gate.transfer.mode,
                    "rate":       gate.transfer.rate,
                    "time_delay": gate.transfer.time_delay,
                    "on_close":   gate.transfer.on_close,
                    "confidence": gate.transfer.confidence,
                    "band_min":   gate.transfer.band_min,
                    "band_max":   gate.transfer.band_max,
                },
                "learnables": [
                    {"name": lrn.name, "initial": lrn.initial,
                     "min": lrn.min, "max": lrn.max}
                    for lrn in gate.learnables
                ],
            }
            for gate in spec.gates
        ],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/api/schema")
def get_schema(lamina: Optional[str] = Query(default=None,
                                             description="Lamina id; omit for the process default.")):
    """
    Return the full schema for one lamina.

    The lamina is a property of the request, not of the process: two tabs can
    hold two laminae at once, and a page can move between them without the
    backend restarting.  `CARDIOTWIN_LAMINA` remains the default for a request
    that names none.

    Response includes:
      - attributes: slider configs (id, name, unit, physio_min, physio_max, source)
      - composites: grouping definitions for charts
      - functions: step-ordered computation models
    """
    print(f"[LOG] GET /api/schema  lamina={lamina or '(default)'}")
    path = _resolve_or_400(lamina)
    try:
        twin = load_twin(path)
    except Exception as e:
        print(f"[ERROR] Failed to load schema: {e}")
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })

    attributes = {}
    for attr_id, attr in twin.attributes.items():
        attributes[attr_id] = {
            "id": attr.id,
            "name": attr.name,
            "unit": attr.unit,
            "source": attr.source,
            "physio_min": attr.physio_min,
            "physio_max": attr.physio_max,
            "description": attr.description,
            "computed_by": attr.computed_by,
            "depends_on": attr.depends_on,
            # Where a synthetic feed rests, and how far it wanders.  Exposed
            # because a control needs to show the value that was *set*, not the
            # jittered reading coming back — conflating the two makes a slider
            # look like it is fighting whoever drags it.  None where the lamina
            # declares nothing.
            "baseline": attr.baseline,
            "noise_sigma": attr.noise_sigma,
        }

    composites = {}
    for comp_id, comp in twin.composites.items():
        composites[comp_id] = {
            "id": comp.id,
            "name": comp.name,
            "attribute_ids": comp.attribute_ids,
            "description": comp.description,
            # Two parallel vectors (D2).  absorption_vector drives the
            # frozen learning loop; distribution_vector is the gate
            # fanout multiplier read by the Phase C feedback kernel.
            "absorption_vector": comp.absorption_vector.tolist() if comp.absorption_vector is not None else None,
            "distribution_vector": comp.distribution_vector.tolist() if comp.distribution_vector is not None else None,
        }

    functions = [
        {
            "id": f.id,
            "name": f.name,
            "step": f.step,
            "formula": f.formula,
            "inputs": f.inputs,
            "output": f.output,
            "description": f.description,
        }
        for f in sorted(twin.functions.values(), key=lambda fn: fn.step)
    ]

    segments = {}
    for seg_id, seg in twin.segments.items():
        segments[seg_id] = {
            "id": seg.id,
            "name": seg.name,
            "attribute_ids": seg.attribute_ids,
            "composite_ids": seg.composite_ids,
            "function_ids": seg.function_ids,
            "description": seg.description,
            "behavioural_outcomes": [
                {
                    "id":           o.id,
                    "name":         o.name,
                    "attribute_id": o.attribute_id,
                    "target_value": o.target_value,
                    "tolerance":    o.tolerance,
                    "unit":         o.unit,
                    "description":  o.description,
                }
                for o in seg.behavioural_outcomes
            ],
        }

    # Permeability gates.  Parsed from <gates> since v1 but never
    # exposed, which left the visualiser unable to show a condition the
    # model genuinely enforces — and pushed anyone who wanted one into
    # typing a threshold into the UI instead.  Serialised verbatim: a
    # gate is domain-expert knowledge declared in XML, and the frontend
    # renders it without holding a second opinion about it.
    gates = [
        {
            "attribute":      g.attribute,
            "gate_type":      g.gate_type,
            "min":            g.min_val,
            "max":            g.max_val,
            "tolerance":      g.tolerance,
            "compare":        g.compare,
            "action_on_fail": g.action_on_fail,
            "flag":           g.flag,
            "steepness":      g.steepness,
        }
        for g in twin.gates
    ]

    # Phase B: expose feedback tag bindings so the frontend (Phase F)
    # can list them.  Polarity is serialised as a float per D7 — the
    # frontend can derive the friendly label client-side if it wants.
    tags = {}
    for tag_id, tag in twin.tags.items():
        tags[tag_id] = {
            "id":             tag.id,
            "outcome":        tag.outcome,
            "deviation_type": tag.deviation_type,
            "emitter":        tag.emitter,
            "gate_kernel":    tag.gate_kernel,
            "polarity":       tag.polarity,
            "targets": [
                {"address": t.address, "weight": t.weight}
                for t in tag.targets
            ],
            "params":         tag.params,
        }

    return {
        "lamina_name": twin.lamina_name,
        "lamina_id": twin.lamina_id,
        "lamina_level": twin.lamina_level,
        "upper_lamina_id": twin.upper_lamina_id,
        "lower_lamina_id": twin.lower_lamina_id,
        "attributes": attributes,
        "composites": composites,
        "functions": functions,
        "segments": segments,
        "channel_mappings": twin.channel_mappings,
        # Phase A: expose the feedback loop selection so the frontend
        # (Phase F) knows which coupling/solver to render.  Defaults
        # apply when the XML omits the optional blocks.
        "feedback_config": {
            "coupling_type": twin.coupling_type,
            "behaviour_solver_type": twin.behaviour_solver_type,
            "behaviour_solver_dt": twin.behaviour_solver_dt,
            "behaviour_solver_unit": twin.behaviour_solver_unit,
            "adaptation_kernel": twin.adaptation_kernel_type,
            "slow_loop_cadence": twin.slow_loop_cadence,
            "adaptation_params": twin.adaptation_params,
        },
        # Phase B: tag registry for the feedback pipeline.
        "tags": tags,
        "gates": gates,
        # What the engine can do, as opposed to what this lamina picked.
        # Every mechanism in the pipeline is a named entry in a registry
        # that the XML selects by name; without this list a reader sees
        # "gate_kernel=sigmoid_leaky_tanh" with no way to know whether
        # that was a choice or the only option.  Names only — the
        # callables stay server-side.
        "registries": {
            "function":          sorted(twin._function_registry.keys()),
            "coupling":          sorted(twin._coupling_registry.keys()),
            "deviation":         sorted(twin._deviation_registry.keys()),
            "emitter":           sorted(twin._emitter_registry.keys()),
            "gate_kernel":       sorted(twin._gate_kernel_registry.keys()),
            "solver":            sorted(twin._solver_registry.keys()),
            "adaptation_kernel": sorted(twin._adaptation_kernel_registry.keys()),
        },
    }


@app.post("/api/compute")
def compute(request: ComputeRequest):
    """
    Run the cardiovascular simulation with JSON sensor data.

    Request body:
        {"sensor_data": {"SBP": 120, "DBP": 80, "HR": 72, ...}}

    Response:
        {
            "sensors": {attr_id: {value, normalised, unit, name}},
            "computed": {attr_id: {value, normalised, unit, name}},
            "vectors": {composite_id: {attr_id: normalised_value}},
            "warnings": ["GATE FAIL: ..."],
            "log": [...]
        }
    """
    print(f"[LOG] POST /api/compute — {len(request.sensor_data)} sensors")
    try:
        result = _run_simulation(request.sensor_data)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Compute failed: {e}")
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })


# ── Feedback loop endpoints (Phase D) ─────────────────────────────────────────

@app.post("/api/feedback/step")
def feedback_step(request: FeedbackStepRequest):
    """
    Run ONE feedback cycle.

    Stateless contract — the client carries kernel_state and the cycle
    counter across requests.  Submit kernel_state={} (default) for a
    fresh start, then keep round-tripping the value returned in
    `kernel_state_out` to continue the loop.

    Response shape:
      {
        "cycle":           int,                 # new cycle counter
        "cycle_report":    CycleReport,         # tags, deltas, norm, snap, etc.
        "state":           SimulationSnapshot,  # same shape as /api/compute
        "kernel_state":    {"tag|attr": {...}}, # round-trip for next request
        "diverged":        bool                 # circuit breaker fired
      }
    """
    print(f"[LOG] POST /api/feedback/step — cycle in={request.cycle}  "
          f"state_keys={len(request.kernel_state)}")
    try:
        twin = _build_feedback_twin(request.sensor_data, request.tag_overrides)
        ctrl = FeedbackController(
            twin,
            epsilon_ratio=request.config.epsilon_ratio,
            max_norm=request.config.max_norm,
        )
        _restore_kernel_state(ctrl, request.kernel_state)
        ctrl.cycle = request.cycle  # continue from client-supplied counter

        report = ctrl.step()

        return {
            "cycle":         ctrl.cycle,
            "cycle_report":  report,
            "state":         _simulation_snapshot(twin),
            "kernel_state":  _serialize_kernel_state(ctrl),
            "diverged":      report["diverged"],
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] /api/feedback/step failed: {e}")
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })


@app.post("/api/feedback/run")
def feedback_run(request: FeedbackRunRequest):
    """
    Batch N feedback cycles in one request.

    Stops early when either:
      - circuit breaker fires (diverged), or
      - feedback_norm stays below `settled_threshold` for `settled_window`
        consecutive cycles (D14 — when settled_threshold is provided), or
      - `cycles` exhausted.

    Response shape:
      {
        "cycles_run":     int,
        "stopped_reason": "settled" | "max_cycles" | "diverged",
        "cycle":          int,                   # final cycle counter
        "trace":          [CycleReport, ...],    # one per cycle
        "state":          SimulationSnapshot,    # final state
        "kernel_state":   {"tag|attr": {...}},   # for client continuation
        "diverged":       bool
      }
    """
    print(f"[LOG] POST /api/feedback/run — max={request.cycles}  "
          f"settled_threshold={request.settled_threshold}  "
          f"window={request.settled_window}  "
          f"state_keys={len(request.kernel_state)}")
    try:
        twin = _build_feedback_twin(request.sensor_data, request.tag_overrides)
        ctrl = FeedbackController(
            twin,
            epsilon_ratio=request.config.epsilon_ratio,
            max_norm=request.config.max_norm,
        )
        _restore_kernel_state(ctrl, request.kernel_state)
        ctrl.cycle = request.cycle

        reports = ctrl.run(
            n_cycles=request.cycles,
            settled_threshold=request.settled_threshold,
            settled_window=request.settled_window,
        )

        if not reports:
            stopped_reason = "max_cycles"
        elif reports[-1]["diverged"]:
            stopped_reason = "diverged"
        elif (request.settled_threshold is not None
              and len(reports) < request.cycles):
            stopped_reason = "settled"
        else:
            stopped_reason = "max_cycles"

        return {
            "cycles_run":     len(reports),
            "stopped_reason": stopped_reason,
            "cycle":          ctrl.cycle,
            "trace":          reports,
            "state":          _simulation_snapshot(twin),
            "kernel_state":   _serialize_kernel_state(ctrl),
            "diverged":       bool(reports and reports[-1]["diverged"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] /api/feedback/run failed: {e}")
        raise HTTPException(status_code=500, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """
    Upload a patient XML file and run the simulation.

    Accepts: .xml file with <patient><sensor_data>...</sensor_data></patient> structure.
    Returns: Same format as /api/compute.
    """
    print(f"[LOG] POST /api/upload — file: {file.filename}")

    if not file.filename or not file.filename.endswith(".xml"):
        raise HTTPException(status_code=400, detail={
            "error": "Only .xml files are accepted",
            "type": "ValidationError",
            "timestamp": datetime.now().isoformat(),
        })

    try:
        content = await file.read()
        xml_string = content.decode("utf-8")
    except Exception as e:
        print(f"[ERROR] Failed to read uploaded file: {e}")
        raise HTTPException(status_code=400, detail={
            "error": f"Could not read file: {e}",
            "type": "FileReadError",
            "timestamp": datetime.now().isoformat(),
        })

    try:
        sensor_data = patient_xml_to_dict(xml_string)
    except ValueError as e:
        print(f"[WARN] XML parse error: {e}")
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "type": "XMLParseError",
            "timestamp": datetime.now().isoformat(),
        })

    print(f"[LOG] Parsed {len(sensor_data)} sensors from XML")

    try:
        result = _run_simulation(sensor_data)
        return result
    except HTTPException:
        raise
    except Exception as e:
        print(f"[ERROR] Compute after upload failed: {e}")
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })


@app.post("/api/download", response_class=PlainTextResponse)
def download(request: DownloadRequest):
    """
    Convert a results dict to a downloadable XML string.

    Request body:
        {"results": {...}, "name": "My Scenario"}

    Response:
        XML string (text/plain), suitable for download as .xml file.
    """
    print(f"[LOG] POST /api/download — name: {request.name}")
    try:
        # Flatten results to the format results_to_xml expects
        flat_results = {
            "sensors": {
                k: v.get("value") if isinstance(v, dict) else v
                for k, v in request.results.get("sensors", {}).items()
            },
            "computed": {
                k: v.get("value") if isinstance(v, dict) else v
                for k, v in request.results.get("computed", {}).items()
            },
            "vectors": request.results.get("vectors", {}),
            "warnings": request.results.get("warnings", []),
        }
        xml_string = results_to_xml(flat_results, name=request.name)
        return PlainTextResponse(content=xml_string, media_type="application/xml")
    except Exception as e:
        print(f"[ERROR] Download failed: {e}")
        raise HTTPException(status_code=400, detail={
            "error": str(e),
            "type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
        })


# ── WebSocket streaming endpoint (Phase 3) ───────────────────────────────────

@app.websocket("/ws/feedback")
async def ws_feedback(websocket: WebSocket, tick_ms: int = 100,
                      lamina: Optional[str] = None):
    """
    Stream the feedback loop to the browser over WebSocket.

    On connect: an isolated Session + SimulatedSource are created
    and a background ticker fires every `tick_ms` milliseconds, sending
    a simulation snapshot as JSON.

    `lamina` names which lamina this connection runs, resolved by the same id
    the schema endpoint takes, so a client can guarantee that the structure it
    drew and the values it is reading came from the same place.  Omit it for
    the process default.  An unknown id closes the socket rather than streaming
    a lamina nobody asked for.

    Inbound control messages (JSON):
      {"type": "set_sensor",        "id": "HR",        "value": 110.0}
      {"type": "pause"}
      {"type": "resume"}
      {"type": "reset"}

    On disconnect: the ticker task is cancelled and the session is freed.
    One ticker task per connection — sessions are never shared.
    """
    # Resolved before accepting: a socket that opens and then closes looks
    # like a network fault, and this is a request for something that does not
    # exist.  1008 (policy violation) with the reason on the close frame says
    # which, and the client reports it instead of retrying forever.
    try:
        path = resolve_lamina(lamina)
    except UnknownLamina as e:
        await websocket.accept()
        await websocket.close(code=1008, reason=str(e)[:120])
        print(f"[WS] /ws/feedback rejected  unknown lamina={lamina}")
        return

    await websocket.accept()
    print(f"[WS] /ws/feedback connected  tick_ms={tick_ms}  lamina={lamina or '(default)'}")

    # The feed is built from the loaded lamina's own sensor declarations, and
    # the session starts at the baselines that feed reports — so a lamina this
    # file has never heard of streams without a line of change here.
    session = Session(lamina=path)
    source  = SimulatedSource(session.twin)
    session.seed(source.starting_state())
    print(f"[WS] feed: {source.describe()}")
    flags   = {"paused": False}

    # ── Layer 1 streaming runtime ────────────────────────────────────
    # Ingestion and control run on two independent timescales (spec
    # §"Layer 1").  The ingestion task pushes sensor readings into the
    # runtime's latest-wins mailbox; the runtime's fixed-rate control
    # cycle consumes the freshest sample and runs one feedback step.
    # Overlapping readings coalesce in the mailbox, so a slow cycle can
    # never build a backlog.  The twin/session know nothing about any of
    # this — the runtime is purely domain-agnostic plumbing around tick().
    period_s = tick_ms / 1000.0

    def _control(sample: dict | None):
        # Paused → emit nothing and do not advance the cycle.  A None
        # sample (mailbox empty this period) still runs a cycle on the
        # current state, matching physiological control that keeps
        # regulating between fresh readings.
        if flags["paused"]:
            return None
        snapshot = session.tick(sample or {})
        # Say what is producing these readings.  Every number on this socket is
        # generated — Gaussian noise around the baselines the lamina declares —
        # and until now nothing on the wire said so, which left a screen full of
        # convincingly wobbling values with no way to tell them from a patient.
        # The frontend reports whatever this says rather than assuming.
        snapshot["source"] = {
            "kind": source.KIND,
            "detail": source.describe(),
        }
        return snapshot

    async def _send(snapshot: dict) -> None:
        # jsonable_encoder handles any numpy scalars inside vectors/outcomes.
        await websocket.send_json(jsonable_encoder(snapshot))

    runtime = StreamingRuntime(
        process=_control,
        emit=_send,
        period_s=period_s,
        refractory_s=period_s * 0.5,   # min spacing floor after an overrun
    )

    async def _ingest() -> None:
        try:
            while True:
                await asyncio.sleep(period_s)
                runtime.submit(source.next())
        except asyncio.CancelledError:
            raise

    runtime.start()
    ingest_task = asyncio.create_task(_ingest())

    try:
        async for msg in websocket.iter_json():
            if not isinstance(msg, dict):
                continue  # non-dict payload — silently skip

            msg_type = msg.get("type", "")

            if msg_type == "set_sensor":
                sensor_id = str(msg.get("id", ""))
                raw       = msg.get("value")
                if sensor_id and raw is not None:
                    value = float(raw)
                    source.set_baseline(sensor_id, value)
                    try:
                        session.twin.set_sensor(sensor_id, value)
                    except (KeyError, ValueError):
                        pass  # PRELIMINARY or unknown attr — ignore

            elif msg_type == "pause":
                flags["paused"] = True

            elif msg_type == "resume":
                flags["paused"] = False

            elif msg_type == "reset":
                session.reset()

            # Unknown types are silently dropped (forward-compatible).

    except WebSocketDisconnect:
        pass
    finally:
        ingest_task.cancel()
        try:
            await ingest_task
        except asyncio.CancelledError:
            pass
        await runtime.stop()
        print("[WS] /ws/feedback disconnected")


# ── WebSocket streaming endpoint — an organism (Phase 2) ─────────────────────

@app.websocket("/ws/organism")
async def ws_organism(websocket: WebSocket, tick_ms: int = 100,
                      organism: Optional[str] = None):
    """
    Stream a whole body — several laminae and the gates between them.

    Stands beside `/ws/feedback` rather than replacing it.  A client
    asking for one lamina gets exactly the payload it always got; a client
    asking for a body knows it is asking for a body, and the two shapes
    never arrive on the same socket by surprise.

    `organism` names an organism file; omit it for `backend/organism.xml`.

    Payload per tick:
        {
          "organism_id": str,
          "laminae": {lamina_id: <the same snapshot one lamina sends>},
          "gates": [...],               # declaration + live state per seam
          "organism_report": {cycle, gates, cycle_reports, warnings, ...}
        }

    Inbound control messages carry a lamina, because on a body "set HR"
    is ambiguous and silently guessing which lamina meant it is the kind
    of thing that looks like it works:
      {"type": "set_sensor", "lamina": "lamina_circulatory",
       "id": "HR", "value": 110.0}
      {"type": "pause"} / {"type": "resume"} / {"type": "reset"}
    """
    try:
        session = OrganismSession(organism)
    except (OrganismError, FileNotFoundError, ET.ParseError) as e:
        # Refused before the socket starts streaming, for the same reason
        # an unknown lamina is: a socket that opens and then closes looks
        # like a network fault, and this is a request for something that
        # does not exist or does not parse.
        await websocket.accept()
        await websocket.close(code=1008, reason=str(e)[:120])
        print(f"[WS] /ws/organism rejected  organism={organism}: {e}")
        return

    await websocket.accept()
    print(f"[WS] /ws/organism connected  tick_ms={tick_ms}  "
          f"organism={organism or '(default)'}  "
          f"laminae={list(session.organism.twins)}")

    flags = {"paused": False}
    period_s = tick_ms / 1000.0

    def _control(sample):
        if flags["paused"]:
            return None
        snapshot = session.tick(sample or {})
        snapshot["source"] = {
            "kind": "simulated",
            "detail": "; ".join(
                f"{lamina_id}: {src.describe()}"
                for lamina_id, src in session.sources.items()
            ),
        }
        return snapshot

    async def _send(snapshot: dict) -> None:
        await websocket.send_json(jsonable_encoder(snapshot))

    runtime = StreamingRuntime(
        process=_control,
        emit=_send,
        period_s=period_s,
        refractory_s=period_s * 0.5,
    )

    async def _ingest() -> None:
        try:
            while True:
                await asyncio.sleep(period_s)
                runtime.submit(session.sample())
        except asyncio.CancelledError:
            raise

    runtime.start()
    ingest_task = asyncio.create_task(_ingest())

    try:
        async for msg in websocket.iter_json():
            if not isinstance(msg, dict):
                continue

            msg_type = msg.get("type", "")

            if msg_type == "set_sensor":
                lamina_id = str(msg.get("lamina", ""))
                sensor_id = str(msg.get("id", ""))
                raw = msg.get("value")
                if lamina_id and sensor_id and raw is not None:
                    session.set_sensor(lamina_id, sensor_id, float(raw))

            elif msg_type == "pause":
                flags["paused"] = True

            elif msg_type == "resume":
                flags["paused"] = False

            elif msg_type == "reset":
                session.reset()

    except WebSocketDisconnect:
        pass
    finally:
        ingest_task.cancel()
        try:
            await ingest_task
        except asyncio.CancelledError:
            pass
        await runtime.stop()
        print("[WS] /ws/organism disconnected")
