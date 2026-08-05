# The anatomical heart asset

The 2D stage can render its heart two ways, switchable from the toggle above the
stage:

| Model        | Component               | Notes                                    |
| ------------ | ----------------------- | ---------------------------------------- |
| `Anatomical` | `AnatomicalHeart.tsx`   | illustrated cross-section (default)      |
| `16-bit`     | `PixelHeart.tsx`        | the hand-authored sprite                 |

Both take the same props and are driven by the same bindings, so the toggle is a
straight A/B of the artwork, not of the physiology.

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
- `frontend/src/game/heartLayers.generated.ts` — placement, pivots, centrelines

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

| Channel               | Source                                          |
| --------------------- | ----------------------------------------------- |
| beat timing           | live HR, via the shared `beatClock`             |
| chamber squeeze       | cardiac phase — atrial kick, then systole       |
| ejection particles    | CO — faster flow at higher cardiac output       |
| great-vessel distension | SV — 70 mL ≈ 1×                               |
| bloom                 | the caller's `alert` flag                       |

Beat timing and the ECG are *synthesised from HR*, and the UI says so. The
lamina model is steady-state algebra with no pulsatility, so it emits no
waveform and no per-chamber volumes; showing real circulation needs the 0D
closed-loop upgrade, which is still outstanding.
