# Getting Started with CardioTwin Development

This guide will help you start developing CardioTwin from where the project currently stands.

## 📁 Current Project Status

**Completed:**
- ✅ Project folder structure reorganized
- ✅ Backend files moved to `backend/` folder
- ✅ Preset XML scenarios created in `presets/` folder
- ✅ Documentation updated (Development Guide + Roadmap)
- ✅ Configuration files created (.gitignore, requirements.txt)
- ✅ Demo script updated to work with new structure

**Ready to build:**
- 🚀 Week 1: Backend API (FastAPI endpoints)
- 🚀 Week 2: Frontend UI (React + Vite)
- 🚀 Week 3: Visualization (Charts)
- 🚀 Week 4: Data persistence (localStorage)

---

## 🗂️ Project Structure Overview

```
cardio-twin/
├── backend/                           # ✅ READY
│   ├── circulatory_lamina.py         # Simulation engine (existing)
│   ├── universal_twin.py             # Base class (existing)
│   ├── circulatory_lamina.xml        # Schema definition (existing)
│   ├── requirements.txt              # Python dependencies
│   ├── __init__.py                   # Package marker
│   ├── README.md                     # Backend documentation
│   │
│   ├── main.py                       # 🔨 TO CREATE (Week 1, Day 1-2)
│   └── xml_converter.py              # 🔨 TO CREATE (Week 1, Day 3-4)
│
├── frontend/                          # 🔨 TO CREATE (Week 2)
│   └── .gitkeep                      # Placeholder
│
├── presets/                           # ✅ READY
│   ├── normal.xml                    # Healthy patient baseline
│   ├── hypertension.xml              # High blood pressure
│   └── heart_failure.xml             # Cardiac dysfunction
│
├── docs/                              # ✅ READY
│   ├── development_guide.md          # Complete tech stack guide
│   └── roadmap.md                    # 4-week day-by-day plan
│
├── demo.py                            # ✅ READY (Test script)
├── README.md                          # ✅ UPDATED
├── .gitignore                         # ✅ READY
└── GETTING_STARTED.md                 # ✅ This file
```

---

## 🚀 Quick Start (Test Current Setup)

### 1. Test the Simulation Engine

The core engine is ready and working. Test it with:

```bash
cd cardio-twin
python demo.py
```

**What this does:**
- Loads the `CirculatoryLamina` engine
- Runs 3 scenarios: Normal, Hypertension, Heart Failure
- Displays computed results and composite vectors

**Expected output:**
- Sensor data, computed values, gate warnings
- Normalized vector visualizations
- No errors (ignore Unicode emoji warnings on Windows)

---

## 📅 Next Steps: Week 1 Development

Follow the [Roadmap](./docs/roadmap.md) for detailed day-by-day tasks.

### **Week 1 Overview: Backend Foundation**

#### **Day 1-2: Create FastAPI App + Schema Endpoint**

**File to create:** `backend/main.py`

**Task:**
1. Set up FastAPI application
2. Add CORS middleware for local development
3. Implement `GET /api/schema` endpoint:
   - Parse `circulatory_lamina.xml`
   - Return slider configs (id, name, unit, min, max)
   - Return composite definitions

**Code template:**
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from circulatory_lamina import CirculatoryLamina

app = FastAPI(title="CardioTwin API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/schema")
def get_schema():
    twin = CirculatoryLamina("circulatory_lamina.xml")
    # Extract sensor attributes for sliders
    # Extract composites for charts
    # Return JSON schema
    pass

@app.get("/health")
def health():
    return {"status": "ok"}
```

**Test:**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Visit: http://localhost:8000/docs (Swagger UI)

---

#### **Day 3-4: Create XML Converter Module**

**File to create:** `backend/xml_converter.py`

**Task:**
1. `patient_xml_to_dict()` - Parse patient XML to sensor dict
2. `dict_to_patient_xml()` - Convert sensor dict to XML
3. `results_to_xml()` - Convert computation results to XML

**Code template:**
```python
import xml.etree.ElementTree as ET
from typing import Dict, Any

def patient_xml_to_dict(xml_string: str) -> Dict[str, float]:
    """Parse patient XML <sensor_data> to dict"""
    root = ET.fromstring(xml_string)
    sensor_data = {}
    for sensor in root.find("sensor_data"):
        sensor_data[sensor.tag] = float(sensor.text)
    return sensor_data

def dict_to_patient_xml(sensor_data: Dict[str, float]) -> str:
    """Convert dict to patient XML"""
    # Build XML structure
    pass

def results_to_xml(twin_results: Dict[str, Any]) -> str:
    """Convert results to XML with sensors, computed, vectors, warnings"""
    # Build comprehensive XML output
    pass
```

**Test:**
```python
# Test in Python REPL
from xml_converter import patient_xml_to_dict
with open("../presets/normal.xml") as f:
    data = patient_xml_to_dict(f.read())
