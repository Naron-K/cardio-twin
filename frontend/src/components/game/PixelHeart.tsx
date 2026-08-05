/**
 * PixelHeart — the 16-bit sprite at the centre of the 2D game stage.
 *
 * Everything that moves is driven from a single rAF loop writing straight to
 * SVG attributes; React never re-renders per frame.  What the animation is
 * actually bound to:
 *
 *   • beat timing        ← live HR (via the shared beatClock)
 *   • chamber squeeze    ← cardiac phase (atrial kick, then ventricular systole)
 *   • ejection particles ← CO (faster flow at higher cardiac output)
 *   • stroke distension  ← SV (bigger stroke volume → aorta bulges more)
 *   • alert bloom        ← caller's `alert` flag (out-of-band vitals)
 */
import { useEffect, useMemo, useRef } from 'react'
import {
  buildHeartPixels,
  CHAMBER_RAMP,
  SPRITE_W,
  SPRITE_H,
  ATRIA,
  VENTRICLES,
  VESSELS,
} from '../../game/heartSprite'
import type { Chamber } from '../../game/heartSprite'
import { beatClock, bump, SYSTOLE, ATRIAL_SYSTOLE } from '../../game/beatClock'

interface Props {
  hr: number
  co: number
  sv: number
  /** Vitals outside the safe band — sprite gets a breathing crimson bloom. */
  alert?: boolean
  paused?: boolean
  /** Dim every chamber except this one (legend hover). */
  focus?: Chamber | null
}

// Ejection streams: [x of the 1px column, upward travel start/end, colour].
const STREAMS: { chamber: Chamber; x: number; from: number; to: number; color: string }[] = [
  { chamber: 'AO', x: 10, from: 4, to: -2.5, color: '#ff9aa2' },
  { chamber: 'PA', x: 7, from: 4, to: -2.5, color: '#6fdcf5' },
]
const PARTICLES_PER_STREAM = 3

