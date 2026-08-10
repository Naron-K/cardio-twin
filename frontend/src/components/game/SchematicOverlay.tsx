/**
 * SchematicOverlay — the stage with its wiring showing.
 *
 * Draws a frame for every placeholder and colours it by where its data comes
 * from.  The point is not decoration: it makes the separation Lee asks for
 * *checkable at a glance*.  A placeholder animated from a raw sensor turns red
 * on screen instead of hiding inside a props chain, and a region the model has
 * nothing to say about reads as unbound rather than quietly faking motion.
 *
 * Rendered as HTML rather than inside the SVG so the type stays crisp and the
 * chips reuse the same tokens as the rest of the game UI.
 */
import { describeBindings, describeRhythm } from '../../game/stageTemplate'
import type { LoadedStage, Provenance } from '../../game/stageTemplate'

interface Props {
  stage: LoadedStage
  values: Record<string, number>
  sources: Record<string, string>
  focus?: string | null
}

const TONE: Record<Provenance, { frame: string; text: string; dot: string; label: string }> = {
  model:    { frame: 'border-oxy-dim',       text: 'text-oxy',      dot: 'bg-oxy-dim',      label: 'model' },
  sensor:   { frame: 'border-danger',        text: 'text-danger',   dot: 'bg-danger',       label: 'sensor' },
  constant: { frame: 'border-warn-strong',   text: 'text-warn',     dot: 'bg-warn-strong',  label: 'const' },
  missing:  { frame: 'border-ink/25',        text: 'text-ink/40',   dot: 'bg-ink/30',       label: 'none' },
}

/** Worst wins: one sensor channel makes the whole placeholder a violation. */
const SEVERITY: Provenance[] = ['sensor', 'missing', 'constant', 'model']

export function SchematicOverlay({ stage, values, sources, focus = null }: Props) {
  const { template } = stage
  const { artwork, placeholders, drawOrder } = template
  const ids = drawOrder.filter((id) => placeholders[id])

  // Shared bindings are counted once, so the tally reads as "how many distinct
  // things drive this stage" rather than multiplying one violation by six.
  const rhythm = describeRhythm(template, sources)
  const tally: Record<Provenance, number> = { model: 0, sensor: 0, constant: 0, missing: 0 }
  for (const row of rhythm) tally[row.provenance]++
  for (const id of ids) {
    for (const row of describeBindings(placeholders[id], template, sources)) {
      if (!row.shared) tally[row.provenance]++
    }
  }
  const total = tally.model + tally.sensor + tally.constant + tally.missing

  return (
    <div className="absolute inset-0 pointer-events-none">
      {ids.map((id) => {
        const place = placeholders[id]
        const rows = describeBindings(place, template, sources)
        const own = rows.filter((r) => !r.shared)
        const worst = SEVERITY.find((p) => own.some((r) => r.provenance === p)) ?? 'missing'
        const tone = TONE[worst]
        const g = place.geometry
        const open = focus === id

        return (
          <div
            key={id}
            className={`absolute border border-dashed rounded-el transition-opacity duration-200 ${tone.frame} ${
              focus && !open ? 'opacity-25' : 'opacity-90'
            }`}
            style={{
              left: `${(g.x / artwork.width) * 100}%`,
              top: `${(g.y / artwork.height) * 100}%`,
              width: `${(g.w / artwork.width) * 100}%`,
              height: `${(g.h / artwork.height) * 100}%`,
            }}
          >
            <span
              className={`absolute -top-2.5 left-1 px-1 rounded-sm bg-surface-lowest font-mono
                          text-[11px] leading-none py-0.5 ${tone.text}`}
            >
              {id}
            </span>

            {open && (
              <div
                className="absolute top-3 left-1 w-[152px] rounded-el border border-white/10
                           bg-surface-lowest/95 backdrop-blur-sm p-2 space-y-1 shadow-inset1"
              >
                <p className="font-mono text-[10px] readout text-ink/50">{place.label}</p>
                {rows.map((row, i) => {
                  const t = TONE[row.provenance]
                  const v = row.attribute ? values[row.attribute] : undefined
                  return (
                    <div key={`${row.channel}-${row.attribute}-${i}`} className="flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${t.dot}`} />
                      <span className="font-mono text-[9px] readout text-ink/40 w-[52px] shrink-0">
                        {row.channel}
                      </span>
                      <span className={`font-mono text-[10px] readout truncate ${t.text}`}>
                        {row.attribute ?? t.label}
                        {v !== undefined && ` ${v.toFixed(1)}`}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}

      {/* Bottom strip, the only band no placeholder frame reaches.  Beat timing
          drives every placeholder, so it is reported once here rather than
          colouring all six frames identically. */}
      <div
        className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-el border border-white/10
                   bg-surface-lowest/90 backdrop-blur-sm px-3 py-1.5 space-y-1"
      >
        <div className="flex items-center gap-2.5">
          {rhythm.map((row, i) => (
            <span key={`${row.channel}-${row.attribute}-${i}`} className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${TONE[row.provenance].dot}`} />
              <span className={`font-mono text-[10px] readout ${TONE[row.provenance].text}`}>
                {row.attribute ?? TONE[row.provenance].label}
              </span>
            </span>
          ))}
          <span className="font-mono text-[10px] readout text-ink/30">rhythm</span>
        </div>
        <div className="flex items-center gap-2.5">
          {(['model', 'sensor', 'constant'] as Provenance[]).map((p) => (
            <span key={p} className="flex items-center gap-1.5">
              <span className={`w-1.5 h-1.5 rounded-full ${TONE[p].dot}`} />
              <span className={`font-mono text-[10px] readout ${TONE[p].text}`}>
                {tally[p]} {TONE[p].label}
              </span>
            </span>
          ))}
          <span className="font-mono text-[10px] readout text-ink/30">/ {total}</span>
        </div>
      </div>
    </div>
  )
}
