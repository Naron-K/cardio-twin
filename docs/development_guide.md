# CardioTwin Web App - Development Guide (MVP)

This document outlines the technology stack, architecture, and implementation strategy for the **CardioTwin Research MVP** - a lightweight, anonymous cardiovascular simulation tool for research and educational purposes.

## 1. MVP Scope & Philosophy

**Target:** Research tool for cardiovascular simulation experimentation
**Timeline:** 4 weeks to working demo
**Data:** Anonymous patient data only (no PHI)
**Deployment:** Local development environment (production deployment in future phases)

**MVP Principles:**
- ✅ **Speed over perfection** - Fast iteration for researcher feedback
- ✅ **XML-first architecture** - Domain experts work with familiar XML format
- ✅ **Browser-based storage** - No database infrastructure needed for MVP
- ✅ **Core functionality** - Input → Compute → Visualize workflow
- ❌ **Skip for now:** Authentication, cloud deployment, complex security, multi-user features

---

## 2. System Architecture & Data Flow

### Data Format: XML-Centric Design

**Why XML?**
- Domain experts already familiar with XML structure
- Matches existing `circulatory_lamina.xml` schema
- Easy to validate and version control
- Human-readable for research collaboration

**Patient Data XML Format:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<patient>
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

### Data Flow Pipeline

```
┌─────────────────┐
│  User Input     │
│  - Manual sliders│
│  - XML upload   │
│  - Load preset  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  XML Parser     │
│  (Frontend/     │
│   Backend)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  FastAPI        │
│  /api/compute   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ CirculatoryLamina│
│  Computation    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  JSON Results   │
│  {values,       │
│   vectors,      │
│   warnings}     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  React Charts   │
│  - Gauge        │
│  - Radar        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  Save to        │
│  localStorage   │
│  (as XML)       │
└─────────────────┘
```

### Data Input Methods

1. **Manual UI Entry (Sliders):**
   - Left sidebar with dynamic sliders
   - Ranges auto-generated from `circulatory_lamina.xml` (`physio_min`/`physio_max`)
   - Debounced API calls (300ms) on slider change
   - Real-time chart updates

2. **XML File Upload:**
   - Drag-and-drop or file picker
   - Backend endpoint: `POST /api/upload`
   - Parses `<sensor_data>` block
   - Auto-populates sliders with uploaded values
   - User can continue adjusting after upload

3. **Preset Scenarios:**
   - Repository includes `presets/` folder:
     - `normal.xml` - Healthy patient baseline
     - `hypertension.xml` - High blood pressure scenario
     - `heart_failure.xml` - Cardiac dysfunction case
   - One-click load from dropdown

### Data Output & Export

1. **On-Screen Visualization:**
   - Numerical values table
   - Interactive charts (Gauge + Radar)
   - Gate warning alerts

2. **Download Options:**
   - Download current state as `patient.xml`
   - Download computation results as `results.xml`
   - Download chart as PNG (future enhancement)

3. **Browser Storage:**
   - Save scenarios to `localStorage` with custom names
   - Stored as XML strings
   - Load/Delete saved scenarios from sidebar

---

## 3. Technology Stack (MVP)

### 3.1 Backend Framework

**Choice: FastAPI (Python)**

**Why FastAPI?**
- ✅ Native Python - directly imports `CirculatoryLamina` engine
- ✅ Async/await - handles concurrent slider updates efficiently
- ✅ Fast - Starlette-based ASGI performance
- ✅ Auto-documentation - Swagger UI out-of-box for testing
- ✅ Pydantic validation - type-safe request/response models

**Alternatives Considered:**
- ❌ **Flask:** Synchronous by default, slower for real-time updates
- ❌ **Django:** Too heavyweight for simple API wrapper
- ❌ **Streamlit:** Great for prototypes but laggy for interactive sliders (requires server round-trip per update)

**MVP Backend Structure:**
```
backend/
├── main.py              # FastAPI app + 4 endpoints
├── xml_converter.py     # XML ↔ JSON utilities
├── circulatory_lamina.py  # (existing engine)
├── universal_twin.py      # (existing base class)
└── circulatory_lamina.xml # (existing schema)
```

