/**
 * OrganismMap — the body, drawn from its own declaration, running live.
 *
 * One level up from LaminaMap. That map draws what happens INSIDE a lamina:
 * inputs, functions, outcomes, tags, and the return path X'' takes. This one
 * draws what happens between laminae, which is a different and much smaller
 * question — a lamina is a box here, because from the body's point of view
 * that is all it is. What the body adds is the seams.
 *
 * A seam is a VALVE, not a wire, and the whole point of drawing it is that a
 * valve has a state. Three of them:
 *
 *   open   something is crossing right now
 *   held   nothing is crossing, and the far side is still holding the last
 *          value that did — labelled with how many cycles ago
 *   shut   nothing is crossing and nothing ever has
 *
 * The middle one is why this is worth drawing at all. A held value and a live
 * one are the same number on screen, and this project has already shipped that
 * bug once: CO_ref sat at 8.73 calling itself current while the circulation had
 * gone back to 4.84. The backend now says which it is; a diagram that drew both
 * as a glowing line would put the lie back.
 *
 * Every box, every edge and every label is read out of `GET /api/organism` and
 * the gate entries on the socket. Nothing is positioned by hand and no lamina,
 * attribute or gate is named in this file, so a body of four laminae and six
 * seams draws itself here on first load.
 */
import { useMemo, useState } from 'react'
import { fmtValue } from '../../twin/schema'
import { gateDisplayState, gateSummary } from '../../twin/organism'
import type {
  GateDisplayState,
  GateState,
  OrganismSchema,
} from '../../twin/organism'
import type { LaminaTick } from '../../hooks/useOrganismStream'

interface Props {
  /** The declaration — what this body is made of. */
  schema: OrganismSchema
  /** Live gate state, in declaration order. Empty before the first tick. */
  gates: GateState[]
  /** Live per-lamina headline, by lamina id. */
  laminae: Record<string, LaminaTick>
  /** True once the body-level breaker has shut every gate. */
  gatesLocked?: boolean
}

// ── Layout ───────────────────────────────────────────────────────────────────
//
// Laminae are laid out left to right in declaration order, and a gate is an
// edge between two of them. Nothing here knows how many there are.

const BOX_W = 250
const BOX_H = 132
const GAP_X = 210
const PAD = 28
/** Vertical separation between two gates joining the same pair of laminae. */
const LANE_H = 46

const STATE_TONE: Record<GateDisplayState, {
  stroke: string
  label: string
  dash?: string
  width: number
  glow?: string
}> = {
  open: { stroke: '#00e3fd', label: '#bdf4ff', width: 2.4, glow: 'rgba(0,227,253,0.35)' },
  held: { stroke: '#f0a13c', label: '#ffd8a8', width: 1.6, dash: '7 4' },
  shut: { stroke: 'rgba(216,227,251,0.22)', label: 'rgba(216,227,251,0.45)', width: 1.2, dash: '2 5' },
}

interface Placed {
  id: string
  name: string
  x: number
  y: number
  inbound: string[]
}

interface Drawn {
  gate: GateState | null
  spec: OrganismSchema['gates'][number]
  path: string
  midX: number
  midY: number
  state: GateDisplayState
}

/**
 * Where each lamina sits, and the path each gate takes between two of them.
 *
 * A gate running right-to-left (a lamina sending back to one declared before
 * it) is routed under the boxes rather than through them. That case does not
 * arise on the body that ships, and leaving it to overlap would mean the first
 * organism that declares a return seam draws a line through a box and looks
 * broken rather than looking like a return seam.
 */
