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
  GET  /                - The built dashboard (frontend/dist), when it exists

Run:
    uvicorn main:app --reload --port 8000
"""

import asyncio
import json
import logging
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
from universal_twin import INTER_LAMINA, SENSOR, UniversalTwin
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

# Shrink the JSON and asset payloads that cross the wire.  Below a kilobyte
# the framing overhead outweighs any gain, hence the floor.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Path to the XML schema, relative to this file
# Which lamina this process is running.  Overridable via CARDIOTWIN_LAMINA so
# "point the backend at a different lamina and the visualiser follows" is a
# thing anyone can try rather than a claim in a document — the 2D view builds
# itself out of /api/schema and names no attribute of its own.  laminae.py
# pairs the file with the class holding its arithmetic.
SCHEMA_PATH = lamina_path()

# Path to presets folder (one level up from backend/)
PRESETS_PATH = Path(__file__).parent.parent / "presets"

# Where the Vite build lands.  Overridable so a deployment can point at a
# build staged elsewhere without moving files into the checkout.
FRONTEND_DIST = Path(os.environ.get(
    "CARDIOTWIN_FRONTEND_DIST",
    str(Path(__file__).parent.parent / "frontend" / "dist"),
))

# Serve preset XML files as static files at /presets/<name>.xml
if PRESETS_PATH.exists():
    app.mount("/presets", StaticFiles(directory=str(PRESETS_PATH)), name="presets")


class FrontendFiles(StaticFiles):
    """
    StaticFiles with cache headers that match what the filenames promise.

    Vite fingerprints everything under assets/, so those files can be cached
    forever: a changed file gets a changed name.  index.html keeps its name,
    so it must not be cached — after a redeploy a cached index.html would
    point at hashed asset files that no longer exist and the screen would
    load blank.
    """

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        # Starlette hands back OS separators on Windows; the URL contract is "/".
        if path.replace("\\", "/").startswith("assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response


def frontend_build_id(dist: Path) -> Optional[str]:
    """
    The hashed entry script named by the built index.html.

    The client compares this with its own script name to know a new version
    was deployed.  Returns None when the build is absent or names no script,
    so a machine running the API alone answers the health check instead of
    failing it.
    """
    try:
        html = (Path(dist) / "index.html").read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r'src="/assets/([^"]+\.js)"', html)
    return match.group(1) if match else None


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
        "states":     twin.get_all_composite_states(),
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

class _QuietHealthChecks(logging.Filter):
    """
    Drop uvicorn's access line for GET /health.

    Render polls /health every 5 seconds, which at that rate buries every
    other line in the log.  Only the health request is dropped; a failed
    one still surfaces through uvicorn's error logging, not this filter.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return '"GET /health ' not in record.getMessage()
        except Exception:               # noqa: BLE001 — a filter may not raise
            return True


logging.getLogger("uvicorn.access").addFilter(_QuietHealthChecks())


@app.get("/health")
def health():
    """Health check, including which frontend build (if any) is being served."""
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "build": frontend_build_id(FRONTEND_DIST),
        # How to check from outside that nothing runs when no page is open:
        # a browser tab left streaming keeps a non-zero count here.
        "streams": _open_streams,
    }


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


