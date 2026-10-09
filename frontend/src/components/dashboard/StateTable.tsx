/**
 * StateTable — every attribute the lamina declares, as two tables side by side.
 *
 * Inputs on the left, what the model computed from them on the right, because
 * that is the direction the data travels — and because one long table puts the
 * computed half below the fold, where an audience never sees it.
 *
 * Each table carries only the columns that mean something for its rows. An
 * input says which channel brought it in (or that it has none); a computed
 * value says what the feedback loop is holding on it and the model's own
 * verdict where it declares an outcome. A row the model has no outcome for
 * says so instead of borrowing a verdict from somewhere else.
 */
import type { ReactNode } from 'react'
import type { StreamTick } from '../../hooks/useCardioStream'
import type { AttributeSchema, LaminaIndex } from '../../twin/schema'
import { fmtValue } from '../../twin/schema'
import { outcomeForAttribute } from '../../twin/outcomes'

interface Props {
  index: LaminaIndex
  latest: StreamTick | null
}

export function StateTable({ index, latest }: Props) {
  const channels = index.schema.channel_mappings ?? {}
  const inputs = [...index.sensors, ...index.inbound]

  return (
    <div className="w-full h-full min-h-0 grid grid-cols-2 gap-5">
      <Section title={`Inputs · ${inputs.length}`}>
        <thead>
          <tr>
            <Th>Attribute</Th>
            <Th>Channel</Th>
            <Th right>Value</Th>
            <Th right>Range</Th>
          </tr>
        </thead>
        <tbody>
          {inputs.map((attr) => {
            const inbound = attr.source === 'INTER_LAMINA'
            const value = inbound ? latest?.inbound[attr.id] : latest?.sensors[attr.id]
            return (
              <tr key={attr.id} className="border-t border-white/5" title={attr.description}>
                <NameCell attr={attr} />
                <Td className="text-ink/45">
                  {inbound ? (
                    'other lamina'
                  ) : (
                    channels[attr.id] ?? <span className="text-warn/80">none</span>
                  )}
                </Td>
                <ValueCell attr={attr} value={value} />
                <RangeCell attr={attr} />
              </tr>
            )
          })}
        </tbody>
      </Section>

      <Section title={`Computed · ${index.computed.length}`}>
        <thead>
          <tr>
            <Th>Attribute</Th>
            <Th right>Value</Th>
            <Th right>Loop</Th>
            <Th right>Target</Th>
            <Th>Status</Th>
          </tr>
        </thead>
        <tbody>
          {index.computed.map((attr) => {
            const value = latest?.computed[attr.id]
            const xpp = latest?.computedFeedback[attr.id]
            const staleReason = latest?.staleComputed[attr.id]
            const outcome = latest ? outcomeForAttribute(latest.beforeAfter, attr.id) : undefined
            const declared = index.outcomesOfAttribute[attr.id]?.[0]

            let status: { text: string; tone: string }
            if (staleReason) status = { text: 'stale', tone: 'text-warn' }
            else if (outcome) {
              status = outcome.within_after
                ? { text: 'within', tone: 'text-oxy' }
                : { text: 'outside', tone: 'text-crimson-container' }
            } else if (declared) status = { text: 'waiting', tone: 'text-ink/30' }
            else status = { text: 'no outcome', tone: 'text-ink/25' }

            return (
              <tr
                key={attr.id}
                className="border-t border-white/5"
                title={staleReason ? `${attr.id}: ${staleReason}` : attr.description}
              >
                <NameCell attr={attr} />
                <ValueCell attr={attr} value={value} stale={Boolean(staleReason)} />
                <Td right className="text-warn/80">
                  {xpp !== undefined && Math.abs(xpp) > 1e-4
                    ? `${xpp > 0 ? '+' : ''}${fmtValue(xpp)}`
                    : ''}
                </Td>
                <Td right className="text-ink/55">
                  {declared ? `${fmtValue(declared.target_value)} ± ${fmtValue(declared.tolerance)}` : ''}
                </Td>
                <Td className={status.tone}>{status.text}</Td>
              </tr>
            )
          })}
        </tbody>
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="min-h-0 overflow-auto">
      <p className="font-mono text-[10px] font-bold readout uppercase text-oxy/55 mb-1">{title}</p>
      <table className="w-full border-collapse font-mono text-[11px] readout tabular-nums">
        {children}
      </table>
    </div>
  )
}

function NameCell({ attr }: { attr: AttributeSchema }) {
  return (
    <Td className="max-w-[160px] truncate">
      <span className="font-bold text-ink/85">{attr.id}</span>
      <span className="ml-2 text-ink/30">{attr.name}</span>
    </Td>
  )
}

/** The value with its unit, flagged when it sits outside the range the lamina declares. */
function ValueCell({
  attr,
  value,
  stale = false,
}: {
  attr: AttributeSchema
  value: number | undefined
  stale?: boolean
}) {
  const outOfRange = value !== undefined && (value < attr.physio_min || value > attr.physio_max)
  return (
    <Td
      right
      className={`font-bold ${
        stale
          ? 'text-ink/30 line-through decoration-warn/50'
          : outOfRange
            ? 'text-crimson-container'
            : 'text-ink'
      }`}
    >
      {fmtValue(value)}
      <span className="ml-1 font-normal text-ink/35 no-underline">{attr.unit}</span>
    </Td>
  )
}

function RangeCell({ attr }: { attr: AttributeSchema }) {
  return (
    <Td right className="text-ink/40">
      {fmtValue(attr.physio_min)}–{fmtValue(attr.physio_max)}
    </Td>
  )
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th
      className={`sticky top-0 bg-surface-lowest px-1.5 py-1.5 text-[10px] font-bold uppercase text-ink/35 ${
        right ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  )
}

function Td({
  children,
  right,
  className = '',
}: {
  children: ReactNode
  right?: boolean
  className?: string
}) {
  return (
    <td className={`px-1.5 py-[5px] whitespace-nowrap ${right ? 'text-right' : ''} ${className}`}>
      {children}
    </td>
  )
}