function layout(schema: OrganismSchema, gates: GateState[]) {
  const placed: Placed[] = schema.laminae.map((lamina, i) => ({
    id: lamina.id,
    name: lamina.name || lamina.id,
    x: PAD + i * (BOX_W + GAP_X),
    y: PAD,
    inbound: lamina.inbound,
  }))
  const at = new Map(placed.map((p) => [p.id, p]))
  const byId = new Map(gates.map((g) => [g.id, g]))

  // How many gates already join this same pair, so the second one is drawn on
  // its own lane instead of on top of the first.
  const lanes = new Map<string, number>()

  const drawn: Drawn[] = schema.gates.map((spec) => {
    const from = at.get(spec.from_lamina)
    const to = at.get(spec.to_lamina)
    const live = byId.get(spec.id) ?? null
    const pairKey = [spec.from_lamina, spec.to_lamina].sort().join('>')
    const lane = lanes.get(pairKey) ?? 0
    lanes.set(pairKey, lane + 1)

    if (!from || !to) {
      return { gate: live, spec, path: '', midX: 0, midY: 0, state: 'shut' as const }
    }

    const forward = from.x < to.x
    const y = from.y + BOX_H / 2 + lane * LANE_H
    const x1 = forward ? from.x + BOX_W : from.x
    const x2 = forward ? to.x : to.x + BOX_W

    let path: string
    let midX: number
    let midY: number
    if (forward) {
      midX = (x1 + x2) / 2
      midY = y
      path = `M ${x1} ${y} C ${x1 + 50} ${y}, ${x2 - 50} ${y}, ${x2} ${y}`
    } else {
      // Route beneath, so a return seam never crosses a box.
      const drop = from.y + BOX_H + 46 + lane * LANE_H
      midX = (x1 + x2) / 2
      midY = drop
      path =
        `M ${x1} ${y} C ${x1 - 60} ${y}, ${x1 - 60} ${drop}, ${midX} ${drop} ` +
        `C ${x2 + 60} ${drop}, ${x2 + 60} ${y}, ${x2} ${y}`
    }
    return {
      gate: live,
      spec,
      path,
      midX,
      midY,
      state: live ? gateDisplayState(live) : 'shut',
    }
  })

  // Height comes from what is actually drawn, not from a guess with room
  // to spare. A fixed reserve looks fine on the body that prompted it and
  // leaves a band of empty canvas on every other one — and because the svg
  // scales to its container by viewBox, that band is stretched along with
  // everything else rather than staying the size it was reserved at.
  const lowest = drawn.reduce(
    (deepest, d) => Math.max(deepest, d.path ? d.midY + 34 : 0),
    PAD + BOX_H
  )
  return {
    placed,
    drawn,
    width: PAD * 2 + placed.length * BOX_W + Math.max(0, placed.length - 1) * GAP_X,
    height: lowest + PAD,
  }
}

// ── Component ────────────────────────────────────────────────────────────────

