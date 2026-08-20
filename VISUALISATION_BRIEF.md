# CardioTwin — visualisation architecture brief

A self-contained description of what this system is, what it can and cannot
display, and the question we want researched. Written for a reader with no prior
exposure to the project. Every number here was read out of the running code, not
recalled.

---

## 1. What the system is

A cardiovascular **physiological digital twin**. Python/FastAPI backend, React +
Vite frontend, streaming over a WebSocket at 10 Hz.

The model is **declared in XML**, not hard-coded. A domain expert edits
`circulatory_lamina.xml` to change the physiology without touching Python. The
XML declares attributes, the functions that compute them, logical groupings, and
numerical targets.

### Vocabulary

| Term | Meaning |
| --- | --- |
| **Lamina** | one layer of the body. There is exactly one: `lamina_circulatory` |
| **Segment** | a named subsystem of a lamina. Three exist |
| **Attribute** | a measurable or computed quantity |
| **Function** | a formula computing one attribute from others |
| **Behavioural outcome** | a target + tolerance attached to an attribute |

### The three segments

| Segment | Attributes |
| --- | --- |
| `seg_arterial` | SBP, DBP, MAP, R, Q |
| `seg_cardiac` | EDV, HR, SV, CO, T_cycle, T_sys |
| `seg_conduction` | r_m, r_i, r_e, lambda |

---

## 2. The data — this is the binding constraint

**18 attributes, split into two kinds. The split is the whole story.**

### 10 SENSOR attributes — raw input, forbidden to the visualiser

`SBP` `DBP` `HR` `EDV` — measured from the patient (the XML literally
annotates HR as "Heart rate from Apple Watch").

`eta` `L` `r` `r_m` `r_i` `r_e` — model configuration a domain expert sets
(blood viscosity, the geometry of *one representative vessel segment*, cable-theory
resistances). No wearable measures these.

### 8 PRELIMINARY attributes — computed by the model, the only things allowed to drive visuals

| Attribute | Unit | Meaning |
| --- | --- | --- |
| `MAP` | mmHg | mean arterial pressure |
| `R` | mmHg·min/L | Poiseuille resistance of one representative vessel |
| `SV` | mL | stroke volume |
| `CO` | L/min | cardiac output |
| `Q` | L/min | flow rate |
| `lambda` | mm | electrical length constant |
| `T_cycle` | s | cardiac cycle length |
| `T_sys` | s | ventricular ejection time |

### 5 behavioural outcomes

`Q` → 5.5 ± 1.5 · `MAP` → 85 ± 15 · `CO` → 5.0 ± 1.5 · `SV` → 70 ± 15 ·
`lambda` → 2.0 ± 0.5

Each evaluates per cycle to `{target, actual, deviation, within_tolerance}`.

### An adaptive feedback loop

Every attribute decomposes as **X = X′ + X″** — an external value plus a
correction the loop computed. A two-timescale controller drives outcomes back
toward target and tunes its own gain online. Each tick also ships a **shadow
pass**: the same cycle recomputed with X″ zeroed, i.e. what would have happened
with no loop at all.

### What does NOT exist — read this twice

- **No per-chamber anything.** There is ONE stroke volume and ONE end-diastolic
  volume for the whole heart. No left-atrial pressure, no right-ventricular
  volume, no per-chamber elastance.
- **No pulsatility.** The model is steady-state algebra, not a time integration.
  It has no notion of a pressure waveform.
- **No ECG.** No conduction waveform of any kind is computed. `lambda` is a
  single scalar length constant, not a signal.
- **No anatomy.** The model does not know the heart has four chambers.

`Q`'s absolute value is documented as unreliable (it is a single-segment
estimate); only its trend is meaningful.

---

## 3. The architectural rule we must satisfy

From the project's academic supervisor, and it is non-negotiable:

> The visualiser must never see the raw data stream. It reads processed model
> attributes only. Medical complexity is absorbed by the behavioural model,
> which digests raw input into a behavioural outcome; the visualiser then does
> the simple job of displaying that result.

The stated example: raw 8- or 12-channel ECG must go **into** the model, which
reduces it to a behavioural outcome per region; the region then pulses from that
outcome. Wiring ECG channels straight to the picture is exactly the error.