def _gate_declaration(gate) -> dict:
    """
    One gate as the frontend needs to draw it.

    Kind and side are the two facts a diagram cannot infer: they decide
    which glyph the valve gets and which end of the edge it sits on. An
    auto gate and a key gate look different because they ARE different —
    one reads its own lamina, the other reads what arrives — and a
    reader who cannot tell them apart cannot tell a protection layer
    from a policy.
    """
    from organism import AutoGate

    entry = {
        "id":            gate.id,
        "kind":          "auto" if isinstance(gate, AutoGate) else "key",
        "side":          gate.side,
        "description":   gate.description,
        # Rule 1, as a value the reader can show rather than a promise
        # they have to take on trust.
        "starts_closed": True,
        "learnables": [
            {"name": lrn.name, "initial": lrn.initial,
             "min": lrn.min, "max": lrn.max}
            for lrn in gate.learnables
        ],
    }
    if isinstance(gate, AutoGate):
        entry["trigger"] = gate.trigger_kind
        entry["params"] = dict(gate.trigger)
        entry["refractory_cycles"] = gate.refractory_cycles
    else:
        entry["metric"] = gate.key.get("metric", "identity")
        entry["params"] = dict(gate.key)
        entry["weight"] = gate.weight
        entry["rate"] = gate.rate
        entry["on_close"] = gate.on_close
        entry["confidence"] = gate.confidence
    return entry



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
        "levels": dict(spec.levels),
        "channels": [
            {
                "id":          channel.id,
                "from":        str(channel.source),
                "to":          str(channel.dest),
                "from_lamina": channel.source.lamina,
                "from_member": channel.source.member,
                "to_lamina":   channel.dest.lamina,
                "to_member":   channel.dest.member,
                "carry":       channel.carry,
                "time_delay":  channel.time_delay,
                "description": channel.description,
                # Which way this wire climbs, so a diagram can lay the
                # stack out vertically without recomputing it.
                "direction":   ("up" if spec.levels.get(channel.dest.lamina, 0)
                                > spec.levels.get(channel.source.lamina, 0)
                                else "down"),
                "transmit":    [_gate_declaration(g) for g in channel.transmit],
                "receive":     [_gate_declaration(g) for g in channel.receive],
            }
            for channel in spec.channels
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

# How long a stream may go without hearing from the client.  The dashboard
# sends a keepalive every 4 minutes, so 10 minutes of silence means no page is
# there.  Read at call time so a test can shrink it.
STREAM_SILENCE_S = 600.0
# A frame this slow to leave means the client has stopped reading.  Without
# this the send can park forever and the stream outlives the tab.
STREAM_SEND_TIMEOUT_S = 15.0
# Close code for a stream reaped for silence.  App-defined range, so it cannot
# be mistaken for a protocol-level close.
STREAM_SILENT_CLOSE = 4408

# Streams currently accepted and not yet torn down, in this process.  /health
# reports it so "nothing runs when no page is open" is observable from outside.
_open_streams = 0

# Close tasks started off the send path are kept here until they finish, so
# the loop does not warn about a pending task during teardown.
_close_tasks: set[asyncio.Task] = set()


def _close_soon(websocket: WebSocket, code: int, reason: str) -> None:
    """
    Close a socket from outside the task that is using it.

    A close on an already-closed socket, or one started while the server is
    shutting down, must never raise out of whoever asked for it.  The task is
    retained until done so the event loop does not report it as pending.
    """

    async def _close() -> None:
        try:
            await websocket.close(code=code, reason=reason)
        except Exception:               # noqa: BLE001 — teardown must not raise
            pass

    try:
        task = asyncio.create_task(_close())
    except RuntimeError:                # no loop left to run the close in
        return
    _close_tasks.add(task)
    task.add_done_callback(_close_tasks.discard)


def _shown(raw: Any, limit: int = 40) -> str:
    """A refused value as the notice quotes it: repr, cut short so a client
    that sends a megabyte of junk does not get a megabyte of notice back."""
    text = repr(raw)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def validate_sensor_command(
    twin: UniversalTwin, sensor_id: Any, raw: Any
) -> tuple[Optional[float], Optional[dict]]:
    """
    Decide whether one inbound set_sensor command may be applied.

    Returns ``(value, None)`` for a command the twin can accept, or
    ``(None, notice)`` for one it cannot.  The notice is a frame the
    browser can render: it names the command that was refused and says in
    plain English why.  A control that silently does nothing is
    indistinguishable from a broken one, and an exception in the receive
    loop used to close the socket — which looks like a network fault.

    Nothing here is allowed to raise.  Every value comes off the wire, so
    "a number" may arrive as a string, a list, a bool or a NaN, and the
    caller's only safe assumption is that none of it is well formed.
    """
    # The id is shown back to the user verbatim, so keep it printable even
    # when the frame carried a list or an object where a string belongs.
    sid = None if sensor_id is None else str(sensor_id)

    # A command addresses a declared SENSOR by id.  Anything else — empty,
    # unknown, or a computed/inter-lamina attribute such as MAP — is not
    # an input this model has a slot for.
    if not isinstance(sensor_id, str) or not sensor_id:
        return None, {
            "type": "notice",
            "level": "warning",
            "code": "unknown_input",
            "id": sid,
            "message": (
                f"'{sid}' is not an input this model accepts, "
                "so the change was not applied."
            ),
        }

    attr = twin.attributes.get(sensor_id)
    if attr is None or attr.source != SENSOR:
        return None, {
            "type": "notice",
            "level": "warning",
            "code": "unknown_input",
            "id": sid,
            "message": (
                f"'{sid}' is not an input this model accepts, "
                "so the change was not applied."
            ),
        }

    # bool is a subclass of int, and float(True) is 1.0, so it would sail
    # through a numeric check while meaning something else entirely.
    try:
        if raw is None or isinstance(raw, bool):
            raise TypeError
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return None, {
            "type": "notice",
            "level": "warning",
            "code": "invalid_value",
            "id": sid,
            "message": (
                f"{sid} needs a number; {_shown(raw)} is not one, "
                "so the change was not applied."
            ),
        }

    if not math.isfinite(value):
        return None, {
            "type": "notice",
            "level": "warning",
            "code": "invalid_value",
            "id": sid,
            "message": (
                f"{sid} needs a number; {_shown(raw)} is not one, "
                "so the change was not applied."
            ),
        }

    if value < attr.physio_min or value > attr.physio_max:
        return None, {
            "type": "notice",
            "level": "warning",
            "code": "out_of_range",
            "id": sid,
            "message": (
                f"{sid} = {value:g} {attr.unit} is outside the range this "
                f"model accepts ({attr.physio_min:g}-{attr.physio_max:g} "
                f"{attr.unit}), so the change was not applied."
            ),
        }

    return value, None


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
      {"type": "keepalive"}

    Outbound, beside the snapshots: {"type": "notice", "level": "warning",
    "code": ..., "id": ..., "message": ...} when a command was not applied.

    On disconnect: the ticker task is cancelled and the session is freed.
    One ticker task per connection — sessions are never shared.

    A client that vanishes without closing is reaped too: no inbound message
    for STREAM_SILENCE_S closes the socket with STREAM_SILENT_CLOSE, and a
    send that cannot finish within STREAM_SEND_TIMEOUT_S stops the runtime
    and closes the wedged socket from a separate task.
    """
    global _open_streams

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
    _open_streams += 1
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
        try:
            # A send that blocks past the timeout means the peer has stopped
            # reading.  Left alone it parks the control loop forever and the
            # stream outlives the page that asked for it.
            await asyncio.wait_for(
                websocket.send_json(jsonable_encoder(snapshot)),
                STREAM_SEND_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            # End the stream from this side, but not by awaiting close()
            # here: the receive loop is still parked in receive_text() and
            # the send that just timed out still holds the socket.  A
            # separate close task gives the receive loop its disconnect.
            print("[WS] /ws/feedback client stopped reading, closing")
            runtime.request_stop()
            _close_soon(websocket, 1011, "Client stopped reading")
        except (WebSocketDisconnect, RuntimeError):
            # A tab closing, or a send racing the close after one, is the
            # normal way a stream ends.  Stop the loop quietly — this is
            # not a failure and must not print a traceback.  Every other
            # exception propagates so the runtime can report it loudly.
            runtime.request_stop()
            return

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
        while True:
            # Read text ourselves rather than iter_json(): a malformed frame
            # is a message the user can be told about, not a reason to close
            # the socket under them.
            try:
                # The dashboard's keepalive resets this timer.  When it stops
                # arriving, nobody is on the other end: a vanished client
                # never sends a close frame, so silence is the only signal.
                text = await asyncio.wait_for(
                    websocket.receive_text(), STREAM_SILENCE_S
                )
            except asyncio.TimeoutError:
                print(f"[WS] /ws/feedback silent for {STREAM_SILENCE_S:g}s, closing")
                try:
                    await websocket.close(
                        code=STREAM_SILENT_CLOSE,
                        reason="No message from the client",
                    )
                except Exception:       # noqa: BLE001 — close must not escape
                    pass
                break
            try:
                msg = json.loads(text)
            except (json.JSONDecodeError, TypeError):
                await websocket.send_json({
                    "type": "notice",
                    "level": "warning",
                    "code": "bad_message",
                    "id": None,
                    "message": (
                        "That message was not valid JSON, "
                        "so it was ignored."
                    ),
                })
                continue

            if not isinstance(msg, dict):
                await websocket.send_json({
                    "type": "notice",
                    "level": "warning",
                    "code": "bad_message",
                    "id": None,
                    "message": (
                        "That message was not a JSON object, "
                        "so it was ignored."
                    ),
                })
                continue

            msg_type = msg.get("type", "")

            if msg_type == "set_sensor":
                sensor_id = msg.get("id")
                raw       = msg.get("value")
                value, notice = validate_sensor_command(
                    session.twin, sensor_id, raw
                )
                if notice is not None:
                    await websocket.send_json(notice)
                    continue
                sensor_id = str(sensor_id)
                source.set_baseline(sensor_id, value)
                session.twin.set_sensor(sensor_id, value)

            elif msg_type == "pause":
                flags["paused"] = True

            elif msg_type == "resume":
                flags["paused"] = False

            elif msg_type == "reset":
                session.reset()

            elif msg_type == "keepalive":
                # The dashboard sends one every few minutes so a host that
                # sleeps idle services (Render's free plan counts inbound
                # WebSocket messages as activity) does not stop a screen
                # someone is watching.  It needs no reply.
                pass

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
        _open_streams -= 1
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
          "channels": [...],            # both ends + live state per seam
          "organism_report": {cycle, channels, cycle_reports, warnings, ...}
        }

    Inbound control messages carry a lamina, because on a body "set HR"
    is ambiguous and silently guessing which lamina meant it is the kind
    of thing that looks like it works:
      {"type": "set_sensor", "lamina": "lamina_circulatory",
       "id": "HR", "value": 110.0}
      {"type": "pause"} / {"type": "resume"} / {"type": "reset"}
    """
    global _open_streams

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
    _open_streams += 1
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
        _open_streams -= 1
        print("[WS] /ws/organism disconnected")


# ── Frontend ──────────────────────────────────────────────────────────────────

# Mounted last, after every API route and websocket, so "/" only catches what
# nothing above claimed and the API keeps priority.  A missing build is not an
# error: the API is useful on its own.
if (FRONTEND_DIST / "index.html").is_file():
    app.mount("/", FrontendFiles(directory=str(FRONTEND_DIST), html=True), name="frontend")
else:
    print("[serve] frontend/dist not built - the API runs alone; "
          "build the UI with: cd frontend && npm run build")
