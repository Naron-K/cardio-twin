# CardioTwin MVP - Development Roadmap

This roadmap outlines the **4-week development plan** to build a working CardioTwin research MVP - a lightweight cardiovascular simulation tool with XML-based data flow and browser-based storage.

---

## 🎯 MVP Goal

**Deliverable:** Functional web application where researchers can:
1. Upload patient XML files or manually input sensor data via sliders
2. Run cardiovascular simulations using the `CirculatoryLamina` engine
3. Visualize results through interactive charts (Gauge + Radar)
4. Save/load scenarios to browser localStorage
5. Download results as XML files

**Timeline:** 4 weeks (20 working days)
**Scope:** Research tool with anonymous data only
**Deployment:** Local development environment (production deployment deferred)

---

## 📅 Week-by-Week Breakdown

### **Week 1: Backend Foundation + XML Converter**
**Focus:** Get the API layer working with XML support

#### **Day 1-2: FastAPI Setup & Schema Endpoint**
- ✅ Initialize FastAPI project structure
- ✅ Create `backend/main.py` with CORS configuration
- ✅ Implement `GET /api/schema` endpoint:
  - Parse `circulatory_lamina.xml`
  - Return JSON with slider configs (id, name, unit, min, max)
  - Return composite definitions for chart configuration
- ✅ Test with Swagger UI at `/docs`

**Deliverable:** `curl http://localhost:8000/api/schema` returns slider configuration

---

#### **Day 3-4: XML Converter Module**
- ✅ Create `backend/xml_converter.py`
- ✅ Implement `patient_xml_to_dict()` function:
  - Parse `<sensor_data>` block from patient XML
  - Return dict of sensor values
  - Handle malformed XML gracefully
- ✅ Implement `results_to_xml()` function:
  - Convert computation results to structured XML
  - Include sensors, computed values, vectors, warnings
- ✅ Implement `dict_to_patient_xml()` function:
  - Convert sensor dict back to patient XML (for saving scenarios)
- ✅ Write basic test cases (manual testing OK for MVP)

**Deliverable:** XML ↔ JSON conversion works in Python REPL

---

#### **Day 5: Computation & Upload Endpoints**
- ✅ Implement `POST /api/compute`:
  - Accept JSON payload: `{"sensor_data": {"SBP": 120, ...}}`
  - Initialize `CirculatoryLamina` instance
  - Set sensors, run `compute_all()`
  - Return JSON: `{sensors, computed, vectors, warnings}`
  - Add error handling with structured responses
- ✅ Implement `POST /api/upload`:
  - Accept XML file upload
  - Use `patient_xml_to_dict()` to parse
  - Run computation (reuse logic from `/api/compute`)
  - Return same JSON format
- ✅ Add console logging: `[LOG]`, `[WARN]`, `[ERROR]` prefixes

**Deliverable:** Both endpoints working, tested with Postman/curl

---

### **Week 2: Frontend Foundation + Dynamic Sliders** ✅ COMPLETE
**Focus:** Build the UI and connect to backend

#### **Day 6-7: React/Vite Setup & Layout** ✅
- ✅ Vite project already initialised (`npm create vite@latest frontend -- --template react-ts`)
- ✅ Dependencies installed: `tailwindcss`, `recharts`, `axios` (shadcn-ui skipped — plain Tailwind sufficient)
- ✅ Created `tailwind.config.js` + `postcss.config.js`
- ✅ Added Vite dev proxy: `/api` + `/presets` → `http://localhost:8000` in `vite.config.ts`
- ✅ 2-column layout in `App.tsx`: sidebar (300px fixed) + main area (flex-1)
- ✅ Dark slate/cyan medical theme applied via Tailwind utility classes

**Deliverable:** App with 2-column layout renders at `http://localhost:5173` ✅

---

#### **Day 8-9: Dynamic Slider Component** ✅
- ✅ `GET /api/schema` fetched on app mount via `useEffect`
- ✅ Created `src/components/Sidebar.tsx`:
  - Filters `source === 'SENSOR'` attributes (10 sliders total)
  - Each slider: name label, live value + unit, range bounds from `physio_min`/`physio_max`
  - Default value = midpoint of physiological range
  - Sliders disabled while API call is in flight
- ✅ State: `useState` for values, `useRef` for debounce timer
- ✅ "Reset to Defaults" button resets all sliders and triggers recompute

