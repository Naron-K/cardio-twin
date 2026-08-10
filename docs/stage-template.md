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
  allowed**, and `GameDashboard` does not put any of them in the `values` it
  hands the stage.

Each binding therefore resolves to one of four provenances, which Schematic mode
colours: `model` (oxy), `sensor` (danger), `constant` (warn), `missing` (dim).

## What Schematic mode is for

It draws a frame per placeholder and colours it by where its data comes from, so
a violation is visible on screen instead of buried in a props chain. The bottom
strip reports the beat binding once — it is stage-wide, and letting it colour
all six frames would drown out everything else — then tallies the distinct
channels.

At the time of writing that tally reads **6 model · 1 sensor · 2 constant**:

- The one sensor is beat timing. The model emits no rhythm outcome, so
  `beatClock` is still fed from `HR`. This is a real violation, displayed rather
  than hidden, and the fix is a rhythm outcome in `seg_conduction`.
- The two constants are the atria. No model output describes an atrium, so their
  amplitude is a number declared in the template — visible in Schematic mode —
  rather than one hidden in the renderer.

Splitting motion into channels is what keeps an unbound region from freezing:
timing is shared and comes from the model once it has a rhythm outcome, while
amplitude falls back to a declared constant where the model has nothing to say.

## Editing

`tools/cut_heart_layers.py` owns `geometry` and rewrites it on every run.
`label`, `motion`, `flow` and `drawOrder` are hand-editable and preserved. The
template is fetched at runtime, so bindings can change without a rebuild.

## Still hard-coded in the UI

Honest list of clinical knowledge that has not moved yet:

- `VITAL_RANGE` in `protocol.ts`, and the `alert` flag derived from it — the
  model already ships `within_tolerance` per outcome, and two of these bands
  disagree with the XML (`CO` and `SV`)
- `ecgAt()` — the ECG strip is synthesised from HR; the model takes no ECG input
  and emits no waveform
- The cardiac phase windows now live in `template.json` rather than in
  `beatClock.ts`, which makes them visible but still does not make them model
  output
