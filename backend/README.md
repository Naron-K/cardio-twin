# CardioTwin Backend

FastAPI app and the domain-neutral twin engine. The project overview, the model
and the API table are in the [root README](../README.md).

## Run

```bash
pip install -r requirements.txt
python serve.py                    # circulatory lamina on port 8000
python serve.py respiratory        # another lamina
python serve.py circulatory 8010   # another port
```

`serve.py` sets the default lamina; the dashboard can still switch lamina per
request. Swagger UI is at `http://localhost:8000/docs`.

## Test

```bash
python -m pytest tests -q
```

## Layout

| File | What it holds |
|------|---------------|
| `universal_twin.py` | The engine: XML parsing, the function chain, gates, composites, the feedback loop. Knows no physiology. |
| `*_lamina.xml` + `*_lamina.py` | One lamina each: its declaration, and the arithmetic for every function it declares. |
| `laminae.py` | Pairs a lamina XML with the class that implements it, by the XML's own id. |
| `organism.py`, `organism*.xml` | Bodies: several laminae joined by channels with a gate on each side. |
| `feedback_controller.py` | The adaptive feedback loop. |
| `session.py`, `streaming_runtime.py`, `signal_source.py`, `snapshot.py` | The live stream behind `/ws/feedback` and `/ws/organism`. |
| `main.py` | The FastAPI routes. |
| `xml_converter.py` | XML ↔ JSON for patient files. |
| `tools/capture_gate_traces.py` | Regenerates the gate-trace fixtures the tests compare against. |
