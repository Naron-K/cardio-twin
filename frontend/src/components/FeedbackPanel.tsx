import { useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts'

export interface NormPoint {
  cycle: number
  norm: number
}

interface FeedbackPanelProps {
  cycle: number
  feedbackNorm: number
  diverged: boolean
  busy: boolean
  history: NormPoint[]
  stoppedReason?: 'settled' | 'max_cycles' | 'diverged' | null
  onStep: () => void
  onRun: (cycles: number, settledThreshold: number) => void
  onReset: () => void
}

const DEFAULT_RUN_CYCLES = 50
const DEFAULT_SETTLED_THRESHOLD = 1e-3

export function FeedbackPanel({
  cycle,
  feedbackNorm,
  diverged,
  busy,
  history,
  stoppedReason,
  onStep,
  onRun,
  onReset,
}: FeedbackPanelProps) {
  const [runCycles, setRunCycles] = useState<number>(DEFAULT_RUN_CYCLES)
  const [settledThreshold, setSettledThreshold] = useState<number>(
    DEFAULT_SETTLED_THRESHOLD
  )

  const normLabel = feedbackNorm.toExponential(2)
  const normTone =
    diverged
      ? 'text-red-400'
      : feedbackNorm < settledThreshold
        ? 'text-emerald-400'
        : 'text-amber-300'

  const reasonLabel =
    stoppedReason === 'settled'
      ? { text: 'Settled', tone: 'text-emerald-400' }
      : stoppedReason === 'diverged'
        ? { text: 'Diverged', tone: 'text-red-400' }
        : stoppedReason === 'max_cycles'
          ? { text: 'Max cycles', tone: 'text-slate-400' }
          : null

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg p-4 mb-6">
      {/* Header row: cycle counter + norm + last run reason */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <p className="text-slate-300 text-sm font-semibold">Feedback Loop</p>
          <p className="text-slate-500 text-xs mt-0.5">
            X = X′ (sensor) + X″ (feedback). Tweak sliders to advance one cycle.
          </p>
        </div>
        <div className="flex items-center gap-4">
          <div className="text-right">
            <p className="text-slate-500 text-xs uppercase tracking-wide">Cycle</p>
            <p className="text-slate-100 text-lg font-mono font-bold leading-none">
              {cycle}
            </p>
          </div>
          <div className="text-right">
            <p className="text-slate-500 text-xs uppercase tracking-wide">‖X″‖</p>
            <p className={`${normTone} text-lg font-mono font-bold leading-none`}>
              {normLabel}
            </p>
          </div>
          {reasonLabel && (
            <div className="text-right">
              <p className="text-slate-500 text-xs uppercase tracking-wide">Last run</p>
              <p className={`${reasonLabel.tone} text-xs font-semibold leading-none mt-1`}>
                {reasonLabel.text}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Controls */}
      <div className="flex flex-wrap items-end gap-3 mb-4 pb-4 border-b border-slate-700">
        <button
          onClick={onStep}
          disabled={busy || diverged}
          className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 active:bg-slate-500
                     disabled:opacity-40 disabled:cursor-not-allowed
                     text-slate-100 text-xs rounded-md border border-slate-600 transition-colors"
        >
          Step
        </button>
        <button
          onClick={() => onRun(runCycles, settledThreshold)}
          disabled={busy || diverged}
          className="px-3 py-1.5 bg-cyan-700 hover:bg-cyan-600 active:bg-cyan-500
                     disabled:opacity-40 disabled:cursor-not-allowed
                     text-slate-100 text-xs rounded-md border border-cyan-600 transition-colors"
        >
          Run {runCycles}
        </button>
        <button
          onClick={onReset}
          disabled={busy}
          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 active:bg-slate-600
                     disabled:opacity-40 disabled:cursor-not-allowed
                     text-slate-400 text-xs rounded-md border border-slate-700 transition-colors"
        >
          Reset
        </button>

        <div className="flex items-center gap-2 ml-auto">
          <label className="text-slate-500 text-xs">
            cycles
            <input
              type="number"
              min={1}
              max={10000}
              value={runCycles}
              onChange={(e) =>
                setRunCycles(Math.max(1, Math.min(10000, Number(e.target.value) || 1)))
              }
              className="ml-1.5 w-16 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5
                         text-slate-200 text-xs font-mono focus:outline-none focus:border-cyan-600"
            />
          </label>
          <label className="text-slate-500 text-xs">
            settle ≤
            <input
              type="number"
              step="0.0001"
              min={0}
              value={settledThreshold}
              onChange={(e) =>
                setSettledThreshold(Math.max(0, Number(e.target.value) || 0))
              }
              className="ml-1.5 w-20 bg-slate-900 border border-slate-700 rounded px-1.5 py-0.5
                         text-slate-200 text-xs font-mono focus:outline-none focus:border-cyan-600"
            />
          </label>
        </div>
      </div>

      {/* Norm history line chart */}
      <div className="h-44">
        {history.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <p className="text-slate-600 text-xs italic">
              No cycles yet — press Step or Run.
            </p>
          </div>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={history} margin={{ top: 8, right: 12, left: 0, bottom: 4 }}>
              <CartesianGrid stroke="#334155" strokeDasharray="2 4" />
              <XAxis
                dataKey="cycle"
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                label={{
                  value: 'cycle',
                  position: 'insideBottom',
                  offset: -2,
                  fill: '#64748b',
                  fontSize: 10,
                }}
              />
              <YAxis
                stroke="#64748b"
                tick={{ fill: '#94a3b8', fontSize: 11 }}
                tickFormatter={(v: number) => v.toExponential(0)}
                domain={[0, 'auto']}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: '#0f172a',
                  border: '1px solid #334155',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontSize: 12,
                }}
                formatter={(v: number) => [v.toExponential(3), 'feedback_norm']}
                labelFormatter={(c) => `cycle ${c}`}
              />
              <ReferenceLine
                y={settledThreshold}
                stroke="#10b981"
                strokeDasharray="4 4"
                label={{
                  value: 'settle',
                  fill: '#10b981',
                  fontSize: 10,
                  position: 'right',
                }}
              />
              <Line
                type="monotone"
                dataKey="norm"
                stroke="#06b6d4"
                strokeWidth={2}
                dot={false}
                isAnimationActive={false}
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}
