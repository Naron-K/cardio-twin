"""
Cut the anatomical heart illustration into the layers the 2D stage animates.

Input is one opaque PNG (`screen.png`): a heart cross-section drawn over a flat
navy background, with closed outlines and a distinct flat fill per touching
region.  Image models cannot segment, so the brief asked for a single
machine-separable picture and the separation happens here — see
`HEART_SPRITE_SPEC.md` for the brief and `docs/heart-asset.md` for the design.

Writes to `frontend/`:
    public/heart/base.png              static myocardium, valves, vessel walls
    public/heart/{ra,rv,la,lv,ao,pa}.png   per-region cutouts
    src/game/heartLayers.generated.ts   placement, pivots and vessel centrelines

Run from the repo root:  python tools/cut_heart_layers.py
"""
import json
import os
from collections import deque

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "screen.png")
IMG_OUT = os.path.join(ROOT, "frontend", "public", "heart")
TS_OUT = os.path.join(ROOT, "frontend", "src", "game", "heartLayers.generated.ts")

# Seed points inside each region, at the source image's native 1024².  These
# were found by hand and verified to produce six closed, zero-overlap regions.
SEEDS = {
    "RA": (350, 520), "RV": (500, 700), "PA": (560, 320),
    "LA": (640, 450), "LV": (660, 650), "AO": (470, 220),
}
CAVITIES = ["RA", "RV", "LA", "LV"]   # shrink → must be painted out underneath
VESSELS = ["AO", "PA"]                # only distend → their base copy stays hidden

TOL = 60      # per-channel colour tolerance for the flood fill
GROW = 3      # px: pull each region's own dark outline into its layer
PAD = 6       # px of slack around each cropped layer


def flood(img, seed, tol=TOL):
    """Connected region of pixels within `tol` of the seed's colour."""
    sx, sy = seed
    d = np.abs(img - img[sy, sx].astype(np.int16)).max(axis=2)
    lab, _ = ndimage.label(d <= tol)
    return lab == lab[sy, sx]


def centreline(mask, root, offset):
    """
    Walk a geodesic distance transform out from the vessel root and take the
    centroid of each distance band.  This follows whatever axis the artwork
    actually drew — which matters because this illustration routes the
    pulmonary artery sideways rather than upward, so a straight column of
    ejection particles would leave the vessel.
    """
    ry, rx = root
    if not mask[ry, rx]:                                  # snap onto the mask
        ys, xs = np.nonzero(mask)
        i = int(np.argmin((ys - ry) ** 2 + (xs - rx) ** 2))
        ry, rx = int(ys[i]), int(xs[i])

    h, w = mask.shape
    dist = np.full((h, w), -1, np.int32)
    dist[ry, rx] = 0
    q = deque([(ry, rx)])
    while q:
        y, x = q.popleft()
        d = dist[y, x] + 1
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            ny, nx = y + dy, x + dx
            if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and dist[ny, nx] < 0:
                dist[ny, nx] = d
                q.append((ny, nx))

    pts = []
    for band in np.linspace(0, dist.max() * 0.94, 12):
        sel = (dist >= max(0, band - 6)) & (dist <= band + 6)
        if sel.sum() < 30:
            continue
        lab, n = ndimage.label(sel)
        sizes = ndimage.sum(sel, lab, range(1, n + 1))
        sel = lab == int(np.argmax(sizes)) + 1            # ignore arch branches
        cy, cx = ndimage.center_of_mass(sel)
        pts.append([float(cx) + offset[0], float(cy) + offset[1]])

    # The aortic arch splits into its head/neck branches, so the largest-band
    # component jitters up there; one smoothing pass takes the kink out.
    smooth = [pts[0]] + [
        [round((pts[i - 1][j] + 2 * pts[i][j] + pts[i + 1][j]) / 4, 1) for j in (0, 1)]
        for i in range(1, len(pts) - 1)
    ] + [pts[-1]]
    return [[round(x, 1), round(y, 1)] for x, y in smooth]


def save_rgba(rgb, alpha, path, blur=0.6):
    """Write RGBA with a slightly feathered edge — the source has mild
    compression noise, so a hard mask edge shows a fringe."""
    im = Image.fromarray(np.dstack([rgb.astype(np.uint8), alpha.astype(np.uint8)]), "RGBA")
    r, g, b, a = im.split()
    Image.merge("RGBA", (r, g, b, a.filter(ImageFilter.GaussianBlur(blur)))).save(path, optimize=True)


