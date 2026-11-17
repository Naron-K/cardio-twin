# Forecast twin: plan a week, enter test results, read load, flags and disease risk

Written 2026-11-17, version 2 the same day after the user's direction. Nothing here is
built. It follows `PLANNED_DAY_PLAN.md` on branch `feature/wearable-lamina` and keeps its
rules (section 5 there). This is a handoff plan: whoever builds a phase needs this file and
the repository.

## 1. Direction (the user, 2026-11-17)

| Question | Decision |
|---|---|
| Simulate a person who has no recordings? | **No.** Only a person with recordings, through their fitted model. |
| Disease risk | **Yes.** A section where the person enters what the recordings lack (test results and history). The page then shows the chance of disease ahead and how a plan raises or lowers it, where that can be done. |
| Missing data | Asked for, never assumed. |
| Exact algorithms now? | **No.** This is a twin: build the frame first, with placeholder models an expert can replace later without touching the frame. |
| The recommendations of section 5 | **Agreed** (2026-11-17): cardiovascular disease and type 2 diabetes first; one equation per disease, chosen with an expert later; the plan changes risk through a dose-response curve; a "research demonstration" banner; fields start empty with an "invented example" button. The expert reviewer is still to be named. |

### 1.1 Skeleton first

The frame is built end to end before any model in it is right. What is fixed is the shape;
what is replaceable is every number and formula inside it.

- **The models are a lamina.** `backend/health_lamina.xml` (`lamina_health`) declares what a
  person enters, what arrives from the activity twin, the coefficients, the functions and the
  flags, like every other lamina. `health_lamina.py` holds the arithmetic.
- **Every function carries a status**: `placeholder`, `draft` or `reviewed`, with its source
  and, once reviewed, who reviewed it. The status travels with each number to the screen. A
  placeholder result is always shown as "Placeholder model · not validated".
- **Replacing a model** is one of three edits, none of them in the frame: change a
  coefficient's value in the XML; rewrite one function's body in `health_lamina.py` and its
  `<formula>` text; or add an attribute the new model needs and list it in the view. The
  form, the "needs" messages, the endpoints and the page follow from the XML.
- **The view block** (`<assessment_view>`, domain-neutral, parsed and validated by the
  engine like `<day_view>` and `<plan_view>`) names the roles: what is entered and in which
  group, what is linked from another lamina, which outputs are results, which are flags,
  and an invented example.
- **The placeholder models have invented coefficients.** They have the shape the real ones
  will have (a weighted sum turned into a probability; a curve of relative risk against
  weekly activity) so that swapping in a published equation changes numbers and terms, not
  structure. They are not published equations and say so in the XML and on screen.

## 2. How the pieces fit

```
recordings ──► fitted model ──► projected day ──► projected week ──► weekly dose
     │                                                                   │
     └──► current habit (the weekly dose this person records now)        │
                                                                         ▼
entered test results ──► published risk equation ──► risk now ──► risk with the plan
                                                     (absolute)   (published dose-response,
                                                                   plan's dose vs current)
```

Three kinds of number appear on the page, and each is labelled as what it is:

| Kind | Example | Where it comes from | Checked here? |
|---|---|---|---|
| **Measured** | this person's current weekly activity | their recordings | yes |
| **Projected by this person's model** | heart rate, energy and load of a planned session | the fitted lamina | yes, by backtest (`PLANNED_DAY_PLAN.md` section 2) |
| **Published population figure applied to this person** | 10-year risk of cardiovascular disease; change in risk for a change in weekly activity | a named equation or meta-analysis | **no, and it cannot be**: the recordings hold no disease outcomes |

The third kind is what makes the request possible, and it is also its limit. The twin does
not learn who gets ill. It supplies what a risk calculator lacks: this person's real current
activity, and what a specific plan adds to it. The risk itself is the published equation's.

## 3. What was measured (exploratory, 2026-11-17)

**The records give the current habit without any entered value.** As built (step S1):

