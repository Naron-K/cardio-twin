"""Build the static mockup of the adapting "week and risk" screen.  Run from backend/.

usage: python ../tools/mockups/build_adaptation_mockup.py <subject> <out.html>

Calls the backend's own endpoints in process (GET /api/assessment/options,
GET /api/plan/options, POST /api/assessment) and writes their answers into a
page.  The page holds no model: every figure it draws is one of those answers.
The head and styles are taken from forecast_template.html (the approved
mockup of the screen this one extends); adaptation_body.html holds the rest.

The entered values are the lamina's invented examples, labelled as such.  The
models behind every figure are placeholders (docs/design/ADAPTATION_TWIN_PLAN.md).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from fastapi.testclient import TestClient  # noqa: E402

import universal_twin  # noqa: E402
from main import app  # noqa: E402

universal_twin._ECHO_LOG = False
HERE = Path(__file__).resolve().parent

subject, out = sys.argv[1:3]
client = TestClient(app)


def get(url: str) -> dict:
    response = client.get(url)
    if response.status_code != 200:
        raise SystemExit(f"GET {url} -> {response.status_code}: {response.text[:400]}")
    return response.json()


options = get("/api/assessment/options")
if not options.get("examples") or not options.get("horizons"):
    raise SystemExit("The assessment lamina declares no examples or no horizons.")
plan_lamina = next(
    entry["id"] for entry in get("/api/laminae")["laminae"]
    if get(f"/api/schema?lamina={entry['id']}").get("plan_view")
)
plan = dict(get(f"/api/plan/options?subject={subject}&lamina={plan_lamina}")["default_plan"])
plan["subject"] = subject
examples = {e["id"]: e["values"] for e in options["examples"]}
first = options["examples"][1]["id"] if len(options["examples"]) > 1 else options["examples"][0]["id"]


def post(entries: dict, days: int) -> dict:
    body = {"subject": subject, "entries": entries, "plan": plan, "days_per_week": days}
    response = client.post(f"/api/assessment?activity_lamina={plan_lamina}", json=body)
    if response.status_code != 200:
        raise SystemExit(f"POST /api/assessment -> {response.status_code}: {response.text[:400]}")
    answer = response.json()
    answer["day"] = None  # the minute arrays are not drawn here
    return answer


states = {"empty": {"entries": {}, "profile": None, "days_per_week": 3, "response": post({}, 3)}}
for pid, values in examples.items():
    states[pid] = {"entries": values, "profile": pid, "days_per_week": 3, "response": post(values, 3)}
states["lighter"] = {"entries": examples[first], "profile": first, "days_per_week": 0, "response": post(examples[first], 0)}
states["daily"] = {"entries": examples[first], "profile": first, "days_per_week": 7, "response": post(examples[first], 7)}

head = (HERE / "forecast_template.html").read_text(encoding="utf-8")
head = head[: head.index("</style>") + len("</style>")]
head = head.replace("<title>Forecast twin mockup</title>", "<title>Adapting risk mockup</title>")
page = head + "\n" + (HERE / "adaptation_body.html").read_text(encoding="utf-8")
page = page.replace("<script>window.MOCK = /*DATA*/;</script>", "")
page = page.replace("<script>\n(function () {", "<script>window.MOCK = " + json.dumps({"options": options, "states": states}) + ";</script>\n<script>\n(function () {", 1)
Path(out).write_text(page, encoding="utf-8")

print(f"wrote {out} ({Path(out).stat().st_size // 1024} KB)")
for name, state in states.items():
    a = state["response"]["assessment"]
    print(f"{name:10s} days {state['days_per_week']}",
          [(r["id"], r["now"], [s["value"] for s in r.get("series", [])], r.get("settled")) for r in a["results"]])
