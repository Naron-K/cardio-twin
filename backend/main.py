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

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Ensure backend package is importable when running from project root
sys.path.insert(0, str(Path(__file__).parent))

from circulatory_lamina import CirculatoryLamina
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
    sensors_out: Dict[str, Any] = {}
    for attr_id in twin.list_attributes("SENSOR"):
        attr = twin.attributes[attr_id]
        sensors_out[attr_id] = {
            "value": attr.value,
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
            "absorption_vector": comp.absorption_vector.tolist() if comp.absorption_vector is not None else None,
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
