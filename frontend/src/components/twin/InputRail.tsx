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
 * on screen reads what came out.
 *
 * ## Why the slider and the reading are two numbers
 *
 * The control used to display the live reading, and it fought whoever dragged
 * it. Two reasons, and they compound.
 *
 * The reading is the value that was set *plus synthetic noise*, so a slider
 * showing it never settles — it wobbles by whatever `noise_sigma` the lamina
 * declares. And releasing the drag dropped the held value before the socket had
 * echoed the new one back, so the thumb jumped to the previous reading for a
 * frame and then forward again. Measured: set to 30, and 100 ms after release
 * the control read 12.1 before landing on 30.1. Do that twice and the control
 * feels like it is refusing the input.
 *
 * So the slider now carries the *commanded* value — what you set, or the
 * baseline the lamina declares before you set anything — and never moves on its
 * own. The reading sits beside it, dimmer and labelled, free to wobble, because
 * that is what a reading does. Showing one number for both was the error.
 */
import { useState } from 'react'
import type { InboundProvenance } from '../../hooks/useCardioStream'
import type { LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  /** Live sensor readings off the tick — the commanded value plus noise. */
  values: Record<string, number>
  /** Values that crossed from another lamina, by attribute id. */
  inbound?: Record<string, number>
  /** What the backend says about each of those crossings. */
  inboundProvenance?: Record<string, InboundProvenance>
  /** What kind of feed is producing those readings, per the backend. */
  sourceKind?: string
  disabled?: boolean
  /**
   * How to group the controls. `segment` asks which subsystem an input
   * belongs to; `channel` asks how it gets in, by the ingestion channel the
   * lamina maps it to. An input the lamina maps to no channel is listed under
   * that heading rather than folded into a channel it does not have.
   */
  groupBy?: 'segment' | 'channel'
  onChange: (id: string, value: number) => void
}

