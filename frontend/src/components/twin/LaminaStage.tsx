/**
 * LaminaStage — draws whatever stage template it is handed.
 *
 * This component knows nothing about hearts.  It reads a template (artwork +
 * placeholders + bindings), looks each animator up in the registry, and writes
 * transforms straight to SVG attributes from one rAF loop; React never
 * re-renders per frame.
 *
 * The `values` it animates from are model outputs only.  Beat timing is the
 * one exception and arrives on its own prop, because the model does not yet
 * emit a rhythm outcome — Schematic mode reports that as a violation rather
 * than letting it pass quietly.
 */
import { useEffect, useMemo, useRef } from 'react'
import { FLOW_ANIMATORS, MOTION_ANIMATORS } from '../../twin/animators'
import type { AnimatorContext } from '../../twin/animators'
import { alongPath, resolveEnvelope } from '../../twin/stageTemplate'
import type { EnvelopeId, LoadedStage } from '../../twin/stageTemplate'
import { beatClock, bump } from '../../twin/beatClock'
import { SchematicOverlay } from './SchematicOverlay'

interface Props {
  stage: LoadedStage
  /**
   * Model-computed attributes only.  This is the component's *entire* data
   * input — beat timing included, via the template's rhythm binding — so there
   * is no route by which a sensor could reach the stage.
   */
  values: Record<string, number>
  /** Attribute id → 'SENSOR' | 'PRELIMINARY', straight from the lamina schema. */
  sources: Record<string, string>
  paused?: boolean
  /** Dim everything except this placeholder (legend hover). */
  focus?: string | null
  mode?: 'showcase' | 'schematic'
}