export function PixelHeart({ hr, co, sv, alert = false, paused = false, focus = null }: Props) {
  const { pixels, geometry } = useMemo(() => buildHeartPixels(), [])

  const rootRef = useRef<SVGGElement | null>(null)
  const bloomRef = useRef<SVGGElement | null>(null)
  const chamberRefs = useRef<Partial<Record<Chamber, SVGGElement | null>>>({})
  const particleRefs = useRef<(SVGRectElement | null)[]>([])

  // Live inputs the rAF loop reads without re-subscribing every render.
  const live = useRef({ co, sv, alert })
  useEffect(() => {
    live.current = { co, sv, alert }
  }, [co, sv, alert])

  useEffect(() => {
    beatClock.setHr(hr)
  }, [hr])

  useEffect(() => {
    beatClock.setPaused(paused)
  }, [paused])

  useEffect(() => {
    const release = beatClock.acquire()
    let raf = 0
    let flow = 0
    let last = performance.now()

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now

      const phase = beatClock.phase
      const vent = bump(phase, SYSTOLE)
      const atr = bump(phase, ATRIAL_SYSTOLE)
      const { co: coNow, sv: svNow } = live.current

      // ── Chambers ────────────────────────────────────────────────────────
      // Ventricles squeeze; atria fill while the ventricles eject, then kick.
      for (const c of VENTRICLES) {
        setScale(chamberRefs.current[c], geometry[c].cx, geometry[c].cy, 1 - 0.085 * vent)
      }
      for (const c of ATRIA) {
        setScale(chamberRefs.current[c], geometry[c].cx, geometry[c].cy, 1 + 0.035 * vent - 0.09 * atr)
      }
      // Great vessels distend on ejection, scaled by stroke volume (70 mL ≈ 1×).
      const svGain = clamp(svNow / 70, 0.5, 1.6)
      for (const c of VESSELS) {
        const g = geometry[c]
        setScale(chamberRefs.current[c], g.cx, g.maxY + 1, 1 + 0.13 * vent * svGain)
      }

      // ── Whole sprite: a small lub-dub bounce ────────────────────────────
      if (rootRef.current) {
        const s = 1 + 0.025 * vent
        const cx = SPRITE_W / 2
        const cy = SPRITE_H / 2
        rootRef.current.setAttribute(
          'transform',
          `translate(${cx} ${cy - 0.18 * vent}) scale(${s.toFixed(4)}) translate(${-cx} ${-cy})`
        )
      }
      if (bloomRef.current) {
        const base = live.current.alert ? 0.4 : 0.22
        bloomRef.current.setAttribute('opacity', (base + 0.45 * vent).toFixed(3))
      }

      // ── Ejection particles ──────────────────────────────────────────────
      // Flow rate tracks cardiac output: 5 L/min ≈ one particle-cycle per 0.95 s.
      flow = (flow + dt * (0.28 + clamp(coNow, 0, 12) * 0.14)) % 1
      let i = 0
      for (const stream of STREAMS) {
        for (let p = 0; p < PARTICLES_PER_STREAM; p++) {
          const el = particleRefs.current[i++]
          if (!el) continue
          const u = (flow + p / PARTICLES_PER_STREAM) % 1
          el.setAttribute('y', (stream.from + (stream.to - stream.from) * u).toFixed(3))
          // Fade out at the far end, and only really show during ejection —
          // at full brightness the particles read as chimneys above the heart.
          el.setAttribute('opacity', (Math.min(1, (1 - u) * 2.2) * 0.85 * vent).toFixed(3))
        }
      }

      raf = requestAnimationFrame(frame)
    }

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      release()
    }
  }, [geometry])

  // Group pixels by chamber once — one <g> per chamber is what makes
  // independent contraction possible.
  const byChamber = useMemo(() => {
    const map = new Map<Chamber, typeof pixels>()
    for (const px of pixels) {
      const list = map.get(px.chamber)
      if (list) list.push(px)
      else map.set(px.chamber, [px])
    }
    return [...map.entries()]
  }, [pixels])

  // ~250 <rect>s: memoised so the 10 Hz stream re-render doesn't re-diff the
  // whole sprite.  Only a legend hover (focus) rebuilds it.
  const body = useMemo(
    () =>
      byChamber.map(([chamber, list]) => {
        const ramp = CHAMBER_RAMP[chamber]
        const dim = focus !== null && focus !== chamber
        return (
          <g
            key={chamber}
            ref={(el) => {
              chamberRefs.current[chamber] = el
            }}
            opacity={dim ? 0.28 : 1}
            style={{ transition: 'opacity 180ms ease' }}
          >
            {list.map((px) => (
              <rect
                key={`${px.x}-${px.y}`}
                x={px.x}
                y={px.y}
                width={1}
                height={1}
                fill={ramp[px.tone]}
              />
            ))}
          </g>
        )
      }),
    [byChamber, focus]
  )

  return (
    <svg
      viewBox={`-4 -4 ${SPRITE_W + 8} ${SPRITE_H + 8}`}
      className="w-full h-full overflow-visible"
      role="img"
      aria-label="Pixel heart model beating at the simulated heart rate"
    >
      <defs>
        <filter id="ph-bloom" x="-60%" y="-60%" width="220%" height="220%">
          <feGaussianBlur stdDeviation="1.1" />
        </filter>
      </defs>

      <g ref={rootRef}>
        {/* Bloom — a blurred copy of the body underneath, pulsing with systole.
            Lives inside the root group so it bounces with the sprite. */}
        <g ref={bloomRef} filter="url(#ph-bloom)" opacity="0.22">
          <use href="#ph-body" />
        </g>

        <g id="ph-body" shapeRendering="crispEdges">
          {body}
        </g>

        {/* Ejection particles ride on top of the vessels. */}
        <g shapeRendering="crispEdges">
          {STREAMS.flatMap((stream, s) =>
            Array.from({ length: PARTICLES_PER_STREAM }, (_, p) => (
              <rect
                key={`${stream.chamber}-${p}`}
                ref={(el) => {
                  particleRefs.current[s * PARTICLES_PER_STREAM + p] = el
                }}
                x={stream.x}
                y={stream.from}
                width={1}
                height={1}
                fill={stream.color}
                opacity={0}
              />
            ))
          )}
        </g>
      </g>
    </svg>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

function setScale(el: SVGGElement | null | undefined, px: number, py: number, s: number) {
  if (!el) return
  el.setAttribute(
    'transform',
    `translate(${px} ${py}) scale(${s.toFixed(4)}) translate(${-px} ${-py})`
  )
}

function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v
}
