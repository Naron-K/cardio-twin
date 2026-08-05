/**
 * heartLayers — geometry for the anatomical heart cutouts.
 *
 * The illustration in `public/heart/` was cut into one static base (myocardium,
 * valves, chordae, great-vessel walls) plus six chamber cutouts, all sliced
 * from a single source image so registration is exact by construction.  The
 * numbers come out of `tools/cut_heart_layers.py`; this module only adds the
 * types, the draw order and the lookups the renderer wants.
 */
import { BASE_H, BASE_W, GEOMETRY } from './heartLayers.generated'
import type { Chamber } from './heartSprite'

export interface HeartLayerGeometry {
  /** Cutout placement inside the base image. */
  x: number
  y: number
  w: number
  h: number
  /**
   * Scale pivot: the cavity centroid for the four chambers, the vessel root
   * for the two great vessels — so distension pushes outward along the trunk
   * instead of sliding it off its outflow tract.
   */
  px: number
  py: number
  /** Great vessels only: centreline from the root outward, for ejection flow. */
  path?: [number, number][]
}

export const HEART_BASE_W = BASE_W
export const HEART_BASE_H = BASE_H
export const HEART_LAYERS = GEOMETRY as Record<Chamber, HeartLayerGeometry>

/**
 * Painter's order.  The base goes down first; the pulmonary artery is drawn
 * last because it crosses in front of the aortic root in this illustration.
 */
export const HEART_DRAW_ORDER: Chamber[] = ['RA', 'LA', 'RV', 'LV', 'AO', 'PA']

export const HEART_ASSET: Record<Chamber | 'BASE', string> = {
  BASE: `${import.meta.env.BASE_URL}heart/base.png`,
  RA: `${import.meta.env.BASE_URL}heart/ra.png`,
  RV: `${import.meta.env.BASE_URL}heart/rv.png`,
  LA: `${import.meta.env.BASE_URL}heart/la.png`,
  LV: `${import.meta.env.BASE_URL}heart/lv.png`,
  AO: `${import.meta.env.BASE_URL}heart/ao.png`,
  PA: `${import.meta.env.BASE_URL}heart/pa.png`,
}

/** Point at fraction `u` ∈ [0,1] along a polyline, linearly interpolated. */
export function alongPath(path: [number, number][], u: number): [number, number] {
  const t = Math.min(0.9999, Math.max(0, u)) * (path.length - 1)
  const i = Math.floor(t)
  const f = t - i
  const a = path[i]
  const b = path[i + 1] ?? a
  return [a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f]
}
