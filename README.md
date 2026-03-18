# CardioTwin — Cardiovascular Physiological Digital Twin

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-20232A?style=flat&logo=react&logoColor=61DAFB)](https://react.dev/)
[![Status](https://img.shields.io/badge/Status-MVP_Complete-green)]()

CardioTwin is a browser-based physiological digital twin for the cardiovascular system. It models hemodynamic variables in real time using first-principles physics, driven entirely by an XML schema that separates domain knowledge from implementation code.

---

## Overview

The system allows researchers, clinicians, and students to:

- Adjust patient sensor inputs via interactive sliders and observe computed haemodynamic values instantly
- Upload patient data as XML files or load built-in clinical presets (normal, hypertension, heart failure)
- Visualise results through semi-circle gauges, composite radar charts, and tabular vector views
- Save and restore named patient profiles in the browser
- Download full simulation results as structured XML

---

## Simulation Model

The cardiovascular simulation (`CirculatoryLamina`) computes six derived variables from ten sensor inputs using established physiological laws:

| Step | Variable | Law / Model |
|------|----------|-------------|
| 1 | Mean Arterial Pressure (MAP) | Weighted average of SBP and DBP |
| 2 | Vascular Resistance (R) | Poiseuille's Law |
| 3a | Stroke Volume (SV) | Frank-Starling Law |
| 3b | Cardiac Output (CO) | CO = HR x SV |
| 4 | Haemodynamic Flow (Q) | Ohm's analogy: Q = delta-P / R |
| 5 | Conduction Length Constant (lambda) | Cable Theory |

All computed values are normalised to a `[0, 1]` physiological range. Physiological gate checks flag abnormal values and model inconsistencies as warnings.

The schema (`circulatory_lamina.xml`) defines all attributes, physiological ranges, composite groupings, and gate conditions. Extending the model — adding new sensors, adjusting ranges, or defining new gates — requires only XML edits, with no changes to application code.

---

## Architecture

```
cardio-twin/
├── backend/
│   ├── universal_twin.py          # Base class: XML parsing, dependency resolution, gate validation
│   ├── circulatory_lamina.py      # Cardiovascular physics functions
│   ├── circulatory_lamina.xml     # Domain schema (attributes, composites, gates, functions)
│   ├── main.py                    # FastAPI REST API
│   ├── xml_converter.py           # XML <-> JSON utilities
│   └── requirements.txt
│
├── frontend/
│   └── src/
│       ├── App.tsx                # Main application component
│       ├── components/
│       │   ├── Sidebar.tsx        # Sensor input sliders
│       │   ├── GaugeChart.tsx     # Semi-circle gauges (MAP, CO, Q)
│       │   ├── CardioRadarChart.tsx  # Composite radar chart
│       │   ├── DataTable.tsx      # Tabular vector view
│       │   ├── XMLUpload.tsx      # File upload and preset loader
│       │   ├── ProfileManager.tsx # Save / load / export patient profiles
│       │   ├── Toast.tsx          # Notification system
│       │   └── ErrorBoundary.tsx  # Top-level error handler
│       └── utils/
│           ├── api.ts             # Typed API client
│           └── localStorage.ts   # Profile persistence helpers
│
├── presets/
│   ├── normal.xml
│   ├── hypertension.xml
│   └── heart_failure.xml
│
├── docs/
│   ├── development_guide.md
│   └── roadmap.md
│
└── demo.py                        # Standalone CLI demo (no frontend required)
```

**Stack:** Python 3.10+ / FastAPI — React 19 / Vite / TypeScript / TailwindCSS / Recharts

---

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Node.js 18 or higher

### 1. Start the backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

The API will be available at `http://localhost:8000`.
Interactive API documentation (Swagger UI) is at `http://localhost:8000/docs`.

### 2. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

The application will be available at `http://localhost:5173`.

### 3. Run the standalone demo (optional)

The demo script exercises the simulation engine directly from the command line, without the web interface:

```bash
python demo.py
```

This runs the normal, hypertension, and heart failure scenarios and prints computed values, composite vectors, and gate validation results to the console.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/schema` | Returns full schema (attributes, composites, functions) as JSON |
| POST | `/api/compute` | Accepts sensor values, returns computed results and vectors |
| POST | `/api/upload` | Accepts a patient XML file, returns computed results |
| POST | `/api/download` | Accepts a results object, returns formatted XML for download |

**Example request — `POST /api/compute`:**

```json
{
  "sensor_data": {
    "SBP": 120, "DBP": 80, "HR": 72,
    "eta": 3.5, "L": 50, "r": 0.15,
    "EDV": 120, "r_m": 5000, "r_i": 200, "r_e": 300
  }
}
```

**Example response:**

```json
{
  "sensors": { "SBP": { "value": 120, "normalised": 0.33, "unit": "mmHg", "name": "Systolic Blood Pressure" } },
  "computed": { "MAP": { "value": 93.33, "normalised": 0.56, "unit": "mmHg", "name": "Mean Arterial Pressure" } },
  "vectors": { "pressure_state": { "SBP": 0.33, "DBP": 0.33, "MAP": 0.56 } },
  "warnings": [],
  "log": ["..."]
}
```

---

## Patient XML Format

Patient input files follow this structure:

```xml
<?xml version="1.0" encoding="utf-8"?>
<patient>
  <name>Patient Name</name>
  <created>2026-03-19T00:00:00</created>
  <sensor_data>
    <SBP>120</SBP>
    <DBP>80</DBP>
    <HR>72</HR>
    <eta>3.5</eta>
    <L>50</L>
    <r>0.15</r>
    <EDV>120</EDV>
    <r_m>5000</r_m>
    <r_i>200</r_i>
    <r_e>300</r_e>
  </sensor_data>
</patient>
```

The three preset files in `presets/` demonstrate the expected format for normal, hypertensive, and heart failure scenarios.

---

## Known Limitations

- **Q vs CO gate warning on the normal preset:** The flow variable Q is computed via MAP/R (Ohm's analogy) while cardiac output CO uses HR x SV (Frank-Starling). These two independent pathways may diverge by more than the 10% gate tolerance under typical inputs. This is a known model characteristic, not an error.
- **Windows terminal encoding:** The Omega character in console output may render incorrectly on some Windows terminals. This is cosmetic and does not affect computation.
- **Local deployment only:** This MVP is designed for local research use. There is no authentication, database, or cloud deployment.

---

## Documentation

- [Development Guide](./docs/development_guide.md) — Architecture decisions, tech stack rationale, and design patterns
- [Roadmap](./docs/roadmap.md) — Four-week development plan with deliverables

---

## License

This project is licensed under the MIT License.
