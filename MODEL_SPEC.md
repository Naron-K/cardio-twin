# CardioTwin — Input Variables, Equations, Outputs


## 1. Input variables (sensors)

Ten externally-supplied values. These are the only quantities fed into the
model; everything else is derived.

| # | Symbol | Name | Unit | Accepted range | Notes |
|---|---|---|---|---|---|
| 1 | `SBP` | Systolic blood pressure | mmHg | 90 – 180 | Peak pressure during ventricular contraction |
| 2 | `DBP` | Diastolic blood pressure | mmHg | 60 – 120 | Minimum pressure during ventricular relaxation |
| 3 | `HR` | Heart rate | bpm | 40 – 200 | Wearable-derived |
| 4 | `EDV` | End-diastolic volume | mL | 50 – 250 | Ventricular volume before contraction |
| 5 | `eta` (η) | Blood viscosity | mPa·s | 3.0 – 4.0 | Dynamic viscosity |
| 6 | `L` | Vessel length | cm | 1 – 100 | ONE representative segment, not the whole systemic tree |
| 7 | `r` | Vessel radius | cm | 0.01 – 1.5 | ONE representative segment. Drives R via `r⁴` — the model is extremely sensitive to it |
| 8 | `r_m` | Membrane resistance | Ω·cm | 1 000 – 10 000 | Cable theory, per unit length |
| 9 | `r_i` | Intracellular axial resistance | Ω/cm | 100 – 500 | Cable theory, per unit length |
| 10 | `r_e` | Extracellular axial resistance | Ω/cm | 100 – 500 | Cable theory, per unit length |

