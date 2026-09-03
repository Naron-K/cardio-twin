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

## Putting a lamina into a body

A lamina runs on its own. Joining it to another one is a separate declaration,
and it lives in the organism file rather than in either lamina — "circulation
feeds oxygen delivery" is a fact about neither end, and putting it in one of
them would make that lamina un-runnable alone.

Four things to write in `organism.xml`:

1. **A level.** `<lamina id="..." level="2"/>`. Where a lamina stands is a
   property of the BODY, not of the lamina: the same lamina can sit at a
   different height in a different organism, so the `level` in its own file is
   informational and this is what adjacency is judged against.

2. **A channel to its neighbour, and only to its neighbour.** A channel steps
   exactly one level (rule 7). If you want to reach past the middle of the
   stack, say what the missing middle is — the alternative is the
   cross-laminar tangle the layering exists to prevent.

3. **Gates on BOTH ends.** A channel with no gate on its receiving side is a
   wire that writes straight into the far lamina, and it is refused (rule 12).
   The sending lamina decides whether to offer; the receiving lamina decides
   whether to take; a value crosses only when both are open.

   - an **auto gate** reads the lamina it sits on, and is the protection
     layer: evaluated first, and not switchable off by configuration;
   - a **key gate** reads what the other side presents at the channel —
     `identity` matches the label, `weighted_distance` and `cosine` match the
     shape.

   How fast to absorb (`rate`), what to do when nothing is crossing
   (`on_close`), and how much of the offer to take (`weight`) all belong to
   the RECEIVING gate. How fast to believe something is the receiver's
   business, not the sender's.

4. **One interface composite, at most eight gates.** From outside, a lamina IS
   one composite, and it presents the same one in every direction (rule 9); a
   lamina needing two faces is two laminae wearing one id. Each face —
   upward and downward — carries at most four gates (rule 8).

A lamina at the END of a stack sends nothing, so it derives no interface
composite. If you want an auto gate on its receiving side, give the `<lamina>`
an explicit `face="<composite_id>"`; without one it has no own-state to read
and the body is refused rather than loading a gate that could never open.

Every rule is enforced when the file is parsed, so a wrong body fails before it
runs rather than during. The full list, with the measurement behind each, is in
the comment at the top of [`organism.xml`](../backend/organism.xml).

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

A better fix lives in the model rather than in either, and it has since been
made: `<target>` takes its own `polarity`, and omitting it inherits the tag's,
so every XML written before the attribute existed still means exactly what it
did. The sign now sits where the coupling does — per composite the tag fans
into, not once for all of them.

Declaring it on `PACO2_DEVIATION` is what showed the second target had no
coupling to declare. Under forced hypoventilation, with the
`gas_exchange_state` sign set positive, negative and zero in turn, PaCO2
settles on 44.65 mmHg in all three. It has to: `PaCO2 = 0.863 · VCO2 / V_A`
reads VCO2 and V_A, and gas exchange holds neither. The coupling that target
was declared for is real but runs one way — the alveolar gas equation carries
PaCO2 into PAO2, not back — and the chain already propagates it, so PAO2 climbs
out of −55.75 mmHg on V_A's correction alone in every run. The sign there was
adding X″ on top of a correction that had already arrived, and it is now `0`:
the target stays declared, because the coupling is worth stating, and acts on
nothing, because it cannot.

A sign that changes nothing is the cheapest possible answer to the question.
The point is that until the model could hold two signs, the question could not
be asked.

### 2. X″ writes after the function's guards

`_calc_alveolar_ventilation` floors its result at 0.05 L/min. The floor
protects X′, and the loop adds X″ afterwards, so the visible X went to −2.88.
The same happened to the A-a gradient, which clamps at zero in code and
displayed −2.69.

This is inherent to additive coupling: a function guards the value it returns,
not the value anyone reads. Anything that must hold on the *visible* value has
to be enforced after the coupling — which is a decision for the feedback
design, not something to patch into individual laminae.

It is enforced there now, in `Attribute.apply_feedback()`, the one point both
the controller's apply step and the kernel-state restore path pass through. The
allowed band is the declared physiological range **widened to contain X′**:

```
lo = min(physio_min, X′)      hi = max(physio_max, X′)
X″ ← clamp(X″, lo − X′, hi − X′)
```

The widening is the part that matters. A pathological reading is a reading, and
clamping to the declared range would hide it — which is the `soft_range` bug
fixed on 2026-06-23, and not one worth having twice. So a MAP of 120 against a
declared max of 110 still shows 120; what the band forbids is the *feedback*
making a value unphysical, so with X′ already outside the range X″ can only
pull back toward it.

Run the old runaway again and V_A floors at its declared 0.5 L/min instead of
reaching −2.88, while PaCO2 still climbs past 300 mmHg — a wrong sign is still
a wrong sign, and the guard is not a substitute for one. The controller reports
each clamp in the cycle report, because wanting to drive an attribute somewhere
the model says it cannot go is usually a sign problem rather than a strong
correction.

One deliberate consequence: the kernel's own `x_pp` keeps the number it
computed, so it can disagree with what was applied. `rollback_feedback` already
had that property, and the dead-zone snap clears the disagreement — except in
the one case the snap could not see. Its condition excludes a `value_feedback`
already at `0.0`, so an attribute the clamp pins at zero *every* cycle would
keep integrating behind a value that never moves, and dump the accumulated
charge the instant X′ came back into range.

A shunt does exactly that. FiO2 0.9 against SpO2 85% puts the A-a gradient near
540 mmHg on a declared max of 80; `PF_DEVIATION` keeps asking to widen it, the
clamp refuses every cycle, and `x_pp` saturated at ~21 mmHg and stayed there.
The snap now also takes attributes the clamp held at zero, so the state clears
each cycle and the loop restarts its request instead of charging up. The
warnings keep firing, which is right: the loop really is still asking for
something the model says cannot happen.

### 3. A failed computation used to look exactly like a healthy one

When a function raises, `_resolve` logs `ERROR computing …` and moves on. The
attribute keeps last cycle's value. Nothing downstream can tell, so the screen
showed a stale number as live and confidently — a PaCO2 frozen at 1928 mmHg
while the loop kept running around it.

The snapshot's `warnings` list carries `ERROR computing` and
`No function registered` alongside the gate lines, and the Cycle Report panel
renders warnings, so the screen says something went wrong. That was the cheap
half: a warning says something broke somewhere, and a value renderer cannot
read it.

The twin now also reports *which* attributes failed. `failed_attributes` maps
id → reason, is cleared at the top of every `compute_all()` so membership means
"failed on the most recent pass" rather than "failed once, ever", and reaches
the screen as `stale` and `error` on each computed entry of the snapshot. The
Model output panel dims a stale row, strikes its value through, replaces the
unit with the word `stale`, and puts the reason in the tooltip — so the number
is still there, and it no longer claims to be this cycle's.

Both failure branches are covered, not just the raising one: an attribute whose
`computed_by` names a function nobody registered is marked the same way, which
is what a lamina with no Python behind it looks like on screen.

## The limit that has not moved

The visualiser is universal. The compute layer is not: a new lamina still needs
a Python implementation per declared function.

Do not "fix" this by evaluating the `<formula>` strings. They are written for
humans — `SV = k * EDV (with Starling limit)`,
`Q = (MAP - CVP) / R (CVP held constant at ~5 mmHg)` — and an evaluator would
silently disagree with the code that actually runs. A machine-readable
expression alongside the prose formula is the way in, and it is a change to the
model, not to the visualiser.