def main():
    src = np.asarray(Image.open(SRC).convert("RGB")).astype(np.int16)
    H, W, _ = src.shape

    raw = {k: ndimage.binary_fill_holes(flood(src, s)) for k, s in SEEDS.items()}

    # Grow each region so it swallows its own outline (otherwise the outline
    # stays behind at full size while the cavity contracts away from it).
    # Contested pixels go to whichever region was originally nearest, which is
    # what keeps LA and LV from bleeding into each other across the septum.
    keys = list(SEEDS)
    grown = {k: ndimage.binary_dilation(raw[k], iterations=GROW) for k in keys}
    owner = np.stack([ndimage.distance_transform_edt(~raw[k]) for k in keys]).argmin(axis=0)
    masks = {k: grown[k] & (owner == i) for i, k in enumerate(keys)}

    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            assert not (masks[keys[i]] & masks[keys[j]]).any(), f"{keys[i]}/{keys[j]} overlap"

    solid = ~flood(src, (5, 5))

    # Base layer: paint the four cavities over in a shadowed wall tone, so a
    # contracting chamber uncovers thickened myocardium rather than a hole.
    base = src.copy()
    for k in CAVITIES:
        ring = ndimage.binary_dilation(masks[k], iterations=6) & ~masks[k] & solid
        base[masks[k]] = np.median(src[ring], axis=0) * 0.80

    ys, xs = np.nonzero(solid)
    x0, y0 = max(0, xs.min() - PAD), max(0, ys.min() - PAD)
    x1, y1 = min(W, xs.max() + PAD + 1), min(H, ys.max() + PAD + 1)

    os.makedirs(IMG_OUT, exist_ok=True)
    save_rgba(base[y0:y1, x0:x1], solid[y0:y1, x0:x1] * 255, os.path.join(IMG_OUT, "base.png"))

    layers = {}
    for k in keys:
        m = masks[k]
        ys, xs = np.nonzero(m)
        lx0, ly0 = max(0, xs.min() - PAD), max(0, ys.min() - PAD)
        lx1, ly1 = min(W, xs.max() + PAD + 1), min(H, ys.max() + PAD + 1)
        crop = (slice(ly0, ly1), slice(lx0, lx1))
        save_rgba(src[crop], m[crop] * 255, os.path.join(IMG_OUT, f"{k.lower()}.png"))

        if k in VESSELS:
            # Pivot at the vessel root (bottom-most run) so distension pushes
            # outward along the trunk instead of sliding it off its outflow.
            row = int(ys.max())
            py, px = float(row), float(xs[ys >= row - 3].mean())
        else:
            py, px = (float(v) for v in ndimage.center_of_mass(m))

        entry = {
            "x": int(lx0 - x0), "y": int(ly0 - y0),
            "w": int(lx1 - lx0), "h": int(ly1 - ly0),
            "px": round(px - x0, 1), "py": round(py - y0, 1),
        }
        if k in VESSELS:
            entry["path"] = centreline(m[crop], (int(py) - ly0, int(px) - lx0),
                                       (lx0 - x0, ly0 - y0))
        layers[k] = entry

    with open(TS_OUT, "w", newline="\n", encoding="utf-8") as f:
        f.write(
            "// Generated by tools/cut_heart_layers.py — do not edit by hand.\n"
            "// Coordinates are base-image pixels, origin at the base's top-left.\n"
            "import type { HeartLayerGeometry } from './heartLayers'\n\n"
            f"export const BASE_W = {int(x1 - x0)}\n"
            f"export const BASE_H = {int(y1 - y0)}\n\n"
            "export const GEOMETRY: Record<string, HeartLayerGeometry> = "
            + json.dumps(layers, indent=2)
            + " as const\n"
        )

    print(f"base {int(x1 - x0)}×{int(y1 - y0)}")
    for k, v in layers.items():
        print(f"  {k}: {v['w']}×{v['h']} at ({v['x']},{v['y']}) pivot ({v['px']},{v['py']})"
              + (f" path {len(v['path'])}pts" if "path" in v else ""))


if __name__ == "__main__":
    main()
