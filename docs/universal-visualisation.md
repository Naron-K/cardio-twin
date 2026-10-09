# The universal visualiser

The 2D view is not a dashboard for a heart. It is a renderer for whatever
lamina the backend is running, and it learns what to draw by asking the model
to describe itself.

Two sentences carry the whole design:

> **Structure comes from the schema. Values come from the tick. Nothing comes
> from a constant typed into a component.**

Swap `circulatory_lamina.xml` for a lamina describing a kidney, a battery pack
or a water network, and the screen rebuilds itself — different inputs,
different functions, different targets, different tabs — with no code change.

---

## Why this and not a dashboard

The previous version of this screen knew it was drawing a heart. It named `HR`,
`MAP`, `CO` and `SV` directly, carried a table of six chamber labels, held
missions keyed to `target_map`, and pushed commands into `HR`/`SBP`/`r`. Every
one of those is a fact about *one* lamina living in the UI, and each is a place
where an edit to the XML and the picture on screen can quietly disagree.

The supervisor's rule — the visualiser reads processed model attributes and
never the raw stream — was already honoured for the stage. What was not
honoured was the rest of the screen: the panels around the stage were still
hand-built for a circulation. The universal skeleton finishes the job by making
the *shape* of the screen a model output too.

---

## What the model already tells us

`GET /api/schema` is the backend parsing the lamina XML and handing back
everything it found. It was always richer than the frontend used:

| Block | What it carries | Drawn as |
| --- | --- | --- |
| `attributes` | id, name, unit, source, declared range, description, `computed_by`, `depends_on` | input controls, output list, every bar |
| `functions` | step, formula, inputs, output, description | Functions tab; the middle band of the map |
| `segments` | attributes, composites, functions, behavioural outcomes | Segments tab; input grouping |
| `composites` | members, absorption and distribution vectors | Vector space tab |
| `tags` | outcome, deviation type, emitter, gate kernel, polarity, targets, params | Tags table; the return band of the map |
| `gates` | attribute, type, bounds, action on fail, flag | Machinery tab; gate bands on segment rows |
| `feedback_config` | coupling, solver, adaptation kernel, cadence, params | Machinery tab |
| `registries` | mechanism names the engine offers per pipeline slot | Machinery tab — what was chosen *from* |

`gates` and `registries` are new. Both were already parsed and both were
invisible, which pushed anyone who wanted a limit on screen into typing a
threshold into a component — the exact failure the architecture is built to
prevent.

`registries` is worth its own sentence. Read alone,
`gate_kernel="sigmoid_leaky_tanh"` looks like a fact about the world. Read
beside the list it was selected from, it is visibly a decision someone made.

---

## The skeleton

Four modules under `frontend/src/twin/`. None of them contains an attribute id,
a unit, a threshold or a clinical word.

**`schema.ts`** — the wire types, and one `indexLamina()` that resolves the
cross-references every view would otherwise redo: which function produces an
attribute, which segment owns it, which outcome judges it, which composites a
tag writes into. Optional blocks normalise to empty, so a minimal lamina flows
through every view without existence checks at the call site.

**`graph.ts`** — builds the computation graph from five declarations
(`inputs`, `output`, `depends_on`, `outcome`, `targets`) and lays it out.
Forward depth is a longest-path layering from the raw inputs, iterated to a
fixpoint rather than topologically sorted, because a lamina may legitimately
declare a cycle and a topological sort would refuse it. A layer past six rows
wraps into sub-columns instead of growing down; rows in the return band are
swept left to right so two tags under the same column cannot hide each other.

**`views.tsx`** — the view registry. Each view declares `applies(schema)`, and
a view whose requirement the lamina does not meet is never rendered. A lamina
with no composites has no vector-space tab; a lamina with no tags has no
feedback tab. That predicate is the difference between a dashboard that happens
to work for one model and a skeleton that reads whatever it is given.

**`stageRegistry.tsx`** — the deliberate exception, and the only file allowed
to name a lamina. Artwork cannot be derived: someone drew a heart, and nothing
in the XML says a heart is what its attributes look like. So the artwork layer
is quarantined to one screen of code. A lamina with no entry is not broken — it
simply has no stage, and the lamina map takes the centre.

---

## What is on screen

The app is one dashboard (`components/dashboard/Dashboard.tsx`) in four zones:
data sources, the twin, outcomes, and deviation over time. The twin zone shows
the artwork if this lamina has any (otherwise the map), a trend per computed
attribute, or a table of inputs beside outputs. The views below live behind
**Inspect**, a drawer built from the same view registry.

