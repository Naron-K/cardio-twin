/**
 * LaminaMap — the model, drawn from its own declarations, running live.
 *
 * Every box and every line here was read out of the lamina XML: attributes and
 * where each comes from, the functions that compute them and the formulae they
 * use, the outcomes that judge them, the tags that fire when an outcome drifts,
 * and the composites those tags write their correction into. Nothing is
 * positioned or connected by hand, so a lamina describing something other than
 * a circulation draws itself here on first load.
 *
 * It is the answer to "what is the model actually computing", which is a
 * question no gauge or trace can answer: a number tells you a value, this tells
 * you where the value came from and what it goes on to affect. The forward band
 * reads left to right — inputs, function, computed value, target. The band
 * underneath reads back the other way, and is the part worth looking at: an
 * outcome outside tolerance fires a tag, the tag fans into composites, and the
 * composites are the addresses where X'' lands on attributes that sit back at
 * the start of the chain. That return path is the loop, and it lights up when
 * it carries something.
 *
 * Values shown on a node are the model's; a node the model has no value for
 * shows a dash rather than a zero, because zero is a measurement and a blank is
 * not.
 */
import { useLayoutEffect, useMemo, useRef, useState } from 'react'
import { buildGraph, neighbourhood } from '../../twin/graph'
import type { EdgeKind, GraphNode, NodeKind } from '../../twin/graph'
import { fmtValue } from '../../twin/schema'
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  /** Model-computed attributes. */
  computed: Record<string, number>
  /** Raw inputs — drawn on their own nodes, and nowhere else. */
  sensors: Record<string, number>
  /** Tag ids that fired this cycle, straight from the cycle report. */
  firing: string[]
  /** Outcome id → whether the model says it is inside its tolerance. */
  withinByOutcome: Record<string, boolean>
  /** Whether the map currently has the whole body area rather than the stage. */
  expanded?: boolean
  onToggleExpand?: () => void
}

const NODE_TONE: Record<NodeKind, { stroke: string; fill: string; text: string; dim: string }> = {
  sensor:    { stroke: 'rgba(216,227,251,0.22)', fill: '#0b1728', text: '#d8e3fb', dim: 'rgba(216,227,251,0.4)' },
  function:  { stroke: 'rgba(0,227,253,0.35)',   fill: '#0a1b2a', text: '#bdf4ff', dim: 'rgba(189,244,255,0.5)' },
  computed:  { stroke: 'rgba(0,227,253,0.55)',   fill: '#071a26', text: '#bdf4ff', dim: 'rgba(189,244,255,0.45)' },
  outcome:   { stroke: 'rgba(255,82,95,0.5)',    fill: '#1a0d14', text: '#ffb3b3', dim: 'rgba(255,179,179,0.5)' },
  tag:       { stroke: 'rgba(240,161,60,0.55)',  fill: '#1b1408', text: '#ffd8a8', dim: 'rgba(255,216,168,0.5)' },
  composite: { stroke: 'rgba(216,227,251,0.28)', fill: '#101a2b', text: '#d8e3fb', dim: 'rgba(216,227,251,0.4)' },
}

const EDGE_TONE: Record<EdgeKind, { stroke: string; dash?: string }> = {
  flow:    { stroke: 'rgba(0,227,253,0.35)' },
  judge:   { stroke: 'rgba(255,82,95,0.35)' },
  emit:    { stroke: 'rgba(240,161,60,0.45)', dash: '4 3' },
  fanout:  { stroke: 'rgba(240,161,60,0.45)', dash: '4 3' },
  correct: { stroke: 'rgba(216,227,251,0.16)', dash: '2 4' },
}

const KIND_LABEL: Record<NodeKind, string> = {
  sensor: 'input',
  function: 'function',
  computed: 'computed',
  outcome: 'outcome',
  tag: 'tag',
  composite: 'composite',
}

/** SVG has no ellipsis; trim to what the box holds at this font size. */
function trim(text: string, chars: number): string {
  return text.length <= chars ? text : `${text.slice(0, chars - 1)}…`
}