He explicitly does **not** care whether the visuals are 2D or 3D, or whether the
anatomy is accurate. He cares only about **where data crosses the boundary**.

---

## 4. How the current visualisation is built

### Layers, templates, placeholders

- **Artwork** — a static illustration of a heart cross-section. Never moves.
- **Placeholder** — a rectangle, a scale pivot, and *bindings*. Holds no pixels
  and no logic. Six of them: RA, RV, LA, LV, AO, PA.
- **Template** — a JSON file declaring the artwork plus its placeholders. Fetched
  at runtime, so bindings change without a rebuild.
- **Animator** — a named function in a registry that converts a model quantity
  into motion. Currently `scale` and `flow_along_path`.

```
model state ──WebSocket──▶ renderer ──template says who reads it──▶ animator ──▶ transform
```

The renderer knows nothing about hearts; it draws whatever template it is given.
The model never learns a screen exists.

### Channels

Each placeholder's motion splits into independently bound channels — `timing`,
`amplitude`, `flow` — so a region the model cannot describe still moves with the
shared beat instead of freezing, while its amplitude falls back to a constant
that is **declared in the template and displayed**, not hidden in code.

### Three display modes, one template

| Mode | What it shows |
| --- | --- |
| `Anatomical` | the illustration, animated. The showcase view |
| `Schematic` | the same stage with placeholder frames coloured by data provenance |
| `16-bit` | a pixel-art sprite, kept for artwork comparison |

Schematic mode is the compliance proof: every channel is coloured **model**
(computed), **sensor** (violation), **constant** (declared), or **missing**, and
tallied. It currently reads **8 model · 0 sensor · 3 constant**. The three
constants are both atrial amplitudes and the atrial phase window — because no
model output describes an atrium.

### The panel below the stage

Plots `D = Σ |actual − target| / tolerance` over the outcomes, in units of
tolerance so mmHg, L/min, mL and mm can be summed. Two lines: with the loop, and
the shadow pass without it. The gap is the loop's live contribution.

An ECG strip previously sat here and was **deleted**, not fixed: every sample of
it was fabricated in the browser from gaussians. A caption reading "synthesised"
does not survive contact with an audience that reads any waveform as a
measurement.

---

## 5. What has already been decided — do not re-propose

- **No game engine.** Unity/Unigine was considered and rejected: it needs
  per-chamber named meshes, adds a second build pipeline, and an earlier
  procedural 3D attempt was rejected on looks. The project deliberately moved 3D → 2D.
- **No fabricated signals.** Nothing may be displayed that the model did not
  compute. This is why the ECG is gone.
- **The illustration stays.** Artwork direction is settled.
- **No second opinion on clinical thresholds.** Targets and tolerances come from
  the model, not from constants in the UI.

---

## 6. The question we want researched

Given **only** the eight computed attributes, five outcomes, the X′/X″
decomposition and the shadow pass — and given that per-chamber pressures,
volumes and waveforms **do not exist** —

> **What is the most informative and most honest way to display this state?**

Sub-questions worth attention:

1. **Are we using the right visual variables?** Cavity area currently encodes
   stroke volume. Is scaling an anatomical region the best channel for a
   whole-heart scalar, or is it implying spatial specificity the data does not have?
2. **How should "the model has nothing here" be shown?** Two of six regions are
   unbound. Is a declared constant with a visible marker right, or is there a
   better convention for absent data?
3. **How should the feedback loop be made legible?** X″ per attribute, the
   deviation index, the shadow-pass gap, and online gain adaptation are all
   available and mostly unshown.
4. **Is anatomy the right frame at all** for a model with no anatomy — would a
   schematic circuit, a state-space view, or something else serve better, given
   the audience includes secondary-school students at a public open day?
5. **What would change if a 0D closed-loop model were added?** That upgrade
   (8 compartments, 4 valves as diodes, `P = E(t)·(V−V₀)`, ~8–10 ODEs at
   dt ≈ 1 ms) would produce genuine per-chamber pressure and volume. It is the
   main candidate for future work. Is it the right unlock, and what visual
   design would it justify that is unjustifiable today?

Answers that require data the model does not produce are not useful unless they
say explicitly what must be added to the model first — which is itself a
legitimate and welcome answer.