- Per minute, metabolic equivalent = 1 + active energy rate / resting energy rate. The
  resting rate is a coefficient of the person (`BE_ref`, declared default 1.1 kcal/min;
  Subject demo's unworn minutes read 1.098).
- A minute counts towards the dose when it is at or above the floor (`MET_floor`, 3), and
  then adds its metabolic equivalent. The dose of a week is in MET-hours.
- `templates.json` holds the result as `habit`. An independent recomputation gives the same
  figures.

Over Subject demo's 13 full weeks of 2025 with at least 5 worn days:

| Per week, MET-hours | Median | 10th – 90th percentile |
|---|---|---|
| All counted minutes | 21.1 | 6.6 – 27.1 |
| of which inside logged sessions | 12.5 | 0.8 – 18.9 |
| Outside sessions, per day, MET-minutes | 56.8 | 6.5 – 108.7 |

What this says:

- Weeks differ by a factor of four. "Current habit" must be shown as a range, and the plan
  compared with it.
- About 40% of the dose is outside logged sessions. A planned week therefore adds the
  person's own everyday median to the sessions, so plan and habit are on the same basis.
- Watch energy is an estimate, partly derived from heart rate. Nights are not worn.

**A first definition was wrong, and measuring showed it.** The first draft divided by the
minute's recorded basal energy. That record is about 1.10 kcal/min while the watch is off,
about 1.54 while it is worn, and on 9 days holds a fraction of a minute close to zero
(0.0237 on 2025-04-27), which reads as 22 MET for a person sitting still. With that divisor
the median week came out at 9.6 MET-hours. The figures of the first exploratory run (151
moderate-equivalent minutes) used the same divisor and are withdrawn.

An earlier run the same day showed a profile-only model (no recordings) reaches 11.6 bpm
per minute against the fitted 9.8. That route is dropped by the decision above; the result
is kept here only so it is not measured twice.

## 4. What can and cannot be shown

| Wanted | Can be shown | How it is worded |
|---|---|---|
| Is this session a strain | minutes in each intensity class, highest share of reserve and for how long, load | projected by this person's model, with its error |
| Is it risky to do | flags from published screening guidance, from entered answers and the projection | "guidance recommends …", with the source; never "safe" |
| Will it improve health | weekly dose against the guideline range and against the current habit | measured and projected |
| Chance of disease ahead | absolute risk from a published equation, on the entered figures | "the … equation gives N% over 10 years for the figures you entered" |
| Rise or fall with the plan | relative change from a published dose-response curve, applied to that risk, with the curve's interval | "in studies, people at this level of activity had X% (interval) lower risk than at your current level; individual response varies" |
| Will my blood pressure, glucose or cholesterol move | **not shown as a projection.** The person may change an entered value themselves ("if my systolic pressure were 10 lower") and the equation is rerun | "what the equation gives for a different figure", no claim that the plan produces it |
| A fitness trend (VO2max, resting heart rate) over weeks | only if a backtest on the recordings passes (phase 6) | projected, with its error, or "the model cannot tell" |

Not possible, and not to be implied: that the page knows this individual's risk better than
the equation does, a diagnosis, or advice about medicines.

## 5. Decisions the user must make before phase 0

| # | Question | Recommended |
|---|---|---|
| 1 | Which diseases in the first release | Cardiovascular disease and type 2 diabetes: both have published equations and published activity dose-response. Others later |
| 2 | Which equations. Candidates: for cardiovascular disease, Framingham 2008, SCORE2, the Pooled Cohort Equations, PREVENT, or the Australian calculator (the demo subject lives in Australia); for diabetes, AUSDRISK or FINDRISC, both of which already ask about weekly activity | Chosen with the reviewer of 4; one equation per disease, coefficients copied from the publication and tested against its worked examples |
| 3 | How the plan changes the risk: (a) a published dose-response curve applied to the baseline risk, or (b) published average effects of exercise on blood pressure, lipids and glucose fed back into the equation | (a): one curve, one interval, fewer stacked assumptions. Never both, which would count the benefit twice |
| 4 | Who reviews the equations, curves, flag thresholds and wording before they ship (the professor, a clinician) | Someone named. Nothing of phases 3 or 5 merges without it |
| 5 | The site is public with no login, and a page that computes disease risk for a person may fall under medical-software rules | Banner "research demonstration, not medical advice"; confirm with the professor whether the public deployment may carry phases 3 and 5 |
| 6 | Demo values for the section: the demo subject's real test results are not known | Fields start empty. A button "Fill with example values" loads invented figures, labelled as invented on screen and in any screenshot |

## 6. Design

### 6.1 The person

Only a subject with recordings, a fitted `params.json` and templates can be planned for,
as today. Nothing about that changes.

### 6.2 The health section ("Your health")

A panel beside Setup. It lists what the chosen equations and flags need, grouped, each with
its unit, its allowed range and why it is asked. A value the recordings already hold is
shown as "from your recordings" and not asked again.

| Group | Fields (the final list follows the chosen equations) |
|---|---|
| About you | age, sex, height, body mass, waist |
| Test results | systolic and diastolic blood pressure, total and HDL cholesterol, fasting glucose or HbA1c, with the date of each |
| History | smoking, diabetes, treatment for blood pressure, family history, a heart-rate-lowering medicine |
| Screening answers | the questions of a published pre-participation screen |
| From the recordings, read-only | resting heart rate, maximum recorded heart rate, current weekly activity (section 3) |

Rules:

- **Missing data is asked for, not filled in.** Each result names the fields it still
  needs ("10-year risk: needs HDL cholesterol"). An equation is never run on a default.
- An equation is refused outside the ages and ranges it was derived for, saying so.
- A test result older than a year is used, with its age stated.
- Entered values are sent in the request body and held in the page's memory. They are
  **never put in the URL**, never written to disk and never logged on the server. Keeping
  them in the browser is opt-in ("Remember on this device"). The plan link keeps encoding
  the schedule only.
- Ranges are checked on the server and refused by field, as plans are today.

### 6.3 A week, not only a day

Disease risk responds to habit, so the unit becomes a week:

- "Repeat this day N times a week" (default), with the other days taken as this person's
  typical day without sessions. Later, a different plan per weekday.
- The backend runs each distinct day through `planned_day` and adds them up. No effect of
  one day on the next is modelled.

### 6.4 Reading a day and a week: intensity, load, dose

New per-minute quantities in the lamina, each a function of values it already has:

- metabolic equivalent, and absolute class (moderate, vigorous) with boundaries declared
  in the XML and cited;
- share of heart-rate reserve in use, from this person's recorded resting and maximum
  heart rate, and relative class;
- training load per minute (Banister's impulse) and its running total.

The answer for a day adds minutes in each class per session and for the day, the load,
and the highest share of reserve with its duration. The answer for a week adds
moderate-equivalent minutes and MET-hours, drawn against the WHO range and against the
range of **current habit** from the recordings (`tools/make_activity_templates.py` gains
that summary, so it lives in `templates.json`).

Peaks are still missed (a session is one flat rate), so time near maximal is a lower bound
and says so. If a heart-rate-lowering medicine is entered, relative classes are not shown.

### 6.5 Screening flags

A rules file (XML) of flags, each with its condition, plain-English text, source, and the
fields it needs. Evaluated on the server.

- From answers: "guidance recommends medical clearance before moderate / vigorous
  exercise".
- From entered results: resting blood pressure or heart rate outside the ranges guidance
  names for starting exercise.
- From the projection: time above a share of reserve the answers make inadvisable;
  vigorous work in heat; a weekly load far above the current habit.

A flag states what was entered, what the guidance says and where it comes from. With no
flag the screen reads "no flag from what you entered", never "no risk". The builder does
not choose thresholds: phase 3 starts from a table of thresholds and sources signed by the
reviewer of decision 4.

### 6.6 Disease risk

Kept apart from the lamina: `backend/risk/` holds one data file per equation (coefficients,
valid ranges, source, worked examples) and one per dose-response curve (points, interval,
reference dose, source), plus a small evaluator. No coefficient is typed from memory; each
file is checked against the publication's own worked examples in a test.

For each chosen disease the page shows:

1. **Risk now**: the equation on the entered figures.
2. **Activity now**: from the recordings (section 3), as a range.
3. **With this plan**: the plan's weekly dose, the relative risk at that dose against the
   current one from the curve, and the absolute risk it implies, with the curve's interval
   carried through. If the plan is below the current habit, the same arithmetic shows a
   rise.
4. **What stands behind it**: the equation, the cohort it came from, the curve, and three
   fixed sentences: this is a population figure; individual response varies; it assumes
   the weekly dose is kept up for the period the studies covered.

Known weaknesses to state on screen, not hide:

- Risk equations were not fitted with measured activity, so multiplying their result by an
  activity ratio is an approximation used in health-economic models, not an equation of its
  own.
- Watch energy overstates or understates true energy by an amount this project has not
  measured; the dose inherits that.
- The current habit comes from 13 weeks.

### 6.7 Fitness trend over weeks (gated)

A projected trend of resting heart rate or VO2max under the plan ships only if a backtest
passes. The local records hold years of both for three people. Rule, fixed before the run:
from a person's logged sessions, the load model must predict the change in the marker over
the next 4 weeks better than "no change" by 20% on held-out months, for at least two of
the three people. If it fails, no trend is shown and the page says the model cannot tell.

## 7. Phases

Each phase ends with its own tests and the whole suite green (backend tests, `npm run
lint`, `npm run build`, every `frontend/scripts/*-check.ts`). Coding is delegated with
`/opencode` from a spec per phase and gated here by tests, a real run and measurement.

| Phase | Work | Accept when |
|---|---|---|
| 0 | Decisions of section 5. Mockup of the health section, the week control, the load and dose panel, the flags and the risk panel, at 1920×1080 and phone width, following the user's DESIGN.md | the user approves the mockup |
| 1 | Intensity, load and MET in the lamina; the day answer carries them; current habit in `templates.json` | a hand-computed day matches to 1e-6; current habit reproduces section 3 |
| 2 | The week: `POST /api/week/plan`, dose against guideline and habit | a week of the default day equals N × the day's figures plus the typical days |
| 3 | Health section schema and guards; flags file and evaluator | every flag has a test for firing and for not firing; a missing field is named, never defaulted; thresholds table signed |
| 4 | Frontend for phases 1 to 3, all states (nothing entered, partly entered, refused field, out of an equation's range, medicine answered yes, server failed), touch targets | every state driven in headless Chrome; entered values absent from the URL, from storage unless opted in, and from server logs |
| 5 | `backend/risk/`: equations, curves, evaluator, the risk panel | each equation reproduces its publication's worked examples; the interval is carried through; the reviewer of decision 4 has signed the wording |
| 6, gated | Fitness trend of 6.7 | the rule passes, or the phase ends with the negative result written here |
| 7, optional | A different plan per weekday; export of the page as a one-page report | — |

Order after the direction of section 1.1: the skeleton cuts across phases 1, 2, 3 and 5 at
placeholder quality, backend first (S1 and S2 below), then the mockup of phase 0 on real
endpoint output, then phase 4. Expert review then upgrades a model's status from
`placeholder` to `reviewed`; it no longer blocks building.

| Skeleton step | Work | Accept when |
|---|---|---|
| S1 | Activity dose in the wearable lamina (metabolic equivalent and a dose rate, with a `<dose>` role); the day answer carries the day's dose; `templates.json` gains the basal rate and the current weekly habit; a planned day carries the basal rate | every figure a plan returned before is unchanged; the habit reproduces section 3 in its own unit |
| S2 | `health_lamina.xml` and `.py` with placeholder models; function status in the engine; `<assessment_view>`; `GET /api/assessment/options`, `POST /api/assessment` | a missing entry is named, never defaulted; every result carries its status; entered values reach no log |

### 7.1 As built: the backend skeleton (S1 and S2, 2026-11-17)

S1, the dose:
- `wearable_lamina.xml` gains `BE_ref`, `MET_floor`, `MET`, `dose_rate` and the optional
  `<dose>` role of `<plan_view>`. `day_summary.summarise_bundle` adds one key, `dose`
  (total, inside sessions, outside sessions, minutes counted, in MET-minutes).
- `templates.json` gains `habit` (section 3). A planned day is built exactly as before.
- Compared with a capture taken before the work, the answers of `/api/plan/options`,
  `/api/day/plan` and `/api/day` differ only by the added keys. The default plan's dose is
  335.76 MET-minutes, equal to the hand sum of its two sessions.

S2, the frame:
- Engine, domain-neutral: a `<function>` may declare `status` (`placeholder`, `draft`,
  `reviewed`), `<source>` and `<reviewed_by>`; "reviewed" without a reviewer is refused.
  `<assessment_view>` is parsed and validated at load (`<group>`/`<entry>`, `<link>`,
  `<range>`, `<result>`, `<flag>`, `<example>`). An entry may not declare a baseline, so
  an entry that was not given is absent. A flag has a `topic` (shown when it is clear) and
  a `label` (the headline when raised).
- `health_lamina.xml` and `health_lamina.py`: 14 entries, 2 links, 25 coefficients, 14
  functions, 2 results, 3 flags. Every coefficient is invented and says so.
- `assessment.py` is generic: it reads the view, walks the dependency chain of each
  result to find the models behind it, their weakest status, and the entries and links it
  still needs. It names no attribute.
- `planned_week.py`: planned weekly dose = days a week × the plan's session dose + 7 × the
  person's own median everyday dose, so it is on the same basis as the habit.
- `GET /api/assessment/options` and `POST /api/assessment` (body: subject, entries, plan
  or null, days_per_week). The answer carries the dose, the planned day and the
  assessment, so the page needs one request per Run.
- Checked by hand: the example's two risks equal a hand computation to 6 decimals; a
  planned week of 3 days equals (3 × 335.76 + 7 × 56.82) / 60 = 23.417; a missing entry is
  named in `needs` and nothing is defaulted; an entry out of range is a 422 naming
  `entries.<id>`; no entered value and no entry id reaches the server log.
- Suite: 1129 passed (945 before).

With Subject demo's recordings, the default day and the invented example, the frame shows:
activity now 21.1 MET-h/week; with the plan 3 days a week 23.4; cardiovascular 7.04% →
6.96%; type 2 diabetes 8.78% → 8.66%; no session at all 8.08% and 10.43%. These are the
placeholder models' figures and mean nothing about a real person.

Open, for the expert who replaces the models:
- The placeholder guideline range (7.5–15) sits below this person's measured habit.
- `BE_ref` is a declared default (1.1). A person's own value should come from their
  recordings into `params.json`; the fitter does not derive it yet.
- The dose counts whole metabolic equivalents of minutes at 3 and above. Published curves
  differ in what they count; the unit must follow the curve that is chosen.

The mockup of phase 0 is `tools/mockups/forecast_template.html`, built from the real
endpoints by `tools/mockups/build_forecast_mockup.py` (run from `backend/`, as its
docstring says). The user approved it on 2026-11-17.

### 7.2 As built: the page (F1 and F2, 2026-11-17 and 18)

- `frontend/src/twin/assessment.ts` holds the types, the two parsers and every pure helper;
  `utils/api.ts` holds `fetchAssessmentOptions`, `runAssessment` and `EntryRefusedError`.
  Entered values travel in the request body only.
- `HealthColumn` is the first column of Setup. `HealthDrawer` is the form (a dialog that
  takes focus, closes on Escape and returns focus to the button that opened it).
  `WeekRisk` draws the weekly activity, the risks and the flags.
- Run goes through `POST /api/assessment` and gives its `day` to the existing parser, so
  the chart and playback are unchanged. The result has two tabs, "The day" and "The week
  and risk". The link gains `days=<n>`; nothing entered is in the URL or in storage.
- Changing an entry, the example, Clear or the days a week marks the result "Setup
  changed", like a slider.
- With no lamina that declares the view, the page is as it was: compared with a screenshot
  taken before this work, 0 of 1920×1080 pixels differ.

Driven in headless Chrome on the real page, with no console error or warning in any of
them: nothing entered; partly entered; example filled; 0, 3 and 7 days a week (7 raises
the jump flag, 0 raises both risks); an out-of-range and a non-numeric value typed in the
form; an entry refused by the server (the form opens on that field with the server's
sentence); the server failing with a retry; the options request failing with a retry; no
assessment lamina; phone width (no sideways scroll).

Found by looking at the pixels and fixed by hand:
- the Day column had lost its phone width and pushed the page sideways on a phone;
- risks were shown to one decimal, so a small change read "7.0 → 7.0"; they now show two;
- the heart-rate chart's text was stretched after visiting the week tab and coming back,
  because its width was measured only once.

Known trade-off: the banner and the result tabs take about 105 px, so at 1920×1080 less of
the chart is above the fold than in the Plan a day layout approved earlier.

Who wrote what: OpenCode wrote F1, the three components and the wiring from the specs in
`FORECAST_FRONTEND_SPECS.md`; the fixes above were made by hand.

Checks: `npm run lint`, `npm run build`, and the five `scripts/*-check.ts`
(assessment-check has 97 checks).

Nothing has been pushed. Pushing this branch redeploys the public Render service with the
health section and its placeholder figures visible.

## 8. Not in this plan

People without recordings; diagnosis; advice to start, stop or change a medicine;
arrhythmia; a projected change in blood pressure, glucose or lipids; sleep, fatigue and
recovery; accounts or saved health data on the server.
