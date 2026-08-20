# The anatomical heart asset

The 2D stage renders four ways for this lamina, switchable from the toggle
above it:

| Mode         | Component                | Notes                                   |
| ------------ | ------------------------ | --------------------------------------- |
| `Anatomical` | `LaminaStage.tsx`        | illustrated cross-section (default)     |
| `Schematic`  | `SchematicOverlay.tsx`   | the same stage with its wiring showing  |
| `16-bit`     | `PixelHeart.tsx`         | the hand-authored sprite                |
| `Lamina map` | `LaminaMap.tsx`          | the model's own wiring, from the schema |

The first three exist because `lamina_circulatory` has an entry in
`twin/stageRegistry.tsx`. The fourth is always available and is the default for
any lamina nobody has illustrated.

`LaminaStage` knows nothing about hearts — it draws whatever stage template it
is handed. See [stage-template.md](stage-template.md) for the architecture and
the provenance rule it enforces, and
[universal-visualisation.md](universal-visualisation.md) for the screen the
stage sits inside.

## Where the pixels come from

`screen.png` at the repo root is the master: one 1024², opaque, unlabelled PNG
over a flat navy background (`rgb(5,17,33)`), commissioned against
[`HEART_SPRITE_SPEC.md`](../HEART_SPRITE_SPEC.md).

The brief deliberately asks for **one** picture rather than per-chamber layers.
Image generators cannot segment — asked to "extract the left atrium" they redraw
a whole new picture, and six such layers come back with mismatched geometry and
no registration. They also cannot export alpha; a request for a transparent
background comes back as a screenshot of the editor's checkerboard, baked in as
opaque pixels. So the brief asks for something *machine-separable* — closed
outlines, a distinct flat fill per touching region, nothing crossing a boundary
— and the separation happens locally:

```bash
python tools/cut_heart_layers.py
```

That script flood-fills from six hand-verified seed points and writes:

- `frontend/public/heart/base.png` — everything static: myocardium, valves,
  chordae, great-vessel walls, with the background knocked out
- `frontend/public/heart/{ra,rv,la,lv,ao,pa}.png` — the six moving regions
- `frontend/public/heart/template.json` — placement, pivots, centrelines,
  merged into the existing file so every hand-written binding survives the run

Because all seven come out of one image, registration is exact by construction.
Re-run the script after any change to `screen.png`; nothing is hand-tuned.

## Two things the artwork forced

**The myocardium is a static layer.** The pink ventricular wall is one
continuous mass — seeding it at the right wall and at the septum returns the
identical region — so it cannot be split into an LV wall and an RV wall.
Instead of scaling the whole silhouette, the wall renders as a fixed frame and
the four cavities pulse *inside* it, which is what a real cross-section does
anyway: the cavity shrinks and the wall thickens. To make that read, the cutting
script paints the cavities out of the base image in a shadowed wall tone, so a
contracting chamber uncovers thickened myocardium rather than a hole.

**The pulmonary artery exits sideways.** The illustration routes it laterally
off the right edge instead of upward, against spec rule A4. Rather than
commission a redraw, the ejection particles follow a centreline derived from the
mask itself — a geodesic walk out from the vessel root, taking the centroid of
each distance band — so they track whatever axis the artwork drew, bend
included. The aorta rises correctly and needs no special case.

## What the animation is bound to

| Channel                 | Source                                          |
| ----------------------- | ----------------------------------------------- |
| beat timing             | `T_cycle`, computed by the model                 |
| phase windows           | `T_sys` in seconds, against the live `T_cycle`   |
| chamber squeeze         | cardiac phase — atrial kick, then systole        |
| ejection particles      | `CO` / `Q` — faster flow at higher output        |
| great-vessel distension | `SV` — 70 mL ≈ 1×                                |
| bloom                   | an outcome outside the tolerance the model set   |

Every one of those is a PRELIMINARY attribute. Beat timing used to be
synthesised in the browser from the HR sensor; it now comes from `T_cycle`,
which the model computes precisely so that consumers never reach for the
sensor. The ECG that used to sit under the stage was deleted rather than
relabelled — see [stage-template.md](stage-template.md).

The lamina remains steady-state algebra with no pulsatility: it emits no
waveform and no per-chamber volumes, so the two atria move on a declared
constant and the strip above the stage says so. Showing real circulation needs
the 0D closed-loop upgrade, which is still outstanding.
