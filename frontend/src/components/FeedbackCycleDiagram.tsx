/**
 * FeedbackCycleDiagram — the fast loop drawn as a signal-flow graph.
 *
 * One tick of FeedbackController.step() read left→right:
 *   outcome (deviation)  →  tag fired  →  composite  →  attribute X″
 * and a dashed return arrow = the recompute (X = X′ + X″) that closes the
 * loop into the next tick.
 *
 * Live wiring (all from the latest StreamTick):
 *   • outcome node     green when within tolerance, red when out (beforeAfter)
 *   • tag node         glows amber when it fired this cycle (tagsEmitted)
 *   • attribute node   glows cyan + shows X″ when it received a correction
 *                      (deltasPerAttr); the feeding edges light with it
 *   • snapped / diverged add a small status note
 *
 * Layout is fixed (derived from circulatory_lamina.xml); only the
 * highlight state is data-driven, so the picture stays legible.
 */
import type { StreamTick } from '../hooks/useCardioStream'

interface Props {
  latest: StreamTick | null
}

// ── Fixed topology (from the XML schema) ────────────────────────────────
const OUTCOMES = [
  { id: 'target_map',    label: 'MAP', attr: 'MAP',    y: 34  },
  { id: 'target_flow',   label: 'Q',   attr: 'Q',      y: 78  },
  { id: 'target_co',     label: 'CO',  attr: 'CO',     y: 150 },
  { id: 'target_sv',     label: 'SV',  attr: 'SV',     y: 200 },
  { id: 'target_lambda', label: 'λ',   attr: 'lambda', y: 250 },
]
const TAGS = [
  { id: 'MAP_DEVIATION',    composite: 'pressure_state',   y: 34  },
  { id: 'Q_DEVIATION',      composite: 'flow_state',       y: 78  },
  { id: 'CO_DEVIATION',     composite: 'pump_state',       y: 150 },
  { id: 'SV_DEVIATION',     composite: 'pump_state',       y: 200 },
  { id: 'LAMBDA_DEVIATION', composite: 'conduction_state', y: 250 },
]
const COMPOSITES = [
  { id: 'pressure_state',   y: 34  },
  { id: 'flow_state',       y: 78  },
  { id: 'pump_state',       y: 176 },
  { id: 'conduction_state', y: 250 },
]
const ATTRS = [
  { id: 'MAP',    label: 'MAP', composite: 'pressure_state',   y: 34  },
  { id: 'Q',      label: 'Q',   composite: 'flow_state',       y: 78  },
  { id: 'CO',     label: 'CO',  composite: 'pump_state',       y: 150 },
  { id: 'SV',     label: 'SV',  composite: 'pump_state',       y: 200 },
  { id: 'lambda', label: 'λ',   composite: 'conduction_state', y: 250 },
]

const EPS = 1e-4
const IDLE = '#334155'
const LIVE = '#22d3ee'

