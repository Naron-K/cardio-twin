/**
 * MachineryPanel — what this lamina picked, and what it picked *from*.
 *
 * Every mechanism in the pipeline is a named entry in a registry the engine
 * holds, and the XML selects one by name: a coupling rule for how X' and X''
 * combine, a solver for the behaviour functions, a deviation measure, an
 * emitter, a gate kernel, an adaptation kernel for the slow loop. Read on its
 * own, `gate_kernel="sigmoid_leaky_tanh"` looks like a fact about the world.
 * Read beside the registry it came from, it is visibly a choice — and when the
 * registry has one entry, that is worth knowing too.
 *
 * The gates below are the model's declared permeability conditions. They are
 * the closest thing the system has to a hard limit, and they live in XML where
 * a domain expert can change them, which is exactly why they are shown here
 * rather than being reimplemented as thresholds in a component.
 *
 * Nothing on this panel is live. It is what the model *is*, refetched only when
 * the schema is.
 */
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  index: LaminaIndex
}

/** Pipeline slot → the config field that selects from it. */
const SLOTS: { registry: string; label: string; chosen: (i: LaminaIndex) => string | undefined }[] = [
  { registry: 'coupling', label: 'X = X′ ⊕ X″', chosen: (i) => i.schema.feedback_config?.coupling_type },
  { registry: 'solver', label: 'Behaviour solver', chosen: (i) => i.schema.feedback_config?.behaviour_solver_type },
  { registry: 'adaptation_kernel', label: 'Slow loop', chosen: (i) => i.schema.feedback_config?.adaptation_kernel },
  // These three are chosen per tag, not per lamina, so the "chosen" column
  // reports the distinct set the tags actually use rather than one name.
  { registry: 'deviation', label: 'Deviation', chosen: (i) => distinct(i.tags.map((t) => t.deviation_type)) },
  { registry: 'emitter', label: 'Emitter', chosen: (i) => distinct(i.tags.map((t) => t.emitter)) },
  { registry: 'gate_kernel', label: 'Gate kernel', chosen: (i) => distinct(i.tags.map((t) => t.gate_kernel)) },
]

function distinct(values: string[]): string | undefined {
  const set = [...new Set(values.filter(Boolean))]
  return set.length ? set.join(', ') : undefined
}

export function MachineryPanel({ index }: Props) {
  const cfg = index.schema.feedback_config ?? {}
  const registries = index.schema.registries ?? {}
  const cadence = cfg.slow_loop_cadence ?? 0

  return (
    <div className="max-h-[268px] overflow-y-auto pr-1 grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-5">
      <div className="min-w-0">
        <p className="font-mono text-[10px] readout uppercase text-ink/35 mb-2">
          Mechanism selected · what was available
        </p>

        <div className="space-y-1">
          {SLOTS.map((slot) => {
            const options = registries[slot.registry] ?? []
            const chosen = slot.chosen(index)
            if (!chosen && options.length === 0) return null
            return (
              <div key={slot.registry} className="grid grid-cols-[112px_minmax(0,1fr)] gap-2 items-baseline">
                <span className="font-mono text-[9px] readout text-ink/35 truncate">{slot.label}</span>
                <span className="font-mono text-[10px] truncate">
                  <span className="text-oxy/85">{chosen ?? '—'}</span>
                  <span className="text-ink/25">
                    {' '}
                    of {options.length || 1}
                    {options.length > 1 && ` (${options.filter((o) => o !== chosen).join(', ')})`}
                  </span>
                </span>
              </div>
            )
          })}
        </div>

        <p className="font-mono text-[10px] readout uppercase text-ink/35 mt-3 mb-1.5">
          Slow loop
        </p>
        <p className="font-mono text-[10px] text-ink/55 leading-snug">
          {cadence > 0 ? (
            <>
              retunes every <span className="text-ink">{cadence}</span> fast cycles ·{' '}
              {Object.entries(cfg.adaptation_params ?? {})
                .map(([k, v]) => `${k} ${v}`)
                .join(' · ')}
            </>
          ) : (
            'disabled — cadence 0, so gain and operating point never move'
          )}
        </p>

        <p className="font-mono text-[9px] readout text-ink/25 leading-snug mt-2">
          Solver {cfg.behaviour_solver_type} at dt {cfg.behaviour_solver_dt}{' '}
          {cfg.behaviour_solver_unit} · lamina level {index.schema.lamina_level} · upper{' '}
          {index.schema.upper_lamina_id ?? 'none'} · lower {index.schema.lower_lamina_id ?? 'none'}
        </p>
      </div>

      <div className="min-w-0 border-l border-white/10 pl-5">
        <p className="font-mono text-[10px] readout uppercase text-ink/35 mb-2">
          Permeability gates · declared in XML
        </p>

        {index.gates.length === 0 ? (
          <p className="font-mono text-[10px] readout text-ink/30">
            This lamina declares no gates.
          </p>
        ) : (
          <div className="space-y-1">
            {index.gates.map((g, i) => (
              <div key={`${g.attribute}-${i}`} className="min-w-0">
                <p className="font-mono text-[10px] text-ink/70 truncate">
                  <span className="text-ink">{g.attribute}</span>
                  <span className="text-ink/30"> · {g.gate_type}</span>
                  {g.min !== null && <span className="text-ink/50"> ≥ {g.min}</span>}
                  {g.max !== null && <span className="text-ink/50"> ≤ {g.max}</span>}
                  {g.tolerance !== null && (
                    <span className="text-ink/50">
                      {' '}
                      ±{g.tolerance} across {(g.compare ?? []).join(' vs ')}
                    </span>
                  )}
                </p>
                <p className="font-mono text-[9px] readout text-ink/25 truncate">
                  on fail: {g.action_on_fail} · {g.flag}
                </p>
              </div>
            ))}
          </div>
        )}

        <p className="font-mono text-[9px] readout text-ink/25 leading-snug mt-2">
          A gate is the model's own limit, editable in the lamina file. The visualiser draws it and
          holds no threshold of its own.
        </p>
      </div>
    </div>
  )
}
