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
import { fetchOrganism, fetchOrganisms, fetchSchema } from '../../utils/api'
import type { OrganismListing, OrganismSchema } from '../../twin/organism'
import { indexLamina } from '../../twin/schema'
import type { LaminaIndex, LaminaSchema } from '../../twin/schema'
import { useOrganismStream } from '../../hooks/useOrganismStream'
import { InputRail } from './InputRail'
import { OrganismMap } from './OrganismMap'
import { Panel } from './ui'

interface Props {
  /** Which body to open, by id; null takes the backend's default. */
  organism?: string | null
  /** Called when the reader picks a different body, so the URL can follow. */
  onOrganism?: (id: string | null) => void
  onBack?: () => void
}

export function BodyDashboard({ organism = null, onOrganism, onBack }: Props) {
  const [schema, setSchema] = useState<OrganismSchema | null>(null)
  const [bodies, setBodies] = useState<OrganismListing[]>([])
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

  // The list of bodies is fetched once and separately: it is a menu, not
  // part of the body on screen, and a failure to load it should cost the
  // picker rather than the whole page.
  useEffect(() => {
    let cancelled = false
    fetchOrganisms()
      .then((list) => { if (!cancelled) setBodies(list.organisms) })
      .catch(() => { if (!cancelled) setBodies([]) })
    return () => { cancelled = true }
  }, [])

  // 5b — the two guards TwinDashboard has had since the lamina picker, and
  // this screen has not. A body picker makes both reachable here.
  //
  // The first: the schema is fetched once and the socket streams
  // continuously, so a backend switched onto a different body underneath an
  // open page would draw one body's structure over another body's numbers.
  // Both halves are TAGGED rather than cleared — clearing leaves a render
  // pass in between holding one model's values under another's labels, which
  // is the bug.
  const streamOrganism = latest?.organismId ?? ''
  const mismatch = Boolean(
    schema && streamOrganism && streamOrganism !== schema.organism_id
  )
  useEffect(() => {
    if (mismatch && streamOrganism) onOrganism?.(streamOrganism)
  }, [mismatch, streamOrganism, onOrganism])

  // The second: when the socket is not open the numbers on screen are a
  // photograph. The connection chip already says so; the numbers, which are
  // what anyone is actually reading, did not.
  const [now, setNow] = useState(() => Date.now())
  const lastTickAt = useMemo(() => Date.now(), [latest])
  useEffect(() => {
    if (status === 'open') return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [status])
  const staleAge =
    status !== 'open' && latest
      ? Math.max(0, Math.round((now - lastTickAt) / 1000))
      : null

  const live = mismatch ? null : latest
  const channels = live?.channels ?? []
  const laminaTicks = useMemo(() => live?.laminae ?? {}, [live])
  const channelStates = useMemo(
    () => Object.fromEntries(channels.map((c) => [c.id, c.state ?? 'shut'])),
    [channels]
  )

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
          {bodies.length > 1 && onOrganism && (
            <label className="flex items-center gap-2 text-ink/45">
              body
              <select
                value={schema.organism_id}
                onChange={(e) => onOrganism(e.target.value)}
                className="rounded-el border border-white/15 bg-surface-low px-2 py-1
                           font-mono text-[11px] text-ink/80 hover:border-oxy/50"
              >
                {bodies.map((body) => (
                  <option key={body.id} value={body.id}>
                    {body.name}
                  </option>
                ))}
              </select>
            </label>
          )}
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
          {/* The numbers are a photograph, and say so with their age. The
              connection chip above says the socket is down; this says the
              readings are, which is the half anyone is actually looking at. */}
          {staleAge !== null && (
            <span
              className="text-danger"
              title="The socket is not open — nothing on screen is updating."
            >
              Frozen · last tick {staleAge}s ago
            </span>
          )}
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

      {/* One body's structure over another body's numbers is the mismatch
          this guard exists to prevent, so no value is rendered at all until
          the schema catches up with what the socket is actually sending. */}
      {mismatch && (
        <div className="mb-gutter rounded-el border border-warn/40 bg-warn/5 p-4
                        font-mono text-[12px] leading-relaxed text-warn">
          This screen was drawn for <b>{schema.organism_id}</b> and the socket
          is sending <b>{streamOrganism}</b>. Values are held back rather than
          shown under the wrong model. Re-reading the structure for{' '}
          {streamOrganism}…
        </div>
      )}

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
          eyebrow="channels"
          title="Where a value crosses, and who has to agree"
          className="min-w-0"
        >
          <OrganismMap
            schema={schema}
            channels={channels}
            laminae={laminaTicks}
            channelStates={channelStates}
            gatesLocked={live?.gatesLocked}
          />

          {live && live.warnings.length > 0 && (
            <ul className="mt-4 space-y-1 font-mono text-[11px] text-warn">
              {live.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}

          <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-1 font-mono text-[11px] text-ink/55 sm:grid-cols-3">
            <div>
              <dt className="inline text-ink/40">cycle </dt>
              <dd className="inline text-ink/80">{live?.tick ?? 0}</dd>
            </div>
            <div>
              <dt className="inline text-ink/40">body |X''| </dt>
              <dd className="inline text-ink/80">
                {(live?.totalFeedbackNorm ?? 0).toFixed(5)}
              </dd>
            </div>
            <div>
              <dt className="inline text-ink/40">crossing </dt>
              <dd className="inline text-ink/80">
                {channels.filter((c) => c.state === 'crossing').length} /{' '}
                {schema.channels.length}
                {channels.some((c) => c.state === 'waiting') && (
                  <span className="text-warn">
                    {' '}· {channels.filter((c) => c.state === 'waiting').length} waiting
                  </span>
                )}
              </dd>
            </div>
          </dl>
        </Panel>
      </div>
    </div>
  )
}
