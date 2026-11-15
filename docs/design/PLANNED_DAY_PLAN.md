# Plan a day: set a day up with sliders, run it, and watch the model draw it

Written 2026-11-15, revised the same day (version 2, after the user's direction). Phase 0
(the mockup) is done and approved; nothing of the feature itself is built. This is a
handoff plan: whoever builds it needs only this file and the repository. Branch
`feature/wearable-lamina`; it follows `WEARABLE_LAMINA_PLAN.md` and `DAY_VIEW_PLAN.md`.

## 0. The approved mockup

Approved by the user on 2026-11-15. It is the visual reference for phases 5 to 7: layout,
controls, states and copy. Rebuild it with:

```bash
cd backend
python ../tools/mockups/build_plan_mockup.py ../tools/mockups/plan_day_template.html subject_demo ../docs/design/mockups/plan-day-demo.html
node ../tools/mockups/plan-model-check.mjs ../docs/design/mockups/plan-day-demo.html
```

The built page is
gitignored, like every mockup built from a real person's days. Open it in a browser; Run
plays the projection.

- `tools/mockups/build_plan_mockup.py` derives the activity templates of 4.2 from the
  recorded days and embeds them with the fitted coefficients. Its `project()` is the
  reference for 4.7: it fills a planned day the same way and runs it through
  `fit_hr_model.simulate_day`. Phase 2's templates tool and phase 4's `planned_day.py`
  should reproduce its numbers.
- `tools/mockups/plan_day_template.html` holds the page. Its `<script id="model">` runs the
  model in the browser so the mockup works without a server. **The product must not do
  this**: section 5 keeps formulas on the server. Copy the layout, not the model.
- `tools/mockups/plan-model-check.mjs` checks that the page's model matches Python on
  three reference plans. At approval the largest difference was 5e-5 bpm.

What the approved mockup settled beyond section 4:

- Each column is 440 px wide with its sliders in two sub-columns, and one column under
  760 px. That way, at 1920x1080, Setup, Run, the figures and the heart-rate chart are
  visible without scrolling.
- The Kind buttons have no label row. The steps slider in a session is labelled "Steps"
  with the note "no effect on heart rate".
- A note sits directly under its own slider ("recorded 75–79", "p10 · p90").
- On the Level slider, an end label that would collide with "typical" is left out.
- When a session band is too narrow for its name, the timeline writes the name beside it.
- The readout never shows a minute outside the waking hours. At the end of a run it stops
  on the last projected minute.
- At the approved defaults the mockup shows the following, and phase 4's endpoint should
  reproduce them:
  - Walk 07:30 (30 min, 3.13 kcal/min) settles at 107 bpm.
  - Strength 18:00 (45 min, 4.29 kcal/min) settles at 109 bpm.
  - The day totals 829 kcal and 14,635 steps.

## 1. Decisions already made (by the user, 2026-11-15)

| Question | Decision |
|---|---|
| Build it? | Yes. |
| What the page opens on | **Plan a day.** It is the first thing a visitor sees. |
| Recorded days | Kept exactly as they are, one click away, so a specialist can look up past days and their figures. |
| The person's name | "s2" is no longer shown anywhere. The person is called **Subject demo**. |
| How a plan is entered | Columns of sliders: kind of training, level, target heart rate, steps and the like. |
| When the model runs | Only after the setup is done and the reader presses Run. Then the chart plays the day through. |

## 2. What was measured, and the limits to keep on screen

First measured 2026-11-15 with a scratch script. Since phase 2 the same measurement is
`backend/tools/backtest_planned_day.py`, and the table shows its figures. The templates of
section 4.2 come from the 90 days before the fitter's split date (2025-04-05) that have any
wear. The 35 days from that date that have heart rate are projected from their schedule
alone: session kind, start and length, the minutes the watch was worn, and outdoor
temperature. Each projection is compared with the recording. The coefficients are the
shipped `params.json`, not refitted.

The scratch script used only the 86 earlier days that had heart rate. That moved the two
baselines slightly (energy 118, steps 2,791) and changed nothing else.

| Quantity | Projection from the schedule | For comparison |
|---|---|---|
| Active energy per day | MAE 51 kcal (median day 340), 12%, r 0.91 | always the median day: MAE 117 |
| Heart rate per minute (4,093 measured minutes) | MAE 10.8 bpm | model fed the recorded energy: 9.8; constant level: 14.7 |
| Session mean heart rate | off by 8 (walk), 12 (strength), 10 (cardio) bpm | model fed the recorded energy: 5, 9, 2 |
| Session mean heart rate, intensity also stated | off by 6, 8, 6 bpm | |
| Session peak heart rate | 20 (walk) to 34 (cardio) bpm too low | a flat session has no peaks |
| Steps per day | MAE 2,500 (median day 9,115), r 0.51 | always the median day: MAE 2,804 |

Only 24 test sessions stand behind the session rows. Wear time was given to the projection,
which flatters the energy total. Apple derives active energy partly from heart rate, so the
chain is partly circular.

Limits the screen must state, not hide:

1. It is one person's model. Another athlete needs their own recordings and fit.
2. Peaks are missed: a session is one flat rate.
3. Steps outside sessions are not projected; the reader sets them.
4. No fatigue, recovery, sleep or effect of training from day to day. No night: the watch
   was off at night.

The project's principle is that the twin does not predict. A planned day is the Scenario
feed stretched over a schedule: "what this person's model shows for this plan". Every screen
and endpoint calls it a projection from a plan, never a forecast.

## 3. Rename: "s2" becomes "Subject demo"

Done 2026-11-15. A shared `bundles.read_subject_label(directory, subject)` reads a
folder's `subject.json`. `/api/sources` and `/api/day`, the fitter's `applies_to`
and report, the preset descriptions and the mockup all use it. Regenerating the presets
changed only the subject and the name, not a number. What `git grep -w s2` still finds:
this section, the two earlier plans, and made-up ids in test fixtures.

The id `demo` is already the synthetic sample day and about ten test files rely on it, so
the real person takes a new id and both get a display name.

- Move `backend/bundles/s2/` to `backend/bundles/subject_demo/` with `git mv`. In each day
  file and in `params.json` set `"subject": "subject_demo"`; `applies_to` becomes
  "Subject demo only: fitted on this person's recordings; not a population value".
- Add an optional `subject.json` beside a subject's days: `{"label": "Subject demo"}`.
  The synthetic folder gets `{"label": "Synthetic sample"}`. `/api/sources` and `/api/day`
  return the label; the frontend shows the label and never the id. A folder with no
  `subject.json` shows its id.
- Replace "s2" in: `.gitignore` (the allow-list for the folder), `README.md`,
  `presets/wearable/*.xml` (`<subject>` and descriptions; regenerate with
  `tools/make_presets.py` rather than editing by hand), `backend/wearable_lamina.xml`
  descriptions, comments in `day_summary.py`, `fit_hr_model.py`, `make_presets.py`, and
  the tests that use "s2" as a made-up id only where they would show on screen.
- Subject order in every picker: `subject_demo` first, the synthetic sample last.
- Not changed: the two earlier plan documents (they are history), and git history itself.
  The old name stays readable in past commits. This rename is presentation, not
  anonymisation; say so in the commit message.
- A local export still named `s2` under `CARDIOTWIN_BUNDLE_DIR` would appear as a second
  subject. The README section on local bundles says to name the folder `subject_demo`.

Accept when: `git grep -w s2` finds it only in the two earlier plan documents and in test
fixtures that never reach a screen; the backend suite and the frontend check scripts pass.

## 4. Design

### 4.1 Page structure

Two views, switched by two tabs at the top left (44 px high, the current one marked by more
than colour):

- **Plan a day** (default; `?view=plan`, also when the URL has no parameters).
- **Recorded days** (`?view=recorded&subject=&date=`): today's `App` and `DayView`,
  untouched, including Play, the session list and the day picker. An old link with only
  `?subject=&date=` opens here.

The plan lives in the URL (`?view=plan&plan=<compact encoding>`) so a link reopens the same
setup. Encode sessions as short positional values, not JSON; an unreadable value opens the
default plan with a notice.

### 4.2 Activity templates (`backend/tools/make_activity_templates.py`)

Reads a subject's bundles and writes `bundles/<subject>/templates.json`:

- per workout label, and per group as fallback: mean energy rate and step rate; the 10th,
  50th and 90th percentile of session means; the number of sessions and minutes behind it;
- per clock hour outside sessions: mean energy rate and step rate; the 10th, 50th and 90th
  percentile of steps per day outside sessions;
- the subject's median daily level, usual waking hours (first and last worn minute,
  median), and `applies_to`.