**API Endpoints (4 total):**
1. `GET /api/schema` - Return slider configs from XML
2. `POST /api/compute` - Accept JSON, return computed results
3. `POST /api/upload` - Accept XML file, return computed results
4. `POST /api/download` - Convert results JSON → XML for download

---

### 3.2 Frontend Framework

**Choice: React 19 + Vite + TypeScript**

**Why React + Vite?**
- ✅ Component reusability - Perfect for dynamic sliders and charts
- ✅ Reactive state - Instant UI updates without page refresh
- ✅ Vite dev server - Lightning-fast hot module replacement
- ✅ TypeScript - Type safety for API contracts
- ✅ Massive ecosystem - Chart libraries, UI components, utilities

**UI Library: Tailwind CSS v3**
- Rapid prototyping with utility-first CSS
- Dark slate/cyan medical theme (no shadcn-ui — plain Tailwind sufficient for MVP)
- Clean, scientific dashboard aesthetic
- Configured via `tailwind.config.js` + `postcss.config.js`

**Chart Library: Recharts**
- Built specifically for React (declarative API)
- Composable chart components
- Smooth animations out-of-box
- Supports Gauge, Radar, Bar, Line charts
- Active maintenance and community

**Alternatives Considered:**
- ❌ **Chart.js:** Imperative API, harder to integrate with React state
- ❌ **D3.js:** Too low-level for MVP timeline
- ❌ **Plotly:** Heavy bundle size

**MVP Frontend Structure (Phase 3 complete):**
```
frontend/
├── tailwind.config.js        # Tailwind v3 content paths
├── postcss.config.js         # PostCSS with Tailwind + autoprefixer
├── vite.config.ts            # Vite proxy: /api + /presets → :8000
└── src/
    ├── components/
    │   ├── Sidebar.tsx           # ✅ 10 dynamic sliders + Reset button
    │   ├── GaugeChart.tsx        # ✅ Semi-circle gauge (MAP/CO/Q) with color zones
    │   ├── CardioRadarChart.tsx  # ✅ Radar chart with composite tabs + bar fallback
    │   ├── DataTable.tsx         # ✅ Tabular composite vector view
    │   ├── ProfileManager.tsx    # TODO Phase 4
    │   └── ErrorBoundary.tsx     # TODO Phase 4
    ├── utils/
    │   ├── api.ts                # ✅ fetchSchema, computeResults, uploadXML
    │   └── localStorage.ts       # TODO Phase 4
    ├── App.tsx                   # ✅ gauges + Radar/Table switcher + localStorage pref
    ├── index.css                 # ✅ Tailwind directives + range input styling
    └── main.tsx                  # Entry point
```

---

### 3.3 Data Persistence Strategy (MVP)

**Choice: Browser localStorage (No Database)**

