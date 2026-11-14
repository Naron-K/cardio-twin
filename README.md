# CardioTwin — Cardiovascular Physiological Digital Twin

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-005571?style=flat&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-20232A?style=flat&logo=react&logoColor=61DAFB)](https://react.dev/)
[![Status](https://img.shields.io/badge/Status-MVP_Complete-green)]()

CardioTwin is a browser-based physiological digital twin for the cardiovascular system. It models hemodynamic variables in real time using first-principles physics, driven entirely by an XML schema that separates domain knowledge from implementation code.

---

## Overview

The app is a single dashboard, read left to right the way the data travels:

1. **Data sources** — the lamina's inputs, grouped by the ingestion channel each one is mapped to, with a slider per input
2. **Digital twin** — what the model computes from them every cycle, shown as an animated heart, a trend per computed attribute, or a table of inputs beside outputs
3. **Outcomes** — each behavioural outcome against the target and tolerance the model declares
4. **Over time** — total distance from the targets, with the feedback loop on and with it off

Everything on screen is built from the lamina XML and the live model state; the UI holds no attribute names, units or thresholds of its own. The functions, segments, feedback loop, composites and pipeline configuration are one click away under **Inspect**.

The **Daily Activity** lamina (`lamina_wearable`) can also replay a recorded day minute by minute, or hold a scenario (sleep, rest, desk work, walk, vigorous). For a replayed day it adds a fourth form, **Day**, written for a specialist rather than a modeller: a one-line summary, the day in numbers, measured heart rate beside the model's expectation with workouts and no-data hours marked, and each session with a verdict against the model's usual error. Which attribute plays which part on that screen is declared in the lamina's `<day_view>` block, so the screen still names no attribute of its own. The model's numbers are estimates, labelled as such, and fitted coefficients apply only to the person they were fitted on.

Other laminae's readings are generated around the baselines the XML declares, and the dashboard says so.

---

## Simulation Model

The circulatory lamina (`CirculatoryLamina`) computes nine attributes from eleven sensor inputs:

| Step | Variable | Law / Model |
|------|----------|-------------|
| 1 | Mean Arterial Pressure (MAP) | MAP = (1/3)·SBP + (2/3)·DBP |
| 2 | Vascular Resistance (R) | Poiseuille's Law, one representative segment |
| 3a | Stroke Volume (SV) | Frank-Starling Law |
| 3b | Cardiac Output (CO) | CO = HR · SV |
| 3c | Cardiac Cycle Length (T_cycle) | T_cycle = 60 / HR |
| 3d | Ventricular Ejection Time (T_sys) | Weissler's regression |
| 4 | Haemodynamic Flow (Q) | Q = (MAP − CVP) / R |
| 5 | Conduction Length Constant (lambda) | Cable Theory |
| 6 | Systemic Vascular Resistance (SVR) | SVR = (MAP − CVP) / CO |

The model does not predict: each time an input changes, it recalculates every state and outcome at once. A feedback loop adds a correction (X″) to computed values to pull outcomes towards their targets; it never changes a measured input.

The schema (`circulatory_lamina.xml`) defines all attributes, physiological ranges, functions, composites, outcomes and gates. Adjusting ranges, targets or groupings requires only XML edits. A new function still needs its arithmetic registered in the lamina's Python class.

[`docs/circulatory_functions_review.xml`](./docs/circulatory_functions_review.xml) lists the nine functions as they run, with their values at baseline and the open points found while cross-checking the XML against the code.

---

## Architecture

```
cardio-twin/
├── backend/
│   ├── universal_twin.py          # Domain-neutral engine: XML parsing, function chain, gates, feedback loop
│   ├── circulatory_lamina.py/.xml # Circulatory lamina: physics + its declaration
│   ├── respiratory_lamina.py/.xml # Respiratory lamina
│   ├── metabolic_lamina.py/.xml   # Metabolic lamina
│   ├── laminae.py                 # Pairs each lamina XML with the class holding its arithmetic
│   ├── organism.py, organism*.xml # Bodies: several laminae joined by gated channels
│   ├── feedback_controller.py     # Adaptive feedback loop
│   ├── session.py, streaming_runtime.py, signal_source.py, snapshot.py  # Live stream
│   ├── main.py, serve.py          # FastAPI app and launcher
│   └── tests/
│
├── frontend/
│   └── src/
│       ├── App.tsx                # The one screen, and its URL state
│       ├── components/
│       │   ├── dashboard/         # The dashboard: zones, tiles, trends, table, Inspect drawer
│       │   └── twin/              # Panels the dashboard and Inspect are built from
│       ├── hooks/                 # Live stream + per-lamina structure
│       ├── twin/                  # Schema index, view registry, stage template, outcome helpers
│       └── utils/api.ts           # /api/laminae and /api/schema client
│
├── presets/                       # Example patient XML files
├── test_dataset/                  # Synthetic patient profiles
├── tools/heart/                   # Cuts the heart illustration into the layers the stage animates
└── docs/                          # Design notes and briefs (see Documentation below)
    └── design/                    # Working plans and decisions from each development phase
```

**Stack:** Python 3.10+ / FastAPI — React 19 / Vite / TypeScript / TailwindCSS / Recharts

---

## Getting Started

### Prerequisites

- Python 3.10 or higher (tested on 3.12)
- Node.js 20.19+ or 22.12+ (required by Vite 8)

### 1. Start the backend

```bash
cd backend
pip install -r requirements.txt
python serve.py
```

The API will be available at `http://localhost:8000`.
Interactive API documentation (Swagger UI) is at `http://localhost:8000/docs`.
Run the tests with `python -m pytest tests -q`.

### 2. Start the frontend

```bash
cd frontend
npm ci
npm run dev
```

The application will be available at `http://localhost:5173`.

### 3. Presenting on a big screen

For a talk or a long-running demo, serve the production build instead of the
dev server:

```bash
cd frontend
npm run build
npm run preview
```

The app is then at `http://localhost:4173`. The dev server is fine for
development but not for a demo left open: React's development build records a
performance entry for every component render, which `src/main.tsx` clears every
10 s to keep the dev tab alive. The production build records none. Measured on
the dashboard over 3 minutes: zero entries, a flat ~13 MB heap, no errors.

If something else already holds port 8000, start the backend on another port
(`python serve.py circulatory 8010`) and point the frontend at it with
`CARDIOTWIN_API=http://localhost:8010` before `npm run dev` or `npm run preview`.

Once `frontend/dist` exists, the backend serves the dashboard as well, at
`http://localhost:8000/`: one process, one port. To open it from another device
on the same network (a touch display, a phone), bind every interface and use
this machine's IP address:

```powershell
$env:CARDIOTWIN_HOST = "0.0.0.0"; python serve.py
```

### 4. Hosting it online (Render)

The repository deploys as a single Docker service: [Dockerfile](./Dockerfile)
builds the dashboard and runs the backend beside it, so the UI, the API and the
WebSocket share one origin and nothing in the frontend needs a URL.
[render.yaml](./render.yaml) describes the service on Render's $7/month plan
(`0.5c-512mb`). A workspace needs a card on file before it can use it.

1. Push this repository to GitHub.
2. In [Render](https://render.com), sign in with GitHub, choose **New → Blueprint**
   and pick the repository. Render reads `render.yaml`, builds the image and
   gives the service an `https://….onrender.com` address.
3. Every push to the branch you linked redeploys. An open dashboard notices the
   new version and offers to reload.

`render.yaml` places the service in Singapore. The region cannot change after
creation, so edit it first if the display is far from there.

What this means for whoever is looking at the screen, and for the bill:

- **It stays awake.** A paid plan does not spin down when idle. The free plan
  does, and because the same server delivers the page, a browser opening a
  sleeping service only shows a spinner until it wakes; the dashboard's notices
  can only appear once the page has loaded. A free service here also once failed
  to wake at all until it was redeployed by hand.
- **The dashboard lets go when nobody is watching.** After 15 minutes with no
  touch it closes its stream and asks for a touch to continue. Add `?idle=30`
  to the address for a longer wait, or `?idle=0` for a screen that should never
  let go. A page hidden for more than 30 seconds (a background tab, a screen
  switched off) closes its stream too, whatever `?idle=` says, and reconnects
  when it is visible again.
- **Nothing runs without an open page.** Each page gets its own session, which
  ends when the page goes. The process itself stays up, at about 60 MB of RAM
  and almost no CPU. `/health` reports `streams`, the number open right now.
- **Bandwidth is the real cost.** Render does not pass WebSocket compression
  through, so one open dashboard at 10 frames a second uses about 264 MB an hour
  (measured on the live service). The Hobby workspace includes 5 GB a month and
  bills $0.15 per GB above that.
- **It stops itself at a limit.** `CARDIOTWIN_MONTHLY_GB` in `render.yaml` caps the
  bytes the streams send in a UTC month. At 80% an open dashboard warns; at the
  limit every stream closes and new ones are refused until the month turns, and
  the screen says so. The page itself still loads. `/health` reports `usage`.
  The count covers the streams, not page loads, so the limit sits a little under
  the allowance. It is kept in a file that a deploy or restart erases, so it
  restarts then and the limit can be overshot; the Billing page stays the source
  of truth. A persistent disk mounted at `CARDIOTWIN_USAGE_FILE`'s folder would
  keep it ($0.25 per GB a month, and no zero-downtime deploys). Anyone with the
  address spends from the same limit.
- **Fewer frames cost less.** `CARDIOTWIN_EMIT_EVERY=5` sends every 5th snapshot
  (2 a second, about 53 MB an hour). The model still runs every cycle, and the
  heart animates in the browser, so only how often the numbers refresh changes.
- **No sign-in.** Anyone with the address can open the dashboard. Nothing is
  stored on the server; each tab gets its own session.

To check the image locally first:

```bash
docker build -t cardio-twin .
docker run -p 8000:8000 cardio-twin
```

### 5. On the LG CreateBoard (Android touch display)

Open the address in Chrome, then use **⋮ → Add to Home screen**. The shortcut
opens the dashboard full screen, without the address bar. On the screen itself:

- Sliders have a finger-sized thumb, and dragging one does not scroll or reload
  the page.
- **Press and hold** a label, a chip or a box to read what it means: the touch
  version of the descriptions a mouse sees on hover.
- While someone is using it, the dashboard keeps the display from dimming; once
  it goes idle, the display's own power settings take over.
- If the text is too small from where people stand, add `?scale=1.25` (or
  1.5) to the address, e.g. `…onrender.com/?scale=1.25&idle=0`. Chrome's page
  zoom (**⋮ → Settings → Accessibility**) works too.

### Screens of every size

The layout follows the screen it is on (`frontend/src/display.ts`):

- **Wide** (1280 × 860 and up: desktops, the board) — the three columns as
  designed.
- **Tablet** (an iPad, or a laptop with little height) — inputs on the left,
  and one scrolling column of twin, outcomes and time beside them.
- **Phone** — one column; the page scrolls.

A screen reporting much more than 1920 × 1080 (a 4K board at full resolution)
is scaled up to match, so text never shrinks to a fraction of its size.
`?scale=` overrides that scale on any screen.

---

## API Reference

The dashboard uses the first three; the rest remain available for scripts.

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/laminae` | The laminae this backend can serve, and the default |
| GET | `/api/schema` | Full lamina structure (attributes, functions, segments, composites, outcomes, tags, gates) as JSON |
| WS | `/ws/feedback` | Live stream: one model snapshot per cycle; accepts `set_sensor`, `pause`, `resume`, `reset`; `source=replay` or `scenario` for the wearable lamina |
| GET | `/api/sources` | The feeds a lamina offers: replay days, speeds, scenario presets |
| GET | `/api/day` | One recorded day, computed whole from the lamina's `<day_view>` roles (`lamina`, `subject`, `date`) |
| GET | `/api/organisms`, `/api/organism` | Bodies of several laminae and the channels between them |
| WS | `/ws/organism` | Live stream for a body |
| POST | `/api/compute` | Accepts sensor values, returns computed results and vectors |
| POST | `/api/feedback/step`, `/api/feedback/run` | Run the feedback loop one or many cycles |
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

This is the format `POST /api/upload` accepts. The files in `presets/` demonstrate it for normal, hypertensive, and heart failure scenarios.

---

## Known Limitations

- **Q and CO disagree:** Q divides by R, a single-segment Poiseuille estimate, so at baseline Q is about 2.2 L/min while CO is about 4.75 L/min. Trust Q's trend, not its magnitude. SVR = (MAP − CVP) / CO is the resistance that moves with the pump.
- **Outcomes outside tolerance at a healthy baseline:** SVR (≈18.6 against a target of 14 ± 4) and lambda read outside tolerance with every input at its declared baseline. These are open questions about the targets and units, listed in `docs/circulatory_functions_review.xml`.
- **Recorded days are not live data:** the wearable lamina replays exported Apple Watch days; nothing streams from a device. Heart rate exists on only a fraction of a day's minutes (the watch is often off at night), and the model's usual error for one person was about 12.6 bpm. Real recordings are never in this repository; only a synthetic demo day is.
- **Windows terminal encoding:** The Omega character in console output may render incorrectly on some Windows terminals. This is cosmetic and does not affect computation.
- **No authentication or database:** a hosted copy (see *Hosting it online*) is open to anyone with its address, and keeps nothing between sessions.

---

## Documentation

- [Circulatory functions for review](./docs/circulatory_functions_review.xml) — the nine functions as they run, values at baseline, open points
- [Universal visualisation](./docs/universal-visualisation.md) — why the screen is built from the schema
- [Laminae](./docs/laminae.md) — what a lamina has to declare to join a body
- [Skeleton diagram brief](./docs/skeleton-diagram-brief.md) and [circulatory diagram brief](./docs/circulatory-diagram-brief.md) — the engine, and the engine with the circulatory lamina loaded
- [The lamina seam](./docs/gate-transmission.html) — what crosses between two laminae, and the gates on each side
- [Architecture refactor](./docs/architecture_refactor.md) — the move to a multi-lamina foundation, and what of it is still unbuilt
- [`docs/design/`](./docs/design/) — working plans from each phase: the feedback loop, permeability gates, two-sided gate channels, lamina switching, the wearable lamina and the Day view

---

## License

This project is licensed under the [MIT License](./LICENSE).
