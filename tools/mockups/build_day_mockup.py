"""Build the static day-view mockup for one bundle. Run from backend/.
usage: python build_mockup.py <template.html> <subject> <date> <out.html>
"""
import json
import re
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
from bundles import load_bundle, load_params  # noqa: E402
from session import Session  # noqa: E402
from signal_source import ReplayExhausted, ReplaySource  # noqa: E402

template, subject, date, out = sys.argv[1:5]
STRENGTH = {"TraditionalStrengthTraining", "FunctionalStrengthTraining", "CoreTraining"}
CARDIO = {"StairClimbing", "Elliptical", "Running", "Cycling", "HighIntensityIntervalTraining", "Rowing"}

b = load_bundle(subject, date)
S = b["samples"]
n = len(S)
params = load_params(subject)
coef = params["coefficients"] if params else None
s = Session(lamina=Path("wearable_lamina.xml"))
f = ReplaySource(s.twin, b, params=coef, speed=600)
s.seed(f.starting_state())
model = []
while True:
    try:
        r = f.next()
    except ReplayExhausted:
        break
    s.tick(r, missing=f.last_missing)
    live = "HR_model" not in s.twin.failed_attributes
    model.append(round(s.twin.attributes["HR_model"].value, 1) if live else None)

hr = [row["hr"] for row in S]
res = [h - m for h, m in zip(hr, model) if h is not None and m is not None]
sd = params["residual_sd"] if params else (st.pstdev(res) if len(res) > 1 else 5.0)

# stretches of 20+ minutes with no active-energy record: the watch said nothing
gaps, i = [], 0
while i < n:
    if S[i]["ae_kcal_min"] is None:
        j = i
        while j < n and S[j]["ae_kcal_min"] is None:
            j += 1
        if j - i >= 20:
            gaps.append([i, j])
        i = j
    else:
        i += 1


def words(label):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", label).replace("Traditional ", "").replace("Training", "training").capitalize()


sessions, i = [], 0
while i < n:
    w = S[i]["workout"]
    if w is None:
        i += 1
        continue
    j = i
    while j < n and S[j]["workout"] == w:
        j += 1
    if j - i >= 5:
        pairs = [(hr[k], model[k]) for k in range(i, j) if hr[k] is not None and model[k] is not None]
        meas = [hr[k] for k in range(i, j) if hr[k] is not None]
        end = [hr[k] for k in range(max(i, j - 2), j) if hr[k] is not None]
        later = [hr[k] for k in range(min(n, j + 4), min(n, j + 7)) if hr[k] is not None]
        enough = len(pairs) >= 3
        group = "walk" if w == "Walking" else "strength" if w in STRENGTH else "cardio" if w in CARDIO else "other"
        name = words(w)
        sessions.append(dict(
            start=i, end=j, group=group, name=name, short=name.split()[0],
            mean=st.mean(meas) if meas else None, peak=max(meas) if meas else None,
            mean_model=st.mean(p[1] for p in pairs) if enough else None,
            diff=(st.mean(p[0] for p in pairs) - st.mean(p[1] for p in pairs)) if enough else None,
            kcal=sum(S[k]["ae_kcal_min"] or 0 for k in range(i, j)),
            recovery=(max(end) - st.mean(later)) if end and later else None))
    i = j

ae10 = [sum(S[k]["ae_kcal_min"] or 0 for k in range(a, min(n, a + 10))) for a in range(0, n, 10)]
steps10 = [sum(S[k]["steps_min"] or 0 for k in range(a, min(n, a + 10))) for a in range(0, n, 10)]
active = sum(row["ae_kcal_min"] or 0 for row in S)
basal = sum(row["be_kcal_min"] or 0 for row in S)
steps = sum(row["steps_min"] or 0 for row in S)
worn = sum(row["ae_kcal_min"] is not None for row in S)
hr_min = sum(h is not None for h in hr)
wk_min = sum(w["end"] - w["start"] for w in sessions)
peak = max((h, k) for k, h in enumerate(hr) if h is not None) if hr_min else None
within = sum(abs(x) <= sd for x in res) / len(res) if res else None
quiet = [h for k, h in enumerate(hr) if h is not None and S[k]["workout"] is None and (S[k]["ae_kcal_min"] or 9) <= 0.5]
hm = lambda m: f"{m // 60:02d}:{m % 60:02d}"
synthetic = b["synthetic"]
owner = "a synthetic demo day (no real person)" if synthetic else f"subject {subject}"

kpis = [
    dict(value=f"{active:,.0f} kcal", label="Active energy", note=f"plus {basal:,.0f} kcal basal"),
    dict(value=f"{steps:,.0f}", label="Steps"),
    dict(value=f"{len(sessions)} · {wk_min} min", label="Sessions"),
    dict(value=f"{st.median(quiet):.0f} bpm" if quiet else "—", label="Heart rate when quiet", note=f"median of {len(quiet)} readings"),
    dict(value=f"{peak[0]:.0f} bpm" if peak else "—", label="Peak heart rate", note=f"at {hm(peak[1])}" if peak else ""),
    dict(value=f"{within:.0%}" if within is not None else "—", label="Readings as the model expected", note=f"within ±{sd:.0f} bpm"),
    dict(value=f"{worn / 60:.1f} h", label="Watch worn", note=f"heart rate on {hr_min} of 1,440 min"),
]
off = [w for w in sessions if w["diff"] is not None and abs(w["diff"]) > sd / 2]
headline = (f"{len(sessions)} session{'s' if len(sessions) != 1 else ''} ({wk_min} min), {active:,.0f} kcal active energy, {steps:,.0f} steps. "
            + ("Heart rate responded as the model expected in every session." if sessions and not off else
               f"Heart rate differed from the model in {len(off)} of {len(sessions)} sessions: " + ", ".join(
                   f"{w['name'].lower()} at {hm(w['start'])} ({'+' if w['diff'] > 0 else '−'}{abs(w['diff']):.0f} bpm)" for w in off) + "." if sessions else "No session recorded."))
sub = (f"Watch worn {worn / 60:.1f} h; heart rate was recorded on {hr_min} of 1,440 minutes, so most of the day has no measured heart rate. "
       + (f"No data: {', '.join(hm(a) + '–' + hm(min(z, 1439)) for a, z in gaps[:3])}." if gaps else ""))
data = dict(
    hr=hr, model=model, sd=sd, gaps=gaps, sessions=sessions, ae10=ae10, steps10=steps10, kpis=kpis,
    headline=headline, sub=sub,
    who=f"{owner} · {date} · {b['timezone']}",
    note=("<b>Static mockup for review, not the live dashboard.</b> Three layout options with the same data; pick with the buttons. "
          + ("This day is synthetic." if synthetic else f"Numbers are {subject}'s recorded day replayed through the model; the model's coefficients were fitted on {subject} only.")
          + " The dashed line is a model estimate, never a measurement. Not a clinical tool."),
    foot=f"Model: wearable lamina, {'fitted on ' + subject + ' only' if coef else 'declared default coefficients'}; usual error ±{sd:.1f} bpm (residual SD). Proxy labels such as sessions come from the watch's own workout records.",
)
Path(out).parent.mkdir(parents=True, exist_ok=True)
html = Path(template).read_text(encoding="utf-8").replace("/*DATA*/", json.dumps(data))
Path(out).write_text(html, encoding="utf-8")
print(f"{out}: sessions {len(sessions)}, gaps {gaps}, sd {sd:.1f}, hr minutes {hr_min}")
print("headline:", headline)
