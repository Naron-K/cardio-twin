# Adding a lamina

There are two laminae. The second exists because a universal claim you cannot
test is a decoration, and building it found three real things wrong that one
lamina could never have shown.

| | `lamina_circulatory` | `lamina_respiratory` |
| --- | --- | --- |
| attributes | 18 | 25 |
| functions | 8 | 13 |
| chain depth | 8 layers | 10 layers |
| segments | 3 | 4, one with no outcome |
| composites | 5 | 4, one no tag writes to |
| tags | 5 | 5, one multi-target, one monitor-only |
| gates | 5 | 4 |
| artwork | anatomical heart | none — the lamina map takes the centre |

## What it takes

Three files and one line.

1. **`<name>_lamina.xml`** — the declarations. Attributes with their source,
   unit and declared range; functions with a step, a human-readable formula,
   inputs and an output; composites; segments; behavioural outcomes; tags;
   gates.
2. **`<name>_lamina.py`** — a `UniversalTwin` subclass whose
   `_register_functions()` maps each `<function>` id to a Python callable.
   Functions receive positional inputs in the order `<inputs>` declares and
   never see an attribute name.
3. One line in `_IMPLEMENTATIONS` in [`laminae.py`](../backend/laminae.py),
   pairing the XML's `id` with the class.

Then:

```bash
CARDIOTWIN_LAMINA=backend/respiratory_lamina.xml python -m uvicorn main:app --port 8000
```

**Nothing in the frontend changes.** The 2D view reads `/api/schema` and names
no attribute of its own, so the new lamina draws itself — inputs grouped by
segment, one card per function with live values substituted in, every attribute
on its declared range, the computation graph laid out from the declarations,
and only the tabs the lamina earns.

A lamina with no entry in `_IMPLEMENTATIONS` still loads, on bare
`UniversalTwin`. Every function logs "no function registered" and every
computed attribute stays unset, so the visualiser draws the whole structure
with a dash on each computed node. That is the honest picture of "declared but
not implemented", and it is more useful than a crash.

## Baselines belong to the lamina

`<baseline>` and `<noise_sigma>` on a SENSOR attribute say where a synthetic
feed should sit at rest and how far it should wander. Both are optional; both
used to be a table in `signal_source.py`, which made the resting state of the
twin a fact about a Python file rather than about the patient.

Do not reach for the midpoint of the declared range as a substitute. The
midpoint of an FiO2 range of 0.21–1.0 is 0.6 — a patient on heavy respiratory
support. A midpoint is legal, not healthy. `SimulatedSource` falls back to it
when nothing is declared and `describe()` names every attribute it had to guess
for, so the gap shows up in the log rather than in the numbers.

Both laminae are declared to rest inside every one of their behavioural
outcomes, so a session starts healthy and a slider is what makes it sick.

## Three things the second lamina found

### 1. Polarity is about the coupling, not about correcting

The gate kernel computes `raw = polarity · gain · w · G · d`. A tag marked
`negative` pushes every attribute in its target composites **down** when its
outcome sits above target. That corrects an outcome that rises with the
composite and *amplifies* one that falls with it.

`PaCO2 = 0.863 · VCO2 / V_A` is the second kind: arterial CO2 comes down by
ventilating more. With `polarity="negative"`, hypoventilation drove V_A down,
which raised PaCO2, which drove V_A down further. Measured: PaCO2 reached
1928 mmHg and alveolar ventilation went negative within two cycles.

Every relation in the circulatory lamina is positive — CO rises with HR and SV,
MAP with SBP and DBP — so nothing there ever exercised this. **Any new lamina
must ask, per tag: does raising this composite raise or lower the outcome it
watches?** Where it lowers it, the corrective polarity is `positive`.

The UI was making this worse. It labelled polarity "corrective" and
"amplifying", which sounds like a fact about the tag and is not one — it was
printing "amplifying" beside a tag that was correcting. The labels now state
what the sign does (`pushes target up on rise`) and leave the judgement to a
reader who can see the coupling in the map.

A better fix lives in the model rather than in either: polarity is per tag, so
a tag cannot say "push V_A up and VCO2 down" for one outcome. A per-target sign
would express the coupling where it actually lives. That is a change to the
feedback design and it is not made here.

### 2. X″ writes after the function's guards

`_calc_alveolar_ventilation` floors its result at 0.05 L/min. The floor
protects X′, and the loop adds X″ afterwards, so the visible X went to −2.88.
The same happened to the A-a gradient, which clamps at zero in code and
displayed −2.69.

This is inherent to additive coupling: a function guards the value it returns,
not the value anyone reads. Anything that must hold on the *visible* value has
to be enforced after the coupling — which is a decision for the feedback
design, not something to patch into individual laminae.

### 3. A failed computation used to look exactly like a healthy one

When a function raises, `_resolve` logs `ERROR computing …` and moves on. The
attribute keeps last cycle's value. Nothing downstream can tell, so the screen
showed a stale number as live and confidently — a PaCO2 frozen at 1928 mmHg
while the loop kept running around it.

The snapshot's `warnings` list now carries `ERROR computing` and
`No function registered` alongside the gate lines, and the Cycle Report panel
already renders warnings, so the screen at least says something went wrong.
**The value is still stale and still looks live.** Marking the attribute itself
needs the twin to report which attributes failed this cycle, which is a change
to the snapshot contract and is left open deliberately.

## The limit that has not moved

The visualiser is universal. The compute layer is not: a new lamina still needs
a Python implementation per declared function.

Do not "fix" this by evaluating the `<formula>` strings. They are written for
humans — `SV = k * EDV (with Starling limit)`,
`Q = (MAP - CVP) / R (CVP held constant at ~5 mmHg)` — and an evaluator would
silently disagree with the code that actually runs. A machine-readable
expression alongside the prose formula is the way in, and it is a change to the
model, not to the visualiser.
