/**
 * SegmentPanel — the lamina broken into the subsystems it says it has.
 *
 * A `<segment>` is the model's own grouping: it lists the attributes it owns,
 * the functions that run inside it, the composites it uses and the outcomes it
 * is judged by. So the panel groups by segment rather than by anything the UI
 * decided, and a lamina with one segment or eleven lays out the same way.
 *
 * Each attribute gets a bar across its **declared** range. That range is
 * `physio_min`/`physio_max` from the XML and it is a display scale, not a
 * verdict — nothing here calls a value good or bad on the strength of it. The
 * only verdicts drawn are ones the model computes: a behavioural outcome's
 * tolerance band, and a permeability gate's permitted range. Both are marked
 * on the bar and named underneath, so a reader can see which numbers on screen
 * are judgements and where each judgement was declared.
 *
 * An attribute with no outcome and no gate gets a bar and no verdict, which is
 * the honest rendering of "the model tracks this but does not judge it".
 */
import { fmtValue, pctOfRange } from '../../twin/schema'
import type { GateSchema, LaminaIndex, SegmentSchema } from '../../twin/schema'
import type { BeforeAfter } from '../../hooks/useCardioStream'

interface Props {
  index: LaminaIndex
  computed: Record<string, number>
  sensors: Record<string, number>
  outcomes: Record<string, BeforeAfter>
}

export function SegmentPanel({ index, computed, sensors, outcomes }: Props) {
  if (index.segments.length === 0) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        This lamina declares no segments.
      </p>
    )
  }

  return (
    <div className="max-h-[268px] overflow-y-auto pr-1 space-y-4">
      {index.segments.map((seg) => (
        <Segment
          key={seg.id}
          seg={seg}
          index={index}
          computed={computed}
          sensors={sensors}
          outcomes={outcomes}
        />
      ))}
    </div>
  )
}

function Segment({
  seg,
  index,
  computed,
  sensors,
  outcomes,
}: Props & { seg: SegmentSchema }) {
  return (
    <section>
      <header className="flex items-baseline gap-2 mb-2">
        <h4 className="font-display text-[13px] font-semibold text-ink">{seg.name}</h4>
        <span className="font-mono text-[9px] readout text-ink/25">{seg.id}</span>
        <span className="font-mono text-[9px] readout text-ink/30 ml-auto truncate">
          {(seg.function_ids ?? []).length} functions · {(seg.behavioural_outcomes ?? []).length}{' '}
          outcomes
        </span>
      </header>

      <div className="space-y-1.5">
        {(seg.attribute_ids ?? []).map((id) => {
          const attr = index.attribute(id)
          if (!attr) return null
          const raw = attr.source === 'SENSOR'
          const value = raw ? sensors[id] : computed[id]
          const outcome = (index.outcomesOfAttribute[id] ?? [])
            .map((o) => outcomes[o.id])
            .find(Boolean)
          const gates = index.gatesOfAttribute[id] ?? []

          return (
            <div key={id} className="grid grid-cols-[64px_minmax(0,1fr)_92px] items-center gap-2.5">
              <span
                className="font-mono text-[10px] font-bold readout text-ink/70 truncate"
                title={`${attr.name} — ${attr.description}`}
              >
                {id}
              </span>

              <Bar
                attr={attr}
                value={value}
                outcome={outcome}
                gates={gates}
              />

              <span className="text-right font-mono text-[10px] tabular-nums text-ink/80 truncate">
                {fmtValue(value)}
                <span className="text-ink/25 ml-1">{attr.unit}</span>
              </span>

              <span
                className={`col-start-1 font-mono text-[8px] readout ${
                  raw ? 'text-ink/25' : 'text-oxy/50'
                }`}
              >
                {raw ? 'input' : 'computed'}
              </span>
              <span className="col-start-2 col-span-2 font-mono text-[8px] readout text-ink/25 truncate">
                {[
                  outcome && `outcome ${outcome.target} ± ${outcome.tolerance}`,
                  ...gates.map((g) => `gate ${g.gate_type}${gateSpan(g)} — ${g.flag}`),
                ]
                  .filter(Boolean)
                  .join(' · ') || 'no outcome, no gate — tracked, not judged'}
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

function gateSpan(g: GateSchema): string {
  if (g.min !== null && g.max !== null) return ` ${g.min}–${g.max}`
  if (g.min !== null) return ` ≥ ${g.min}`
  if (g.max !== null) return ` ≤ ${g.max}`
  if (g.tolerance !== null) return ` ±${g.tolerance} on ${(g.compare ?? []).join(', ')}`
  return ''
}

function Bar({
  attr,
  value,
  outcome,
  gates,
}: {
  attr: NonNullable<ReturnType<LaminaIndex['attribute']>>
  value: number | undefined
  outcome: BeforeAfter | undefined
  gates: GateSchema[]
}) {
  const has = value !== undefined && Number.isFinite(value)
  const x = has ? pctOfRange(attr, value as number) : 0
  const within = outcome?.within_after

  return (
    <div className="relative h-3">
      <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-surface-lowest" />

      {/* Permitted range of any gate the model enforces on this attribute —
          drawn only where it is narrower than the scale. Several gates here
          repeat the attribute's own declared range exactly, and an outline
          spanning the whole bar looks like information while carrying none;
          the note under the row still names every gate either way. */}
      {gates.map((g, i) => {
        if (g.min === null && g.max === null) return null
        const lo = pctOfRange(attr, g.min ?? attr.physio_min)
        const hi = pctOfRange(attr, g.max ?? attr.physio_max)
        if (hi - lo >= 99) return null
        return (
          <div
            key={i}
            className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full border border-warn-strong/35"
            style={{ left: `${lo}%`, width: `${Math.max(0.5, hi - lo)}%` }}
          />
        )
      })}

      {/* Tolerance band, where the model declares an outcome for this attribute. */}
      {outcome && (
        <>
          <div
            className="absolute top-1/2 -translate-y-1/2 h-1.5 rounded-full bg-oxy-container/25"
            style={{
              left: `${pctOfRange(attr, outcome.target - outcome.tolerance)}%`,
              width: `${Math.max(
                0.5,
                pctOfRange(attr, outcome.target + outcome.tolerance) -
                  pctOfRange(attr, outcome.target - outcome.tolerance)
              )}%`,
            }}
          />
          <div
            className="absolute top-1/2 -translate-y-1/2 w-px h-3 bg-oxy/60"
            style={{ left: `${pctOfRange(attr, outcome.target)}%` }}
          />
        </>
      )}

      {has && (
        <div
          className={`absolute top-1/2 w-2 h-2 -translate-x-1/2 -translate-y-1/2 rounded-full ${
            within === false
              ? 'bg-crimson-container shadow-bloom-sm'
              : within === true
                ? 'bg-oxy-container shadow-oxybloom-sm'
                : 'bg-ink/60'
          }`}
          style={{ left: `${x}%` }}
        />
      )}
    </div>
  )
}
