/**
 * InputRail — the model's inputs, one control per declared sensor.
 *
 * Generated from the schema: every attribute whose source is SENSOR gets a
 * slider, its span is that attribute's declared range, and its group is the
 * segment that lists it. There is no list of ids here, so a lamina with two
 * inputs or forty renders without an edit.
 *
 * These are inputs, not readings — the distinction the architecture rests on.
 * Nothing on this rail drives a picture: the stage is handed the computed half
 * of the snapshot and has no prop through which a sensor could arrive. The rail
 * writes values *into* the model, the model digests them, and everything else
 * on screen reads what came out. Each row says "raw input" for the same reason
 * the stage says where its numbers came from.
 *
 * Values track the stream while a control is idle, so a slider shows what the
 * backend actually holds rather than the last thing this component sent.
 */
import { useRef, useState } from 'react'
import type { LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  /** Live sensor values off the tick. */
  values: Record<string, number>
  disabled?: boolean
  onChange: (id: string, value: number) => void
}

export function InputRail({ index, values, disabled = false, onChange }: Props) {
  // While a slider is being dragged its own value wins; otherwise the stream
  // does. Without this the control fights the 10 Hz tick under the cursor.
  const [held, setHeld] = useState<Record<string, number>>({})
  const holding = useRef<string | null>(null)

  if (index.sensors.length === 0) {
    return (
      <p className="font-mono text-[10px] readout text-ink/35">
        This lamina declares no sensor inputs.
      </p>
    )
  }

  // Grouped by the segment that owns each input, in segment declaration order,
  // with anything unclaimed collected at the end rather than dropped.
  const groups = new Map<string, { label: string; ids: string[] }>()
  for (const attr of index.sensors) {
    const seg = index.segmentOfAttribute[attr.id]
    const key = seg?.id ?? '·unassigned'
    if (!groups.has(key)) groups.set(key, { label: seg?.name ?? 'Listed by no segment', ids: [] })
    groups.get(key)!.ids.push(attr.id)
  }

  return (
    <div className="space-y-3">
      {[...groups.entries()].map(([key, group]) => (
        <div key={key}>
          <p className="font-mono text-[9px] readout uppercase text-ink/25 mb-1.5">{group.label}</p>
          <div className="space-y-2">
            {group.ids.map((id) => {
              const attr = index.attribute(id)!
              const live = held[id] ?? values[id] ?? (attr.physio_min + attr.physio_max) / 2
              const span = attr.physio_max - attr.physio_min
              return (
                <label key={id} className="block group" title={attr.description}>
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-[10px] font-bold readout text-ink/70">{id}</span>
                    <span className="font-mono text-[9px] readout text-ink/25 truncate">
                      {attr.name}
                    </span>
                    <span className="ml-auto font-mono text-[10px] tabular-nums text-ink shrink-0">
                      {fmtValue(live)}
                      <span className="text-ink/30 text-[9px] ml-0.5">{attr.unit}</span>
                    </span>
                  </span>
                  <input
                    type="range"
                    min={attr.physio_min}
                    max={attr.physio_max}
                    // 200 steps across whatever range the XML declares, so a
                    // 0.01–1.5 cm radius is as controllable as a 40–200 bpm rate.
                    step={span / 200}
                    value={live}
                    disabled={disabled}
                    onPointerDown={() => (holding.current = id)}
                    onPointerUp={() => {
                      holding.current = null
                      setHeld({})
                    }}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setHeld((prev) => ({ ...prev, [id]: v }))
                      onChange(id, v)
                    }}
                    className="mt-1 w-full h-1 appearance-none rounded-full bg-surface-lowest
                               accent-crimson-container disabled:opacity-40 cursor-pointer"
                  />
                </label>
              )
            })}
          </div>
        </div>
      ))}

      <p className="font-mono text-[9px] readout text-ink/25 leading-snug pt-1 border-t border-white/5">
        Raw input, written straight into the lamina. Ranges are each attribute's declared
        physiological span — edit the XML and these controls move with it. Nothing here reaches the
        stage; the model digests it first.
      </p>
    </div>
  )
}
