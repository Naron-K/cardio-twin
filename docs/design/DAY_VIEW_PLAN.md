# Day view: one person's day, readable by a specialist

Written 2026-11-13. Phases 0 to 6 built 2026-11-14 (uncommitted at the time of writing).
It follows `WEARABLE_LAMINA_PLAN.md` (phases 0 to 6 done) and the per-type activity gains.

## 1. Why

The current dashboard explains the model: inputs, functions, outcomes. A nutritionist, a
cardiologist or a coach wants something else: what this person's day looked like, and whether
the heart responded to activity as expected. On the current screen that reader meets eleven
small charts of equal weight, variable names (`HR_circ`, `g_activity`), 9 to 10 px labels at
25 to 30% opacity, and no marking of workouts or of the hours the watch was off.

## 2. Decisions already made (by the user, 2026-11-13)

| Question | Decision |
|---|---|
| Layout | **Option C** of the mockup: day KPIs on top, whole-day chart on the left, the selected session enlarged on the right, session list under it. |
| Theme | **Dark** (the existing Scientific Indie tokens). The mockup's light theme is not built. |
| Existing dashboard | Kept. Everything it shows today stays reachable (Inspect, Graph, Table). |
| Mockup as reference | `docs/design/mockups/day-view-demo.html` (synthetic, tracked). Open it with `?opt=C`. |

The mockup is rebuilt with:

```bash
cd backend
python ../tools/mockups/build_day_mockup.py ../tools/mockups/day_view_template.html demo 2025-06-01 ../docs/design/mockups/day-view-demo.html
```

A real subject's mockup (`CARDIOTWIN_BUNDLE_DIR` set, subject `s2`) is written to the same
folder and is gitignored. Never commit one: the repository is public.

## 3. Settled in phase 0 (by the user, 2026-11-14)

Measured first on all 83 s2 sessions of at least 5 minutes with 3 or more paired readings
(fitted coefficients, residual SD 12.6 bpm): the median |session mean measured − session
mean modelled| is 3.4 bpm, the 75th percentile 7.4, the 90th 11.0.