export function FeedbackCycleDiagram({ latest }: Props) {
  const deltas   = latest?.deltasPerAttr ?? {}
  const fired    = new Set(latest?.tagsEmitted ?? [])
  const snapped  = new Set(latest?.snapped ?? [])
  const ba       = latest?.beforeAfter ?? {}

  const attrActive  = (id: string) => Math.abs(deltas[id] ?? 0) > EPS
  const compActive  = (cid: string) => ATTRS.some(a => a.composite === cid && attrActive(a.id))
  // A tag "drives" the chain when it fired this tick OR its target
  // composite still holds a (decaying) correction — keeps the lit path
  // connected even on ticks where the binary emitter didn't re-fire.
  const tagDriving  = (t: { id: string; composite: string }) => fired.has(t.id) || compActive(t.composite)

  const fmt = (v: number) => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1))

  return (
    <svg viewBox="0 0 624 276" width="100%" role="img"
      aria-label="Feedback cycle: outcomes that leave tolerance fire a tag, which targets a composite and applies an X-double-prime correction to attributes, then the chain recomputes.">
      <defs>
        <marker id="fc-idle" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#475569" />
        </marker>
        <marker id="fc-live" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill={LIVE} />
        </marker>
      </defs>

      {/* Column headers */}
      <text x="62"  y="12" fill="#64748b" fontSize="10" textAnchor="middle">outcome</text>
      <text x="241" y="12" fill="#64748b" fontSize="10" textAnchor="middle">tag fired</text>
      <text x="407" y="12" fill="#64748b" fontSize="10" textAnchor="middle">composite</text>
      <text x="567" y="12" fill="#64748b" fontSize="10" textAnchor="middle">attribute X″</text>

      {/* Edges: outcome → tag (lit when the tag is driving) */}
      {TAGS.map(t => {
        const on = tagDriving(t)
        return (
          <path key={`ot-${t.id}`} d={`M116 ${t.y} H172`} fill="none"
            stroke={on ? LIVE : IDLE} strokeWidth={on ? 2 : 1}
            markerEnd={`url(#${on ? 'fc-live' : 'fc-idle'})`} />
        )
      })}

      {/* Edges: tag → composite (lit when the tag is driving) */}
      {TAGS.map(t => {
        const c = COMPOSITES.find(c => c.id === t.composite)!
        const on = tagDriving(t)
        return (
          <path key={`tc-${t.id}`} d={`M308 ${t.y} C330 ${t.y} 332 ${c.y} 352 ${c.y}`} fill="none"
            stroke={on ? LIVE : IDLE} strokeWidth={on ? 2 : 1}
            markerEnd={`url(#${on ? 'fc-live' : 'fc-idle'})`} />
        )
      })}

      {/* Edges: composite → attribute (lit when the attribute got an X″) */}
      {ATTRS.map(a => {
        const c = COMPOSITES.find(c => c.id === a.composite)!
        const on = attrActive(a.id)
        return (
          <path key={`ca-${a.id}`} d={`M460 ${c.y} C486 ${c.y} 490 ${a.y} 516 ${a.y}`} fill="none"
            stroke={on ? LIVE : IDLE} strokeWidth={on ? 2 : 1}
            markerEnd={`url(#${on ? 'fc-live' : 'fc-idle'})`} />
        )
      })}

      {/* Recompute return arrow — closes the loop into the next tick */}
      <path d="M566 214 V258 C566 268 556 268 540 268 H70 C58 268 50 266 50 256 V214"
        stroke="#475569" strokeWidth="1.5" strokeDasharray="5 4" fill="none" markerEnd="url(#fc-idle)" />
      <text x="308" y="274" fill="#64748b" fontSize="9.5" textAnchor="middle">
        recompute: X = X′ + X″ (next tick)
      </text>

      {/* Outcome nodes */}
      {OUTCOMES.map(o => {
        const e = ba[o.id]
        const known = e !== undefined
        const ok = known ? e.within_after : true
        const fill   = !known ? '#1e293b' : ok ? '#0b2434' : '#3b1414'
        const stroke = !known ? IDLE      : ok ? '#1e3a5f' : '#7f1d1d'
        const text   = !known ? '#64748b' : ok ? '#7dd3fc' : '#fca5a5'
        const val = known ? ` ${fmt(e.after)} ${ok ? '✓' : '✕'}` : ''
        return (
          <g key={`o-${o.id}`}>
            <rect x="8" y={o.y - 14} width="108" height="28" rx="5" fill={fill} stroke={stroke} />
            <text x="62" y={o.y + 4} fill={text} fontSize="11" textAnchor="middle">{o.label}{val}</text>
          </g>
        )
      })}

      {/* Tag nodes — amber when driving; "fired" sub-label only on a real
          binary emission this tick */}
      {TAGS.map(t => {
        const on = tagDriving(t)
        const justFired = fired.has(t.id)
        return (
          <g key={`t-${t.id}`}>
            <rect x="174" y={t.y - 14} width="134" height="28" rx="5"
              fill={on ? '#3a2c08' : '#1e293b'} stroke={on ? '#fbbf24' : IDLE} />
            <text x="241" y={justFired ? t.y - 1 : t.y + 4} fill={on ? '#fbbf24' : '#64748b'}
              fontSize="10.5" textAnchor="middle">{t.id}</text>
            {justFired && <text x="241" y={t.y + 10} fill="#b58a18" fontSize="8.5" textAnchor="middle">fired</text>}
          </g>
        )
      })}

      {/* Composite nodes */}
      {COMPOSITES.map(c => {
        const on = compActive(c.id)
        return (
          <g key={`c-${c.id}`}>
            <rect x="354" y={c.y - 14} width="106" height="28" rx="5"
              fill={on ? '#082f3a' : '#1e293b'} stroke={on ? LIVE : IDLE} />
            <text x="407" y={c.y + 4} fill={on ? '#67e8f9' : '#94a3b8'} fontSize="10.5" textAnchor="middle">{c.id}</text>
          </g>
        )
      })}

      {/* Attribute nodes */}
      {ATTRS.map(a => {
        const d = deltas[a.id] ?? 0
        const on = Math.abs(d) > EPS
        const snap = snapped.has(a.id)
        const label = on ? `${a.label} X″ ${d > 0 ? '+' : ''}${d.toFixed(2)}` : `${a.label} · 0`
        return (
          <g key={`a-${a.id}`}>
            <rect x="518" y={a.y - 14} width="98" height="28" rx="5"
              fill={on ? '#082f3a' : '#1e293b'} stroke={snap ? '#a16207' : on ? LIVE : IDLE} />
            <text x="567" y={a.y + 4} fill={on ? '#67e8f9' : '#64748b'} fontSize="10" textAnchor="middle">{label}</text>
          </g>
        )
      })}

      {latest?.diverged && (
        <text x="62" y="270" fill="#f87171" fontSize="9">⚠ circuit breaker</text>
      )}
    </svg>
  )
}
