# CardioTwin — Heart Illustration Brief

**Deliver exactly one file: a single PNG of an anatomical heart cross-section.**

Do not attempt to split it into layers. Do not deliver SVG, pixel art, or
per-chamber "extractions" — earlier attempts at those failed, because an image
generator redraws rather than segments. One illustration is the whole job. The
chambers are separated downstream by software, which is why the drawing rules
in §3 are non-negotiable.

---

## 1. The image

A medical textbook–style cross-section of a human heart, cut open so all four
chambers and both great vessels are visible:

| Region | Blood | Colour family |
| --- | --- | --- |
| Right atrium | deoxygenated | blue / cyan |
| Right ventricle | deoxygenated | blue / cyan |
| Pulmonary artery | deoxygenated | blue / cyan |
| Left atrium | oxygenated | red / crimson |
| Left ventricle | oxygenated | red / crimson |
| Aorta | oxygenated | red / crimson |

- **Canvas:** square, 1024×1024 or larger.
- **Background:** solid opaque `#040e1f` (very dark navy), filling the canvas
  edge to edge. **Do not use transparency.** Two previous deliveries were
  ruined by screenshotting a transparency preview, so transparency is simply
  removed from the requirements — a flat known background colour is easier for
  everyone and works perfectly.
- **Style:** clean vector-look illustration, flat colour with soft shading,
  confident dark linework. Educational and approachable, not photorealistic and
  not gory. Muscle texture inside the ventricle walls is welcome.

---

## 2. Anatomy

1. **Viewer's left is the patient's right.** The blue chambers sit on the left
   of the image, the red ones on the right.
2. **Atria above ventricles**, with a clear boundary between them.
3. **Asymmetric.** The left ventricle wall is visibly thicker than the right,
   and the apex points down and toward the viewer's right. Do not draw a
   symmetrical Valentine ♥ shape.
4. **Both great vessels exit upward** through the top of the drawing. *The
   previous version had the pulmonary artery running sideways off the right
   edge — this must be fixed.* Both the aorta and the pulmonary artery rise
   vertically before any branching.
5. **No text.** No labels, no letters, no leader lines, no arrows, no
   watermark. The regions are identified by position and colour only.

---

## 3. Rules that make the image machine-separable

The six regions are cut apart by software after delivery. These three rules
decide whether that succeeds:

**S1 — Every region is fully enclosed by an unbroken dark outline.** The
outline must be a closed loop with no gaps, however small. A one-pixel gap lets
the separation algorithm leak from one chamber into its neighbour and the whole
region is lost.

**S2 — Every region has its own flat base colour, distinct from every region it
touches.** Shading and highlights within a region are fine as long as they stay
clearly closer to that region's base colour than to any neighbour's. Two
touching regions must never share the same fill.

**S3 — Nothing crosses a boundary.** No drop shadow, glow, translucency or
texture may spill from one region across an outline into another. Anything that
crosses makes the regions ambiguous.

Also: no region may be split into disconnected pieces by something drawn on top
of it. Each of the six must remain one continuous area.

---

## 4. Export

- Use your editor's **Export / Save As** command. **Never screenshot the
  canvas** — that is how both previous deliveries failed.
- PNG, 8-bit, opaque. No JPEG, no re-encoding through a lossy format. A flat
  area of background must contain exactly one colour; if a patch of empty
  background contains hundreds of slightly different colours, the file has been
  compressed and the outlines are already damaged.
- Outlines must stay crisp. Do not upscale a smaller image to reach 1024px.

---

## 5. Checklist before sending

1. One PNG, square, ≥1024px, opaque `#040e1f` background.
2. No text anywhere in the image.
3. Blue on the viewer's left, red on the viewer's right.
4. Aorta and pulmonary artery both rise upward and reach the top area.
5. Left ventricle wall clearly thicker than the right.
6. Trace each of the six regions' outlines with your eye — every loop closed.
7. No shadow or glow crossing any outline.
8. Zoom to 100% on a background area: one uniform colour, no compression noise.

---

*State plainly whether the image is AI-generated, and name any source it was
traced from or derived from. This asset goes into a public repository and into
slides for an academic audience, so unclear provenance is disqualifying.*
