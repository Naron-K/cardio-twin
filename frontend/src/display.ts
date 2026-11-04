/**
 * Display profile — how large the dashboard should draw, and how much of it fits.
 *
 * The dashboard is opened on a laptop, on an iPad in someone's hands, and on a
 * 75-inch 4K board on the wall. Those are not the same screen, but the layout
 * used to treat them as if they were: a fixed three-column grid gave the middle
 * column about 250 px on an iPad, so the readings wrapped into a narrow ribbon
 * while the empty side columns kept their width. The tier below is what the
 * layout keys off (through Tailwind's tier variants) so the phone, the tablet
 * and the wall board can each arrange themselves instead of sharing one grid.
 *
 * Height needs its own treatment. On iPad Safari, 100vh includes the area under
 * the toolbars, so a panel sized with it puts its bottom edge somewhere behind
 * the browser chrome. --app-h carries the height the viewer can actually see
 * and `.h-app` uses it, which is why this module publishes both dimensions as
 * custom properties rather than only setting a zoom.
 *
 * Scale is automatic by default: the design is 1920x1080, and a screen is only
 * scaled up when both sides are at least 20% larger. A 3840x2160 board that
 * reports its full resolution is therefore laid out like 1920x1080 and then
 * zoomed to twice the size, rather than being given a canvas four times as
 * wide and type too small to read from across the room. `?scale=1.25` in the
 * URL (for example `?scale=1.25&idle=0`) overrides that for a screen viewed
 * from far away, including one that is not physically large.
 */
export type Tier = 'phone' | 'tablet' | 'wide'

export interface DisplayProfile {
  /** CSS pixels per design pixel; 1 leaves the layout at its natural size. */
  scale: number
  tier: Tier
  /** Effective CSS pixels after scale, not the raw viewport size. */
  width: number
  height: number
}

export const DESIGN_WIDTH = 1920
export const DESIGN_HEIGHT = 1080

/** The scale the URL asks for, or null when it names nothing usable. */
export function scaleFromUrl(search: string): number | null {
  try {
    const raw = new URLSearchParams(search).get('scale')
    // `?scale=` and `?scale` both mean "not given", not "zero".
    if (raw === null || raw.trim() === '') return null
    const scale = Number(raw)
    return Number.isFinite(scale) && scale >= 0.5 && scale <= 3 ? scale : null
  } catch {
    // A malformed query string must not stop the dashboard from drawing.
    return null
  }
}

/**
 * The profile for a viewport. Bad measurements fall back to the design size so
 * a stray 0 from a hidden window never divides by zero or produces NaN.
 */
export function computeProfile(
  viewportW: number,
  viewportH: number,
  requestedScale: number | null,
): DisplayProfile {
  const W = Number.isFinite(viewportW) && viewportW > 0 ? viewportW : DESIGN_WIDTH
  const H = Number.isFinite(viewportH) && viewportH > 0 ? viewportH : DESIGN_HEIGHT

  let scale: number
  if (typeof requestedScale === 'number' && Number.isFinite(requestedScale) && requestedScale > 0) {
    scale = requestedScale
  } else {
    // Only grow when both sides are comfortably larger than the design. On a
    // screen that is merely a bit bigger, leaving the layout at 1 keeps the
    // text at its designed physical size instead of shrinking it.
    const s = Math.min(W / DESIGN_WIDTH, H / DESIGN_HEIGHT)
    scale = s >= 1.2 ? Math.round(s * 20) / 20 : 1
  }

  const width = W / scale
  const height = H / scale
  const tier: Tier =
    width >= 1280 && height >= 700
      ? 'wide'
      : width >= 720 && height >= 500
        ? 'tablet'
        : 'phone'

  return { scale, tier, width, height }
}

/**
 * Apply the profile to <html> and keep it current as the window changes.
 * `style.zoom` does the growing, the `data-tier` attribute lets Tailwind pick
 * a layout, and the custom properties give CSS the visible size. Returns a
 * cleanup function for React StrictMode's mount/unmount/mount cycle.
 */
export function installDisplayProfile(): () => void {
  let frame: number | null = null

  const apply = () => {
    frame = null
    const profile = computeProfile(
      window.innerWidth,
      window.innerHeight,
      scaleFromUrl(window.location.search),
    )

    try {
      const root = document.documentElement
      // The tier and the custom properties are the essential part: put them
      // down first so a browser that rejects `zoom` still gets them.
      root.dataset.tier = profile.tier
      root.style.setProperty('--app-h', `${profile.height}px`)
      root.style.setProperty('--app-w', `${profile.width}px`)
      try {
        root.style.zoom = profile.scale === 1 ? '' : String(profile.scale)
      } catch {
        // No zoom support: the unscaled layout still has its tier.
      }
    } catch {
      // No document to style (for example a test environment): give up quietly.
    }
  }

  // resize, orientationchange and visualViewport resize can all fire in the
  // same frame (iPad Safari does this while its toolbars settle), so coalesce
  // them into one apply per frame instead of recomputing and touching the DOM
  // three times.
  const schedule = () => {
    if (frame !== null) return
    frame = requestAnimationFrame(apply)
  }

  apply()

  window.addEventListener('resize', schedule)
  window.addEventListener('orientationchange', schedule)

  let viewport: VisualViewport | null = null
  try {
    viewport = window.visualViewport
  } catch {
    viewport = null
  }
  viewport?.addEventListener('resize', schedule)

  return () => {
    window.removeEventListener('resize', schedule)
    window.removeEventListener('orientationchange', schedule)
    viewport?.removeEventListener('resize', schedule)
    if (frame !== null) {
      cancelAnimationFrame(frame)
      frame = null
    }
  }
}