**Lamina map** — the flagship, and the only view that shows the model's shape
rather than its values. The forward band reads left to right: inputs →
function → computed value → target. The band beneath reads back the other way,
and is the part worth looking at — an outcome outside tolerance fires a tag,
the tag fans into composites, and composites are the addresses where X″ lands
on attributes back at the start of the chain. That return path is the loop, and
it lights amber on the cycles it carries something. Hover any node to isolate
what it reads and what reads it.

**Functions** — one card per declared computation, with the live values
substituted into it. The formula string is printed verbatim because it is the
domain expert's own sentence; paraphrasing it in the UI would be the UI holding
an opinion. Where the loop is holding part of an output, the card splits it
into X′ and X″, so a value that disagrees with a hand-check of the formula
explains itself.

**Segments** — the lamina broken into the subsystems it says it has, every
attribute on its declared range. The range is a display scale, not a verdict.
The only verdicts drawn are ones the model computes: an outcome's tolerance
band and a gate's permitted range. An attribute with neither says
*tracked, not judged*, which is the honest rendering.

**Outcomes**, **Convergence** — unchanged in substance. Each outcome on its own
tolerance band with the shadow pass beside it, and D = Σ |actual − target| ÷
tolerance over time with and without the loop.

**Feedback loop** — X″ per attribute and the gain the slow loop has learned,
plus the tag table: outcome watched, deviation measure, emitter, gate kernel,
polarity, composites written to and with what weight, lit on the cycles it
fires.

**Vector space** — composites with their members' normalised values, the
distribution weight each carries, and the absorbed value the twin computes from
the two. A composite is the address a correction is delivered to, and nothing
had ever drawn it.

**Machinery** — what this lamina selected and what it selected from, plus every
declared gate.

**Data sources** — one control per SENSOR attribute, span from its declared
range, grouped by the ingestion channel the lamina maps it to. These are inputs, not readings: the stage
takes the computed half of the snapshot as its single data prop and has no prop
through which a sensor could arrive.

---

## Running a different lamina

```bash
CARDIOTWIN_LAMINA=backend/respiratory_lamina.xml python -m uvicorn main:app --port 8000
```

`laminae.py` reads the XML's own `id` and pairs it with the class holding that
lamina's arithmetic; `main.py` and `session.py` both go through it, so the API
and the streaming session always agree on which lamina is loaded.

### It has been done, not just claimed

`lamina_respiratory` is the second lamina, and it was written to break this
skeleton if it could. 25 attributes against 18, a ten-layer chain against
eight, twelve sensors that force the map's first column to wrap, a function
taking four inputs, a segment declaring no outcome at all, a composite no tag
writes into, a tag fanning into two composites, and a tag with polarity 0 that
evaluates and corrects nothing.

The frontend needed no change. Not a line — the lamina map took the centre
because no artwork is registered for it, the input rail generated twelve
controls grouped by segment, thirteen function cards appeared in declared step
order with live values substituted into each formula, and the tab strip dropped
nothing because this lamina happens to declare all seven views' worth of
structure.

Two things did change, and both were the UI making claims the model does not
support. Polarity was being labelled "corrective" and "amplifying" — printed
beside a tag that was correcting through an inversely coupled composite, which
made it exactly wrong; the labels now say what the sign does. And a function
that raises used to leave a stale value on screen looking live, so compute
errors now reach the snapshot's warnings.

Both, and the modelling trap that produced them, are written up in
[laminae.md](laminae.md).

### The honest limit

**The visualiser is universal. The compute layer is not yet.**

`UniversalTwin` resolves a function by looking its id up in
`_function_registry`, and a subclass is what populates that registry. Functions
receive generic positional inputs and are not coupled to attribute names — the
decoupling is real and deliberate — but a brand-new lamina still needs a
subclass registering a Python implementation per declared function. Without one
the twin logs `WARNING: No function registered for '…'` and the attribute stays
unset; the visualiser then draws a dash rather than a zero, because zero is a
measurement and a blank is not.

Making the engine read arithmetic straight from the XML is the obvious next
step and is **not** something to do by evaluating the `<formula>` strings: they
are written for humans (`SV = k * EDV (with Starling limit)`,
`Q = (MAP - CVP) / R (CVP held constant at ~5 mmHg)`) and an evaluator would
silently disagree with the Python that actually runs. A machine-readable
expression alongside the prose formula would be the way in, and it is a change
to the model, not to the visualiser.
