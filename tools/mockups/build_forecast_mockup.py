"""Build the static "forecast twin" mockup.  Run from backend/.

usage: python ../tools/mockups/build_forecast_mockup.py <template.html> <subject> <out.html>

Calls the backend's own endpoints in process (GET /api/assessment/options,
GET /api/plan/options, POST /api/assessment) and writes their answers into the
template at /*DATA*/.  The page holds no model: every figure it draws is one
of those answers.

The entered values are the lamina's own <example>, which is INVENTED and says
so.  Nothing here is a real person's test result.  The models behind the
figures are placeholders (docs/design/FORECAST_TWIN_PLAN.md, section 1.1).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from fastapi.testclient import TestClient  # noqa: E402

import universal_twin  # noqa: E402
from main import app  # noqa: E402

universal_twin._ECHO_LOG = False

template, subject, out = sys.argv[1:4]
client = TestClient(app)


def get(url: str) -> dict:
    response = client.get(url)
    if response.status_code != 200:
        raise SystemExit(f"GET {url} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def post(body: dict) -> dict:
    response = client.post("/api/assessment?activity_lamina=" + plan_lamina, json=body)
    if response.status_code != 200:
        raise SystemExit(f"POST /api/assessment -> {response.status_code}: {response.text[:400]}")
    answer = response.json()
    # The day's minute-by-minute arrays are not drawn on this mockup.
    answer["day"] = None
    return answer


options = get("/api/assessment/options")
if not options.get("example"):
    raise SystemExit("The assessment lamina declares no <example>; the mockup needs one.")
example = options["example"]["values"]

plan_lamina = next(
    entry["id"] for entry in get("/api/laminae")["laminae"]
    if get(f"/api/schema?lamina={entry['id']}").get("plan_view")
)
plan_options = get(f"/api/plan/options?subject={subject}&lamina={plan_lamina}")
plan = dict(plan_options["default_plan"])
plan["subject"] = subject

# "Partly entered": the first group whole, plus the first entry of every other group.
partial = {}
for index, group in enumerate(options["groups"]):
    for position, entry in enumerate(group["entries"]):
        if index == 0 or position == 0:
            partial[entry["attribute"]] = example[entry["attribute"]]

DAYS = 3

# "Flags raised": the example with two figures raised by hand and a daily plan.
# The ids come from the view itself, so this script names no attribute.
raised = dict(example)
for group in options["groups"]:
    for entry in group["entries"]:
        if entry["kind"] == "yesno" and entry["attribute"] in {f["entries"][0] for f in options["flags"] if len(f["entries"]) == 1}:
            raised[entry["attribute"]] = 1
for flag in options["flags"]:
    for attribute in flag["entries"]:
        entry = next(e for g in options["groups"] for e in g["entries"] if e["attribute"] == attribute)
        if entry["kind"] == "number":
            raised[attribute] = round(entry["min"] + 0.52 * (entry["max"] - entry["min"]))

states = {}
for name, entries, days in (
    ("empty", {}, DAYS),
    ("partial", partial, DAYS),
    ("example", example, DAYS),
    ("less", example, 0),
    ("flags", raised, 7),
):
    body = {"subject": subject, "entries": entries, "plan": plan, "days_per_week": days}
    states[name] = {"entries": entries, "days_per_week": days, "response": post(body)}

data = {"options": options, "states": states, "example_label": options["example"]["label"]}
page = Path(template).read_text(encoding="utf-8")
if "/*DATA*/" not in page:
    raise SystemExit(f"{template} has no /*DATA*/ marker.")
Path(out).write_text(page.replace("/*DATA*/", json.dumps(data)), encoding="utf-8")

shown = states["example"]["response"]
print(f"wrote {out} ({Path(out).stat().st_size // 1024} KB)")
print("dose:", json.dumps(shown["dose"])[:300])
for result in shown["assessment"]["results"]:
    print(result["id"], "now", result["now"], "planned", result["planned"], result["status"])
