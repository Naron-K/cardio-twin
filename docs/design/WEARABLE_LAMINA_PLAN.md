# Wearable lamina: replaying and simulating Apple Watch data on the dashboard

Written 2026-11-13, revised the same day (version 2). Nothing here is built.
This is a handoff plan for Claude Code.

Two repositories are involved:

- **cardio-twin** (this repo): the universal twin and its dashboard.
- **Apple Health Data** (`C:\Project\Apple Health Data`): the Health Trajectory pipeline.
  v5 and v6 are frozen. Do not edit them. New code goes in a new directory, `twin_export/`.

## 1. Decisions already made

| Question | Decision |
|---|---|
| Consent | All three subjects have agreed to this use. |
| First subject | **s2**, because it has the most dense workouts (66) and the widest range of activity. |
| First demo days | 2025-04-03 (walk, strength, cooldown; HR 44 to 157; 16 h with data), 2025-04-04 (173 min of workouts), 2025-02-09 (the only dense run, 28 min). |
| Measured HR beside modelled HR | Solved with one rule, section 4. No new chart type, no new XML block. |
| Dashboard | Kept. Two additions only, section 6. |
| Lamina id and name | `lamina_wearable`, "Daily Activity". |

## 2. Goal

1. **Replay.** Show one real day on the dashboard under the new lamina: heart rate, how it
   rises and falls around activity, and energy burned.
2. **Explain.** Beside the measured heart rate, show the heart rate a small personal model
   expects from activity, time of day and weather, and the gap between the two.
3. **Simulate.** With no measured data, pick a state (sleep, rest, desk work, walking,
   vigorous exercise), move activity and weather inputs, and watch modelled heart rate and
   energy respond over time.

Out of scope: clinical claims, arrhythmia, blood pressure, any deep-learning model.

## 3. What the data allows (measured 2026-11-13, from `v5/results/`)

| Finding | Number | Consequence |
|---|---|---|
| The ingest loses no HR records | s1 raw export 356,862; v5 clean 356,860 | sparse HR is how the export is, not a bug |
| HR is dense (about every 5 s) only in the last months before an export | s2 dense workouts: 2023-05 to 2025-05, 65 of 66 in 2025 | demo days come from Feb to May 2025 |
| s2 dense workouts of 10 min or more | 29 walking, 26 strength, 4 stair climbing, 3 elliptical, 1 running, 1 HIIT, 1 cycling | enough to fit about 8 numbers, not a neural network |
| Outside workouts HR is sparse | median 147 samples per day for s2 | the rest of the day replays with visible gaps |
| Active energy is dense | median record 51 s for s2 in 2025 | energy per minute is reliable all day |
| s2 workout rows carry no energy | `energy_kcal` is NaN for every s2 workout | take energy from `channel_active_energy` |
| Weather effect at rest (s1) | +0.11 bpm per deg C | a weather slider moves resting HR by 1 to 3 bpm |
| Static model HR ~ energy + temperature + hour (s1) | R2 = 0.25 | the time lag has to be modelled |
| Night coverage | median 0.0 per day | sleep is a proxy, not a measured stage |

Reference: Nazaret et al., npj Digital Medicine 2023 (doi:10.1038/s41746-023-00926-4)
model workout HR with two coupled ODEs and report a median error of 6.1 bpm per workout on
7,465 users. Their neural networks personalise the ODE across thousands of users. With one
subject the ODE is the part to keep.

**Still missing, and how the plan handles each**

- "Alone" has no signal. There is no such state in this plan.
- "Desk work" and "sleep" have no labels. They are proxies (weekday 09:00 to 17:00 with a
  low step rate; night hours with zero steps and HR at or below the personal level) and the
  preset descriptions say so.
- Weather is outdoor ERA5 at the home base while the subject is often indoors.
- Strength training raises HR with little measured energy. Expect the model to underpredict
  there. Report the fit per workout type and do not hide it.
- Maximum HR is not measured. Use the 99.9th percentile of the subject's HR.
- The heat effect during exercise cannot be estimated from this data. Only the resting
  value is fitted.
- No blood pressure or EDV, so the wearable cannot drive the circulatory lamina. Joining
  laminae is the last, optional phase.