Groups come from the lamina's `<replay_field>` sets, so the Python names no workout type.
A kind with fewer than 5 sessions is not offered. The synthetic sample has no templates and
is not offered for planning.

As built (phase 2):

- A minute is worn when it has an active-energy record.
- A session is a run of minutes with the same workout label. It counts towards `sessions`
  and the level percentiles when it lasts 5 minutes or more and has at least 3 worn
  minutes.
- The hour of a minute is its local clock hour, so the 23- and 25-hour days of daylight
  saving fall in the right hours.
- `session_rate` takes the energy and steps for a session minute from the first of these
  that has enough data:
  - its workout label, with 30 minutes or more;
  - its group, with 10 minutes or more;
  - all sessions.
- `hour_rate` gives the same for a minute outside sessions, from its hour. An hour with
  fewer than 30 minutes uses the mean of all of them.
- Steps outside sessions add up every minute outside a session, worn or not, because the
  phone also records steps.

For the kinds' level ranges, the waking hours, the resting level and the steps range, the
tool gives the same numbers as the approved mockup.

### 4.3 Roles in the lamina XML (engine, domain-neutral)

A new optional block, parsed and validated like `<day_view>` and returned by `/api/schema`:

```xml
<plan_view>
  <intensity attribute="AE_rate" label="Level"/>      <!-- the input a session sets -->
  <settles attribute="HR_target" label="Target heart rate"/>  <!-- where the output settles -->
  <count attribute="step_rate" label="Steps"/>        <!-- an input added up, per minute -->
  <ambient attribute="T_app" label="Outdoor temperature"/>
  <level attribute="HR_level" label="Resting level"/>
</plan_view>
```

