/**
 * BodyDashboard — the screen for a body rather than for one lamina.
 *
 * TwinDashboard shows one lamina in full: its stage, its computation map, its
 * outcomes, its loop. This shows several laminae and almost nothing about any
 * of them, because from up here a lamina is a box and the subject is the
 * seams between them. Anyone who wants a lamina in full opens that lamina's
 * own screen; duplicating a quarter of it here would produce two places that
 * answer the same question and eventually disagree.
 *
 * The rails on the left are the reason the screen is worth opening rather
 * than reading a log: a gate is shut until something makes it open, and
 * without a way to drive the sending lamina the diagram is a still life. They
 * are the same InputRail the single-lamina view uses, one per lamina, built
 * from that lamina's own schema — so the controls are generated, and a body
 * of four laminae grows four rails without an edit here.
 */
import { useEffect, useMemo, useState } from 'react'
import { fetchOrganism, fetchSchema } from '../../utils/api'
import type { OrganismSchema } from '../../twin/organism'
import { indexLamina } from '../../twin/schema'
import type { LaminaIndex, LaminaSchema } from '../../twin/schema'
import { useOrganismStream } from '../../hooks/useOrganismStream'
import { InputRail } from './InputRail'
import { OrganismMap } from './OrganismMap'
import { Panel } from './ui'

interface Props {
  /** Which organism file to open; null takes the backend's default. */
  organism?: string | null
  onBack?: () => void
}

export function BodyDashboard({ organism = null, onBack }: Props) {
  const [schema, setSchema] = useState<OrganismSchema | null>(null)
  const [indices, setIndices] = useState<Record<string, LaminaIndex>>({})
  const [error, setError] = useState<string | null>(null)

  const { latest, status, sendControl, closeReason } = useOrganismStream({
    organism,
    tickMs: 100,
  })

  // The body's own declaration, and then each lamina's, because the rails
  // need the declared ranges and names and the body payload only lists ids.
  // Fetched together so the screen never renders half-built: a rail drawn
  // before its schema arrives would have to invent a range, and an invented
  // range is a slider that lies about what the model accepts.
  useEffect(() => {
    let cancelled = false
    fetchOrganism(organism)
      .then(async (body) => {
        const schemas = await Promise.all(
          body.laminae.map((lamina) => fetchSchema(lamina.id))
        )
        if (cancelled) return
        setError(null)
        setSchema(body)
        setIndices(
          Object.fromEntries(
            body.laminae.map((lamina, i) => [
              lamina.id,
              indexLamina(schemas[i] as LaminaSchema),
            ])
          )
        )
      })
      .catch((e: unknown) => {
        if (cancelled) return
        const detail = (e as { response?: { data?: { detail?: { error?: string } } } })
          ?.response?.data?.detail?.error
        setError(detail ?? (e instanceof Error ? e.message : String(e)))
      })
    return () => { cancelled = true }
  }, [organism])

  const gates = latest?.gates ?? []
  const laminaTicks = useMemo(() => latest?.laminae ?? {}, [latest])

  if (error) {
    return (
      <div className="p-margin">
        <Panel eyebrow="organism" title="This body did not load">
          <p className="text-[13px] text-ink/70">{error}</p>
          <p className="mt-2 text-[12px] text-ink/45">
            A body is refused by name rather than quietly falling back to
            another one, for the same reason an unknown lamina is: a diagram of
            a body nobody asked for arrives looking like a success.
          </p>
          {onBack && (
            <button
              onClick={onBack}
              className="mt-4 font-mono text-[11px] text-oxy hover:text-oxy-container"
            >
              ← back
            </button>
          )}
        </Panel>
      </div>
    )
  }

  if (!schema) {
    return (
      <div className="p-margin font-mono text-[12px] text-ink/50">
        Loading the body…
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-surface text-ink p-margin">
      <header className="mb-gutter flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-[11px] font-bold uppercase text-oxy/55">
            {schema.organism_id}
          </p>
          <h1 className="font-display text-2xl font-semibold leading-tight">
            {schema.name || 'Body'}
          </h1>
          {schema.description && (
            <p className="mt-1 max-w-3xl text-[13px] leading-snug text-ink/60">
              {schema.description}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-4 font-mono text-[11px]">
          <span
            className={
              status === 'open'
                ? 'text-oxy'
                : status === 'connecting'
                  ? 'text-warn'
                  : 'text-danger'
            }
          >
            ● {closeReason ?? status}
          </span>
          <button
            onClick={() => sendControl({ type: 'reset' })}
            className="rounded-el border border-white/15 px-3 py-1 text-ink/70 hover:border-oxy/50 hover:text-oxy"
          >
            reset
          </button>
          {onBack && (
            <button onClick={onBack} className="text-oxy hover:text-oxy-container">
              ← back
            </button>
          )}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-gutter xl:grid-cols-[340px_minmax(0,1fr)]">
        <div className="flex flex-col gap-gutter">
          {schema.laminae.map((lamina) => {
            const index = indices[lamina.id]
            const tick = laminaTicks[lamina.id]
            if (!index) return null
            return (
              <Panel
                key={lamina.id}
                eyebrow={lamina.id}
                title={lamina.name || lamina.id}
              >
                <InputRail
                  index={index}
                  values={tick?.sensors ?? {}}
                  inbound={tick?.inbound ?? {}}
                  inboundProvenance={tick?.inboundProvenance ?? {}}
                  disabled={status !== 'open'}
                  onChange={(id, value) =>
                    // A body needs to be told WHICH lamina a reading is for.
                    // "set HR" is ambiguous once there is more than one, and
                    // guessing is how a control ends up driving the wrong
                    // model while looking like it works.
                    sendControl({ type: 'set_sensor', lamina: lamina.id, id, value })
                  }
                />
              </Panel>
            )
          })}
        </div>

        <Panel
          eyebrow="permeability gates"
          title="Where a value crosses from one lamina to another"
          className="min-w-0"
        >
          <OrganismMap
            schema={schema}
            gates={gates}
            laminae={laminaTicks}
            gatesLocked={latest?.gatesLocked}
          />

          {latest && latest.warnings.length > 0 && (
            <ul className="mt-4 space-y-1 font-mono text-[11px] text-warn">
              {latest.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}

          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[11px] text-ink/55 sm:grid-cols-3">
            <div>
              <dt className="inline text-ink/40">cycle </dt>
              <dd className="inline text-ink/80">{latest?.tick ?? 0}</dd>
            </div>
            <div>
              <dt className="inline text-ink/40">body |X''| </dt>
              <dd className="inline text-ink/80">
                {(latest?.totalFeedbackNorm ?? 0).toFixed(5)}
              </dd>
            </div>
            <div>
              <dt className="inline text-ink/40">gates </dt>
              <dd className="inline text-ink/80">
                {gates.filter((g) => g.open).length} / {schema.gates.length} open
              </dd>
            </div>
          </dl>
        </Panel>
      </div>
    </div>
  )
}