## 4. The one rule that keeps measured and modelled HR simple

**Data enters in zone 1 only. Everything in zone 2 is computed by the lamina.**

This is already the rule of the dashboard and of the project (the visualiser never reads the
raw stream). Applied here:

- `HR_obs` is an ordinary SENSOR input. It appears in zone 1 with the other inputs.
- The lamina's first function turns it into a computed attribute, `HR_measured`: the mean of
  the cleaned samples in the grid step, or "not computed" when the step has none. This is
  real processing (cleaning, gridding, gap handling), not a renamed copy.
- `HR_model` and `HR_residual` are computed attributes as well.

Zone 2's existing trend grid then shows three small charts in chain order, with no frontend
work at all:

| chart | what the reader sees |
|---|---|
| `HR_measured` | the day's heart rate, gaps left as gaps |
| `HR_model` | what the model expects, on the same declared range, so the same height means the same bpm |
| `HR_residual` | the gap, with the tolerance band shaded, because the trend grid already shades the band of any attribute that has an outcome |

So there is no overlay chart, no `<comparisons>` block and no new view. The residual chart
with its band *is* the comparison. An overlay can be added later if someone asks for it;
it is not needed to tell the story.

## 5. Design

### 5.1 The day bundle (Apple Health repo, `twin_export/export_bundle.py`)

One JSON file per subject and local day. JSON, because the backend has no parquet dependency.

```
bundles/s2/2025-04-03.json
{
  "schema_version": 1, "subject": "s2", "date": "2025-04-03",
  "timezone": "Australia/Adelaide", "grid_s": 60, "synthetic": false,
  "samples": [   // one row per minute, local midnight to midnight
    {"t": 0, "hr": 51.2, "hr_n": 3, "ae_kcal_min": 0.31, "be_kcal_min": 1.18,
     "steps_min": 0, "t_app_c": 12.4, "rh_pct": 71, "workout": null},
    {"t": 60, "hr": null, "hr_n": 0, ...}    // null where nothing was recorded
  ],
  "day": {"hr_level_rts": 58.9, "coverage_hr_frac": 0.58, "dense_minutes": 60}
}
bundles/s2/params.json     // written by fit_hr_model.py, section 5.4
```

- `hr` is the mean of the cleaned samples in the minute; `hr_n` is how many. No
  interpolation. A gap stays `null`.
- No coordinates and no device or owner names in a bundle.
- If basal energy is not in the v5 intermediates, ingest `BasalEnergyBurned` in
  `twin_export/`. If the subject has none, use a constant from the subject's median and say
  so in `params.json`.
- `twin_export/make_demo_bundle.py` writes `bundles/demo/`: a synthetic day made by running
  the model forward on an invented schedule, marked `"synthetic": true`. Tests use it, so
  they never depend on a real export.

### 5.2 The lamina (`backend/wearable_lamina.xml` + `wearable_lamina.py`)

Follow `docs/laminae.md`: the XML, a `UniversalTwin` subclass, one line in `laminae.py`.
Coefficients are declared attributes, not constants in Python. No `<tags>` block: the lamina
monitors and corrects nothing, the same decision the metabolic lamina made.

Inputs (SENSOR), each with `physio_min`, `physio_max`, `baseline`:

| id | unit | meaning |
|---|---|---|
| `HR_obs` | bpm | mean measured HR in this minute |
| `AE_rate` | kcal/min | active energy rate |
| `BE_rate` | kcal/min | basal energy rate |
| `step_rate` | steps/min | steps |
| `T_app` | deg C | outdoor apparent temperature |
| `hour_local` | h | local clock hour, 0 to 24 |
| `dt_s` | s | data time since the previous tick |
| `HR_level` | bpm | slow personal level for that day (v5 Kalman RTS level) |
| `HR_max`, `k_I`, `p_I`, `A_circ`, `phi_circ`, `k_T`, `T_ref`, `tau_on`, `tau_off` | | coefficients, seeded from `params.json` |

Computed (PRELIMINARY), one function each, in this order:

| step | id | formula | note |
|---|---|---|---|
| 1 | `HR_measured` | `HR_obs`, or not computed when the minute has no sample | section 4 |
| 2 | `EE_total` | `AE_rate + BE_rate` | kcal/min |
| 3 | `VO2_est` | `EE_total / 4.86 * 1000` | mL/min; 4.86 kcal per litre O2 is an approximation (4.69 to 5.05), stated in the description |
| 4 | `HR_circ` | `A_circ * cos(2*pi*(hour_local - phi_circ)/24)` | bpm |
| 5 | `HR_thermal` | `k_T * max(0, T_app - T_ref)` | bpm |
| 6 | `HR_drive` | `k_I * AE_rate ** p_I` | bpm |
| 7 | `HR_target` | `clamp(HR_level + HR_circ + HR_thermal + HR_drive, 35, HR_max)` | where HR would settle if inputs held |
| 8 | `HR_model` | `prev + (1 - exp(-dt_s / tau)) * (HR_target - prev)`; `tau = tau_on` when target > prev, else `tau_off` | stateful |
| 9 | `HR_residual` | `HR_measured - HR_model` | not computed when step 1 is not |
| 10 | `kcal_active_cum` | running sum of `AE_rate * dt_s / 60` | stateful; resets at local midnight and on reset |

Outcome: `target_residual` on `HR_residual`, target 0, tolerance = 2 x the residual SD in
`params.json` (default 10 bpm). No outcome on `HR_model`.

Two things to check in the engine before writing steps 1, 8 and 10:

- **State.** Steps 8 and 10 need the previous value. Keep it in the lamina instance, seed
  step 8 with `HR_target` on the first tick, and clear it on reset. First read how
  `Session.reset()` and `rollback_feedback` rebuild a twin. If instance state can survive a
  reset, hold the state in a solver registered through `register_solver` instead.
- **A missing reading.** When the bundle has `null`, the source omits `HR_obs` for that
  tick. Step 1 must then come out as "not computed" through the existing `staleComputed`
  path, not keep the previous minute's value. If a SENSOR keeps its old value when omitted,
  add an explicit way for a source to unset it.

### 5.3 Sources and the wire (`signal_source.py`, `main.py`)

- `ReplaySource(twin, bundle, params)`, `KIND = "replay"`. `next()` returns the next minute
  mapped onto the SENSOR ids, plus `dt_s`. It stops at the end of the day and says so.
- `ScenarioSource(twin, params, preset)`, `KIND = "scenario"`. Emits a preset's inputs with
  no noise and never emits `HR_obs`. `set_baseline()` works as today, so sliders work.
- `/ws/feedback` gains `source=simulated|replay|scenario`, `subject`, `date`, `speed`,
  `preset`. The default stays `simulated`: existing clients and tests see no change. An
  unknown subject or date closes with 1008 and a reason, like an unknown lamina.
- New control messages: `set_speed`, `set_preset`. In replay mode `set_sensor` on a measured
  input is refused with a notice.
- The snapshot's `source` block gains `data_time` (local ISO), `position_s`, `duration_s`,
  `speed`.
- In replay mode every minute must reach the browser. `STREAM_EMIT_EVERY` thins snapshots;
  for `KIND == "replay"` advance the source only on ticks that are sent. Test: a 1,440-minute
  day arrives as 1,440 snapshots.
- `GET /api/sources?lamina=...` lists modes, subjects, dates and presets. Bundles are read
  from `CARDIOTWIN_BUNDLE_DIR`; when it is unset only `demo` is offered.

### 5.4 Fitting (Apple Health repo, `twin_export/fit_hr_model.py`)

No neural network. `scipy.optimize.least_squares` with `soft_l1` loss.

- Stage A, rest: fit `A_circ`, `phi_circ`, `k_T`, `T_ref` on minutes outside workouts.
  `HR_level` comes from v5 (`kalman_final.parquet`, `level_rts`) and is not refitted.
- Stage B, activity: fit `k_I`, `p_I`, `tau_on`, `tau_off` on the dense workouts plus 30 min
  before and after each, by simulating the trajectory against measured HR.
- Split by time: earliest 70% of dense workouts to fit, latest 30% to test.
- Report test MAE overall and per workout type, with two baselines: (a) HR held at the
  pre-workout median, (b) the model without the lag (`HR_target`).
