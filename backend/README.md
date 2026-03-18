# CardioTwin Backend

FastAPI-based simulation engine for cardiovascular modeling.

## Quick Start

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Run the development server:**
   ```bash
   uvicorn main:app --reload --port 8000
   ```

3. **Test the API:**
   - Swagger UI: http://localhost:8000/docs
   - Test endpoint: http://localhost:8000/health

## Project Structure

```
backend/
├── main.py                 # FastAPI app (Week 1)
├── xml_converter.py        # XML ↔ JSON utilities (Week 1)
├── circulatory_lamina.py   # Simulation engine
├── universal_twin.py       # Base class
├── circulatory_lamina.xml  # Schema definition
├── requirements.txt        # Python dependencies
└── __init__.py            # Package marker
```

## API Endpoints (Week 1 Implementation)

- `GET /api/schema` - Return slider configs
- `POST /api/compute` - Run simulation with JSON input
- `POST /api/upload` - Upload patient XML file
- `POST /api/download` - Download results as XML
- `GET /health` - Health check

## Development

See [docs/roadmap.md](../docs/roadmap.md) for the 4-week development plan.