1. **Verdict: three levels**, relative to the model's own usual error (residual SD, from
   params.json; the lamina's declared default when there is none):
   - |difference| < SD/2 → "As expected" (65% of s2's sessions);
   - SD/2 to SD → "Slightly higher / lower than expected" (28%);
   - > SD → "Higher / lower than expected" (7%).
   The difference is session mean measured minus session mean modelled, over minutes that
   have both. Fewer than 3 such minutes → no verdict, "Too few readings to compare".
2. **"Drop 5 min after": removed.** Under a rule of 3 readings on each side it was
   computable for 0 of 83 sessions; with one reading per side 56 of 83, each resting on a
   single sample. The zoomed session chart still shows what heart rate did afterwards.
3. **Outside sessions the modelled line is drawn as 10-minute means**; inside a session and
   30 minutes either side it stays per minute. Measured readings are always drawn as they
   are (dots, joined only across consecutive minutes).
4. **A one-sentence day summary** sits above the KPI row, built from the same verdict rule
   (it names only sessions at the third level, or says every session was as expected or
   only slightly off).

## 4. What the reader must be able to answer in 10 seconds

1. How active was the day (energy, steps, sessions)?
2. When was the watch worn, and where is there no data?
3. What was heart rate when quiet, and its peak?
4. In each session, did heart rate respond as the model expects for this person?
5. Which numbers are measured and which are model estimates?

## 5. Design

### 5.1 Rules that stay in force

- The frontend names no attribute, unit or threshold. The day view needs to know which
  attribute is "measured", which is "modelled" and so on, so **the lamina declares roles**
  (5.2) and the frontend reads roles, never ids.
- A modelled value is labelled as a model estimate, a synthetic day as synthetic, a gap stays
  a gap, and fitted coefficients are labelled as that subject's only.
- UI copy in English, 24-hour en-GB times, every control at least 44 px, text at least
  13 px, contrast at least 4.5:1 (the present 25 to 30% opacity labels fail this).
- No real person's data in the repository, in a test, or on Render without the user's say-so.

### 5.2 Roles in the lamina XML (engine, domain-neutral)

A new optional block in a lamina file, parsed by `universal_twin.py` and returned by
`/api/schema`:

```xml
<day_view>
  <pair measured="HR_measured" modelled="HR_model" label="Heart rate" />
  <rate attribute="AE_rate" label="Active energy" per_minute="true" />
  <rate attribute="step_rate" label="Steps" per_minute="true" />
  <event indicator="is_walk" group="walk" />
  <event indicator="is_strength" group="strength" />
  <event indicator="is_cardio" group="cardio" />
  <worn attribute="AE_rate" />   <!-- no value for 20+ minutes means "not worn" -->
</day_view>
```

Validation at load: every id must exist; `measured`/`modelled` must be PRELIMINARY; a
`rate` and an `indicator` must be SENSOR. A lamina without the block has no day view and the
dashboard does not offer one. Guard: unknown ids, wrong sources and duplicate roles raise
`ValueError` naming the lamina and the element.

The session's display name comes from the recording's own label (`sample.workout`), so the
bundle label must reach the day summary (5.3); the indicators only give the colour group.

### 5.3 A day summary endpoint (backend)

`GET /api/day?lamina=<id>&subject=<s>&date=<YYYY-MM-DD>` replays the whole bundle through
the lamina on the server (about 2 s for 1,440 minutes; measured) and returns one JSON:

- per-minute arrays for the pair (`measured`, `modelled`, null where stale or missing) and
  for each `rate`;
- `gaps`: stretches of 20+ minutes where the `worn` attribute has no value;
- `sessions`: start, end, label, group, minutes, mean and peak measured, mean modelled,
  difference, verdict level (section 3, item 1) and energy; no recovery figure (item 2);
- `kpis`: totals and the figures of the mockup's top row, each with its unit and a note;
- `model`: residual SD, whether coefficients are fitted, and for whom (`applies_to`);
- `synthetic`, `timezone`, `date`, `subject`.

Reuse: `bundles.load_bundle`, `bundles.load_params`, `ReplaySource`, `Session.tick(...,
missing=...)`. `tools/mockups/build_day_mockup.py` already computes all of this for the
wearable lamina with hard-coded ids; move its logic into `backend/day_summary.py`, driven by
the roles of 5.2, and delete the hard-coded ids. Cache the result per (lamina, subject,
date, params file mtime). Unknown subject or date: 404 with the available list, like
`/api/sources`. A lamina with no `<day_view>`: 400 with a reason.

Why an endpoint and not the live replay: a specialist should see the finished day at once,
not wait 2.4 minutes for a replay to draw it. The replay stays for the existing Graph view.

### 5.4 Frontend

- A fourth form beside Animation/Map, Graph and Table: **Day**. Offered only when the schema
  has a `<day_view>` and the feed is a replay (a subject and date are chosen). Hash route
  `#dashboard/<lamina>/day`. For such a lamina in replay mode, Day is the default form.
- The Day form takes the full width of the body (zones 1, 3 and 4 collapse behind Inspect
  while it is shown); the source bar's subject and date pickers move into its header.
- Components (new, under `frontend/src/components/day/`): `DayView`, `DayKpis`,
  `DayChart` (the overlay: measured solid with dots, modelled dashed, ±SD band, session
  bands with labels, hatched or shaded "watch not worn · no data"), `RateStrip` (energy and
  steps per 10 minutes on the same x axis), `SessionDetail` (zoomed chart plus figures and
  the verdict), `SessionList`. Port the SVG drawing from
  `tools/mockups/day_view_template.html`; it is plain SVG, no chart library.
- Colour is never the only signal: sessions carry a text label, the model line is dashed,
  the legend names each. Session groups use the mockup's dark-theme colours as tokens in
  `tailwind.config.js` (extend only).
- Pure logic (binning to 10 minutes, splitting runs at gaps, the verdict text, clock
  labels) goes in `frontend/src/twin/dayView.ts` with `frontend/scripts/dayview-check.ts`,
  in the style of the existing `*-check.ts` scripts.
- States to build, not only the happy path: loading, endpoint failed with a retry, a day
  with no session, a day with no heart rate at all, a session with too few readings
  (figures show a dash and the verdict says so), a synthetic day (labelled), declared-default
  coefficients (labelled "not fitted to this person").

## 6. Phases

Each phase ends with its own tests and the whole existing suite green (808 backend tests,
`npm run lint`, `npm run build`, the four `scripts/*-check.ts`).

| Phase | Work | Accept when |
|---|---|---|
| 0 | Settle section 3 with the user | done 2026-11-14 (section 3) |
| 1 | `<day_view>` roles: parse, validate, expose in `/api/schema`; add the block to `wearable_lamina.xml` | bad ids and sources are refused at load; the three other laminae are unchanged; schema returns the roles |
| 2 | `backend/day_summary.py` + `GET /api/day`, driven by roles | on the demo day the JSON equals what `build_day_mockup.py` computes today (sessions, gaps, KPIs); 404/400 cases covered; no attribute id in the Python |
| 3 | `dayView.ts` + check script; `DayChart`, `RateStrip` | gaps are gaps; a single isolated reading is a dot; clock labels at window edges |
| 4 | `DayView` with KPIs, session detail and list; the Day form and its route | at 1920x1080 it matches the mockup's option C in the dark theme; selecting a session updates the detail without a request |
| 5 | States of 5.4, touch sizes, contrast | every state has a screenshot; no text under 13 px; contrast checked on the muted text tokens |
| 6 | Screens for the other laminae unchanged; README section | screenshots of circulatory before and after are the same |

Screenshots: the Browser pane cannot composite this app. Drive headless Chrome over CDP with
a real wall-clock wait (see the project memory "Screenshotting the app").

## 7. Known facts to carry in

- Heart rate exists on only 3 to 22% of a day's minutes for s2; nights have none (the watch
  is off). The day view must say so rather than look broken.
- With s2's fitted coefficients the model's usual error is about 12.6 bpm; a session's mean
  is matched to about 2 bpm for walking and cardio, strength is overpredicted by about 6,
  cardio peaks fall short by about 12. The verdict wording must not promise more than that.
- Apple derives active energy partly from heart rate, so "expected from activity" is partly
  circular inside workouts. Keep the note "model estimate, not a clinical tool" on screen.
- Render has only the synthetic demo day; real days are served only where
  `CARDIOTWIN_BUNDLE_DIR` is set.
