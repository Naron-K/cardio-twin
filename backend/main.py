"""
CardioTwin - FastAPI Backend
=============================
Wraps the CirculatoryLamina simulation engine in a REST API.

Endpoints:
  GET  /health          - Health check
  GET  /api/schema      - Return slider configs from XML schema
  POST /api/compute     - Run simulation with JSON sensor data
  POST /api/upload      - Upload patient XML file, run simulation
  POST /api/download    - Convert results to downloadable XML

Run:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure backend package is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from circulatory_lamina import CirculatoryLamina
from feedback_controller import (
    FeedbackController,
    DEFAULT_EPSILON_RATIO,
    DEFAULT_MAX_NORM,
)
from session import Session
from signal_source import SimulatedCardioSource, _DEFAULT_BASELINE
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
SCHEMA_PATH = Path(__file__).parent / "circulatory_lamina.xml"

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
    Initialise a fresh CirculatoryLamina, feed sensor values,
    run compute_all(), and return a structured results dict.
    """
    twin = CirculatoryLamina(str(SCHEMA_PATH))

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

    # Collect computed (preliminary) values
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
        }

    # Collect gate warnings
    warnings = [line for line in twin.get_log() if "GATE FAIL" in line]

    # Collect composite vectors
    vectors = twin.get_all_vectors()

    return {
        "sensors":    sensors_out,
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


def _apply_tag_overrides(twin: CirculatoryLamina,
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
                          tag_overrides: Dict[str, "TagOverride"]) -> CirculatoryLamina:
    """
    Fresh twin per request (stateless server).  Applies sensor values
    and any tag overrides before the controller is wired up.
    """
    twin = CirculatoryLamina(str(SCHEMA_PATH))
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


@app.get("/api/schema")
def get_schema():
    """
    Return the full schema from circulatory_lamina.xml.

    Response includes:
      - attributes: slider configs (id, name, unit, physio_min, physio_max, source)
      - composites: grouping definitions for charts
      - functions: step-ordered computation models
    """
    print("[LOG] GET /api/schema")
    try:
        twin = CirculatoryLamina(str(SCHEMA_PATH))
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
        },
        # Phase B: tag registry for the feedback pipeline.
        "tags": tags,
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
async def ws_feedback(websocket: WebSocket, tick_ms: int = 100):
    """
    Stream the feedback loop to the browser over WebSocket.

    On connect: an isolated Session + SimulatedCardioSource are created
    and a background ticker fires every `tick_ms` milliseconds, sending
    a simulation snapshot as JSON.

    Inbound control messages (JSON):
      {"type": "inject_arrhythmia", "magnitude": 30.0, "decay": 0.15}
      {"type": "set_sensor",        "id": "HR",        "value": 110.0}
      {"type": "pause"}
      {"type": "resume"}
      {"type": "reset"}

    On disconnect: the ticker task is cancelled and the session is freed.
    One ticker task per connection — sessions are never shared.
    """
    await websocket.accept()
    print(f"[WS] /ws/feedback connected  tick_ms={tick_ms}")

    session = Session(dict(_DEFAULT_BASELINE))
    source  = SimulatedCardioSource()
    flags   = {"paused": False}

    async def _ticker() -> None:
        try:
            while True:
                await asyncio.sleep(tick_ms / 1000.0)
                if flags["paused"]:
                    continue
                snapshot = session.tick(source.next())
                # jsonable_encoder handles any numpy scalars inside vectors/outcomes.
                await websocket.send_json(jsonable_encoder(snapshot))
        except asyncio.CancelledError:
            raise  # propagate so the task cancels cleanly
        except Exception:
            pass   # WebSocket closed mid-send; outer finally cancels the task

    task = asyncio.create_task(_ticker())

    try:
        async for msg in websocket.iter_json():
            if not isinstance(msg, dict):
                continue  # non-dict payload — silently skip

            msg_type = msg.get("type", "")

            if msg_type == "inject_arrhythmia":
                source.inject_arrhythmia(
                    magnitude=float(msg.get("magnitude", 30.0)),
                    decay=float(msg.get("decay", 0.15)),
                )

            elif msg_type == "set_sensor":
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
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        print("[WS] /ws/feedback disconnected")
