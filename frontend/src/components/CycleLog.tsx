/**
 * CycleLog — a scrolling event feed of the 7-step feedback cycle.
 *
 * Surfaces the per-tick cycle_report (previously dropped on the client):
 * which tag fired, the X″ applied per attribute, dead-zone snaps, circuit
 * breaker trips, and slow-loop adaptation ticks — interleaved newest-first.
 * Idle cycles (nothing fired, no correction) are omitted so the log stays
 * meaningful.
 */
import type { StreamTick } from '../hooks/useCardioStream'

interface Props {
  ticks: StreamTick[]
}

type Kind = 'fast' | 'slow' | 'snap' | 'diverge'
interface Event {
  key: string
  kind: Kind
  tick: number
  text: string
}

const COLOR: Record<Kind, string> = {
  fast:    'text-slate-200',
  slow:    'text-violet-300',
  snap:    'text-slate-500',
  diverge: 'text-red-400',
}
const TAG_COLOR: Record<Kind, string> = {
  fast:    'text-amber-400',
  slow:    'text-violet-400',
  snap:    'text-slate-600',
  diverge: 'text-red-500',
}
const PREFIX: Record<Kind, string> = { fast: '#', slow: '⚙ #', snap: '↩ #', diverge: '⚠ #' }

// Build the displayable event list from the ring buffer (oldest→newest in,
// newest-first out), capped to the most recent `limit` events.
function buildEvents(ticks: StreamTick[], limit: number): Event[] {
  const out: Event[] = []
  for (const t of ticks) {
    if (t.diverged) {
      out.push({ key: `${t.tick}-d`, kind: 'diverge', tick: t.tick, text: 'CIRCUIT BREAKER — cycle rolled back' })
    }
    if (t.tagsEmitted.length > 0) {
      const deltas = Object.entries(t.deltasPerAttr)
        .filter(([, v]) => Math.abs(v) > 1e-3)
        .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
        .slice(0, 3)
        .map(([id, v]) => `Δ${id} ${v > 0 ? '+' : ''}${v.toFixed(2)}`)
        .join('  ')
      const tags = t.tagsEmitted.join(', ')
      out.push({
        key: `${t.tick}-f`, kind: 'fast', tick: t.tick,
        text: `${tags}  ${deltas}${deltas ? '  ' : ''}‖X″‖ ${t.feedback_norm.toFixed(3)}`,
      })
    }
    const adapt = Object.entries(t.adaptation)
    if (adapt.length > 0) {
      const parts = adapt.slice(0, 2).map(([oid, a]) =>
        `${oid.replace('target_', '')} gain→${a.gain.toFixed(2)}`)
      out.push({ key: `${t.tick}-s`, kind: 'slow', tick: t.tick, text: `slow-loop: ${parts.join(' · ')}` })
    }
    if (t.snapped.length > 0) {
      out.push({ key: `${t.tick}-n`, kind: 'snap', tick: t.tick, text: `snapped ${t.snapped.join(', ')} (dead-zone)` })
    }
  }
  return out.slice(-limit).reverse()
}

export function CycleLog({ ticks }: Props) {
  const events = buildEvents(ticks, 40)

  if (events.length === 0) {
    return (
      <div className="h-[120px] flex items-center justify-center text-slate-600 text-xs">
        all outcomes in band — loop idle
      </div>
    )
  }

  return (
    <div className="font-mono text-[10px] leading-[1.85] max-h-[180px] overflow-y-auto pr-1">
      {events.map(e => (
        <div key={e.key} className={COLOR[e.kind]}>
          <span className={TAG_COLOR[e.kind]}>{PREFIX[e.kind]}{e.tick}</span>{' '}
          {e.text}
        </div>
      ))}
    </div>
  )
}