Inputs 8–10 feed only the conduction equation (#6) and are **not** coupled to
the haemodynamic chain in the current version.

---

## 2. Equations

Solved in dependency order, once per control cycle (~10 cycles/second).

### (1) Mean arterial pressure

```
MAP = (1/3)·SBP + (2/3)·DBP
```

- **In:** `SBP`, `DBP` (mmHg) → **Out:** `MAP` (mmHg)
- DBP weighted 2/3 because diastole lasts roughly twice as long as systole.

### (2) Vascular resistance — Poiseuille

```
R_cgs = 8·η·L / (π·r⁴)                    [dyne·s/cm⁵]
R     = R_cgs · 4.5006e-5                 [mmHg·min/L]
```

- **In:** `eta`, `L`, `r` → **Out:** `R` (mmHg·min/L)
- Single rigid cylindrical segment, steady laminar Newtonian flow.
- `r⁴` dependence: a 50 % radius reduction raises R 16×.
- Not whole-body SVR (which is the parallel sum of billions of vessels).
- ⚠️ The Hagen–Poiseuille expression is correct, but **both unit steps as
  currently implemented are not** — see the unit check in §5. Treat R's trend
  as meaningful and its absolute value as not.

### (3) Stroke volume — Frank–Starling

```
SV = k · min(EDV, EDV_limit)
```

- **In:** `EDV` (mL) → **Out:** `SV` (mL)
- **Constants:** `k = 0.55`, `EDV_limit = 200 mL` (plateau above the limit).
- Selectable profiles: normal `k=0.55, limit=200`; heart failure `k=0.30,
  limit=150`; athletic `k=0.65, limit=220`.
- `k` is a fixed ejection fraction — it does not respond to afterload.

### (4) Cardiac output

```
CO = HR · SV / 1000
```

- **In:** `HR` (bpm), `SV` (mL) → **Out:** `CO` (L/min)
- The `/1000` converts mL/min to L/min. CO scales linearly with HR.

### (5) Flow — Ohm's law for haemodynamics

```
Q = (MAP − CVP) / R
```

- **In:** `MAP` (mmHg), `R` (mmHg·min/L) → **Out:** `Q` (L/min)
- **Constant:** `CVP = 5.0 mmHg`, held fixed (normal resting range 2–6).
- Driving pressure is the arterio-venous gradient, not MAP alone.
- Because `R` comes from equation (2), `Q`'s absolute magnitude inherits that
  equation's caveat. **`CO` and `Q` are computed on two independent paths and
  are not reconciled** — they can disagree.

### (6) Length constant — cable theory

```
λ = √( r_m / (r_i + r_e) )
```

- **In:** `r_m`, `r_i`, `r_e` → **Out:** `λ` (mm)
- Distance over which a passive signal decays to 1/e.
- Standalone: not coupled to the haemodynamic chain. Absolute magnitude and
  units are pending domain calibration.

---

## 3. Outputs and clinical targets

Six derived quantities. Five of them carry a target band; anything outside its
tolerance emits a corrective feedback signal every cycle.

| Symbol | Name | Unit | Target | Tolerance | Band | From |
|---|---|---|---|---|---|---|
| `MAP` | Mean arterial pressure | mmHg | 85 | ±15 | 70 – 100 | eq. 1 |
| `R` | Vascular resistance | mmHg·min/L | — | — | — | eq. 2 |
| `SV` | Stroke volume | mL | 70 | ±15 | 55 – 85 | eq. 3 |
| `CO` | Cardiac output | L/min | 5.0 | ±1.5 | 3.5 – 6.5 | eq. 4 |
| `Q` | Blood flow rate | L/min | 5.5 | ±1.5 | 4.0 – 7.0 | eq. 5 |
| `λ` | Length constant | mm | 2.0 | ±0.5 | 1.5 – 2.5 | eq. 6 |

`R` is an intermediate quantity with no target — it is consumed by equation (5).

The headline metric is the total normalised deviation

```
D = Σ |actual − target| / tolerance        (summed over the 5 targeted outputs)
```

i.e. "how many tolerance-bands off, in total". The feedback loop's job is to
shrink D.

---

## 4. Worked example

Dataset profile #03 (hypertension stage 1), before any feedback correction:

| Step | Computation | Result |
|---|---|---|
| Inputs | SBP 145, DBP 92, HR 75, EDV 120, η 3.5, L 50, r 0.14, r_m 5000, r_i 200, r_e 300 | |
| eq. 1 | (145 + 2×92) / 3 | MAP = 109.7 mmHg |
| eq. 2 | 8×3.5×50 / (π×0.14⁴) × 4.5006e-5 | R = 52.2 mmHg·min/L |
| eq. 3 | 0.55 × 120 | SV = 66.0 mL |
| eq. 4 | 75 × 66.0 / 1000 | CO = 4.95 L/min |
| eq. 5 | (109.7 − 5) / 52.2 | Q = 2.00 L/min |
| eq. 6 | √(5000 / 500) | λ = 3.16 mm |

Of these, MAP (109.7 vs band 70–100), Q (2.00 vs 4.0–7.0) and λ (3.16 vs
1.5–2.5) are out of band, so three tags fire. SV and CO are on target and are
left untouched.

---

## 5. Implementation notes

- **Timescale.** This is steady-state algebra, not a differential-equation
  model. The x-axis on every chart counts control cycles, not seconds. There is
  no pulsatility and no vessel compliance.
- **Causality.** `MAP` enters as an input, whereas physiologically it is an
  output (≈ CO × SVR). This is the direct cause of the CO/Q split noted above.
- **Unit check on equation (2).** The Hagen–Poiseuille form `8ηL/(πr⁴)` is
  correct. The conversion into `mmHg·min/L` is not, in two independent places:

  1. **Viscosity scale.** `eta` is declared in mPa·s but fed into the CGS
     expression, which requires poise. Since 1 poise = 100 mPa·s, blood at
     3.5 mPa·s = 0.035 poise, so the value entering the formula is **100×
     too large**.
  2. **Conversion constant.** The implementation uses
     `60/(1333.22×1000) = 4.5004e-5`. Dimensional analysis gives
     `1/(1333.22×0.06) = 1000/(1333.22×60) = 1.2501e-2` — the 60 and the 1000
     are transposed, making the constant **277.8× too small**.

  The two offsets partly cancel, leaving R about **2.78× too low**. At the
  defaults (η 3.5 mPa·s, L 50 cm, r 0.15 cm) the model reports
  R ≈ 39.6 mmHg·min/L where the dimensionally-consistent value is
  ≈ 110.0. R therefore lands in a plausible-looking range through compensating
  constants plus chosen geometry, not through dimensional correctness.

  Correcting both steps changes the calibration, so it is not a one-line fix:
  at r = 0.15 cm the corrected R = 110 falls outside the model's own
  `[10, 40]` gate and drives Q down to ≈ 0.7 L/min. Recovering a normal
  systemic resistance (≈ 17.6 mmHg·min/L) with L = 50 cm and η = 3.5 mPa·s
  requires **r ≈ 0.237 cm**. Note also that the conversion constant is
  hard-coded in `backend/circulatory_lamina.py`, not in the XML.
- **One set of targets for everybody** — no adjustment for body size, sex or
  age.