**Why localStorage for MVP?**
- ✅ Zero infrastructure setup
- ✅ Instant read/write - no network latency
- ✅ Perfect for anonymous research data
- ✅ 5-10MB storage limit (sufficient for scenarios)
- ✅ Works offline
- ✅ No privacy concerns (data never leaves user's browser)

**Storage Structure:**
```javascript
localStorage.setItem('cardiotwin_profiles', JSON.stringify([
  {
    id: '1678901234567',
    name: 'My Hypertension Case',
    xmlData: '<patient><sensor_data>...</sensor_data></patient>',
    timestamp: '2024-03-12T10:30:00Z'
  },
  // ... more profiles
]))
```

**Operations:**
- **Save:** Store current slider state as XML string
- **Load:** Parse XML, populate sliders
- **Delete:** Remove from localStorage array
- **Export:** Download XML file to disk
- **Import:** Upload XML file, add to localStorage

**Future Migration Path:**
- Phase 2 can add PostgreSQL for multi-user features
- localStorage profiles can be exported/imported to database
- No breaking changes to user workflow

---

### 3.4 Development Tools

**Package Management:**
- Backend: `pip` + `requirements.txt` (simple for MVP)
- Frontend: `npm` or `pnpm`

**Code Quality:**
- Python: `black` (formatting), `mypy` (type checking) - optional for MVP
- TypeScript: Built-in type checking
- ESLint: Minimal config for catching errors

**Local Development:**
- Backend: `uvicorn main:app --reload` (port 8000)
- Frontend: `npm run dev` (port 5173)
- CORS enabled for local cross-origin requests

**Version Control:**
- Git + GitHub
- `.gitignore` excludes `node_modules/`, `__pycache__/`, `.env`
- Presets stored in `presets/` folder (committed to repo)

---

## 4. Visualization & Charting Strategy

### Chart Selection (MVP: 2 Chart Types)

**Priority 1: Gauge Chart** (Critical Metrics)
- **Purpose:** Display single critical values (MAP, CO, Q)
- **Why First:** Easiest to implement, immediately useful
- **Design:** Semi-circle gauge with color zones:
  - 🟢 Green zone: `physio_min` to `physio_max` (normal range)
  - 🟡 Yellow zone: ±10% outside range (warning)
  - 🔴 Red zone: >20% outside range (critical)
- **Data Source:** `physio_min`/`physio_max` from `circulatory_lamina.xml`
- **Library:** Recharts `RadialBarChart` component

**Priority 2: Radar Chart** (Composite Vectors)
- **Purpose:** Visualize multi-dimensional imbalances
- **Why Second:** Most impactful for understanding system-wide state
- **Design:** Spider chart with normalized `[0,1]` values
  - Perfect circle = healthy balance
  - Skewed shape = pathological imbalance
- **Data Source:** `composite_vectors` from computation results
- **Composites to Display:**
  - Pressure State (SBP, DBP, MAP)
  - Vessel State (eta, L, r, R)
  - Pump State (EDV, SV, HR, CO)
  - Conduction State (r_m, r_i, r_e, lambda)

**Future Enhancements (Post-MVP):**
- Line Chart: Historical tracking of slider changes
- Bar Chart: Comparison against baseline profile
- Heatmap: Gate violation history

---

### The Chart Switcher System

**Architecture:** Decouple data from presentation

**User Workflow:**
1. User sees Radar Chart displaying Pressure State
2. User clicks dropdown: "View as: [Radar] ▼"
3. Options appear: Radar, Bar, Table
4. User selects "Bar"
5. React swaps `<RadarChart />` → `<BarChart />` with same data
6. Preference saved to `localStorage`

**Implementation (Phase 3):**
```typescript
// Initialise from localStorage on mount
const [chartType, setChartType] = useState<'radar' | 'table'>(
  () => (localStorage.getItem('cardiotwin_chart_type') as 'radar' | 'table') ?? 'radar'
)

// Persist on change
const handleChartType = useCallback((type: 'radar' | 'table') => {
  setChartType(type)
  localStorage.setItem('cardiotwin_chart_type', type)
}, [])

// Render logic
{chartType === 'radar' && <CardioRadarChart results={results} schema={schema} />}
{chartType === 'table' && <DataTable results={results} schema={schema} />}
```

**Benefits:**
- ✅ No additional API calls needed
- ✅ Instant switching (no loading delay)
- ✅ User preferences persist across sessions
- ✅ Accommodates different learning styles (visual vs tabular)

---

## 5. Error Handling & Logging Strategy

**Philosophy:** Transparent errors for researchers to understand what went wrong

### Backend Error Handling

**Structured Error Responses:**
```python
@app.post("/api/compute")
def compute(request: ComputeRequest):
    try:
        # ... computation logic
        return result
    except Exception as e:
        print(f"[ERROR] Compute failed: {e}")  # Console log
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "type": type(e).__name__,
                "timestamp": datetime.now().isoformat()
            }
        )
```

**Error Categories:**
- `ValidationError` - Invalid sensor values
- `GateViolation` - Physiological range exceeded (warning, not error)
- `ComputationError` - Math errors (division by zero, sqrt of negative)
- `XMLParseError` - Malformed XML upload

**Logging:**
- All errors logged to console with `[ERROR]` prefix
- Warnings logged with `[WARN]` prefix
- Info logged with `[LOG]` prefix
- Format: `[LEVEL] Context: message`

### Frontend Error Handling

**React Error Boundary:**
```typescript
<ErrorBoundary>
  <App />
</ErrorBoundary>
```
- Catches React component crashes
- Displays user-friendly error screen
- Logs full stack trace to console
- Provides "Reload" button

**API Error Handling:**
```typescript
try {
  const response = await fetch('/api/compute', ...)
  if (!response.ok) {
    const error = await response.json()
    console.error('[ERROR] API call failed:', error)
    showToast('Computation failed: ' + error.detail.error)
  }
} catch (e) {
  console.error('[ERROR] Network error:', e)
  showToast('Network error - check if backend is running')
}
```

**User-Facing Errors:**
- Toast notifications for API errors
- Inline validation for slider ranges
- Alert banners for gate violations (non-blocking warnings)

**Debug Mode:**
- Add `?debug=1` to URL to show full error details
- Display computation logs in expandable panel
- Show raw API responses for troubleshooting

---

## 6. XML Conversion Architecture

### Bidirectional XML ↔ JSON Flow

**Backend Converter (`xml_converter.py`):**

**Function 1: XML → Dict (Input)**
```python
def patient_xml_to_dict(xml_string: str) -> Dict[str, float]:
    """Parse patient XML to sensor data dictionary"""
    # Parses <sensor_data> block
    # Returns: {'SBP': 120, 'DBP': 80, ...}
```

**Function 2: Dict → XML (Output)**
```python
def dict_to_patient_xml(sensor_data: Dict[str, float]) -> str:
    """Convert sensor data to patient XML"""
    # For saving scenarios
```

**Function 3: Results → XML (Export)**
```python
def results_to_xml(twin_results: Dict[str, Any]) -> str:
    """Convert computation results to structured XML"""
    # Includes: sensors, computed values, vectors, warnings
```

**Frontend Helpers (`xmlParser.ts`):**
- Parse uploaded XML files (FileReader API)
- Generate downloadable XML (Blob + download link)
- Validate XML structure before upload

**XML Schema Validation (Future):**
- Define XSD schema for patient XML
- Validate uploads against schema
- Provide helpful error messages for malformed XML

---

## 7. Performance Optimization

### API Request Optimization

**Debouncing:**
```typescript
// Prevent API spam from slider dragging
const debouncedCompute = useDebounce(computeAPI, 300) // 300ms delay
```

**Request Cancellation:**
```typescript
// Cancel in-flight requests if user changes sliders rapidly
const abortController = new AbortController()
fetch('/api/compute', { signal: abortController.signal })
```

**Loading States:**
- Show spinner/skeleton during computation
- Disable sliders during API call (prevent race conditions)
- Display "Computing..." indicator

### Frontend Performance

**Code Splitting:**
```typescript
// Lazy load chart components
const RadarChart = lazy(() => import('./components/RadarChart'))
```

**Memoization:**
```typescript
// Prevent unnecessary re-renders
const chartData = useMemo(() => transformData(results), [results])
```

**Virtual Scrolling:**
- Not needed for MVP (limited number of sliders/profiles)
- Add if profile list exceeds 50 items

### Backend Performance

**Computation Caching (Future):**
- Cache identical sensor inputs for 60 seconds
- Skip re-computation if inputs haven't changed
- Use Redis or in-memory dict

**For MVP:**
- No caching needed (computation is fast ~10-50ms)
- Focus on correctness over speed

---

## 8. Local Development Setup (MVP)

### Prerequisites
- Python 3.10+
- Node.js 18+
- Git

### Quick Start

**1. Clone Repository:**
```bash
git clone https://github.com/your-username/cardio-twin.git
cd cardio-twin
```

**2. Backend Setup:**
```bash
cd backend
pip install fastapi uvicorn python-multipart
uvicorn main:app --reload --port 8000
```

**3. Frontend Setup:**
```bash
cd frontend
npm install
npm run dev
```

**4. Open Browser:**
- Frontend: http://localhost:5173
- Backend API Docs: http://localhost:8000/docs

### Project Structure

```
cardio-twin/
├── backend/
│   ├── main.py                    # FastAPI app
│   ├── xml_converter.py           # XML utilities
│   ├── circulatory_lamina.py      # Simulation engine
│   ├── universal_twin.py          # Base class
│   └── circulatory_lamina.xml     # Schema definition
│
├── frontend/
│   ├── src/
│   │   ├── components/            # React components
│   │   ├── utils/                 # Helper functions
│   │   └── App.tsx                # Main app
│   ├── package.json
│   └── vite.config.ts
│
├── presets/                       # Preset XML files
│   ├── normal.xml
│   ├── hypertension.xml
│   └── heart_failure.xml
│
├── docs/                          # Documentation
│   ├── development_guide.md       # This file
│   └── roadmap.md                 # Timeline
│
└── README.md                      # Project overview
```

---

## 9. What We're NOT Building (For Now)

To maintain focus on the 4-week MVP timeline, these features are explicitly **deferred to future phases:**

### Deferred Features (Post-MVP)
- ❌ User authentication & authorization
- ❌ Database (PostgreSQL/MongoDB)
- ❌ Cloud deployment & scaling
- ❌ Multi-user collaboration
- ❌ Patient data privacy/encryption (using anonymous data only)
- ❌ HIPAA/GDPR compliance
- ❌ Automated testing suite
- ❌ CI/CD pipelines
- ❌ Mobile responsive design
- ❌ Accessibility (WCAG) compliance
- ❌ Internationalization (i18n)
- ❌ Advanced analytics dashboard
- ❌ Machine learning predictions
- ❌ EHR system integration
- ❌ PDF report generation
- ❌ Real-time collaboration (WebSocket)
- ❌ API rate limiting
- ❌ Monitoring & observability
- ❌ Advanced error recovery
- ❌ Data backup & recovery
- ❌ Inter-lamina communication (Metabolic, Respiratory)

### Why Defer These?

**Speed to prototype:** Get working demo in researcher hands quickly
**Validate concept:** Ensure core simulation is useful before infrastructure investment
**Iterate based on feedback:** Build what users actually need, not what we assume
**Technical debt is acceptable:** For research MVP, working > perfect

### Migration Path

When ready to scale beyond MVP:
1. Export localStorage profiles to PostgreSQL
2. Add authentication layer (JWT)
3. Deploy to cloud (Vercel + Railway)
4. Add testing & CI/CD
5. Implement advanced features based on user feedback

---

## 10. Success Metrics for MVP

How do we know the MVP is successful?

### Technical Metrics
- ✅ Backend responds to `/api/compute` in <100ms
- ✅ Frontend renders charts in <500ms after API response
- ✅ No crashes during 30-minute continuous use session
- ✅ Handles 100+ saved profiles in localStorage
- ✅ XML upload/download works for all preset scenarios

### User Experience Metrics
- ✅ Researcher can load preset, adjust sliders, see results in <30 seconds
- ✅ Gate violations clearly displayed when physiological limits exceeded
- ✅ Chart switcher works without confusion
- ✅ Saved profiles persist across browser sessions
- ✅ Error messages are understandable (not cryptic stack traces)

### Research Utility Metrics
- ✅ Can simulate normal vs pathological scenarios
- ✅ Composite vectors clearly show imbalances
- ✅ Researchers can export scenarios for collaboration
- ✅ System helps build intuition about cardiovascular dynamics

---

## 11. Next Steps After MVP

Once MVP is validated with researchers:

**Phase 2 (Weeks 5-8): Polish & Features**
- Add Line Chart for historical tracking
- Implement comparison mode (current vs baseline)
- Add batch XML processing (upload multiple files)
- Improve mobile responsiveness
- Add keyboard shortcuts

**Phase 3 (Weeks 9-12): Infrastructure**
- PostgreSQL database setup
- User authentication (JWT)
- Deploy to cloud hosting
- Add basic testing suite
- CI/CD with GitHub Actions

**Phase 4 (Weeks 13-16): Advanced Features**
- Inter-lamina support (Metabolic, Respiratory)
- PDF report generation
- Advanced analytics
- Machine learning predictions
- EHR integration planning

**Ongoing:**
- Gather researcher feedback continuously
- Iterate on UX based on usage patterns
- Expand preset library
- Improve documentation
