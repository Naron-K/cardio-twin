# Test Dataset — Feedback Loop Scenarios

Ten patient profiles for exercising the CardioTwin feedback loop. Each scenario picks one or more clinically realistic deviations so that the feedback machinery has something to correct.

## How to use

1. Start the backend (`uvicorn main:app --port 8000`) and the frontend (`npm run dev`).
2. In the UI, drag any `XX_*.xml` file into the **"Drop XML or click to browse"** zone.
3. The sliders snap to the patient's vitals; the dashboard shows the X′-only baseline.
4. Press **Run 50** (or higher) on the Feedback Loop panel.
5. Watch the **‖X″‖** chart — it should decrease as the body settles. The badge under "Last run" will read **Settled**, **Max cycles**, or **Diverged**.
6. If the run settles, the green **Save settled state** button exports an XML snapshot.

`patient_profiles.csv` holds the same ten profiles in tabular form for batch tools.

## Behavioural targets (from `backend/circulatory_lamina.xml`)

| Target | Value | Tolerance | Range |
|---|---|---|---|
| MAP   | 85   | ±15  | 70 – 100 mmHg |
| CO    | 5.0  | ±1.5 | 3.5 – 6.5 L/min |
| Q     | 5.5  | ±1.5 | 4.0 – 7.0 L/min |
| SV    | 70   | ±15  | 55 – 85 mL |
| λ     | 2.0  | ±0.5 | 1.5 – 2.5 mm |

Anything outside its tolerance band emits a feedback tag in every cycle.

## Profiles

| # | File | Story | Expected violations | Predicted loop behaviour |
|---|---|---|---|---|
| 01 | `01_healthy_resting.xml` | 30-y/o male at rest | None | Settles in ~5 cycles near zero |
| 02 | `02_athletic_resting.xml` | Endurance athlete, low HR, large LV | SV high-borderline, CO low-borderline | Mild correction, settles quickly |
| 03 | `03_hypertension_stage1.xml` | Mild essential HTN | MAP high (~110) | Single-tag pull-down, settles in tens of cycles |
| 04 | `04_hypertension_stage2.xml` | Severe HTN + vasoconstriction | MAP very high (~133), Q low | Tests kernel saturation; may approach circuit breaker |
| 05 | `05_tachycardia_anxiety.xml` | Sympathetic surge | CO high (~7.9) | Pump-side correction |
| 06 | `06_bradycardia.xml` | Sinus node dysfunction | CO low (~3.2) | Mirror of #05 — opposite-direction correction |
| 07 | `07_heart_failure_reduced_ef.xml` | Chronic systolic dysfunction | SV very low (~41), CO low-borderline | Multi-tag interaction on pump composite |
| 08 | `08_hypovolemic_shock.xml` | ~1500 mL blood loss + baroreflex | SV very low (~36), MAP at lower edge | Two pathways correcting at once |
| 09 | `09_septic_shock.xml` | Warm phase, vasodilation | MAP very low (~62), Q very high | Opposing-direction tags exercise per-tag isolation |
| 10 | `10_cardiogenic_shock.xml` | Post-MI pump failure + reflex constriction | SV low (~39), Q low | Multi-target failure scenario |

## Suggested experiment

For each profile, record:
- final cycle count and `stopped_reason`
- final `‖X″‖`
- which attributes carry the largest X″ at convergence

Profiles 01, 02 should converge to ≈ 0. Profiles 03, 05, 06 should settle to a small non-zero X″. Profiles 04, 09 are the stress tests — they may need a relaxed `settle ≤` (e.g. 5e-3) to reach the **Settled** badge.

## Notes

- All values are within the schema's physiological ranges (see `physio_min`/`physio_max` in `backend/circulatory_lamina.xml`).
- Membrane resistances (`r_m`, `r_i`, `r_e`) are held at typical values across all profiles — none of these scenarios target the conduction composite. To exercise λ feedback, vary these explicitly.
- The model uses a fixed Starling constant (k = 0.55) so `SV = 0.55 × EDV`. If the ejection-fraction override is ever restored, SV expectations change.
