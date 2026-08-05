/**
 * BeforeAfterPanel — how far the feedback loop moved each outcome.
 *
 * One horizontal track per outcome over its physiological range:
 *   • green band   = tolerance band (target ± tolerance)
 *   • hollow ○     = "before" — the value with the loop OFF (X″ = 0)
 *   • solid ●      = "after"  — the current value with the loop ON
 *   • amber arrow  = the correction the loop applied this tick
 *
 * The before value comes from the backend shadow-pass, so coupling like
 * CO = HR·SV is reflected: a correction on SV shows up in the CO row too.
 * Out-of-band signals get pulled toward their band; healthy ones are left
 * untouched (○ and ● coincide).
 */
import type { BeforeAfter, StreamTick } from '../hooks/useCardioStream'

interface Props {
  latest: StreamTick | null
}

// Display order + short labels (keyed by outcome id).
const ROWS = [
  { id: 'target_co',     label: 'CO'  },
  { id: 'target_sv',     label: 'SV'  },
  { id: 'target_map',    label: 'MAP' },
  { id: 'target_flow',   label: 'Q'   },
  { id: 'target_lambda', label: 'λ'   },
]

const X0 = 120   // track left (px)
const X1 = 540   // track right (px)
const ROW_H = 36
const TOP = 16

function clampX(v: number, lo: number, hi: number): number {
  const t = (v - lo) / (hi - lo)
  return X0 + Math.max(0, Math.min(1, t)) * (X1 - X0)
}

function Row({ e, label, y }: { e: BeforeAfter; label: string; y: number }) {
  const { physio_min: lo, physio_max: hi, target, tolerance, before, after, within_after } = e
  const bandLo = clampX(target - tolerance, lo, hi)
  const bandHi = clampX(target + tolerance, lo, hi)
  const xb = clampX(before, lo, hi)
  const xa = clampX(after, lo, hi)
  const moved = Math.abs(after - before) > Math.max(1e-3, (hi - lo) * 0.002)

  const fmt = (v: number) => (Math.abs(v) >= 10 ? v.toFixed(0) : v.toFixed(1))
  const labelColor = within_after ? '#7dd3fc' : '#fca5a5'

  return (
    <g>
      <text x="8" y={y + 4} fill={labelColor} fontSize="11">{label}</text>
      <line x1={X0} y1={y} x2={X1} y2={y} stroke="#334155" />
      <rect x={bandLo} y={y - 7} width={Math.max(2, bandHi - bandLo)} height="14" rx="3"
        fill="#052e16" stroke="#15803d" />
      {moved && (
        <line x1={xb} y1={y} x2={xa} y2={y} stroke="#fbbf24" strokeWidth="1.3"
          strokeDasharray="4 3" markerEnd="url(#ba-arrow)" />
      )}
      {moved && <circle cx={xb} cy={y} r="4.5" fill="#0f172a" stroke="#94a3b8" strokeWidth="1.5" />}
      <circle cx={xa} cy={y} r="4.5" fill="#22d3ee" />
      <text x="556" y={y + 4} fill="#94a3b8" fontSize="10">
        {moved
          ? <>{fmt(before)} → <tspan fill="#22d3ee">{fmt(after)}</tspan></>
          : <>{fmt(after)} <tspan fill="#475569">· no change</tspan></>}
      </text>
    </g>
  )
}

export function BeforeAfterPanel({ latest }: Props) {
  const ba = latest?.beforeAfter ?? {}
  const rows = ROWS.filter(r => ba[r.id] !== undefined)

  if (rows.length === 0) {
    return (
      <div className="h-[180px] flex items-center justify-center text-slate-600 text-xs animate-pulse">
        waiting for data…
      </div>
    )
  }

  const height = TOP + rows.length * ROW_H

  return (
    <svg viewBox={`0 0 624 ${height}`} width="100%" role="img"
      aria-label="Before versus after the feedback loop, per outcome, on its tolerance band.">
      <defs>
        <marker id="ba-arrow" markerWidth="7" markerHeight="7" refX="6" refY="3.5" orient="auto">
          <path d="M0,0 L7,3.5 L0,7 Z" fill="#fbbf24" />
        </marker>
      </defs>
      {rows.map((r, i) => (
        <Row key={r.id} e={ba[r.id]} label={r.label} y={TOP + i * ROW_H} />
      ))}
    </svg>
  )
}
