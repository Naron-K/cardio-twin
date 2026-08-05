/**
 * heartSprite — the 16-bit pixel heart used by the 2D game stage.
 *
 * The sprite is authored as ASCII art where every glyph names an anatomical
 * region, so the renderer can colour, outline and *contract* each chamber
 * independently (the whole point: this is a physiological twin, not a clipart
 * heart).  Right-side chambers carry deoxygenated blood → Oxygenated-Blue
 * family; left-side chambers carry oxygenated blood → Crimson family.
 *
 * Glyphs
 *   A  aorta                 P  pulmonary artery
 *   R  right atrium          L  left atrium
 *   V  right ventricle       M  left ventricle (M = thick myocardium)
 *   .  empty
 *
 * Viewer's left = patient's right, matching how a heart is drawn in textbooks.
 */

export type Chamber = 'AO' | 'PA' | 'RA' | 'LA' | 'RV' | 'LV'

const GLYPH: Record<string, Chamber> = {
  A: 'AO',
  P: 'PA',
  R: 'RA',
  L: 'LA',
  V: 'RV',
  M: 'LV',
}

// 18 × 19 — every row is exactly SPRITE_W glyphs wide.
// The great vessels are 3px wide up top so their middle column survives the
// outline pass; they taper to 2px at the cleft between the atrial lobes.
const ART = [
  '......PPPAAA......',
  '......PPPAAA......',
  '......PPPAAA......',
  '..RRRR.PPAA.LLLL..',
  '.RRRRRRRRLLLLLLLL.',
  'RRRRRRRRRLLLLLLLLL',
  'RRRRRRRRRLLLLLLLLL',
  'RRRRRRRRRLLLLLLLLL',
  'RRRRRRRRRLLLLLLLLL',
  '.VVVVVVVVMMMMMMMM.',
  '.VVVVVVVVMMMMMMMM.',
  '..VVVVVVVMMMMMMM..',
  '..VVVVVVVMMMMMMM..',
  '...VVVVVVMMMMMM...',
  '....VVVVVMMMMM....',
  '.....VVVVMMMM.....',
  '......VVVMMM......',
  '.......VVMM.......',
  '........VM........',
]

export const SPRITE_W = 18
export const SPRITE_H = ART.length

/** One rendered pixel. `tone` indexes into a chamber's 5-step ramp. */
export interface HeartPixel {
  x: number
  y: number
  chamber: Chamber
  /** 0 = silhouette, 1 = internal seam, 2 = shadow, 3 = base, 4 = highlight */
  tone: 0 | 1 | 2 | 3 | 4
}

/** Per-chamber bounding box + centroid, used as the contraction pivot. */
export interface ChamberGeometry {
  minX: number
  maxX: number
  minY: number
  maxY: number
  cx: number
  cy: number
}

function chamberAt(x: number, y: number): Chamber | null {
  if (y < 0 || y >= SPRITE_H || x < 0 || x >= SPRITE_W) return null
  return GLYPH[ART[y][x]] ?? null
}

/**
 * Expand the ASCII art into positioned, shaded pixels.
 *
 * Two distinct border tones, which is what makes the anatomy readable at this
 * size: an almost-black *silhouette* where a neighbour is empty, and a lighter
 * *seam* where the neighbour is a different chamber.  The seam is what draws
 * the interventricular septum and the AV valve plane for free.
 *
 * Shading: one light source from the upper-left, evaluated over the *whole*
 * sprite rather than per chamber — a chamber-local ramp made the left atrium
 * read as a bruise because its own box put every pixel in the far corner.
 * Thresholds are deliberately lopsided so the base tone dominates and only the
 * apex falls into shadow.
 */
