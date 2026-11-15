"""Build the static "Plan a day" mockup.  Run from backend/.

usage: python ../tools/mockups/build_plan_mockup.py <template.html> <subject> <out.html> [data.json]

Reads every recorded day of <subject>, derives activity templates (energy and
steps per kind of session and per clock hour outside sessions), and writes them
with the subject's fitted coefficients into the template at /*DATA*/.  It also
projects three reference plans with the fitter's own forward model
(fit_hr_model.simulate_day) and embeds the result under "check", so the page's
JavaScript model can be compared with the lamina's numbers.

This is mockup scaffolding: the real feature computes projections on the
server (docs/design/PLANNED_DAY_PLAN.md).  The person is shown as "Subject
demo", never by folder name.
"""
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path.cwd()))
sys.path.insert(0, str(Path.cwd() / "tools"))
import fit_hr_model as F  # noqa: E402
from bundles import read_subject_label  # noqa: E402

template, subject, out = sys.argv[1:4]
data_out = sys.argv[4] if len(sys.argv) > 4 else None
LABEL = read_subject_label(Path("bundles") / subject, subject)
MIN_SESSION = 5
N = 1440

# The kinds offered: the lamina's three indicator groups, read from its XML.
twin = F.load_twin(F.WEARABLE_XML)
GROUPS = {}
for group, attr, label in (("walk", "is_walk", "Walk"),
                           ("strength", "is_strength", "Strength"),
                           ("cardio", "is_cardio", "Cardio")):
    rf = twin.attributes[attr].replay_field
    GROUPS[group] = dict(indicator=attr, label=label,
                         labels=set(rf.split(" in ", 1)[1].split(", ")))


def group_of(workout):
    for g, spec in GROUPS.items():
        if workout in spec["labels"]:
            return g
    return None


days = F.load_days(Path("bundles"), subject)
params = json.loads((Path("bundles") / subject / "params.json").read_text())
coef = params["coefficients"]

