/**
 * AnatomicalHeart — the illustrated cross-section at the centre of the stage.
 *
 * Same contract and same bindings as PixelHeart, so the two are swappable:
 *
 *   • beat timing        ← live HR (via the shared beatClock)
 *   • chamber squeeze    ← cardiac phase (atrial kick, then ventricular systole)
 *   • ejection particles ← CO (faster flow at higher cardiac output)
 *   • stroke distension  ← SV (bigger stroke volume → great vessels bulge more)
 *   • alert bloom        ← caller's `alert` flag (out-of-band vitals)
 *
 * What differs is the anatomy.  The pink ventricular wall in the source
 * illustration is one continuous mass and cannot be split into an LV wall and
 * an RV wall, so it renders as a *fixed frame* and the four cavities pulse
 * inside it — which is what a real cross-section does anyway: the cavity
 * shrinks and the wall thickens, rather than the whole silhouette scaling.
 * The base image has the cavities painted over in a shadowed wall tone, so a
 * contracting chamber uncovers thickened myocardium, not a hole.
 *
 * Everything that moves is driven from a single rAF loop writing straight to
 * SVG attributes; React never re-renders per frame.
 */
import { useEffect, useRef } from 'react'
import {
  HEART_ASSET,
  HEART_BASE_H,
  HEART_BASE_W,
  HEART_DRAW_ORDER,
  HEART_LAYERS,
  alongPath,
} from '../../game/heartLayers'
import type { Chamber } from '../../game/heartSprite'
import { ATRIA, VENTRICLES, VESSELS } from '../../game/heartSprite'
import { beatClock, bump, SYSTOLE, ATRIAL_SYSTOLE } from '../../game/beatClock'

interface Props {
  hr: number
  co: number
  sv: number
  /** Vitals outside the safe band — the heart gets a breathing crimson bloom. */
  alert?: boolean
  paused?: boolean
  /** Dim everything except this chamber (legend hover). */
  focus?: Chamber | null
}

const STREAMS: { chamber: Chamber; color: string }[] = [
  { chamber: 'AO', color: '#ffd0d4' },
  { chamber: 'PA', color: '#bff0ff' },
]
const PARTICLES_PER_STREAM = 4
/** In base-image pixels — small enough to read as flow rather than as beads. */
const PARTICLE_R = 7