export function LaminaMap({
  index,
  computed,
  sensors,
  firing,
  withinByOutcome,
  expanded = false,
  onToggleExpand,
}: Props) {
  const graph = useMemo(() => buildGraph(index), [index])
  const [hover, setHover] = useState<string | null>(null)
  const [fitZoom, setFitZoom] = useState(1)
  /** Null until the reader touches the zoom controls; the fit applies until then. */
  const [manualZoom, setManualZoom] = useState<number | null>(null)
  const zoom = manualZoom ?? fitZoom
  const boxRef = useRef<HTMLDivElement | null>(null)

  // Fit to the panel on mount and on resize.  The graph's natural size depends
  // entirely on how big the lamina is, so there is no sensible fixed default.
  useLayoutEffect(() => {
    const el = boxRef.current
    if (!el) return
    const measure = () => {
      const scale = Math.min(
        1.4,
        Math.max(0.3, (el.clientWidth - 8) / graph.width, 0.3)
      )
      const vertical = (el.clientHeight - 8) / graph.height
      setFitZoom(Math.max(0.3, Math.min(scale, vertical, 1.4)))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [graph.width, graph.height])

  const keep = neighbourhood(graph, hover)
  const firingSet = useMemo(() => new Set(firing), [firing])

  const valueOf = (node: GraphNode): number | undefined =>
    node.valueOf === undefined
      ? undefined
      : node.kind === 'sensor'
        ? sensors[node.valueOf]
        : computed[node.valueOf]

  return (
    <div className="relative w-full h-full flex flex-col">
      <div ref={boxRef} className="flex-1 min-h-0 overflow-auto">
        <svg
          width={graph.width * zoom}
          height={graph.height * zoom}
          viewBox={`0 0 ${graph.width} ${graph.height}`}
          role="img"
          aria-label={`Computation map of ${index.schema.lamina_name}: ${index.functions.length} functions over ${index.sensors.length} inputs`}
        >
          <defs>
            <marker
              id="twin-arrow"
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

          {graph.edges.map((e) => {
            const tone = EDGE_TONE[e.kind]
            const lit = e.tag !== undefined && firingSet.has(e.tag)
            const faded = keep !== null && !(keep.has(e.from) && keep.has(e.to))
            return (
              <path
                key={e.key}
                d={e.path}
                fill="none"
                stroke={lit ? '#f0a13c' : tone.stroke}
                strokeWidth={lit ? 1.8 : 1}
                strokeDasharray={tone.dash}
                opacity={faded ? 0.12 : 1}
                markerEnd="url(#twin-arrow)"
                color={lit ? '#f0a13c' : tone.stroke}
                style={{ transition: 'opacity 180ms ease' }}
              />
            )
          })}

          {graph.nodes.map((n) => {
            const tone = NODE_TONE[n.kind]
            const faded = keep !== null && !keep.has(n.key)
            const value = valueOf(n)
            const within = n.kind === 'outcome' ? withinByOutcome[n.id] : undefined
            const lit = n.kind === 'tag' && firingSet.has(n.id)
            return (
              <g
                key={n.key}
                transform={`translate(${n.x} ${n.y})`}
                opacity={faded ? 0.18 : 1}
                onMouseEnter={() => setHover(n.key)}
                onMouseLeave={() => setHover(null)}
                style={{ transition: 'opacity 180ms ease', cursor: 'default' }}
              >
                <title>{`${KIND_LABEL[n.kind]} · ${n.id}\n${n.sublabel}`}</title>
                <rect
                  width={n.w}
                  height={n.h}
                  rx={7}
                  fill={tone.fill}
                  stroke={
                    lit
                      ? '#f0a13c'
                      : within === false
                        ? '#ff525f'
                        : tone.stroke
                  }
                  strokeWidth={lit || within === false ? 1.8 : 1}
                />
                <text
                  x={8}
                  y={14}
                  fontSize={10.5}
                  fontFamily="var(--font-mono, monospace)"
                  fontWeight={700}
                  fill={tone.text}
                >
                  {trim(n.label, n.kind === 'function' ? 22 : 18)}
                </text>
                <text
                  x={8}
                  y={25}
                  fontSize={8}
                  fontFamily="var(--font-mono, monospace)"
                  fill={tone.dim}
                >
                  {trim(n.sublabel, 26)}
                </text>
                <text x={8} y={34} fontSize={7} fontFamily="var(--font-mono, monospace)" fill="rgba(216,227,251,0.22)">
                  {KIND_LABEL[n.kind]}
                </text>
                {n.valueOf !== undefined && (
                  <text
                    x={n.w - 8}
                    y={34}
                    fontSize={11}
                    textAnchor="end"
                    fontFamily="var(--font-mono, monospace)"
                    fontWeight={700}
                    fill={tone.text}
                  >
                    {fmtValue(value)}
                  </text>
                )}
              </g>
            )
          })}
        </svg>
      </div>

      {/* Zoom, because the graph's size is the lamina's size and neither is
          known in advance. */}
      <div className="absolute bottom-2 right-2 flex items-center gap-1 rounded-full border border-white/10
                      bg-surface-lowest/85 backdrop-blur-sm px-1.5 py-1">
        {[
          { label: '−', to: () => Math.max(0.3, zoom - 0.15) },
          { label: '+', to: () => Math.min(2, zoom + 0.15) },
        ].map((b) => (
          <button
            key={b.label}
            onClick={() => setManualZoom(b.to())}
            className="w-5 h-5 rounded-full font-mono text-[11px] text-ink/50 hover:text-ink hover:bg-white/10"
          >
            {b.label}
          </button>
        ))}
        <button
          onClick={() => setManualZoom(null)}
          className="px-1.5 font-mono text-[9px] readout uppercase text-ink/40 hover:text-ink"
        >
          fit
        </button>
        {onToggleExpand && (
          <button
            onClick={onToggleExpand}
            title={expanded ? 'Back to the stage panel' : 'Give the map the whole panel'}
            className="px-1.5 font-mono text-[9px] readout uppercase text-ink/40 hover:text-ink"
          >
            {expanded ? '⤡ shrink' : '⤢ expand'}
          </button>
        )}
      </div>

      {/* Right padding keeps the caption clear of the zoom cluster, which is
          positioned against the same corner. */}
      <div className="shrink-0 px-2 pt-2 pr-[186px]">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          {(Object.keys(NODE_TONE) as NodeKind[]).map((k) => (
            <span key={k} className="flex items-center gap-1.5">
              <span
                className="w-2.5 h-2.5 rounded-[3px] border"
                style={{ borderColor: NODE_TONE[k].stroke, background: NODE_TONE[k].fill }}
              />
              <span className="font-mono text-[9px] readout text-ink/40">{KIND_LABEL[k]}</span>
            </span>
          ))}
        </div>
        <p className="font-mono text-[9px] readout text-ink/25 mt-1">
          Every box and line is declared in {index.schema.lamina_id} — hover a node to isolate what
          it reads and what reads it. The lower band is the correction returning.
        </p>
      </div>
    </div>
  )
}