sess_ae = {g: [] for g in GROUPS}
sess_steps = {g: [] for g in GROUPS}
sess_n = {g: 0 for g in GROUPS}
hour_ae = [[] for _ in range(24)]
hour_steps = [[] for _ in range(24)]
steps_outside, first_worn, last_worn, levels, temps = [], [], [], [], []
for b in days:
    s = b["samples"]
    if len(s) != N:          # daylight-saving days: keep templates on a 24 h clock
        continue
    if b["day"].get("hr_level_rts") is not None:
        levels.append(b["day"]["hr_level_rts"])
    worn = [r["ae_kcal_min"] is not None for r in s]
    if sum(worn) >= 12 * 60:
        idx = [m for m in range(N) if worn[m]]
        first_worn.append(idx[0])
        last_worn.append(idx[-1] + 1)
        steps_outside.append(sum((r["steps_min"] or 0) for r in s if r["workout"] is None))
    for m, r in enumerate(s):
        if r["t_app_c"] is not None and worn[m]:
            temps.append(r["t_app_c"])
        if worn[m] and r["workout"] is None:
            hour_ae[m // 60].append(r["ae_kcal_min"])
            hour_steps[m // 60].append(r["steps_min"] or 0)
    m = 0
    while m < N:
        w = s[m]["workout"]
        if w is None:
            m += 1
            continue
        e = m
        while e < N and s[e]["workout"] == w:
            e += 1
        g = group_of(w)
        mins = [k for k in range(m, e) if worn[k]]
        if g and e - m >= MIN_SESSION and len(mins) >= 3:
            sess_n[g] += 1
            sess_ae[g].append(float(np.mean([s[k]["ae_kcal_min"] for k in mins])))
            sess_steps[g].append(float(np.mean([s[k]["steps_min"] or 0 for k in mins])))
        m = e

kinds = []
for g, spec in GROUPS.items():
    if sess_n[g] < 5:
        continue
    p10, p50, p90 = (float(np.percentile(sess_ae[g], q)) for q in (10, 50, 90))
    kinds.append(dict(id=g, label=spec["label"], indicator=spec["indicator"],
                      sessions=sess_n[g],
                      ae=dict(p10=round(p10, 3), p50=round(p50, 3), p90=round(p90, 3)),
                      steps_per_min=round(float(np.mean(sess_steps[g])), 1)))
all_ae = float(np.mean([x for h in hour_ae for x in h]))
all_st = float(np.mean([x for h in hour_steps for x in h]))
hourly_ae = [round(float(np.mean(h)), 4) if len(h) >= 30 else round(all_ae, 4) for h in hour_ae]
hourly_steps = [round(float(np.mean(h)), 3) if len(h) >= 30 else round(all_st, 3) for h in hour_steps]


def r5(x):
    return int(5 * round(x / 5))


day = dict(
    awake=[r5(np.median(first_worn)), r5(np.median(last_worn))],
    t_app=dict(min=math.floor(np.percentile(temps, 5)), max=math.ceil(np.percentile(temps, 95)),
               default=round(float(np.median(temps)))),
    # The slider reaches 10 bpm either side of the median, so a what-if can go
    # past this person's own days; the recorded range is shown beside it.
    level=dict(min=math.floor(np.median(levels) - 10), max=math.ceil(np.median(levels) + 10),
               default=round(float(np.median(levels)), 1),
               recorded=[math.floor(np.percentile(levels, 5)), math.ceil(np.percentile(levels, 95))]),
    steps_outside=dict(p10=int(np.percentile(steps_outside, 10)), p50=int(np.median(steps_outside)),
                       p90=int(np.percentile(steps_outside, 90))),
)
KIND = {k["id"]: k for k in kinds}


# ── The reference projection (the rules the page's model must follow) ──────
def project(plan):
    a0, a1 = plan["awake"]
    ae = np.full(N, np.nan)
    steps = np.zeros(N)
    ind = {spec["indicator"]: np.zeros(N) for spec in GROUPS.values()}
    in_session = np.zeros(N, bool)
    for se in plan["sessions"]:
        k = KIND[se["kind"]]
        sl = slice(se["start"], se["start"] + se["minutes"])
        ae[sl] = se["intensity"]
        steps[sl] = se["steps"] / se["minutes"]
        ind[k["indicator"]][sl] = 1.0
        in_session[sl] = True
    outside = [m for m in range(a0, a1) if not in_session[m]]
    for m in outside:
        ae[m] = hourly_ae[m // 60]
    w = np.array([hourly_steps[m // 60] for m in outside], float)
    w = w / w.sum() if w.sum() > 0 else np.full(len(outside), 1.0 / max(1, len(outside)))
    steps[outside] = plan["steps_outside"] * w
    inp = dict(hour_local=np.arange(N) / 60.0, dt_s=np.full(N, 60.0),
               HR_level=np.full(N, plan["level"]), AE_rate=ae,
               T_app=np.full(N, float(plan["t_app"])), **ind)
    target, model = F.simulate_day(inp, coef)
    nn = lambda a: [None if not math.isfinite(x) else round(float(x), 4) for x in a]  # noqa: E731
    return dict(hr=nn(model), target=nn(target), ae=nn(ae), steps=[round(float(x), 4) for x in steps])


def typical(kind, start, minutes):
    k = KIND[kind]
    return dict(kind=kind, start=start, minutes=minutes, intensity=k["ae"]["p50"],
                steps=round(k["steps_per_min"] * minutes))


default_plan = dict(awake=day["awake"], t_app=day["t_app"]["default"], level=day["level"]["default"],
                    steps_outside=day["steps_outside"]["p50"],
                    sessions=[typical("walk", 450, 30), typical("strength", 1080, 45)])
alt1 = dict(default_plan, t_app=34, level=70.0, steps_outside=3000,
            sessions=[dict(typical("cardio", 360, 40), intensity=KIND["cardio"]["ae"]["p90"])])
alt2 = dict(default_plan, awake=[420, 1380], sessions=[])
check = [dict(plan=p, **project(p)) for p in (default_plan, alt1, alt2)]

data = dict(
    subject_label=LABEL,
    applies_to=f"Fitted on {LABEL}'s recordings only",
    days=len(days),
    coef=coef, hr_floor=F.HR_TARGET_FLOOR,
    kinds=kinds, hourly=dict(ae=hourly_ae, steps=hourly_steps),
    day=day, default_plan=default_plan,
    limits=dict(session_minutes=[5, 180], max_sessions=6, step_minutes=5),
    error=dict(kcal_mae=51, kcal_median=340, hr_mae=10.8, hr_mae_measured_energy=9.8,
               peak_low=[20, 34], steps_mae=2500, steps_median=9115, test_days=35, test_sessions=24),
    check=check,
)
html = Path(template).read_text(encoding="utf-8").replace("/*DATA*/", json.dumps(data))
Path(out).parent.mkdir(parents=True, exist_ok=True)
Path(out).write_text(html, encoding="utf-8")
if data_out:
    Path(data_out).write_text(json.dumps(data, indent=1), encoding="utf-8")
print(f"{out}: kinds {[(k['id'], k['sessions'], k['ae']) for k in kinds]}")
print("day", day)
print("default plan", default_plan)
for c in check:
    hr = [x for x in c["hr"] if x is not None]
    print(f"check: sessions {len(c['plan']['sessions'])} minutes {len(hr)} hr {min(hr):.1f}-{max(hr):.1f} "
          f"kcal {np.nansum([x for x in c['ae'] if x is not None]):.0f} steps {sum(c['steps']):.0f}")
