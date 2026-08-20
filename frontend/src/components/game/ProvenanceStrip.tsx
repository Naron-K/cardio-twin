/**
 * ProvenanceStrip — where every moving thing on the stage got its number,
 * on screen at all times.
 *
 * This used to live inside Schematic mode only, which meant the showcase view —
 * the one an open-day visitor actually looks at — moved two atria from a
 * declared constant with nothing on screen saying so.  A binding you can only
 * audit by switching to a debug view is not audited.
 *
 * Colouring follows the missing-data result that highlighting beats downplaying
 * (Song & Szafir, IEEE TVCG 2019): a region the model cannot describe is named
 * outright rather than greyed down until nobody notices it.  `sensor` is the
 * alarm colour because a raw sensor reaching the stage is the one thing the
 * architecture forbids — and it currently reads zero, which is worth showing.
 */
import { constantRegions, tallyProvenance } from '../../game/stageTemplate'
import type { LoadedStage, Provenance } from '../../game/stageTemplate'

interface Props {
  stage: LoadedStage
  sources: Record<string, string>
}

const TONE: Record<Provenance, { dot: string; text: string; label: string }> = {
  model:    { dot: 'bg-oxy-dim',     text: 'text-oxy',     label: 'model' },
  sensor:   { dot: 'bg-danger',      text: 'text-danger',  label: 'sensor' },
  constant: { dot: 'bg-warn-strong', text: 'text-warn',    label: 'declared constant' },
  missing:  { dot: 'bg-ink/30',      text: 'text-ink/40',  label: 'unbound' },
}

export function ProvenanceStrip({ stage, sources }: Props) {
  const { tally, total } = tallyProvenance(stage.template, sources)
  const constants = constantRegions(stage.template, sources)

  // Nothing to report until the schema has arrived and provenance is knowable.
  if (total === 0) return null

  const order: Provenance[] = ['model', 'sensor', 'constant', 'missing']

  return (
    <div
      className="flex items-center gap-3 rounded-el border border-white/10 bg-surface-lowest/85
                 backdrop-blur-sm px-3 py-1.5"
    >
      <span className="font-mono text-[9px] readout uppercase text-ink/30 shrink-0">
        Data source
      </span>

      <div className="flex items-center gap-2.5">
        {order.map((p) =>
          tally[p] === 0 && p !== 'sensor' ? null : (
            <span key={p} className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${TONE[p].dot}`} />
              <span className={`font-mono text-[10px] readout ${TONE[p].text}`}>
                {tally[p]} {TONE[p].label}
              </span>
            </span>
          )
        )}
        <span className="font-mono text-[10px] readout text-ink/25">/ {total} bindings</span>
      </div>

      {constants.length > 0 && (
        <span className="font-mono text-[9px] readout text-warn/70 leading-snug ml-auto text-right">
          {constants.map((c) => c.label).join(' and ')} run on a declared constant — the model
          computes nothing that describes {constants.length > 1 ? 'them' : 'it'}
        </span>
      )}
    </div>
  )
}
