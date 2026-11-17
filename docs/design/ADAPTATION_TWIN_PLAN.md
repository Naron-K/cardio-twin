# One chain from a planned week to risk: risk factors that adapt over weeks

Written 2026-11-18. Nothing here is built. It follows `FORECAST_TWIN_PLAN.md` (read its
sections 7.1 and 7.2 first: they describe the code this plan changes) on branch
`feature/wearable-lamina`. This is a handoff plan: whoever builds a phase needs this file,
that one, and the repository.

## 1. Why, and what the user decided (2026-11-18)

The page built so far has two halves joined by one number. Sessions become a weekly dose;
the dose becomes one multiplier on the risk. The entered test results never move, the
person's own fitness never enters the risk, and the screen reads as two separate tools.

| Question | Decision |
|---|---|
| How a plan changes risk | **Through the risk factors.** Keeping a plan up for weeks shifts fasting glucose, blood pressure, HDL and the like; the risk is the same equation read on the shifted values. This replaces the dose-response multiplier. The two are never both applied: that would count the benefit twice. |
| The person's fitness | **It enters the risk from the recordings**, not from the form: resting heart rate, and VO2max when the recordings hold it. |
| Example values | **Two or three invented profiles, stratified** (low risk; borderline / prediabetes; high cardiovascular risk), each labelled `invented example`. They replace the single example. None sits at the edge of a range, where the equations saturate. |
| Adaptation constants | **Each is its own declared parameter**, with a note a clinician can read, so an expert can correct "how much, after how many weeks" without reading code. |
| Time | **The screen shows the delay**: the effect after 4, 8 and 12 weeks of keeping the plan. One session changes no test result, and the screen must say so. |
| Who builds | Another agent, later, from this plan. |

This reverses two lines of `FORECAST_TWIN_PLAN.md`: its section 4 row "Will my blood
pressure, glucose or cholesterol move: not shown as a projection", and its decision 3
(pathway a). Everything else there stands, above all: every model is a placeholder with a
status, nothing entered is defaulted, nothing entered reaches the URL, storage or a log.

## 2. The chain

```
planned day ─► planned week ─► dose change against the habit (MET-h/week)
                                        │
                                        ▼   kept up for t weeks
recordings ─► fitness now ──────► fitness at t  ┐
form ───────► risk factors now ─► risk factors at t ├─► the same risk equation ─► risk at t
                                                ┘
```

- At t = 0 the plan changes nothing: "risk with the plan" equals "risk now". This is the
  first test of the build and the first thing the screen teaches.
- A plan equal to the habit changes nothing at any t.
- A plan below the habit moves every factor the wrong way, at the same pace.

## 3. What was measured (exploratory, 2026-11-18)

**A resting marker can be read from the published recordings.** Per day: heart rate in
minutes outside sessions with active energy below 0.5 kcal/min ("quiet"), then the 10th
percentile. Over Subject demo's 131 days of 2025:

| | Value |
|---|---|
| Days with at least 10 quiet minutes of heart rate | 115 of 131 (median 62 quiet minutes a day) |
| Quiet 10th percentile, median over days | 64.6 bpm (the watch's own resting heart rate for the same period is about 66) |
| Quiet median | 77.5 bpm (the bundles' `hr_level_rts` is 77.2: that field is a daytime level, not a resting rate) |
| Weekly value, 17 full weeks | 60.3 to 69.0, SD 2.3 |
| Correlation of a week's dose with the next week's change in the marker | 0.09 (16 pairs) |

What this says:

- The marker exists without publishing anything new, and agrees with the watch to 1.4 bpm.
- **Nineteen weeks cannot show adaptation.** The marker's week-to-week noise (2.3 bpm) is
  the size of the effect one would look for, and it does not follow the dose. The fitness
  adaptation therefore starts as a placeholder like the others. The longer record (years,
  kept locally in the health-data repository) is the only place it can be tested: phase 6.
- VO2max is not in a bundle. The bundle's `day` block holds only coverage fields and
  `hr_level_rts`.

## 4. Decisions the user must make before phase 1

| # | Question | Recommended |
|---|---|---|
| 1 | Fitness from the recordings: only the resting marker of section 3 (already derivable), or also the watch's VO2max and resting heart rate, which means adding two fields to the bundle export and publishing them | Start with the resting marker. Add VO2max only with the person's say-so, since it is new data about them in a public repository |
| 2 | Horizons | 4, 8 and 12 weeks, plus "settled" (the value the factor tends to). No horizon beyond a year: ageing is not modelled |
| 3 | Body mass as an adapting factor | Declared, with a shift of zero until an expert sets it: exercise alone moves it little and diet is not in this twin |
| 4 | The expert who replaces the placeholders | Still to be named. The build does not wait; a model's status stays `placeholder` until then |

## 5. Design

### 5.1 Invented profiles

`<assessment_view>` may declare several `<example id label>` blocks instead of one. The
engine validates each as it validates the one today (declared entries only, inside range,
0 or 1 for yes/no, an offered option for a choice) and refuses a repeated id.

Three profiles, values to be written into `health_lamina.xml`. They are invented, sit
inside the usual clinical ranges, and none may be made to resemble the demo subject:

| id | Label on screen | Sketch |
|---|---|---|
| `low` | Low risk · invented example | late thirties, normal pressure, normal lipids, normal glucose, no history |
| `borderline` | Borderline / prediabetes · invented example | early fifties, high-normal pressure, fasting glucose in the impaired range, body mass index near 29, a relative with diabetes |
| `high_cv` | High cardiovascular risk · invented example | early sixties, treated high pressure, high total and low HDL cholesterol, smoker |

On the page the single "Fill with invented example" button becomes a labelled group of
three buttons. The chosen profile's label stays visible beside "14 of 14 entered" until an
entry is edited, so a screenshot always says the values are invented.

Acceptance check on saturation: for each profile, each risk now lies between 1% and 60%
and moves by a visible amount (at least 0.1 points) between the settled values of a plan
of 0 and of 7 days a week.

### 5.2 Risk factors that adapt

A **mediator** is an input of the risk equations that a kept-up plan can move. Each has
the value now (entered, or measured from the recordings) and a projected value at t weeks.

| Mediator | Now comes from | Moves with activity (direction to declare; size is the expert's) |
|---|---|---|
| Fasting glucose | form | down |
| Systolic and diastolic pressure | form | down |
| HDL cholesterol | form | up, slowly |
| Total cholesterol | form | **declared with a shift of zero.** The screen says "not expected to change with activity alone" instead of drawing a flat line with no explanation |
| Body mass | form | decision 3 |
| Resting heart rate | recordings | down |
| VO2max | recordings, if decision 1 allows | up |

Shape, the same for every mediator, chosen so that each number means something a
clinician can check against a trial:

```
added    = dose_planned − dose_current                      (MET-h/week; negative for a lighter plan)
settled  = sign(added) · min(cap, per_10 · |added| / 10)    (the shift the factor tends to)
shift(t) = settled · (1 − 2^(−t / weeks_half))              (t in weeks)
value(t) = clamp(value_now + direction · shift(t), floor, ceiling)
```

Three parameters per mediator, each a declared coefficient in its own segment
"Adaptation (placeholder)" of `health_lamina.xml`:

| Parameter | Reads as | Example of the note beside it |
|---|---|---|
| `<m>_per_10` | shift per 10 MET-h/week added, once settled | "Placeholder. Fasting glucose settles this much lower for every 10 MET-h/week added and kept up. Replace from a meta-analysis of training trials; state the population." |
| `<m>_cap` | the largest shift, however much is added | "Placeholder. No amount of added activity moves it further than this." |
| `<m>_weeks_half` | weeks until half the settled shift is reached | "Placeholder. Pressure responds within weeks; HDL takes months." |

Plus `<m>_floor` (and a ceiling where one applies): a healthy value below which no shift
is applied, so a normal glucose is not projected into hypoglycaemia.

Rules for the XML:

- One function per mediator (`adapt_<m>`), all registered to one Python method, each with
  `status="placeholder"`, a `<source>` saying the numbers are invented, and no reviewer.
- Every coefficient's `<description>` starts with "Placeholder." and says in plain words
  what the number means and what kind of evidence should replace it.
- No adaptation constant is written in Python.
- The dose-response functions of today (`*_rr_current`, `*_rr_planned`, `*_risk_plan` by
  ratio) and their four coefficients are **removed**. `*_risk_plan` becomes the same
  method as `*_risk_now`, read on the projected mediators.

A tool, `backend/tools/list_placeholders.py`, prints every function and coefficient whose
status is not `reviewed` as a table (name, value, unit, the note, the functions that read
it) in Markdown and CSV. It is the sheet handed to the expert, generated from the XML so
it cannot drift from it.

### 5.3 Fitness from the recordings

- `tools/make_activity_templates.py` adds a `fitness` block to `templates.json`:
  the resting marker of section 3 (median, 10th and 90th percentile over days, the number
  of days, and the rule in one sentence). With too few days it is `null`.
- `<assessment_view>` gains a third link role, `measured`, which may be declared more
  than once and names the key it reads (`resting`, later `vo2max`). The evaluator fills
  it from the activity side, as it fills `current` and `planned` today. A missing value
  leaves the attribute absent, and the result that needs it names it under "needs", like
  an entry.
- The risk equations gain a fitness term, with its own coefficients and placeholder
  notes. A result's "what stands behind it" then lists a step marked "from your
  recordings".
- The form shows the measured values read-only under a fourth heading, "From your
  recordings", so the person sees what the twin already knows about them.

Stated on screen and in the XML: fitness is partly how activity lowers the other factors,
so an equation that holds both must be fitted with both. The placeholder is not; the
expert's replacement must be.

### 5.4 Time

- `<assessment_view>` declares the horizons: an attribute for the elapsed weeks and the
  values to evaluate (`4, 8, 12`). The evaluator runs the lamina once per horizon, plus
  once at 0 and once settled, on one fresh twin each, and returns series.
- `POST /api/assessment` answers, additively:
  - `horizons`: `[0, 4, 8, 12]` and the label of the settled column;
  - per result: `series` (`weeks`, `value`), with `now` unchanged and `planned` kept as
    the value at the last horizon so the present page keeps working until phase 5;
  - `mediators`: per mediator its label, unit, where the value now comes from (`entered`,
    `measured`), the value now, the series, the settled value, the model's status, and
    `moves: false` with a sentence for a mediator declared with a shift of zero.
- A mediator whose value now is missing has no series and says what it needs.

### 5.5 The page

Needs a mockup approved by the user before any component is written
(`tools/mockups/forecast_template.html` is the starting point).

- "The week and risk" gains a row of horizon buttons: **Now · 4 weeks · 8 weeks · 12
  weeks · Settled**. The risk cards and the factor list show the selected horizon. "Now"
  is selected after a run, so the first thing read is that nothing has changed yet.
- A panel "What changes, and when": one row per mediator, with the value now, a small
  line from now to settled with marks at 4, 8 and 12 weeks, the value at the selected
  horizon, and the source label (entered · measured from recordings). A mediator that
  does not move says so in words.
- Above the panel, one fixed sentence: "Test results do not change after one session.
  These are the values this plan tends to if it is kept up, and how fast."
- Each risk card shows the risk at every horizon as a short row, so the slope is visible
  without pressing anything.
- Flags may read a projected value only if the flag says which horizon it is about.
- All the rules of `FORECAST_TWIN_PLAN.md` section 6 and `PLANNED_DAY_PLAN.md` section 5
  hold: no attribute, unit or disease named in the frontend; 44 px controls; colour never
  the only signal; nothing entered in the URL or storage.

## 6. Phases

Each phase ends with its own tests and the whole suite green (backend tests, `npm run
lint`, `npm run build`, every `frontend/scripts/*-check.ts`). Coding may be delegated
from a spec per phase and must be gated by tests, a real run and a hand computation.

| Phase | Work | Accept when |
|---|---|---|
| 0 | Decisions of section 4; mockup of 5.5 at 1920×1080 and phone width | the user approves the mockup |
| 1 | Several `<example>` blocks in the engine; the three profiles in the XML; the three buttons on the page | each profile passes the saturation check of 5.1; a repeated id and an out-of-range value are refused at load; the label stays on screen until an entry is edited |
| 2 | Mediators and their adaptation in `health_lamina.xml` and `.py`; the dose-response path removed; `tools/list_placeholders.py` | at t = 0 risk with the plan equals risk now to 1e-9; a plan equal to the habit changes nothing at any t; a hand computation of one mediator at 4, 8 and 12 weeks matches to 1e-9; settled is never passed; a floor is never crossed; total cholesterol does not move; no `*_rr_*` attribute is left; the sheet lists every placeholder |
| 3 | `fitness` in `templates.json`; the `measured` link role; the fitness term in the equations | the block reproduces section 3; with no fitness the result names what it needs; the suite's checks on unchanged `/api/day` and `/api/day/plan` answers still pass |
| 4 | Horizons in the engine, the evaluator and the endpoint (5.4) | the series at each horizon equals a separate run at that horizon; `planned` equals the last horizon; no entered value reaches a log (the test of today, extended) |
| 5 | The page of 5.5, with every state: nothing entered, partly entered, each profile, a mediator that does not move, fitness missing, 0 and 7 days a week, refused entry, server failed | every state driven in a real browser with no console error; the no-assessment page still differs from the reference screenshot by 0 pixels |
| 6, gated | Test the fitness adaptation on the long local record. Rule fixed before the run: from logged sessions, the adaptation must predict the change of the resting marker over the next 4 weeks better than "no change" by 20% on held-out months, for at least two of the three local subjects | the rule passes and the fitness functions move to `draft` with the fitted numbers and the report; or it fails, the result is written here, and they stay `placeholder` |
| 7, optional | The adapted resting level fed back into the day projection: "the same session after 12 weeks" | only after phase 6 passes |

## 7. Limits to keep on screen

1. Every size and pace is a placeholder until an expert replaces it. A placeholder figure
   says nothing about a real person.
2. The shifts are averages of groups. One person may respond more, less, or not at all.
3. No diet, medicine, sleep, illness or ageing. A value that would rise over the years by
   itself is held still.
4. The recordings hold no test result, so nothing about glucose, pressure or lipids can
   be checked against this person. Only the fitness markers can (phase 6).
5. The plan is assumed kept up every week. Stopping is not modelled.

## 8. Not in this plan

Glucose within a day (meals, a walk after eating): it needs continuous glucose
recordings and a model of its own. Diet. Medicines and their doses. Diagnosis. Any
horizon beyond a year. Saved profiles on the server.