export function buildHeartPixels(): {
  pixels: HeartPixel[]
  geometry: Record<Chamber, ChamberGeometry>
} {
  // Pass 1 — bounding boxes.
  const boxes = {} as Record<Chamber, ChamberGeometry>
  for (let y = 0; y < SPRITE_H; y++) {
    for (let x = 0; x < SPRITE_W; x++) {
      const c = chamberAt(x, y)
      if (!c) continue
      const b = boxes[c]
      if (!b) {
        boxes[c] = { minX: x, maxX: x, minY: y, maxY: y, cx: 0, cy: 0 }
      } else {
        b.minX = Math.min(b.minX, x)
        b.maxX = Math.max(b.maxX, x)
        b.minY = Math.min(b.minY, y)
        b.maxY = Math.max(b.maxY, y)
      }
    }
  }
  for (const b of Object.values(boxes)) {
    b.cx = (b.minX + b.maxX + 1) / 2
    b.cy = (b.minY + b.maxY + 1) / 2
  }

  // Pass 2 — outline + shading.
  const pixels: HeartPixel[] = []
  for (let y = 0; y < SPRITE_H; y++) {
    for (let x = 0; x < SPRITE_W; x++) {
      const c = chamberAt(x, y)
      if (!c) continue

      const neighbours = [
        chamberAt(x - 1, y),
        chamberAt(x + 1, y),
        chamberAt(x, y - 1),
        chamberAt(x, y + 1),
      ]
      const touchesVoid = neighbours.some((n) => n === null)
      // Seam only on the top/left side of a boundary, so a chamber divide is a
      // single dark pixel line.  Marking both sides drew a 2px band that made
      // the left atrium read as a separate, much darker organ than the
      // ventricle below it.
      const left = chamberAt(x - 1, y)
      const above = chamberAt(x, y - 1)
      const touchesOther = (left !== null && left !== c) || (above !== null && above !== c)

      let tone: HeartPixel['tone']
      if (c === 'AO' || c === 'PA') {
        // The great vessels are only 2–3px wide, so the generic outline rule
        // turned almost every pixel near-black and they read as grey stubs.
        // Shade them as lit cylinders instead: base | highlight | shadow
        // across the width, no silhouette at all.
        const b = boxes[c]
        const u = b.maxX > b.minX ? (x - b.minX) / (b.maxX - b.minX) : 0.5
        tone = u < 0.34 || u > 0.66 ? 2 : 3
      } else if (touchesVoid) {
        tone = 0
      } else if (touchesOther) {
        tone = 1
      } else {
        // 0 at the lit corner (upper-left of the sprite), 1 at the apex.
        const t = (y / (SPRITE_H - 1)) * 0.75 + (x / (SPRITE_W - 1)) * 0.25
        tone = t < 0.28 ? 4 : t > 0.82 ? 2 : 3
      }

      pixels.push({ x, y, chamber: c, tone })
    }
  }

  return { pixels, geometry: boxes }
}

/** 5-step ramps: [silhouette, seam, shadow, base, highlight]. */
export const CHAMBER_RAMP: Record<
  Chamber,
  [string, string, string, string, string]
> = {
  // Oxygenated — Crimson family
  // Crimson seams are lightened relative to the blue side: the same darkness
  // that reads as shadow on teal reads as a black gash on coral.
  LV: ['#33000a', '#9c1128', '#c4082f', '#ff525f', '#ffb3b3'],
  LA: ['#33000a', '#94162e', '#c02338', '#f4616c', '#ffa5a5'],
  AO: ['#33000a', '#a52a3d', '#d1465a', '#ff7b84', '#ffdad9'],
  // Deoxygenated — Oxygenated-Blue family
  RV: ['#001c22', '#00464f', '#007a8c', '#00b4d8', '#7fe4f7'],
  RA: ['#001c22', '#003f4a', '#006c7d', '#00a3c7', '#6fd8ee'],
  PA: ['#001c22', '#00464f', '#008ba2', '#37c6e4', '#bdf4ff'],
}

/** Swatch used by the legend — the chamber's base tone. */
export const CHAMBER_SWATCH: Record<Chamber, string> = {
  LV: '#ff525f',
  LA: '#f0525f',
  AO: '#ff7b84',
  RV: '#00b4d8',
  RA: '#00a3c7',
  PA: '#37c6e4',
}

export const CHAMBER_LABEL: Record<Chamber, string> = {
  AO: 'Aorta',
  PA: 'Pulmonary artery',
  RA: 'Right atrium',
  LA: 'Left atrium',
  RV: 'Right ventricle',
  LV: 'Left ventricle',
}

/** Chambers that contract during atrial systole vs ventricular systole. */
export const ATRIA: Chamber[] = ['RA', 'LA']
export const VENTRICLES: Chamber[] = ['RV', 'LV']
export const VESSELS: Chamber[] = ['AO', 'PA']
