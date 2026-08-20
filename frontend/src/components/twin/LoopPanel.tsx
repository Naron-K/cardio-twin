/**
 * LoopPanel — what the adaptive loop is holding, and how it is retuning itself.
 *
 * Two things the model computes every tick and the 2D view used to show almost
 * none of:
 *
 *   • X″ per attribute.  Every attribute decomposes as X = X′ + X″ — an
 *     external value plus the correction the loop computed.  The chart that
 *     existed before plotted exactly two of them, CO and SV, because those were
 *     the two the stream hook happened to name.  This reads `computedFeedback`,
 *     which carries all of them, so an attribute the loop starts correcting
 *     appears here without a code change.
 *
 *   • The learned gain.  The slow loop retunes its own gain and operating point
 *     every N cycles, and reports only on the cycles it runs — so the series is
 *     held between reports rather than dropped to zero, which would draw a
 *     sawtooth that never happened.
 *
 * X″ arrives in each attribute's own unit, and mmHg cannot be compared against
 * mL by length.  The bars are therefore drawn as a fraction of each attribute's
 * declared physiological span, with the scale stated — the same trick the
 * deviation index uses with tolerance, for the same reason.
 */
import { useMemo } from 'react'
import type { Adaptation, StreamTick } from '../../hooks/useCardioStream'
import type { LaminaIndex } from '../../twin/schema'

interface Props {
  ticks: StreamTick[]
  latest: StreamTick | null
  index: LaminaIndex
}

const POSITIVE = '#00a5bb'
const NEGATIVE = '#c8801f'

/** Gain per outcome over the buffer, held flat between slow-loop reports. */
function gainSeries(ticks: StreamTick[]): Record<string, number[]> {
  const out: Record<string, number[]> = {}
  const held: Record<string, number> = {}
  for (const t of ticks) {
    for (const [outcomeId, a] of Object.entries(t.adaptation)) held[outcomeId] = a.gain
    for (const [outcomeId, g] of Object.entries(held)) {
      ;(out[outcomeId] ??= []).push(g)
    }
  }
  return out
}

/** Most recent adaptation record per outcome — likewise held between reports. */
function latestAdaptation(ticks: StreamTick[]): Record<string, Adaptation> {
  const held: Record<string, Adaptation> = {}
  for (const t of ticks) {
    for (const [outcomeId, a] of Object.entries(t.adaptation)) held[outcomeId] = a
  }
  return held
}

