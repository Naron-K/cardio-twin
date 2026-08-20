/**
 * CompositePanel — the vector space, which is where corrections are addressed.
 *
 * A `<composite>` groups attributes and carries two weight vectors. The
 * distribution vector is the fan-out multiplier a tag uses when it writes a
 * correction: the tag names a composite, and the composite decides how much of
 * that correction each of its members receives. So a composite is not a label —
 * it is the address the feedback loop delivers to, and until now nothing on
 * screen showed it.
 *
 * Each row draws the member's **normalised** position in its own declared
 * range, which is the number the composite arithmetic actually runs on, beside
 * the weight it carries and the absorbed value the twin computes from the two.
 * Weights come from the XML, normalised and absorbed values come from the tick,
 * and the tags listed against each composite come from the tag declarations.
 *
 * The absorption vector is frozen in v1 — the learning loop that would move it
 * is not enabled — so its weights are shown as declared rather than as
 * something being learned. Saying which of two vectors is live is the whole
 * reason to draw them separately.
 */
import { polarityLabel } from '../../twin/schema'
import type { CompositeSchema, LaminaIndex } from '../../twin/schema'

interface Props {
  index: LaminaIndex
  vectors: Record<string, Record<string, number>>
  absorption: Record<string, Record<string, number>>
}

export function CompositePanel({ index, vectors, absorption }: Props) {
  if (index.composites.length === 0) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        This lamina declares no composites, so the feedback loop has no addresses to write to.
      </p>
    )
  }

  return (
    <div className="max-h-[268px] overflow-y-auto pr-1 grid grid-cols-2 gap-x-5 gap-y-3">
      {index.composites.map((c) => (
        <Composite
          key={c.id}
          c={c}
          index={index}
          normalised={vectors[c.id] ?? {}}
          absorbed={absorption[c.id] ?? {}}
        />
      ))}
    </div>
  )
}

function Composite({
  c,
  index,
  normalised,
  absorbed,
}: {
  c: CompositeSchema
  index: LaminaIndex
  normalised: Record<string, number>
  absorbed: Record<string, number>
}) {
  const tags = index.tagsIntoComposite[c.id] ?? []
  const ids = c.attribute_ids ?? []
  const distribution = c.distribution_vector ?? []

  return (
    <section className="min-w-0">
      <header className="flex items-baseline gap-2">
        <h4 className="font-display text-[12px] font-semibold text-ink truncate">{c.name}</h4>
        <span className="font-mono text-[9px] readout text-ink/25 truncate">{c.id}</span>
      </header>

      <div className="mt-1.5 space-y-1">
        {ids.map((id, i) => {
          const attr = index.attribute(id)
          const n = normalised[id]
          const a = absorbed[id]
          const w = distribution[i]
          return (
            <div key={id} className="grid grid-cols-[52px_minmax(0,1fr)_74px] items-center gap-2">
              <span
                className={`font-mono text-[10px] truncate ${
                  attr?.source === 'SENSOR' ? 'text-ink/45' : 'text-oxy/75'
                }`}
              >
                {id}
              </span>
              <div className="relative h-2 rounded-full bg-surface-lowest">
                {/* Normalised position in the attribute's own declared range. */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-oxy-container/45"
                  style={{ width: `${clamp01(n) * 100}%` }}
                />
                {/* What the composite's weight leaves of it. */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-oxy-container"
                  style={{ width: `${clamp01(a) * 100}%` }}
                />
              </div>
              <span className="text-right font-mono text-[9px] tabular-nums text-ink/45">
                {n === undefined ? '—' : n.toFixed(2)}
                <span className="text-ink/20"> ×</span>
                {w === undefined ? '—' : w.toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>

      <p className="mt-1 font-mono text-[9px] readout text-ink/30 leading-snug">
        {tags.length === 0 ? (
          'no tag writes here — grouping only'
        ) : (
          <>
            written to by{' '}
            <span className="text-warn/70">
              {tags.map((t) => `${t.id} (${polarityLabel(t.polarity)})`).join(', ')}
            </span>
          </>
        )}
      </p>
    </section>
  )
}

function clamp01(v: number | undefined): number {
  if (v === undefined || !Number.isFinite(v)) return 0
  return Math.max(0, Math.min(1, v))
}
