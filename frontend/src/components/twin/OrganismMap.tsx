/**
 * OrganismMap — the body, drawn from its own declaration, running live.
 *
 * One level up from LaminaMap. That map draws what happens INSIDE a lamina:
 * inputs, functions, outcomes, tags, and the return path X'' takes. This one
 * draws what happens between laminae, which is a different and much smaller
 * question — a lamina is a box here, because from the body's point of view
 * that is all it is. What the body adds is the seams.
 *
 * ── Why this looks different from the version before it ─────────────────────
 *
 * A seam used to be one valve in the middle of a wire. It is now a CHANNEL
 * with a gate on each membrane, and three things follow for a diagram:
 *
 *   1. The stack is vertical. Laminae are placed by their declared `level`,
 *      higher level higher on screen, because "the layer above" and "the
 *      layer below" are the words the rules are written in and a left-to-right
 *      row makes them meaningless.
 *
 *   2. An edge carries TWO valves, one at each end, because two laminae are
 *      each deciding. A value crosses only when both are open, and a reader
 *      has to be able to see which end is refusing.
 *
 *   3. An AUTO gate and a KEY gate get different glyphs. They are different
 *      things: an auto gate reads its own lamina and is a protection layer
 *      nobody may switch off; a key gate reads what arrives. Drawing them
 *      alike would leave a reader unable to tell a safety interlock from a
 *      policy.
 *
 * And one new state. `waiting` means the sender has put something on the wire
 * and the receiver has not taken it — which is NOT `held`, where the receiver
 * took something a while ago and it is going stale. This project has already
 * shipped the failure of drawing a stale number as a live one once; drawing
 * "outside the door" and "in the house since Tuesday" in one colour would be
 * the same mistake with a new name.
 *
 * Every box, every edge and every label is read out of `GET /api/organism` and
 * the channel entries on the socket. Nothing is positioned by hand and no
 * lamina, attribute or gate is named in this file, so a body of four laminae
 * and six seams draws itself here on first load.
 */
import { useMemo, useState } from 'react'
import { fmtValue } from '../../twin/schema'
import { channelDisplayState, channelSummary } from '../../twin/organism'
import type {
  ChannelDisplayState,
  ChannelState,
  GateState,
  OrganismSchema,
} from '../../twin/organism'
import type { LaminaTick } from '../../hooks/useOrganismStream'

interface Props {
  /** The declaration — what this body is made of. */
  schema: OrganismSchema
  /** Live channel state, in declaration order. Empty before the first tick. */
  channels: ChannelState[]
  /** Live per-lamina headline, by lamina id. */
  laminae: Record<string, LaminaTick>
  /** What the container reported each channel is doing, by channel id. */
  channelStates?: Record<string, string>
  /** True once the body-level breaker has shut every gate. */
  gatesLocked?: boolean
}

// ── Layout ───────────────────────────────────────────────────────────────────
//
// Laminae are stacked by level; a channel is an edge between two adjacent
// rows. Nothing here knows how many there are.

const BOX_W = 300
const BOX_H = 116
const GAP_Y = 132
const PAD = 28
/** Horizontal separation between two channels joining the same pair. */
const LANE_X = 118
/** How far from a box a valve sits — on the membrane, not in mid-air. */
const VALVE_INSET = 30

const STATE_TONE: Record<ChannelDisplayState, {
  stroke: string
  label: string
  dash?: string
  width: number
  glow?: string
}> = {
  crossing: { stroke: '#00e3fd', label: '#bdf4ff', width: 2.4, glow: 'rgba(0,227,253,0.35)' },
  waiting:  { stroke: '#a78bfa', label: '#d9ccff', width: 2.0, dash: '1 6', glow: 'rgba(167,139,250,0.28)' },
  held:     { stroke: '#f0a13c', label: '#ffd8a8', width: 1.6, dash: '7 4' },
  decaying: { stroke: '#f0a13c', label: '#ffd8a8', width: 1.3, dash: '3 6' },
  shut:     { stroke: 'rgba(216,227,251,0.22)', label: 'rgba(216,227,251,0.45)', width: 1.2, dash: '2 5' },
}

const LEGEND: { state: ChannelDisplayState; caption: string }[] = [
  { state: 'crossing', caption: 'crossing' },
  { state: 'waiting', caption: 'waiting (offered, not taken)' },
  { state: 'held', caption: 'held (shut, value still there)' },
  { state: 'shut', caption: 'shut' },
]

interface Placed {
  id: string
  name: string
  level: number
  x: number
  y: number
  inbound: string[]
}

interface Drawn {
  channel: ChannelState | null
  spec: OrganismSchema['channels'][number]
  path: string
  /** Where each end's valves sit — sender's first. */
  txAt: { x: number; y: number }
  rxAt: { x: number; y: number }
  midX: number
  midY: number
  state: ChannelDisplayState
}