export function LaminaStage({
  stage,
  values,
  sources,
  paused = false,
  focus = null,
  mode = 'showcase',
}: Props) {
  const { template, assetUrl } = stage
  const { artwork, placeholders, drawOrder } = template

  const rootRef = useRef<SVGGElement | null>(null)
  const groupRefs = useRef<Record<string, SVGGElement | null>>({})
  const particleRefs = useRef<Record<string, (SVGCircleElement | null)[]>>({})

  // Live inputs the rAF loop reads without re-subscribing every render.
  const live = useRef(values)
  useEffect(() => {
    live.current = values
  }, [values])

  // Beat rate comes from the model's cycle-length attribute, not from HR.
  const cycleSeconds = values[template.rhythm.bind]
  useEffect(() => {
    if (cycleSeconds !== undefined) beatClock.setCycle(cycleSeconds)
  }, [cycleSeconds])

  useEffect(() => {
    beatClock.setPaused(paused)
  }, [paused])

  const order = useMemo(
    () => drawOrder.filter((id) => placeholders[id]),
    [drawOrder, placeholders]
  )

  useEffect(() => {
    const release = beatClock.acquire()
    let raf = 0
    let last = performance.now()
    const flow: Record<string, number> = {}

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now

      const phase = beatClock.phase
      // Windows are resolved every frame: their durations are model values in
      // seconds, so the share of the cycle they occupy moves with the rate.
      const cycle = live.current[template.rhythm.bind] ?? beatClock.cycle
      const ctx: AnimatorContext = {
        envelope: (id: EnvelopeId) =>
          bump(phase, resolveEnvelope(template.rhythm.envelopes[id], cycle, live.current)),
        value: (attribute: string) => live.current[attribute],
      }

      for (const id of order) {
        const place = placeholders[id]

        if (place.motion) {
          const animator = MOTION_ANIMATORS[place.motion.animator]
          const el = groupRefs.current[id]
          if (animator && el) {
            const s = animator(place.motion, ctx)
            const { px, py } = place.geometry
            el.setAttribute(
              'transform',
              `translate(${px} ${py}) scale(${s.toFixed(4)}) translate(${-px} ${-py})`
            )
          }
        }

        if (place.flow && place.geometry.path) {
          const animator = FLOW_ANIMATORS[place.flow.animator]
          const list = particleRefs.current[id]
          if (animator && list) {
            flow[id] = ((flow[id] ?? 0) + dt * animator(place.flow, ctx)) % 1
            // Ejection only reads as ejection during systole; at full
            // brightness the particles look like beads parked in the vessel.
            const gate = ctx.envelope('ventricular')
            for (let p = 0; p < list.length; p++) {
              const el = list[p]
              if (!el) continue
              const u = (flow[id] + p / list.length) % 1
              const [x, y] = alongPath(place.geometry.path, u)
              el.setAttribute('cx', x.toFixed(1))
              el.setAttribute('cy', y.toFixed(1))
              el.setAttribute(
                'opacity',
                (Math.min(1, (1 - u) * 2.4) * 0.9 * gate).toFixed(3)
              )
            }
          }
        }
      }

      // Whole organ: a small lub-dub bounce.
      if (rootRef.current) {
        const vent = ctx.envelope('ventricular')
        const s = 1 + 0.018 * vent
        const cx = artwork.width / 2
        const cy = artwork.height / 2
        rootRef.current.setAttribute(
          'transform',
          `translate(${cx} ${cy - 4 * vent}) scale(${s.toFixed(4)}) translate(${-cx} ${-cy})`
        )
      }

      raf = requestAnimationFrame(frame)
    }

    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      release()
    }
  }, [order, placeholders, template, artwork])

  const schematic = mode === 'schematic'

  // The wrapper carries the artwork's aspect ratio so the SVG fills it exactly
  // — the schematic overlay positions its frames in percentages and would drift
  // if the SVG were letterboxed inside a squarer box.
  return (
    <div
      className="relative h-full mx-auto"
      style={{ aspectRatio: `${artwork.width} / ${artwork.height}` }}
    >
    <svg
      viewBox={`0 0 ${artwork.width} ${artwork.height}`}
      className="w-full h-full overflow-visible"
      role="img"
      aria-label={
        schematic
          ? 'Stage schematic: placeholder frames and their model bindings'
          : 'Anatomical heart cross-section beating at the simulated heart rate'
      }
    >
      <g ref={rootRef}>
        <image
          href={assetUrl(artwork.src)}
          x={0}
          y={0}
          width={artwork.width}
          height={artwork.height}
          opacity={schematic ? 0.15 : focus ? 0.35 : 1}
          style={{ transition: 'opacity 220ms ease' }}
        />

        {order.map((id) => {
          const g = placeholders[id].geometry
          return (
            <g
              key={id}
              ref={(el) => {
                groupRefs.current[id] = el
              }}
              opacity={schematic ? 0.2 : focus !== null && focus !== id ? 0.25 : 1}
              style={{ transition: 'opacity 220ms ease' }}
            >
              <image
                href={assetUrl(placeholders[id].asset)}
                x={g.x}
                y={g.y}
                width={g.w}
                height={g.h}
              />
            </g>
          )
        })}

        {!schematic &&
          order.map((id) => {
            const place = placeholders[id]
            if (!place.flow || !place.geometry.path) return null
            return (
              <g key={`flow-${id}`}>
                {Array.from({ length: place.flow.particles }, (_, p) => (
                  <circle
                    key={p}
                    // The list is created here, in the ref callback, rather than
                    // reset during render: refs may not be written while
                    // rendering. React hands each callback null on unmount, and
                    // the frame loop skips nulls, so a shrinking count is safe.
                    ref={(el) => {
                      ;(particleRefs.current[id] ??= [])[p] = el
                    }}
                    r={place.flow!.radius}
                    fill={place.flow!.colour}
                    opacity={0}
                  />
                ))}
              </g>
            )
          })}
      </g>
    </svg>

      {schematic && (
        <SchematicOverlay stage={stage} values={values} sources={sources} focus={focus} />
      )}
    </div>
  )
}