print(data)  # Should show {'SBP': 120, 'DBP': 80, ...}
```

---

#### **Day 5: Computation & Upload Endpoints**

**Update:** `backend/main.py`

**Task:**
1. Add `POST /api/compute` - Accept JSON, return results
2. Add `POST /api/upload` - Accept XML file, return results
3. Add console logging (`[LOG]`, `[WARN]`, `[ERROR]`)

**Code template:**
```python
from pydantic import BaseModel
from fastapi import UploadFile

class ComputeRequest(BaseModel):
    sensor_data: Dict[str, float]

@app.post("/api/compute")
def compute(request: ComputeRequest):
    print(f"[LOG] Compute request: {request.sensor_data}")
    twin = CirculatoryLamina("circulatory_lamina.xml")
    # Set sensors, compute, return results
    pass

@app.post("/api/upload")
async def upload_patient_xml(file: UploadFile):
    print(f"[LOG] XML upload: {file.filename}")
    xml_content = await file.read()
    # Parse XML, compute, return results
    pass
```

**Test:**
- Use Swagger UI at http://localhost:8000/docs
- Test `/api/compute` with JSON payload
- Test `/api/upload` with `presets/normal.xml`

---

## 📖 Key Documents to Reference

### **Before Coding:**
1. Read [Development Guide](./docs/development_guide.md) - Understand the architecture
2. Read [Roadmap](./docs/roadmap.md) - See the full 4-week plan

### **During Development:**
- Backend: [backend/README.md](./backend/README.md)
- API design: See Development Guide Section 3.1
- XML format: See Development Guide Section 2

### **Reference Code:**
- Engine logic: `backend/circulatory_lamina.py`
- XML schema: `backend/circulatory_lamina.xml`
- Example usage: `demo.py`

---

## 🛠️ Development Tools Setup

### **Python Backend:**
```bash
# Install dependencies
cd backend
pip install -r requirements.txt

# Run development server
uvicorn main:app --reload --port 8000

# Test API
curl http://localhost:8000/health
```

### **Frontend (Week 2):**
```bash
# Create React + Vite app
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install

# Install UI libraries
npm install tailwindcss recharts axios

# Run development server
npm run dev
```

---

## 🎯 MVP Success Criteria

By Week 4, you should have:

✅ **Backend working:**
- 4 API endpoints responding correctly
- XML upload/download functional
- Console logging for debugging

✅ **Frontend working:**
- Dynamic sliders from schema
- Real-time chart updates (debounced)
- Profile save/load from localStorage

✅ **Visualization working:**
- Gauge charts showing MAP, CO, Q
- Radar charts showing composite vectors
- Chart switcher (Radar ↔ Table)

✅ **Data flow complete:**
- Load preset → Adjust sliders → See charts → Save profile
- Upload XML → Modify → Download results

---

## 🐛 Common Issues & Solutions

### **Demo.py Unicode Error (Windows)**
- **Issue:** Emoji characters fail in Windows terminal
- **Solution:** Ignore for now, or remove emojis from `demo.py` print statements
- **Not critical:** Doesn't affect functionality

### **Import Errors in demo.py**
- **Issue:** `ModuleNotFoundError: No module named 'circulatory_lamina'`
- **Solution:** The path is now updated to use `backend/` folder
- **Verify:** Check line 16-17 of `demo.py` has the path setup

### **XML Not Found**
- **Issue:** `FileNotFoundError: circulatory_lamina.xml`
- **Solution:** Use `backend/circulatory_lamina.xml` as the path
- **All references updated:** demo.py already uses correct path

---

## 📝 Development Workflow

### **Daily Workflow:**
1. Check [Roadmap](./docs/roadmap.md) for today's task
2. Create/edit the files listed
3. Test immediately using Swagger UI or Python REPL
4. Console log everything (`[LOG]` prefix)
5. Commit progress to git

### **Git Workflow:**
```bash
# After completing a day's work
git add .
git commit -m "Week 1 Day X: [brief description]"
git push
```

### **Testing as You Go:**
- Backend: Use Swagger UI at `/docs`
- Functions: Test in Python REPL
- XML: Validate with preset files
- Frontend: Use browser DevTools console

---

## 🎓 Learning Resources

- **FastAPI Tutorial:** https://fastapi.tiangolo.com/tutorial/
- **React Docs:** https://react.dev/learn
- **Recharts Examples:** https://recharts.org/en-US/examples
- **XML in Python:** Built-in `xml.etree.ElementTree` module

---

## 🚦 Ready to Start!

**Current Status:** ✅ Project structure complete and ready for Week 1

**Next Step:** Create `backend/main.py` with FastAPI app (Week 1, Day 1)

**Reference:** See [Roadmap](./docs/roadmap.md) Day 1-2 section for detailed implementation guide

**Questions?** Review [Development Guide](./docs/development_guide.md) for architecture details

---

**Good luck building CardioTwin! 🫀**