export function OrganismMap({ schema, gates, laminae, gatesLocked = false }: Props) {
  const [hover, setHover] = useState<string | null>(null)
  const { placed, drawn, width, height } = useMemo(
    () => layout(schema, gates),
    [schema, gates]
  )
  const selected = drawn.find((d) => d.spec.id === hover) ?? null

  return (
    <div className="w-full">
      <div className="overflow-auto">
        <svg
          width="100%"
          // Never upscale past the size the layout actually asked for. A
          // two-box diagram stretched across a wide panel turns a caption
          // into a headline and makes the seam look like the subject of the
          // page rather than a valve on it.
          style={{ maxWidth: width, display: 'block', margin: '0 auto' }}
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={
            `${schema.name || schema.organism_id}: ${schema.laminae.length} laminae ` +
            `joined by ${schema.gates.length} permeability gate` +
            `${schema.gates.length === 1 ? '' : 's'}`
          }
        >
          <defs>
            <marker
              id="organism-arrow"
              viewBox="0 0 8 8"
              refX="7"
              refY="4"
              markerWidth="6"
              markerHeight="6"
              orient="auto-start-reverse"
            >
              <path d="M0,1 L7,4 L0,7 z" fill="currentColor" />
            </marker>
          </defs>

          {/* Seams first, so a box always sits on top of the line into it. */}
          {drawn.map((d) => {
            const tone = STATE_TONE[d.state]
            const faded = hover !== null && hover !== d.spec.id
            const label = d.gate
              ? `${d.spec.extract} ${fmtValue(d.gate.last_value ?? undefined)}`
              : d.spec.extract
            return (
              <g
                key={d.spec.id}
                opacity={faded ? 0.25 : 1}
                onMouseEnter={() => setHover(d.spec.id)}
                onMouseLeave={() => setHover(null)}
                style={{ transition: 'opacity 180ms ease' }}
              >
                {/* Fat transparent path so the edge is hoverable at all. */}
                <path d={d.path} fill="none" stroke="transparent" strokeWidth={18} />
                {d.state === 'open' && (
                  <path
                    d={d.path}
                    fill="none"
                    stroke={tone.glow}
                    strokeWidth={tone.width + 5}
                    strokeLinecap="round"
                  />
                )}
                <path
                  d={d.path}
                  fill="none"
                  stroke={tone.stroke}
                  strokeWidth={tone.width}
                  strokeDasharray={tone.dash}
                  markerEnd="url(#organism-arrow)"
                  color={tone.stroke}
                />

                {/* The valve itself: a filled wedge showing how open it is. */}
                <g transform={`translate(${d.midX} ${d.midY})`}>
                  <circle
                    r={13}
                    fill="#0b1728"
                    stroke={tone.stroke}
                    strokeWidth={1.4}
                  />
                  <rect
                    x={-7}
                    y={7 - 14 * (d.gate?.open_fraction ?? 0)}
                    width={14}
                    height={14 * (d.gate?.open_fraction ?? 0)}
                    fill={tone.stroke}
                    opacity={0.75}
                  />
                  <text
                    y={-20}
                    textAnchor="middle"
                    fontSize={11}
                    fontFamily="JetBrains Mono, monospace"
                    fill={tone.label}
                  >
                    {label}
                  </text>
                  <text
                    y={32}
                    textAnchor="middle"
                    fontSize={9.5}
                    fontFamily="JetBrains Mono, monospace"
                    fill={tone.label}
                    opacity={0.75}
                  >
                    {d.state === 'held'
                      ? `held ${d.gate?.provenance.age ?? 0}c`
                      : d.state}
                  </text>
                </g>
              </g>
            )
          })}

          {/* Laminae. */}
          {placed.map((lamina) => {
            const live = laminae[lamina.id]
            const touched = drawn.some(
              (d) =>
                d.spec.id === hover &&
                (d.spec.from_lamina === lamina.id || d.spec.to_lamina === lamina.id)
            )
            return (
              <g key={lamina.id} transform={`translate(${lamina.x} ${lamina.y})`}>
                <rect
                  width={BOX_W}
                  height={BOX_H}
                  rx={12}
                  fill="#111c2d"
                  stroke={touched ? 'rgba(0,227,253,0.55)' : 'rgba(216,227,251,0.22)'}
                  strokeWidth={touched ? 1.8 : 1}
                  style={{ transition: 'stroke 180ms ease' }}
                />
                <text
                  x={16}
                  y={26}
                  fontSize={10}
                  fontFamily="JetBrains Mono, monospace"
                  fill="rgba(189,244,255,0.55)"
                >
                  {lamina.id}
                </text>
                <text
                  x={16}
                  y={50}
                  fontSize={17}
                  fontFamily="Sora, sans-serif"
                  fontWeight={600}
                  fill="#d8e3fb"
                >
                  {lamina.name}
                </text>
                <text
                  x={16}
                  y={76}
                  fontSize={11}
                  fontFamily="JetBrains Mono, monospace"
                  fill="rgba(216,227,251,0.5)"
                >
                  {`cycle ${live?.cycle ?? 0}`}
                </text>
                <text
                  x={16}
                  y={95}
                  fontSize={11}
                  fontFamily="JetBrains Mono, monospace"
                  fill="rgba(216,227,251,0.5)"
                >
                  {`|X''| ${fmtValue(live?.feedbackNorm)}`}
                </text>
                {/* What this lamina cannot answer for itself. Drawn on the box
                    because it is the reason the seam exists: a lamina with an
                    inbound attribute has declared a hole in its own model. */}
                {lamina.inbound.length > 0 && (
                  <text
                    x={16}
                    y={116}
                    fontSize={10.5}
                    fontFamily="JetBrains Mono, monospace"
                    fill="rgba(240,161,60,0.85)"
                  >
                    {`inbound: ${lamina.inbound.join(', ')}`}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* The caption, and the legend that makes the three line styles readable.
          A diagram whose states are only distinguishable by colour is a
          diagram that says nothing to a reader who does not already know the
          convention. */}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px]">
        {(['open', 'held', 'shut'] as GateDisplayState[]).map((state) => (
          <span key={state} className="flex items-center gap-2" style={{ color: STATE_TONE[state].label }}>
            <svg width={26} height={8} aria-hidden="true">
              <line
                x1={0}
                y1={4}
                x2={26}
                y2={4}
                stroke={STATE_TONE[state].stroke}
                strokeWidth={STATE_TONE[state].width}
                strokeDasharray={STATE_TONE[state].dash}
              />
            </svg>
            {state === 'held' ? 'held (shut, value still there)' : state}
          </span>
        ))}
        {gatesLocked && (
          <span className="text-danger">
            body breaker tripped — every gate shut until reset
          </span>
        )}
      </div>

      <p className="mt-3 min-h-[2.5rem] text-[13px] leading-snug text-ink/70">
        {selected && selected.gate ? (
          <>
            <span className="font-mono text-oxy">{selected.spec.id}</span>{' '}
            <span className="font-mono text-ink/50">
              {selected.spec.from} → {selected.spec.to}
            </span>{' '}
            — {gateSummary(selected.gate)}.{' '}
            <span className="text-ink/45">
              {selected.spec.controller} controller, {selected.spec.transfer.mode}{' '}
              transfer at rate {selected.spec.transfer.rate}
              {selected.spec.transfer.time_delay > 0
                ? `, delayed ${selected.spec.transfer.time_delay} cycles`
                : ''}
              .
            </span>
          </>
        ) : (
          <span className="text-ink/45">
            {schema.gates.length} seam{schema.gates.length === 1 ? '' : 's'} between{' '}
            {schema.laminae.length} laminae. Hover one to read what it is doing.
            A gate is shut until its controller opens it — closed is the resting
            state, not a failure.
          </span>
        )}
      </p>
    </div>
  )
}