Validation at load: every id exists; `intensity`, `count`, `ambient` and `level` are
SENSOR; `settles` is PRELIMINARY and depends on `intensity`. A lamina without the block has
no plan view. Unknown ids and wrong sources raise `ValueError` naming the lamina and the
element. The three other laminae are unchanged.

### 4.4 Options endpoint

`GET /api/plan/options?lamina=<id>&subject=<s>` returns everything the editor draws:

- `subject` label, `applies_to`, whether coefficients are fitted;
- `kinds`: for each offered kind its label, colour group, intensity range (10th, 50th,
  90th percentile), default steps per minute, sessions behind it, and a **settle table**:
  21 points from the 10th to the 90th percentile of intensity, each with the value the
  `settles` attribute takes there. The backend computes the table by running the lamina
  itself at each point (level at the subject's median, hour 12, the default temperature),
  so the frontend holds no formula;
- `day`: default waking hours, temperature range and default, resting level range and
  default, range and default of steps outside sessions;
- `projection_error` from the backtest of 4.8, and the limits of section 2 as short
  strings;
- limits: at most 6 sessions, 5 to 180 minutes each.

Unknown subject: 404 with the list. A subject with no templates: 404 saying so. A lamina
with no `<plan_view>`: 400.

As built (phase 3), and where it differs from the text above:

- **A sixth role, `<clock attribute="hour_local"/>`.** The settle value depends on the time
  of day through the circadian term. Without a clock role the backend could not vary the
  hour, and the frontend may not name an attribute.
- **The settle table covers every hour, not hour 12 only.** Each kind gets
  `settle.values[hour][point]`: 24 hours × 21 points. The editor reads the row for the
  session's middle hour. It is the same session-time dependence the approved mockup has,
  and at 0.1 ms per lamina pass the full table costs about 0.15 s.
- **Optional `level` and `ambient` query parameters.** Both shift the settle value, so the
  editor asks again when the Day column changes them. Defaults are the subject's median
  level and median temperature. A value outside the slider range, or one that is not a
  number, gets 422.
- **The peaks limit line names each kind.** For Subject demo it reads "Walk 20, Strength
  4, Cardio 34 bpm", because a single range would hide how differently the kinds miss.
- `kind_groups` moved to `backend/plan_options.py`. The templates tool imports it from
  there.
- **Parity.** The table equals `fit_hr_model.simulate_day` at every hour and point tested,
  to 1e-9. The first call takes 0.18 s and the response is 16 KB; it is then cached on the
  two files' modification times.

### 4.5 The editor: columns of sliders

Above the chart, one **Day** column and one column per session, side by side, scrolling
sideways when they do not fit; on a narrow screen they stack. Every control is a slider or
a row of buttons at least 44 px high, labelled in words with its value and unit beside it,
and usable by touch (the LG board).

Day column:

| Control | Range and default |
|---|---|
| Awake from / until | the day; default the subject's usual hours |
| Outdoor temperature | from the options; default the subject's median |
| Resting level | from the options; default the subject's median |
| Steps outside sessions | 10th to 90th percentile; default the median |

Session column (added with "+ Session", removed with a button; at most 6):

| Control | Behaviour |
|---|---|
| Kind | buttons, one per offered kind, each with its text label |
| Start | slider in 5-minute steps inside the waking hours |
| Length | slider, 5 to 180 minutes |
| Level | slider from light (10th percentile) to hard (90th), "typical" marked |
| Target heart rate | slider in bpm, **linked to Level** through the kind's settle table: moving either moves the other. It stops at the table's ends, and the label says "settles near" because it is the model's steady value, not a promise |
| Steps in session | slider; default is the kind's steps per minute times the length, and it follows Length until the reader moves it |

Rules:

- Two sessions may not overlap, and a session stays inside the waking hours. A slider that
  would break this stops and a line under it says why; nothing is silently moved.
- Steps do not change heart rate in this model (the lamina's activity path is energy
  only). The Steps control says "counted, does not change heart rate".
- Under the columns: a thin timeline of the day showing the waking hours and each session
  as a labelled band, updating as sliders move. It costs no request.
- A **Run** button, and "Reset to a typical day". The default plan is not empty: the
  subject's usual waking hours and one typical walk, so a first visitor can press Run.

### 4.6 Running

Nothing is computed while sliders move. On Run:

1. `POST /api/day/plan?lamina=<id>` with the plan.
2. The Day view's existing chart, rate strips, figures and session list draw the answer,
   and its existing Play cursor starts at the first waking minute at x600 and runs the day
   through. Pause, speed and the slider work as on a recorded day.
3. The modelled line is drawn alone, with the projection-error band around it. There is no
   measured line, no verdict and no "expected" wording.
4. Each session row shows the target that was set beside the mean and peak the model
   reached, and the session's energy and steps.
5. Figures on top: active energy with its error (± from the backtest), total steps
   (sessions plus outside, marked "as set"), time in sessions, highest modelled heart rate.
6. A banner stays on screen: "Projection from a plan · Subject demo's model · not
   measured", with the four limits of section 2 one tap away.

After a run, moving any slider marks the result "Setup changed · Run again" and dims the
chart; it does not rerun by itself.

### 4.7 Backend for a plan (`backend/planned_day.py`, `POST /api/day/plan`)

Body:

```json
{"subject": "subject_demo", "awake": [390, 1350], "ambient": 18, "level": 77.2,
 "count_outside": 6500,
 "sessions": [{"kind": "Walking", "start": 420, "minutes": 30, "intensity": 3.2, "count": 3300}]}
```

`build_planned_bundle(plan, templates)` returns an ordinary schema-1 day bundle with
`"synthetic": true`, `"planned": true` and every measured value null. Inside a session the
intensity and steps are the plan's; outside, energy is the template's hourly mean and the
plan's outside steps are spread over the waking hours in proportion to the template's
hourly step rate. Outside the waking hours nothing is recorded, as on a real night.

The endpoint runs that bundle through `day_summary` in memory and returns the `/api/day`
shape plus `planned: true`, `projection_error` and, per session, the target that was set.
`day_summary` must accept a day with no measured value when the bundle is planned: no
verdicts, and "no readings" is not an error there. Nothing is written to disk and nothing
is cached across requests beyond the lamina itself.

Guards, each a 422 naming the field: unknown subject or kind, a session outside the waking
hours, overlapping sessions, more than 6 sessions, a length outside 5 to 180, an intensity
outside the kind's range, a non-finite or negative number, waking hours that are reversed.

### 4.8 The backtest as a gate (`backend/tools/backtest_planned_day.py`)

The measurement of section 2 made repeatable. It writes `projection_report` into
`templates.json`; `/api/plan/options` serves it as `projection_error`. Rules fixed before it
runs on any new subject:

- energy per day must beat the median-day baseline by at least 25%, or the figure is shown
  without a number ("not reliable for this person");
- heart rate per minute must be within 2 bpm of the model fed the recorded energy, or the
  line is labelled "rough";
- the report states how many test sessions it rests on.

As built (phase 2), the report also scores a second mode, "stated_intensity". It is the
same projection, with each session's energy set to its recorded mean, as if the plan had
said how hard each session was. On Subject demo the result is energy reliable (51 against
117 kcal) and heart rate not rough (10.8 against 9.8 bpm), from 24 test sessions.

## 5. Rules that stay in force

- The frontend names no attribute, unit, kind of workout or threshold. All of it comes
  from `/api/schema`, `/api/plan/options` and the plan's answer.
- A projection is labelled as a projection, the synthetic sample as synthetic, and fitted
  coefficients as this person's only.
- UI copy in English, 24-hour en-GB times, controls at least 44 px, text at least 13 px,
  contrast at least 4.5:1, colour never the only signal. The Scientific Indie tokens in
  `tailwind.config.js` are extended, not replaced.
- Coefficients and templates live in XML and JSON, not in Python or TypeScript.
- No other person's data is committed without the user's say-so.
- Screenshots: drive headless Chrome over CDP with a real wall-clock wait; the Browser
  pane cannot composite this app.
- Local ports: 8000 belongs to another program; use the `backend-8010` and `frontend-8010`
  launch configurations.

## 6. Phases

Each phase ends with its own tests and the whole suite green: the backend tests,
`npm run lint`, `npm run build`, and every `frontend/scripts/*-check.ts`.

| Phase | Work | Accept when |
|---|---|---|
| 0 | A static mockup of the plan page (columns, timeline, Run, the chart after a run) at 1920x1080 and at phone width; the user approves it | done 2026-11-15 (section 0) |
| 1 | Rename of section 3 | done 2026-11-15 (section 3) |
| 2 | Templates tool and backtest tool, with tests on generated days | done 2026-11-15: `tools/make_activity_templates.py`, `tools/backtest_planned_day.py`; `bundles/subject_demo/templates.json` holds both, tracked |
| 3 | `<plan_view>` roles and `GET /api/plan/options` | done 2026-11-15 (as built under 4.4) |
| 4 | `planned_day.py`, `POST /api/day/plan`, `day_summary` for a planned day | a plan copied from a recorded day's sessions reproduces that day's session energy; every guard has a test |
| 5 | The two tabs, the plan route and its URL encoding; Recorded days unchanged | screenshots of a recorded day before and after are the same; an old link still opens its day |
| 6 | The editor of 4.5 with its pure logic in `frontend/src/twin/planDay.ts` and a `plan-check.ts` script (linking Level and Target, overlap rules, the URL encoding) | the linked sliders agree with the settle table both ways; an overlap cannot be made |
| 7 | Run and playback of 4.6, and the states: loading, refused plan (the field named), server failed with a retry, setup changed, no templates for the subject | every state has a screenshot; usable by touch at the LG board's size |
| 8, optional | On a recorded day, "Project from its schedule": the projection beside what was measured | both lines drawn together |
| 9, optional | Session shapes (warm-up, intervals) to recover peaks | peak bias halves on the test sessions, or it is not shipped |

## 7. Not in this plan

Multi-day effects (fatigue, recovery, training load), sleep, any person without their own
recordings, heat during exercise, clinical claims, saving plans on the server.