**Deliverable:** Sidebar renders 10 dynamic sliders from schema ✅

---

#### **Day 10: API Integration + Debouncing** ✅
- ✅ Created `src/utils/api.ts` with fully typed functions:
  - `fetchSchema()` → `Schema`
  - `computeResults(sensorData)` → `SimulationResults`
  - `uploadXML(file)` → `SimulationResults`
- ✅ Debouncing via `useRef` + `setTimeout` (custom hook, no lodash needed), 300ms delay
- ✅ Loading state: "Computing…" badge in sidebar; sliders disabled during call
- ✅ Main area shows 6 computed value cards (MAP, R, SV, CO, Q, λ) with colour-coded range bars
- ✅ Gate warnings displayed in a yellow alert banner when physiological limits exceeded
- ✅ Raw vectors JSON panel as placeholder (Phase 3 will replace with Gauge + Radar charts)
- ✅ `npm run build` passes with 0 TypeScript errors
- ✅ End-to-end tested live: sliders → debounced API → results rendered, gate warnings fire correctly

**Deliverable:** Slider changes trigger debounced API calls, results displayed ✅

---

### **Week 3: Visualization + Chart Switcher** ✅ COMPLETE
**Focus:** Make data understandable through charts

#### **Day 11-12: Gauge Charts** ✅
- ✅ Created `components/GaugeChart.tsx`:
  - Uses Recharts `RadialBarChart` (startAngle=180, endAngle=0 semi-circle)
  - Displays MAP, CO, Q as semi-circle gauges with value + unit overlay
  - Color zones based on normalised [0,1] position:
    - 🟢 Green: 25–75% of physiological range (normal)
    - 🟡 Amber: 15–25% or 75–85% (borderline)
    - 🔴 Red: <15% or >85% (extreme)
  - Background arc (gray) + value arc (colored) via `background` prop
- ✅ 3-column grid layout in `App.tsx` above composite vectors
- ✅ Value and unit overlaid absolutely within gauge arc opening
- ✅ Updates live on every computation result

**Deliverable:** 3 gauge charts (MAP, CO, Q) with color zones ✅

---

#### **Day 13-14: Radar Chart** ✅
- ✅ Created `components/CardioRadarChart.tsx`:
  - Uses Recharts `RadarChart` with `PolarGrid`, `PolarAngleAxis`, `PolarRadiusAxis`, `Radar`
  - Displays all 5 composite vectors (Pressure, Vessel, Pump, Conduction, Flow)
  - Values normalised to [0,100]% for display; domain fixed [0,100]
  - Filled cyan area with 20% opacity + stroke + dots
  - Tooltip shows normalised percentage on hover
- ✅ Composite tab switcher (pill buttons): Pressure / Vessel / Pump / Conduction / Flow
- ✅ Composite description shown below tabs (from schema)
- ✅ Fallback: horizontal bar view for single-attribute composites (flow_state/Q)
- ✅ Axis labels use full attribute names from schema (e.g. "Systolic Blood Pressure")

**Deliverable:** Radar chart visualizing composite vectors with tab switcher ✅

---

#### **Day 15: Chart Switcher Implementation** ✅
- ✅ "Radar | Table" toggle buttons in `App.tsx` above composite vectors panel
- ✅ Conditional rendering:
  ```typescript
  {chartType === 'radar' && <CardioRadarChart results={results} schema={schema} />}
  {chartType === 'table' && <DataTable results={results} schema={schema} />}
  ```
- ✅ Preference saved to `localStorage` key `cardiotwin_chart_type`
- ✅ Preference loaded on app mount via `useState` lazy initializer
- ✅ Created `components/DataTable.tsx`:
  - Groups all composite vectors by section
  - Shows attribute name, raw value, unit, colour-coded normalised bar per row

**Deliverable:** Users can switch between Radar and Table views ✅

---

### **Week 4: XML Upload + Profile System + Polish**
**Focus:** Complete the data flow loop

#### **Day 16: XML Upload UI**
- ✅ Create `components/XMLUpload.tsx`:
  - File input with drag-and-drop
  - Accept `.xml` files only
  - Parse uploaded file using `FileReader`
  - Send to `POST /api/upload`
  - Auto-populate sliders with uploaded values
- ✅ Add "Load Preset" dropdown:
  - Options: Normal, Hypertension, Heart Failure
  - Fetch from `presets/` folder (backend serves static files)
  - Parse and populate sliders