export function LoopPanel({ ticks, latest, index }: Props) {
  const gains = useMemo(() => gainSeries(ticks), [ticks])
  const adaptation = useMemo(() => latestAdaptation(ticks), [ticks])

  const corrections = useMemo(() => {
    const rows = Object.entries(latest?.computedFeedback ?? {}).map(([id, xpp]) => {
      const attr = index.attribute(id)
      const span = attr ? Math.max(1e-9, attr.physio_max - attr.physio_min) : 0
      return {
        id,
        xpp,
        unit: attr?.unit ?? '',
        // No declared span means no honest way to size the bar; it stays 0 and
        // the row reports the raw number only.
        fraction: span > 0 ? xpp / span : 0,
        external: latest?.computedExternal[id] ?? 0,
      }
    })
    return rows.sort((a, b) => Math.abs(b.fraction) - Math.abs(a.fraction))
  }, [latest, index])

  // Scale the bars to the largest correction on screen, floored so a settled
  // loop doesn't magnify rounding dust into a full-width bar.
  const scale = Math.max(0.02, ...corrections.map((c) => Math.abs(c.fraction)))
  const outcomeIds = Object.keys(gains).sort()

  if (!latest) {
    return (
      <p className="font-mono text-[11px] readout text-ink/40 py-8 text-center">
        Waiting for twin data…
      </p>
    )
  }

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_248px] gap-5">
      {/* ── X″ per attribute ─────────────────────────────────────────── */}
      <div className="min-w-0">
        <p className="font-mono text-[10px] readout uppercase text-ink/35 mb-2">
          Correction held per attribute · X″
        </p>

        <div className="max-h-[152px] overflow-y-auto pr-1 space-y-1">
          {corrections.map((c) => {
            const half = (Math.abs(c.fraction) / scale) * 50
            const positive = c.fraction >= 0
            return (
              <div key={c.id} className="grid grid-cols-[54px_minmax(0,1fr)_104px] items-center gap-2">
                <span className="font-mono text-[10px] readout text-ink/60 truncate">{c.id}</span>

                <div className="relative h-3 rounded-sm bg-surface-lowest">
                  {/* Zero — X″ = 0 is "the loop is asking for nothing here". */}
                  <div className="absolute left-1/2 inset-y-0 w-px bg-white/15" />
                  <div
                    className="absolute inset-y-[3px] rounded-sm"
                    style={{
                      left: positive ? '50%' : `${50 - half}%`,
                      width: `${Math.max(c.xpp === 0 ? 0 : 0.4, half)}%`,
                      background: positive ? POSITIVE : NEGATIVE,
                    }}
                  />
                </div>

                <span className="font-mono text-[10px] tabular-nums text-ink/55 text-right truncate">
                  {c.xpp > 0 ? '+' : ''}
                  {c.xpp.toFixed(3)}{' '}
                  <span className="text-ink/25">{c.unit}</span>
                </span>
              </div>
            )
          })}
        </div>

        <p className="font-mono text-[9px] readout text-ink/30 leading-snug mt-2">
          Bar length is X″ as a share of that attribute's physiological range, so quantities in
          different units can sit on one scale; full width = {(scale * 100).toFixed(1)}% of range.
          Right of centre the loop is pushing the attribute up, left it is pulling down.
        </p>
      </div>

      {/* ── Learned gain ─────────────────────────────────────────────── */}
      <div className="min-w-0 border-l border-white/10 pl-5">
        <p className="font-mono text-[10px] readout uppercase text-ink/35 mb-2">
          Gain the loop has learned
        </p>

        {outcomeIds.length === 0 ? (
          <p className="font-mono text-[10px] readout text-ink/30 leading-snug">
            The slow loop reports every N cycles and has not run yet in this window.
          </p>
        ) : (
          <div className="space-y-2">
            {outcomeIds.map((id) => {
              const series = gains[id]
              const a = adaptation[id]
              return (
                <div key={id} className="flex items-center gap-2">
                  <span className="font-mono text-[9px] readout text-ink/45 w-[74px] truncate">
                    {id.replace(/^target_/, '')}
                  </span>
                  <Sparkline values={series} />
                  <span className="font-mono text-[10px] tabular-nums text-ink/70 w-[42px] text-right">
                    {series[series.length - 1]?.toFixed(2) ?? '—'}
                  </span>
                  <span
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                      a?.settled ? 'bg-oxy-dim' : 'bg-warn-strong'
                    }`}
                    title={a?.settled ? 'settled' : 'still adapting'}
                  />
                </div>
              )
            })}
          </div>
        )}

        <p className="font-mono text-[9px] readout text-ink/30 leading-snug mt-2">
          Trend, not level: the slow loop only reports on the cycles it runs, so each line is held
          flat between reports. Dot is the model's own settled flag.
        </p>
      </div>
    </div>
  )
}

/** Trend of a short series — no axis, because only its shape is readable. */
function Sparkline({ values, width = 84, height = 18 }: { values: number[]; width?: number; height?: number }) {
  if (values.length < 2) {
    return <div style={{ width, height }} className="rounded-sm bg-surface-lowest" />
  }
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const span = Math.max(1e-9, hi - lo)
  const pad = 2
  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width
      const y = height - pad - ((v - lo) / span) * (height - pad * 2)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')

  return (
    <svg width={width} height={height} className="shrink-0 rounded-sm bg-surface-lowest" aria-hidden>
      <polyline points={points} fill="none" stroke={POSITIVE} strokeWidth={1.2} />
    </svg>
  )
}
