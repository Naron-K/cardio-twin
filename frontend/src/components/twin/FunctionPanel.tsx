/**
 * FunctionPanel — one card per computation the model declares, running.
 *
 * A `<function>` in the lamina XML carries a step, a formula written for a
 * human, its input attribute ids and its output id. That is everything needed
 * to show the calculation actually happening: substitute the live values into
 * the inputs, put the live result on the output, and the reader watches the
 * model compute rather than being told that it did.
 *
 * There is no list of functions in this file. Add a `<function>` to any lamina
 * and a card appears here in its declared step order; delete one and the card
 * goes. The formula string is printed verbatim because it is the domain
 * expert's own sentence about what the function does, and paraphrasing it in
 * the UI would be the UI holding an opinion.
 *
 * The output row splits into X' and X'' where the loop is holding something,
 * so a value that disagrees with a hand-check of the formula explains itself:
 * the formula produced X', and the correction is the rest.
 */
import { fmtValue } from '../../twin/schema'
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  computed: Record<string, number>
  sensors: Record<string, number>
  external: Record<string, number>
  feedback: Record<string, number>
}

export function FunctionPanel({ index, computed, sensors, external, feedback }: Props) {
  const valueOf = (id: string) => (id in computed ? computed[id] : sensors[id])

  if (index.functions.length === 0) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        This lamina declares no functions.
      </p>
    )
  }

  return (
    <div className="max-h-[268px] overflow-y-auto pr-1 grid grid-cols-2 gap-2.5">
      {index.functions.map((fn) => {
        const out = index.attribute(fn.output)
        const xpp = feedback[fn.output] ?? 0
        // Below a thousandth of the correction's own attribute the split is
        // rounding dust and printing it implies a precision the loop has not got.
        const corrected = Math.abs(xpp) > 1e-4

        return (
          <article
            key={fn.id}
            className="rounded-el border border-white/10 bg-surface-lowest/60 p-3 min-w-0"
          >
            <header className="flex items-baseline gap-2">
              <span className="font-mono text-[9px] readout text-oxy/45 shrink-0">
                step {fn.step}
              </span>
              <h4 className="font-display text-[13px] font-semibold text-ink truncate">{fn.name}</h4>
            </header>

            {/* The expert's own sentence, not ours. */}
            <p className="mt-1.5 font-mono text-[10px] text-oxy/70 break-words leading-snug">
              {fn.formula}
            </p>

            <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1">
              {(fn.inputs ?? []).map((id) => {
                const attr = index.attribute(id)
                const raw = attr?.source === 'SENSOR'
                return (
                  <span
                    key={id}
                    className={`font-mono text-[10px] tabular-nums ${raw ? 'text-ink/45' : 'text-oxy/80'}`}
                    title={`${attr?.name ?? id}${raw ? ' · raw input' : ' · computed'}`}
                  >
                    {id}
                    <span className="text-ink/25"> = </span>
                    {fmtValue(valueOf(id))}
                  </span>
                )
              })}
              <span className="font-mono text-[11px] text-ink/30">→</span>
              <span className="font-mono text-[11px] font-bold tabular-nums text-ink">
                {fn.output}
                <span className="text-ink/25"> = </span>
                {fmtValue(computed[fn.output])}
                <span className="text-ink/30 text-[9px] ml-1">{out?.unit}</span>
              </span>
            </div>

            {corrected && (
              <p className="mt-1 font-mono text-[9px] readout text-warn/70">
                X′ {fmtValue(external[fn.output])} + X″ {xpp > 0 ? '+' : ''}
                {xpp.toFixed(3)} — the loop is holding part of this value
              </p>
            )}

            {fn.description && (
              <p className="mt-1.5 font-mono text-[9px] readout text-ink/30 leading-tight">
                {fn.description}
              </p>
            )}
          </article>
        )
      })}
    </div>
  )
}