- ✅ Add visual feedback (upload progress, success message)

**Deliverable:** Users can upload XML or load presets

---

#### **Day 17-18: Profile Management System**
- ✅ Create `components/ProfileManager.tsx`:
  - Display list of saved profiles from localStorage
  - Each profile shows: name, timestamp, actions
- ✅ Implement localStorage operations:
  - Create `utils/localStorage.ts` helper
  - Save current state as XML with custom name
  - Load profile → populate sliders
  - Delete profile with confirmation
  - Export profile as downloadable XML file
- ✅ Add to sidebar (collapsible section)
- ✅ Style profile list (scrollable if >5 items)

**Deliverable:** Users can save/load/delete scenarios in browser

---

#### **Day 19: Error Handling + Logging**
- ✅ Create `components/ErrorBoundary.tsx`:
  - Wrap entire app
  - Display friendly error screen on crash
  - Log full error to console
  - Add "Reload" button
- ✅ Add toast notifications for:
  - API errors (computation failed)
  - XML parse errors
  - Profile save/load success
  - Gate violations (warnings, not errors)
- ✅ Improve console logging:
  - Frontend: `[LOG]`, `[WARN]`, `[ERROR]` prefixes
  - Backend: Already implemented in Week 1
- ✅ Add gate warning display:
  - Alert banner at top of main area
  - List each gate violation from API response
  - Color-coded (yellow for warnings)

**Deliverable:** Comprehensive error handling and user feedback

---

#### **Day 20: Final Polish + Documentation**
- ✅ UI polish:
  - Consistent spacing and colors
  - Responsive text sizing
  - Loading skeletons for charts
  - Smooth transitions
- ✅ Add README instructions:
  - How to run backend
  - How to run frontend
  - How to load presets
  - How to save scenarios
- ✅ Test full workflow:
  - Load preset → Adjust sliders → View charts → Save profile
  - Upload XML → Modify values → Download results
  - Switch chart types → Verify persistence
- ✅ Create demo video/screenshots (optional)
- ✅ Bug fixes and edge cases

**Deliverable:** Polished, documented, working MVP

---

## 📦 Deliverables Summary

### **Week 1 Output:**
- Backend API with 3 endpoints (schema, compute, upload)
- XML converter module
- Console logging system

### **Week 2 Output:** ✅ COMPLETE
- React 19 + Vite + TypeScript frontend with Tailwind CSS dark medical theme
- `src/components/Sidebar.tsx` — 10 dynamic sliders driven by `/api/schema`
- `src/utils/api.ts` — typed API client (fetchSchema, computeResults, uploadXML)
- 300ms debounced computation with loading state and disabled sliders
- Computed value cards with colour-coded physiological range bars
- Gate warning banner (yellow) when backend gate checks fail
- Vite dev proxy configured (`/api` + `/presets` → `:8000`)
- Build verified: `npm run build` passes, end-to-end tested against live backend

### **Week 3 Output:** ✅ COMPLETE
- `src/components/GaugeChart.tsx` — semi-circle gauge (MAP, CO, Q) with green/amber/red color zones
- `src/components/CardioRadarChart.tsx` — radar chart with 5 composite tabs + single-attr bar fallback
- `src/components/DataTable.tsx` — tabular backup view with normalised bars per attribute
- `App.tsx` updated: gauge row above computed cards, Radar/Table switcher with localStorage persistence
- Build verified: `npm run build` passes, end-to-end tested against live backend

### **Week 4 Output:**
- XML upload functionality
- Preset scenario loader
- Profile save/load system (localStorage)
- Error boundaries and user feedback
- Final polish and documentation

---

## 🎯 Definition of Done (MVP Complete)

The MVP is considered **complete** when:

### **Functional Requirements:**
- ✅ User can manually input sensor data via sliders
- ✅ User can upload patient XML file
- ✅ User can load preset scenarios (Normal, Hypertension, Heart Failure)
- ✅ Sliders trigger debounced computation (<300ms delay)
- ✅ Results display in Gauge charts (MAP, CO, Q)
- ✅ Results display in Radar chart (4 composite vectors)
- ✅ User can switch chart types (Radar ↔ Table)
- ✅ User can save current scenario to localStorage
- ✅ User can load previously saved scenarios
- ✅ User can download results as XML
- ✅ Gate violations display as warnings
- ✅ Errors display with helpful messages