export function AnatomicalHeart({ hr, co, sv, alert = false, paused = false, focus = null }: Props) {
  const rootRef = useRef<SVGGElement | null>(null)
  const bloomRef = useRef<SVGEllipseElement | null>(null)
  const chamberRefs = useRef<Partial<Record<Chamber, SVGGElement | null>>>({})
  const particleRefs = useRef<(SVGCircleElement | null)[]>([])

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

      // ── Cavities ────────────────────────────────────────────────────────
      // Ventricles squeeze; atria fill while the ventricles eject, then kick.
      for (const c of VENTRICLES) setScale(chamberRefs.current[c], c, 1 - 0.09 * vent)
      for (const c of ATRIA) setScale(chamberRefs.current[c], c, 1 + 0.035 * vent - 0.085 * atr)

      // Great vessels distend on ejection, scaled by stroke volume (70 mL ≈ 1×).
      // Kept gentle: these layers sit over their own copy in the base image, so
      // a large scale would let the static edge peek out behind the moving one.
      const svGain = clamp(svNow / 70, 0.5, 1.6)
      for (const c of VESSELS) setScale(chamberRefs.current[c], c, 1 + 0.045 * vent * svGain)

      // ── Whole organ: a small lub-dub bounce ─────────────────────────────
      if (rootRef.current) {
        const s = 1 + 0.018 * vent
        const cx = HEART_BASE_W / 2
        const cy = HEART_BASE_H / 2
        rootRef.current.setAttribute(
          'transform',
          `translate(${cx} ${cy - 4 * vent}) scale(${s.toFixed(4)}) translate(${-cx} ${-cy})`
        )
      }
      if (bloomRef.current) {
        const base = live.current.alert ? 0.5 : 0.2
        bloomRef.current.setAttribute('opacity', (base + 0.35 * vent).toFixed(3))
      }

      // ── Ejection particles ──────────────────────────────────────────────
      // Flow rate tracks cardiac output: 5 L/min ≈ one particle-cycle per 0.95 s.
      flow = (flow + dt * (0.28 + clamp(coNow, 0, 12) * 0.14)) % 1
      let i = 0
      for (const stream of STREAMS) {
        const path = HEART_LAYERS[stream.chamber].path
        for (let p = 0; p < PARTICLES_PER_STREAM; p++) {
          const el = particleRefs.current[i++]
          if (!el || !path) continue
          const u = (flow + p / PARTICLES_PER_STREAM) % 1
          const [x, y] = alongPath(path, u)
          el.setAttribute('cx', x.toFixed(1))
          el.setAttribute('cy', y.toFixed(1))
          // Fade out at the far end, and only really show during ejection —
          // at full brightness they read as beads parked inside the vessels.
          el.setAttribute('opacity', (Math.min(1, (1 - u) * 2.4) * 0.9 * vent).toFixed(3))
        }
      }

      raf = requestAnimationFrame(frame)
    }

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      release()
    }
  }, [])

  return (
    <svg
      viewBox={`0 0 ${HEART_BASE_W} ${HEART_BASE_H}`}
      className="w-full h-full overflow-visible"
      role="img"
      aria-label="Anatomical heart cross-section beating at the simulated heart rate"
    >
      <defs>
        <radialGradient id="ah-bloom">
          <stop offset="0%" stopColor={alert ? '#ff525f' : '#ff8a94'} stopOpacity="0.55" />
          <stop offset="100%" stopColor={alert ? '#ff525f' : '#ff8a94'} stopOpacity="0" />
        </radialGradient>
      </defs>

      {/* Bloom sits outside the bouncing group so it stays a steady halo. */}
      <ellipse
        ref={bloomRef}
        cx={HEART_BASE_W / 2}
        cy={HEART_BASE_H * 0.55}
        rx={HEART_BASE_W * 0.62}
        ry={HEART_BASE_H * 0.52}
        fill="url(#ah-bloom)"
        opacity="0.2"
      />

      <g ref={rootRef}>
        {/* Static frame: myocardium, valves, chordae, vessel walls. */}
        <image
          href={HEART_ASSET.BASE}
          x={0}
          y={0}
          width={HEART_BASE_W}
          height={HEART_BASE_H}
          opacity={focus ? 0.35 : 1}
          style={{ transition: 'opacity 180ms ease' }}
        />

        {HEART_DRAW_ORDER.map((c) => {
          const g = HEART_LAYERS[c]
          return (
            <g
              key={c}
              ref={(el) => {
                chamberRefs.current[c] = el
              }}
              opacity={focus !== null && focus !== c ? 0.25 : 1}
              style={{ transition: 'opacity 180ms ease' }}
            >
              <image href={HEART_ASSET[c]} x={g.x} y={g.y} width={g.w} height={g.h} />
            </g>
          )
        })}

        {/* Ejection particles ride along each vessel's own centreline — the
            aorta rises, the pulmonary artery goes up and then sideways, which
            is how this illustration actually routes it. */}
        <g>
          {STREAMS.flatMap((stream, s) =>
            Array.from({ length: PARTICLES_PER_STREAM }, (_, p) => (
              <circle
                key={`${stream.chamber}-${p}`}
                ref={(el) => {
                  particleRefs.current[s * PARTICLES_PER_STREAM + p] = el
                }}
                r={PARTICLE_R}
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

function setScale(el: SVGGElement | null | undefined, chamber: Chamber, s: number) {
  if (!el) return
  const { px, py } = HEART_LAYERS[chamber]
  el.setAttribute(
    'transform',
    `translate(${px} ${py}) scale(${s.toFixed(4)}) translate(${-px} ${-py})`
  )
}

function clamp(v: number, lo: number, hi: number) {
  return v < lo ? lo : v > hi ? hi : v
}