/**
 * Where each lamina sits, and the path each channel takes between two of them.
 *
 * Rows come from the declared levels rather than from declaration order, and
 * a level with two laminae in it spreads them across the row. Nothing on the
 * body that ships exercises that, but a stack is a stack and the first body
 * that puts two systems at one height should not draw them on top of each
 * other.
 */
function layout(
  schema: OrganismSchema,
  channels: ChannelState[],
  reported: Record<string, string>,
) {
  const levels = schema.levels ?? {}
  const rows = [...new Set(schema.laminae.map((l) => levels[l.id] ?? 0))]
    .sort((a, b) => b - a)              // highest level at the top

  const placed: Placed[] = []
  rows.forEach((level, rowIndex) => {
    const inRow = schema.laminae.filter((l) => (levels[l.id] ?? 0) === level)
    inRow.forEach((lamina, columnIndex) => {
      placed.push({
        id: lamina.id,
        name: lamina.name || lamina.id,
        level,
        x: PAD + columnIndex * (BOX_W + 60),
        y: PAD + rowIndex * (BOX_H + GAP_Y),
        inbound: lamina.inbound,
      })
    })
  })

  const at = new Map(placed.map((p) => [p.id, p]))
  const byId = new Map(channels.map((c) => [c.id, c]))
  // How many channels already join this same pair, so the second one is drawn
  // on its own lane instead of on top of the first.
  const lanes = new Map<string, number>()

  const drawn: Drawn[] = schema.channels.map((spec) => {
    const from = at.get(spec.from_lamina)
    const to = at.get(spec.to_lamina)
    const live = byId.get(spec.id) ?? null
    const empty = { x: 0, y: 0 }
    if (!from || !to) {
      return {
        channel: live, spec, path: '', txAt: empty, rxAt: empty,
        midX: 0, midY: 0, state: 'shut' as const,
      }
    }

    const pairKey = [spec.from_lamina, spec.to_lamina].sort().join('>')
    const lane = lanes.get(pairKey) ?? 0
    lanes.set(pairKey, lane + 1)

    // Sending edge of the source box, receiving edge of the destination.
    const fromBottom = from.y < to.y
    const x = from.x + BOX_W / 2 + (lane - 0.5) * LANE_X * (lanes.size > 1 ? 1 : 0)
    const y1 = fromBottom ? from.y + BOX_H : from.y
    const y2 = fromBottom ? to.y : to.y + BOX_H

    const path = `M ${x} ${y1} L ${x} ${y2}`
    const step = fromBottom ? VALVE_INSET : -VALVE_INSET
    return {
      channel: live,
      spec,
      path,
      txAt: { x, y: y1 + step },
      rxAt: { x, y: y2 - step },
      midX: x,
      midY: (y1 + y2) / 2,
      state: live
        ? channelDisplayState(live, reported[spec.id])
        : ('shut' as const),
    }
  })

  const widest = placed.reduce((w, p) => Math.max(w, p.x + BOX_W), 0)
  const lowest = placed.reduce((h, p) => Math.max(h, p.y + BOX_H), 0)
  return { placed, drawn, width: widest + PAD, height: lowest + PAD }
}

/**
 * One valve, drawn as the kind of thing it is.
 *
 * An auto gate is a triangle: a relief valve, and the shape reads as one.
 * A key gate is a circle with a keyway cut into it. The fill height inside
 * each is how open it is, so a half-open gate looks half open rather than
 * needing its number read.
 */
function Valve({ gate, tone }: { gate: GateState | undefined; tone: string }) {
  const open = gate?.open_fraction ?? 0
  const flooding = Boolean(gate?.state?.flood)
  if (!gate) return null
  if (gate.kind === 'auto') {
    return (
      <g>
        <path
          d="M 0,-11 L 11,8 L -11,8 Z"
          fill="#0b1728"
          stroke={tone}
          strokeWidth={1.4}
        />
        <path
          d="M 0,-11 L 11,8 L -11,8 Z"
          fill={tone}
          opacity={0.28 + 0.5 * open}
        />
        {flooding && <circle r={15} fill="none" stroke={tone} strokeWidth={0.8} opacity={0.6} />}
      </g>
    )
  }
  return (
    <g>
      <circle r={11} fill="#0b1728" stroke={tone} strokeWidth={1.4} />
      <rect
        x={-6}
        y={6 - 12 * open}
        width={12}
        height={12 * open}
        fill={tone}
        opacity={0.7}
      />
      {/* the keyway, so the shape is not just "circle" */}
      <path d="M 0,-5 L 0,4 M -3,4 L 3,4" stroke={tone} strokeWidth={1.3} fill="none" />
    </g>
  )
}

// ── Component ────────────────────────────────────────────────────────────────