export function InputRail({
  index,
  values,
  inbound = {},
  inboundProvenance = {},
  sourceKind = 'unknown',
  disabled = false,
  groupBy = 'segment',
  onChange,
}: Props) {
  /** What the reader has set, by attribute id. Empty until they touch one. */
  const [commanded, setCommanded] = useState<Record<string, number>>({})

  if (index.sensors.length === 0 && index.inbound.length === 0) {
    return (
      <p className="font-mono text-[10px] readout text-ink/35">
        This lamina declares no inputs.
      </p>
    )
  }

  // Grouped by the segment that owns each input (or the channel that carries
  // it), in declaration order, with anything unclaimed collected at the end
  // rather than dropped.
  const channels = index.schema.channel_mappings ?? {}
  const groups = new Map<string, { label: string; ids: string[] }>()
  for (const attr of index.sensors) {
    let key: string
    let label: string
    if (groupBy === 'channel') {
      key = channels[attr.id] ?? '·unassigned'
      label = channels[attr.id] ?? 'Mapped to no channel'
    } else {
      const seg = index.segmentOfAttribute[attr.id]
      key = seg?.id ?? '·unassigned'
      label = seg?.name ?? 'Listed by no segment'
    }
    if (!groups.has(key)) groups.set(key, { label, ids: [] })
    groups.get(key)!.ids.push(attr.id)
  }
  // Unclaimed last, whichever way the inputs are grouped.
  const unclaimed = groups.get('·unassigned')
  if (unclaimed) {
    groups.delete('·unassigned')
    groups.set('·unassigned', unclaimed)
  }

  return (
    <div className="space-y-3">
      {[...groups.entries()].map(([key, group]) => (
        <div key={key}>
          <p className="font-mono text-[9px] readout uppercase text-ink/25 mb-1.5">{group.label}</p>
          <div className="space-y-2">
            {group.ids.map((id) => {
              const attr = index.attribute(id)!
              // The commanded value, falling back to what the lamina declares
              // it rests at, and only then to the middle of its range. Never
              // the live reading: that is what made the control unusable.
              const set =
                commanded[id] ?? attr.baseline ?? (attr.physio_min + attr.physio_max) / 2
              const reading = values[id]
              const span = attr.physio_max - attr.physio_min
              // Shown whenever the feed adds noise to this attribute, which is
              // a property of the attribute rather than of this frame. Deciding
              // per frame — "show it when it currently differs" — makes the line
              // appear and vanish at 10 Hz, which is worse than either.
              const noisy = (attr.noise_sigma ?? 0) > 0
              const showReading = reading !== undefined && noisy

              return (
                <label key={id} className="block" title={attr.description}>
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-[10px] font-bold readout text-ink/70">{id}</span>
                    <span className="font-mono text-[9px] readout text-ink/25 truncate">
                      {attr.name}
                    </span>
                    <span className="ml-auto font-mono text-[10px] tabular-nums text-ink shrink-0">
                      {fmtValue(set)}
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
                    value={set}
                    disabled={disabled}
                    onChange={(e) => {
                      const v = Number(e.target.value)
                      setCommanded((prev) => ({ ...prev, [id]: v }))
                      onChange(id, v)
                    }}
                    className="mt-1 w-full h-1 appearance-none rounded-full bg-surface-lowest
                               accent-crimson-container disabled:opacity-40 cursor-pointer"
                  />
                  {showReading && (
                    <span className="block mt-0.5 font-mono text-[9px] readout text-ink/30 tabular-nums">
                      reading {fmtValue(reading)} {attr.unit}
                    </span>
                  )}
                </label>
              )
            })}
          </div>
        </div>
      ))}

      {index.inbound.length > 0 && (
        <div className="pt-2 border-t border-white/5">
          <p className="font-mono text-[9px] readout uppercase text-ink/25 mb-1.5">
            From another lamina
          </p>
          <div className="space-y-2">
            {index.inbound.map((attr) => {
              const prov = inboundProvenance[attr.id]
              const state = prov?.state ?? 'uncoupled'
              // No slider, and that is the point: this value is not yours to
              // set. It arrives through a gate declared in organism.xml, or it
              // rests on the baseline the lamina declares until one opens.
              //
              // Three states, and the middle one is the one worth the code.
              // A gate that opened and then shut leaves this number behind:
              // it is neither live nor the declared baseline, and calling it
              // either is a false claim about where it came from.
              // A fourth thing worth saying, and it is about the CHANNEL
              // rather than about this number: something is on the wire and
              // this lamina has not taken it. The value in front of the
              // reader is still the held one — saying "waiting" instead of
              // "held" would have them believe otherwise — so it is an extra
              // clause, not a different state.
              const waiting = Boolean(prov?.offer_waiting)
              const line =
                state === 'coupled'
                  ? `via ${prov?.gate ?? 'gate'} from ${prov?.from ?? 'another lamina'}`
                  : state === 'held'
                    ? `held from ${prov?.gate ?? 'gate'} — ${prov?.age ?? 0} cycles old` +
                      (waiting
                        ? ', and a newer one is waiting at the gate'
                        : ', gate shut')
                    : (prov?.detail ?? 'baseline (uncoupled)')
              return (
                <div key={attr.id} className="block" title={attr.description}>
                  <span className="flex items-baseline gap-1.5">
                    <span className="font-mono text-[10px] font-bold readout text-ink/70">
                      {attr.id}
                    </span>
                    <span className="font-mono text-[9px] readout text-ink/25 truncate">
                      {attr.name}
                    </span>
                    <span className="ml-auto font-mono text-[10px] tabular-nums text-ink shrink-0">
                      {fmtValue(inbound[attr.id])}
                      <span className="text-ink/30 text-[9px] ml-0.5">{attr.unit}</span>
                    </span>
                  </span>
                  <span
                    className={`block mt-0.5 font-mono text-[9px] readout tabular-nums ${
                      state === 'coupled'
                        ? 'text-oxy-dim/70'
                        : state === 'held'
                          ? 'text-warn-strong/80'
                          : 'text-ink/30'
                    }`}
                  >
                    {line}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}

      <div className="pt-1 border-t border-white/5 space-y-1">
        {index.inbound.length > 0 && (
          <p className="font-mono text-[9px] readout text-ink/25 leading-snug">
            An inbound value has no slider because it is not this lamina's to set. Uncoupled means
            no gate is feeding it yet and it is sitting on its declared baseline — a number that is
            legal rather than live. Held means a gate carried this one and has since shut, so it is
            neither: the age beside it is how long ago it stopped being current.
          </p>
        )}
        <p className="font-mono text-[9px] readout text-ink/25 leading-snug">
          The slider is the value you set. Ranges are each attribute's declared physiological span —
          edit the XML and these controls move with it. Nothing here reaches the stage; the model
          digests it first.
        </p>
        {sourceKind === 'simulated' && (
          <p className="font-mono text-[9px] readout text-warn/60 leading-snug">
            Readings are generated, not measured — noise around the baseline the lamina declares.
            No device or patient is connected.
          </p>
        )}
      </div>
    </div>
  )
}