### **Technical Requirements:**
- ✅ Backend responds in <100ms for computation
- ✅ Frontend renders charts in <500ms
- ✅ No console errors during normal operation
- ✅ localStorage persists across browser sessions
- ✅ All preset XMLs load successfully
- ✅ Code is documented with comments

### **Documentation Requirements:**
- ✅ README with setup instructions
- ✅ Development guide updated (this repo)
- ✅ Roadmap updated (this file)
- ✅ Inline code comments for complex logic

---

## 🚫 Explicitly Out of Scope (For This MVP)

These features are **intentionally deferred** to maintain 4-week timeline:

### **Infrastructure:**
- ❌ Database (using localStorage instead)
- ❌ Authentication/Authorization
- ❌ Cloud deployment (local only)
- ❌ CI/CD pipelines
- ❌ Docker containers
- ❌ Automated testing suite

### **Features:**
- ❌ Real-time collaboration
- ❌ Patient data privacy/encryption (anonymous data only)
- ❌ Advanced analytics dashboard
- ❌ PDF report generation
- ❌ Mobile app version
- ❌ Accessibility (WCAG) compliance
- ❌ Internationalization (English only)

### **UI/UX:**
- ❌ Mobile responsive design (desktop-first)
- ❌ Dark mode
- ❌ Customizable themes
- ❌ Advanced animations
- ❌ Keyboard shortcuts

### **Charts:**
- ❌ Line chart (historical tracking) - deferred to Phase 2
- ❌ Bar chart - deferred to Phase 2
- ❌ Export charts as PNG
- ❌ Interactive tooltips (basic tooltips only)

---

## 📈 Post-MVP Roadmap (Future Phases)

### **Phase 2: Enhanced Features (Weeks 5-8)**
- Add Line Chart for historical tracking
- Add Bar Chart for baseline comparison
- Implement batch XML processing
- Add data export options (CSV, JSON)
- Improve mobile responsiveness
- Add keyboard shortcuts
- Expand preset library

### **Phase 3: Infrastructure & Scaling (Weeks 9-12)**
- PostgreSQL database migration
- User authentication (JWT)
- Deploy to cloud (Vercel + Railway)
- Docker containerization
- Basic automated testing
- CI/CD with GitHub Actions
- Monitoring and logging

### **Phase 4: Advanced Research Features (Weeks 13-16)**
- Inter-lamina support (Metabolic, Respiratory)
- Advanced analytics dashboard
- Machine learning predictions
- Batch simulation runner
- Collaborative features (share scenarios)
- PDF report generation
- API for external tools

### **Phase 5: Production Hardening (Weeks 17-20)**
- HIPAA/GDPR compliance (if handling real patient data)
- Security audit
- Performance optimization
- Comprehensive testing (unit, integration, E2E)
- Accessibility compliance (WCAG 2.1 AA)
- Production deployment
- User training materials

---

## 🎓 Learning Resources for Development

### **Backend (Python/FastAPI):**
- FastAPI Tutorial: https://fastapi.tiangolo.com/tutorial/
- XML Processing in Python: `xml.etree.ElementTree` docs
- CirculatoryLamina code review (existing codebase)

### **Frontend (React/TypeScript):**
- React Docs: https://react.dev/learn
- Vite Guide: https://vitejs.dev/guide/
- Recharts Examples: https://recharts.org/en-US/examples
- Tailwind CSS: https://tailwindcss.com/docs

### **Tools:**
- Git/GitHub workflow basics
- Browser DevTools for debugging
- Postman for API testing

---

## ✅ Success Criteria

The MVP is successful if:

1. **Researchers can use it independently** (no developer hand-holding needed)
2. **Core simulation works correctly** (matches `demo.py` outputs)
3. **Data persists reliably** (localStorage doesn't lose profiles)
4. **Charts are interpretable** (researchers understand what they see)
5. **Errors don't block progress** (graceful degradation)
6. **Positive user feedback** from initial testing

**MVP Complete Target Date:** End of Week 4

---

## 📞 Support & Questions

For development questions or roadblocks:
- Check existing code: `demo.py`, `circulatory_lamina.py`
- Review development guide: `docs/development_guide.md`
- Console logs are your friend (we implemented comprehensive logging)
- Simplify first, optimize later

**Remember:** The goal is a working prototype, not production perfection. Speed and functionality over polish for MVP.