export function OrganismMap({
  schema,
  channels,
  laminae,
  channelStates = {},
  gatesLocked = false,
}: Props) {
  const [hover, setHover] = useState<string | null>(null)
  const { placed, drawn, width, height } = useMemo(
    () => layout(schema, channels, channelStates),
    [schema, channels, channelStates]
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
            `stacked by level and joined by ${schema.channels.length} channel` +
            `${schema.channels.length === 1 ? '' : 's'}, each with a gate at both ends`
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
            const label = d.channel
              ? `${d.spec.extract} ${fmtValue(d.channel.last_value ?? undefined)}`
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
                <path d={d.path} fill="none" stroke="transparent" strokeWidth={22} />
                {tone.glow && (
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

                {/* One valve per membrane. The sender's gates sit against the
                    sending box, the receiver's against the receiving one, so
                    which end is refusing is readable at a glance. */}
                <g transform={`translate(${d.txAt.x} ${d.txAt.y})`}>
                  <Valve gate={d.channel?.transmit?.[0]} tone={tone.stroke} />
                </g>
                <g transform={`translate(${d.rxAt.x} ${d.rxAt.y})`}>
                  <Valve gate={d.channel?.receive?.[0]} tone={tone.stroke} />
                </g>

                <text
                  x={d.midX + 16}
                  y={d.midY - 4}
                  fontSize={11}
                  fontFamily="JetBrains Mono, monospace"
                  fill={tone.label}
                >
                  {label}
                </text>
                <text
                  x={d.midX + 16}
                  y={d.midY + 12}
                  fontSize={9.5}
                  fontFamily="JetBrains Mono, monospace"
                  fill={tone.label}
                  opacity={0.75}
                >
                  {d.state === 'held'
                    ? `held ${d.channel?.provenance.age ?? 0}c`
                    : d.state === 'waiting'
                      ? `waiting ${d.channel?.offered_age ?? 0}c`
                      : d.state}
                </text>
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
                {/* Where it stands. The rules are written in "the layer above"
                    and "the layer below", so the number those phrases refer to
                    belongs on the box. */}
                <text
                  x={BOX_W - 16}
                  y={26}
                  textAnchor="end"
                  fontSize={10}
                  fontFamily="JetBrains Mono, monospace"
                  fill="rgba(189,244,255,0.4)"
                >
                  {`level ${lamina.level}`}
                </text>
                <text
                  x={16}
                  y={52}
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
                  {`cycle ${live?.cycle ?? 0}   |X''| ${fmtValue(live?.feedbackNorm)}`}
                </text>
                {/* What this lamina cannot answer for itself. Drawn on the box
                    because it is the reason the seam exists: a lamina with an
                    inbound attribute has declared a hole in its own model. */}
                {lamina.inbound.length > 0 && (
                  <text
                    x={16}
                    y={98}
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

      {/* The caption, and the legend that makes the line styles readable. A
          diagram whose states are only distinguishable by colour is a diagram
          that says nothing to a reader who does not already know the
          convention. */}
      <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 font-mono text-[11px]">
        {LEGEND.map(({ state, caption }) => (
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
            {caption}
          </span>
        ))}
        <span className="flex items-center gap-2 text-ink/55">
          <svg width={16} height={14} aria-hidden="true">
            <path d="M 8,2 L 14,12 L 2,12 Z" fill="none" stroke="currentColor" strokeWidth={1.2} />
          </svg>
          auto (protection)
          <svg width={16} height={14} aria-hidden="true" className="ml-2">
            <circle cx={8} cy={7} r={5.5} fill="none" stroke="currentColor" strokeWidth={1.2} />
          </svg>
          key (policy)
        </span>
        {gatesLocked && (
          <span className="text-danger">
            body breaker tripped — every gate shut until reset
          </span>
        )}
      </div>

      <p className="mt-3 min-h-[2.5rem] text-[13px] leading-snug text-ink/70">
        {selected && selected.channel ? (
          <>
            <span className="font-mono text-oxy">{selected.spec.id}</span>{' '}
            <span className="font-mono text-ink/50">
              {selected.spec.from} → {selected.spec.to}
            </span>{' '}
            — {channelSummary(selected.channel, channelStates[selected.spec.id])}.{' '}
            <span className="text-ink/45">
              Sender:{' '}
              {selected.spec.transmit.map((g) => `${g.id} (${g.kind})`).join(', ')}.
              {' '}Receiver:{' '}
              {selected.spec.receive.map((g) => `${g.id} (${g.kind})`).join(', ')}.
              {selected.spec.time_delay > 0
                ? ` Delayed ${selected.spec.time_delay} cycles.`
                : ''}
            </span>
          </>
        ) : (
          <span className="text-ink/45">
            {schema.channels.length} channel
            {schema.channels.length === 1 ? '' : 's'} between{' '}
            {schema.laminae.length} laminae, each with a gate at both ends.
            Hover one to read what it is doing. A value crosses only when both
            membranes are open — and a gate is shut until its trigger opens it,
            because closed is the resting state and not a failure.
          </span>
        )}
      </p>
    </div>
  )
}
