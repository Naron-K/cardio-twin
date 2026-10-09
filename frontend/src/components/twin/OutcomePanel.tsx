/**
 * OutcomePanel — every behavioural outcome the model evaluated, on its own
 * tolerance band, with what the feedback loop moved.
 *
 * One row per outcome:
 *
 *   ├─────────[ tolerance band ]─────────┤     scale = the attribute's physio range
 *              ╎                                target, as the model declares it
 *        ○╌╌╌╌►●                                ○ shadow pass · ● current value
 *
 * The hollow marker is **not** X′.  It is the shadow pass: the same cycle
 * recomputed with X″ zeroed on every attribute, so coupling like CO = HR·SV is
 * carried through it.  A correction that lands on SV moves the CO row too,
 * which a per-attribute X′ could never show.  Labelling it "X′" would be a new
 * lie told by a panel built to stop one.
 *
 * Each row also states its own share of D in tolerance bands, so the total on
 * the convergence chart can be read back to the outcome that caused it — and so
 * an outcome the model itself flags as unreliable can be discounted by eye
 * rather than silently dropped by us.  The note under each row is the model's
 * own text: the attribute's description plus the description of the function
 * that computes it, verbatim from the schema.  Q's warning that its absolute
 * value cannot be trusted is the model's sentence, not ours.
 */
import type { BeforeAfter } from '../../hooks/useCardioStream'
import { bandOf, deviationBands, orderedOutcomes } from '../../twin/outcomes'
import type { Outcomes } from '../../twin/outcomes'
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  outcomes: Outcomes
  index: LaminaIndex
}

/** The model's own words about this attribute — description + its function's. */
function modelNote(index: LaminaIndex, attributeId: string): string {
  const attr = index.attribute(attributeId)
  const fn = index.functionByOutput[attributeId]
  return [attr?.description, fn?.description].filter(Boolean).join(' · ')
}

/** Percent position of a value on the attribute's physiological scale. */
function pct(v: number, lo: number, hi: number): number {
  const span = Math.max(1e-9, hi - lo)
  return Math.max(0, Math.min(100, ((v - lo) / span) * 100))
}

function fmt(v: number): string {
  const a = Math.abs(v)
  return a >= 100 ? v.toFixed(0) : a >= 10 ? v.toFixed(1) : v.toFixed(2)
}



/**
 * One outcome on its physiological scale: the tolerance band, the target, the
 * current value, and — when the loop moved it — the shadow pass with the loop
 * switched off. Shared by this panel and the dashboard's outcome tiles, so the
 * two cannot draw the same outcome differently.
 */
export function ToleranceBar({ o }: { o: BeforeAfter }) {
  const lo = o.physio_min
  const hi = o.physio_max
  const [bandLo, bandHi] = bandOf(o)
  const xBand = pct(bandLo, lo, hi)
  const wBand = pct(bandHi, lo, hi) - xBand
  const xTarget = pct(o.target, lo, hi)
  const xBefore = pct(o.before, lo, hi)
  const xAfter = pct(o.after, lo, hi)

  // Below this the two markers overlap and the "loop moved it" line is noise.
  const moved = Math.abs(o.after - o.before) > (hi - lo) * 0.002
  const [linkLo, linkHi] = xBefore <= xAfter ? [xBefore, xAfter] : [xAfter, xBefore]

  return (
    <div className="relative h-5">
      {/* Scale */}
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-surface-lowest" />
      {/* Tolerance band — target ± tolerance, as the outcome declares it */}
      <div
        className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-oxy-container/25"
        style={{ left: `${xBand}%`, width: `${Math.max(0.5, wBand)}%` }}
      />
      {/* Target */}
      <div
        className="absolute top-1/2 -translate-y-1/2 w-px h-4 bg-oxy/60"
        style={{ left: `${xTarget}%` }}
      />
      {/* What the loop moved */}
      {moved && (
        <div
          className="absolute top-1/2 -translate-y-1/2 h-px border-t border-dashed border-warn-strong/70"
          style={{ left: `${linkLo}%`, width: `${Math.max(0.4, linkHi - linkLo)}%` }}
        />
      )}
      {/* Shadow pass — the same cycle with the loop switched off */}
      {moved && (
        <div
          className="absolute top-1/2 w-2 h-2 -translate-x-1/2 -translate-y-1/2 rounded-full
                     border border-warn-strong bg-surface-lowest"
          style={{ left: `${xBefore}%` }}
        />
      )}
      {/* Current value */}
      <div
        className={`absolute top-1/2 w-2.5 h-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full ${
          o.within_after ? 'bg-oxy-container shadow-oxybloom-sm' : 'bg-crimson-container shadow-bloom-sm'
        }`}
        style={{ left: `${xAfter}%` }}
      />
    </div>
  )
}

function Row({ o, note }: { o: BeforeAfter; note: string }) {
  return (
    <div className="grid grid-cols-[58px_minmax(0,1fr)_96px] items-center gap-3">
      <div className="min-w-0">
        <p
          className={`font-mono text-[11px] font-bold readout truncate ${
            o.within_after ? 'text-ink/75' : 'text-crimson-container'
          }`}
        >
          {o.attribute_id}
        </p>
        <p className="font-mono text-[9px] readout text-ink/30 truncate">{o.unit}</p>
      </div>

      <div>
        <ToleranceBar o={o} />
      </div>

      <div className="text-right">
        <p className="font-mono text-[12px] font-bold tabular-nums text-ink leading-none">
          {fmt(o.after)}
        </p>
        <p className="font-mono text-[9px] readout text-ink/35 mt-0.5">
          {deviationBands(o).toFixed(2)} bands
        </p>
      </div>

      {note && (
        <p className="col-start-2 col-span-2 font-mono text-[9px] readout text-ink/30 leading-tight -mt-1">
          {note}
        </p>
      )}
    </div>
  )
}

export function OutcomePanel({ outcomes, index }: Props) {
  const rows = orderedOutcomes(outcomes)

  if (rows.length === 0) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        Waiting for the first outcome evaluation…
      </p>
    )
  }

  return (
    <div>
      {/* Tall enough that all five outcomes are on screen together — the panel
          exists to be compared across, and a row below the fold is a row that
          does not get read.  Scrolls rather than clipping if the model gains
          outcomes or an attribute carries a longer note. */}
      <div className="max-h-[276px] overflow-y-auto pr-1 space-y-2">
        {rows.map(({ id, o }) => (
          <Row key={id} o={o} note={modelNote(index, o.attribute_id)} />
        ))}
      </div>

      <div className="mt-2.5 pt-2 border-t border-white/10 flex flex-wrap items-center gap-x-4 gap-y-1">
        <Key className="bg-oxy-container">current value</Key>
        <Key className="border border-warn-strong bg-surface-lowest">
          same cycle, loop off (shadow pass)
        </Key>
        <Key className="bg-oxy/60 !w-px !h-3 !rounded-none">target</Key>
        <Key className="bg-oxy-container/20">tolerance band</Key>
        <span className="font-mono text-[9px] readout text-ink/25 ml-auto">
          scale = physiological range · target, tolerance and range all declared by the model
        </span>
      </div>
    </div>
  )
}

function Key({ children, className }: { children: React.ReactNode; className: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${className}`} />
      <span className="font-mono text-[9px] readout text-ink/40">{children}</span>
    </span>
  )
}
