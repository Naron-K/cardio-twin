# Stage templates

The visualiser must never read raw data. It reads processed model attributes,
and nothing else. That is the whole rule; everything below exists to make it
checkable rather than aspirational.

## The pieces

| Concept       | Here                                              |
| ------------- | ------------------------------------------------- |
| Layer         | a lamina — `lamina_circulatory`                    |
| Component     | a segment — `seg_cardiac`, `seg_arterial`, `seg_conduction` |
| Artwork       | `public/heart/base.png`, static                    |
| Placeholder   | an entry in `public/heart/template.json`           |
| Animation     | a cutout PNG moved by an animator                  |

A placeholder is a rectangle, a pivot, and a set of **bindings** saying which
model quantity drives it and through which animator. It holds no pixels and no
logic. Swap the template and the same renderer draws a different lamina.

```
model state ──WebSocket──▶ LaminaStage ──template says which──▶ animator ──▶ transform
```

The model emits state. The template says who reads it. The animator converts it
to motion. The model never learns a screen exists.

## Where the numbers may come from

The lamina schema already classifies every attribute, so the stage uses the
model's own labels rather than holding a second opinion:

- `PRELIMINARY` — computed by the model. **Allowed to drive the stage.**
- `SENSOR` — raw input, including `HR` ("Heart rate from Apple Watch"). **Not
  allowed.**

`LaminaStage` takes exactly one data prop, `values`, and `GameDashboard` fills
it from the `computed` half of the snapshot — every PRELIMINARY attribute, and
nothing else. Sensors are absent by construction rather than by omission: there
is no prop through which one could arrive.

Each binding therefore resolves to one of four provenances, which Schematic mode
colours: `model` (oxy), `sensor` (danger), `constant` (warn), `missing` (dim).

## What Schematic mode is for

It draws a frame per placeholder and colours it by where its data comes from, so
a violation is visible on screen instead of buried in a props chain. The bottom
strip reports the beat binding once — it is stage-wide, and letting it colour
all six frames would drown out everything else — then tallies the distinct
channels.

At the time of writing that tally reads **8 model · 0 sensor · 3 constant**.

The three constants are the two atrial amplitudes and the atrial phase window:
no model output describes an atrium, so those numbers are declared in the
template — visible in Schematic mode — rather than hidden in the renderer.

Splitting motion into channels is what keeps an unbound region from freezing:
timing is shared and comes from the model, while amplitude falls back to a
declared constant where the model has nothing to say.

## Rhythm

`seg_cardiac` computes two attributes purely so consumers never need the HR
sensor:

| Attribute | Function            | Formula                    |
| --------- | ------------------- | -------------------------- |
| `T_cycle` | `cardiac_rhythm`    | `60 / HR`                  |
| `T_sys`   | `systolic_interval` | `0.413 − 0.0017 · HR`      |

`T_cycle` is arithmetically trivial, and that is fine — its job is to put the
seam in the right place. When rhythm grows real content, it grows in the model
and no consumer changes.

`T_sys` is Weissler's regression for left ventricular ejection time. It is not
cosmetic: ejection time falls with rate far more slowly than cycle length does,
so systole occupies a *larger* share of a fast cycle. Phase windows are
therefore declared as durations in seconds and converted against the live
`T_cycle`, which a fixed fraction cannot express. Measured on the running stage,
the ventricular window grows from 0.29 to 0.33 of the cycle between 72 and
93 bpm; the old constant `[0.08, 0.42]` never moved.

The coefficients are a population regression from an adult male resting cohort,
not a per-patient fit — worth recalibrating before any clinical claim.

## Editing

`tools/cut_heart_layers.py` owns `geometry` and rewrites it on every run.
`label`, `motion`, `flow` and `drawOrder` are hand-editable and preserved. The
template is fetched at runtime, so bindings can change without a rebuild.

## Still hard-coded in the UI

Honest list of clinical knowledge that has not moved yet:

- `VITAL_RANGE` in `protocol.ts`, and the `alert` flag derived from it — the
  model already ships `within_tolerance` per outcome, and two of these bands
  disagree with the XML (`CO` and `SV`)
- `ecgAt()` — the strip's *rate* now follows `T_cycle`, but its waveform is
  still synthesised from P–QRS–T gaussians. The model takes no ECG input and
  emits no waveform, so this remains a decoration that the UI labels as such
- `SYSTOLE` / `ATRIAL_SYSTOLE` in `beatClock.ts` — the fixed windows, still used
  by the 16-bit sprite. The anatomical stage no longer reads them
- The atrial phase window is a declared constant, because no model output
  describes atrial timing