- Rule, written into the script before the first run: the lagged model counts as fitted only
  if its test MAE beats baseline (b) by at least 1 bpm. If it does not, the lamina ships
  with `tau_on = tau_off = 0` and the `HR_model` description says the lag was not found.
- `params.json` holds the coefficients, residual SD, the number of workouts, every MAE above
  and the result of the rule.

### 5.5 Presets for the scenario mode

Existing patient-preset format, in `presets/wearable/`: `sleep.xml`, `rest_awake.xml`,
`desk_work.xml`, `walk.xml`, `vigorous.xml`. Values are s2's own medians of `AE_rate`,
`step_rate` and `hour_local` inside each proxy state, written by `export_bundle.py`. Each
`<description>` states the proxy rule that produced it.

## 6. Dashboard: two additions, nothing replaced

The four zones stay. A lamina with no artwork already gets the lamina map in the centre, and
section 4 means the trend grid already draws the comparison.

1. **Source bar** above zone 1, built from `/api/sources`: mode (Synthetic, Replay,
   Scenario); for Replay a date picker, play/pause and speed (x60, x600, x3600); for
   Scenario the presets as buttons. Mode, subject and date go in the URL beside `lamina`.
   A mode the backend does not offer is not drawn. No scrubber in this version.
2. **Data time in the trend grid.** When `source.data_time` is present, the x axis is data
   time and the presenter picks the window (30 min, 3 h, whole day) instead of "the last
   half-minute". The tick buffer must then hold a full day (1,440 points); measure memory
   before and after.

Smaller changes: in replay mode the measured inputs in zone 1 are readouts, not sliders;
the feed chip reads "Replay · s2 · 2025-04-03 · x600" or "Scenario · walk"; with no tags the
"over time" panel says the loop is not acting instead of drawing two identical lines.

Open the dashboard on the **Graph** form for this lamina by default.

What the screen then shows, in order of value: measured HR, expected HR and the gap
(section 4); the activity behind each rise (`AE_rate`, `step_rate` in zone 1); energy so far
today (`kcal_active_cum`); what each cause adds to the expected HR (`HR_level`, `HR_circ`,
`HR_thermal`, `HR_drive`, already visible in the function cards under Inspect).

## 7. Phases

One verified function at a time. Each phase ends with its own tests and the whole existing
suite green.

| Phase | Work | Accept when |
|---|---|---|
| 0 | `export_bundle.py`, `make_demo_bundle.py`, bundles for the three s2 days | bundles pass a JSON Schema; gaps are `null`; no owner or device name in any bundle |
| 1 | XML and the stateless steps (1 to 7, 9), `laminae.py` line, `tests/test_wearable.py` | `/api/schema?lamina=lamina_wearable` loads and the dashboard draws it on the synthetic feed with no frontend change |
| 2 | `ReplaySource`, query parameters, `/api/sources`, the `source` block | the demo day replays in a test, 1,440 in and 1,440 out; `test_ws*.py` pass unmodified |
| 3 | Steps 8 and 10, reset, missing reading | a step in `AE_rate` approaches the target with the declared tau within 1%; replay, reset, replay gives identical series; a `null` minute gives a stale `HR_measured` and `HR_residual` |
| 4 | `fit_hr_model.py`, `params.json`, presets | the report table exists for s2 with the result of the 1 bpm rule |
| 5 | Source bar, data-time trend window | `npm run lint` and `npm run build` clean; circulatory and respiratory screens unchanged; `scripts/display-check.ts` passes |
| 6 | `ScenarioSource`, preset buttons, sliders | a preset change moves `HR_target` at once and `HR_model` with the declared lag |
| 7, optional | s1 and s3; `VO2_est` to the metabolic lamina's `VO2_demand` through `organism.xml`; an overlay chart if wanted | separate plan |

## 8. Rules that stay in force

- Data enters in zone 1 only; zone 2 shows computed attributes only.
- The frontend names no attribute, unit or threshold.
- A modelled value is labelled as modelled, a synthetic day as synthetic, a proxy state as a
  proxy, and a gap stays a gap.
- Coefficients live in XML or `params.json`, not in Python.
- v5 and v6 of the pipeline are not modified.
