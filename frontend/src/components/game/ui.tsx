/**
 * Shared "Scientific Indie" primitives for the 2D game view.
 *
 * These implement the component rules in DESIGN.md directly — pill chips with
 * 2px borders, tonal card layers with a 1px inner stroke, thick rounded vitals
 * bars that flip crimson + bloom when a value leaves its safe band, and
 * solid/ghost buttons with a hover bloom.
 */
import type { ReactNode } from 'react'

// ── Card ──────────────────────────────────────────────────────────────────────

interface PanelProps {
  children: ReactNode
  className?: string
  /** Monospaced "sensor ID" style eyebrow. */
  eyebrow?: string
  title?: string
  action?: ReactNode
  /** Level 2 — backdrop blur + faint primary tint. */
  interactive?: boolean
}

export function Panel({ children, className = '', eyebrow, title, action, interactive }: PanelProps) {
  return (
    <section
      className={`rounded-card border border-white/10 shadow-inset1 p-6 ${
        interactive
          ? 'bg-crimson-container/5 backdrop-blur-lg'
          : 'bg-surface-low/80'
      } ${className}`}
    >
      {(eyebrow || title || action) && (
        <header className="flex items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            {eyebrow && (
              <p className="font-mono text-[11px] font-bold readout text-oxy/55 uppercase">
                {eyebrow}
              </p>
            )}
            {title && (
              <h3 className="font-display text-base font-semibold text-ink leading-tight mt-0.5">
                {title}
              </h3>
            )}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

// ── Chip ──────────────────────────────────────────────────────────────────────

type ChipTone = 'oxy' | 'crimson' | 'warn' | 'neutral'

const CHIP_TONE: Record<ChipTone, string> = {
  oxy:     'border-oxy-container/60 bg-oxy-container/15 text-oxy',
  crimson: 'border-crimson-container/60 bg-crimson-container/15 text-crimson',
  warn:    'border-warn-strong/60 bg-warn-strong/15 text-warn',
  neutral: 'border-white/15 bg-white/5 text-ink/70',
}

export function Chip({
  children,
  tone = 'neutral',
  dot = false,
  pulse = false,
}: {
  children: ReactNode
  tone?: ChipTone
  dot?: boolean
  pulse?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border-2 px-2.5 py-1
                  font-mono text-[11px] font-bold readout uppercase ${CHIP_TONE[tone]}`}
    >
      {dot && (
        <span
          className={`inline-block w-1.5 h-1.5 rounded-full bg-current ${pulse ? 'animate-pulse' : ''}`}
        />
      )}
      {children}
    </span>
  )
}

// ── Vitals bar ────────────────────────────────────────────────────────────────

interface VitalCardProps {
  sensorId: string
  label: string
  value: number
  unit: string
  min: number
  max: number
  safeLo: number
  safeHi: number
  decimals?: number
  /** Optional second line, e.g. "SBP / DBP". */
  sub?: string
}

export function VitalCard({
  sensorId,
  label,
  value,
  unit,
  min,
  max,
  safeLo,
  safeHi,
  decimals = 0,
  sub,
}: VitalCardProps) {
  const span = Math.max(1e-6, max - min)
  const pct = clampPct(((value - min) / span) * 100)
  const bandLeft = clampPct(((safeLo - min) / span) * 100)
  const bandWidth = clampPct(((safeHi - safeLo) / span) * 100)
  const out = value < safeLo || value > safeHi

  return (
    <div
      className={`rounded-el border p-4 bg-gradient-to-b transition-colors duration-300 ${
        out
          ? 'border-crimson-container/50 from-crimson-container/10 to-transparent animate-bloom-alert'
          : 'border-white/10 from-oxy-container/[0.07] to-transparent'
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="font-mono text-[10px] font-bold readout uppercase text-ink/40">{sensorId}</p>
        <p className="font-mono text-[10px] font-bold readout uppercase text-ink/40">{label}</p>
      </div>

      <div className="flex items-baseline gap-1.5 mt-1.5">
        <span
          className={`font-mono text-[28px] font-bold leading-none tabular-nums transition-colors ${
            out ? 'text-crimson-container' : 'text-ink'
          }`}
        >
          {value.toFixed(decimals)}
        </span>
        <span className="font-mono text-[11px] readout text-ink/45">{unit}</span>
      </div>

      {sub && <p className="font-mono text-[10px] readout text-ink/35 mt-1">{sub}</p>}

      {/* Thick rounded vitals bar with the safe band marked underneath. */}
      <div className="relative mt-3 h-2.5 rounded-full bg-surface-lowest overflow-hidden">
        <div
          className="absolute inset-y-0 bg-white/[0.07]"
          style={{ left: `${bandLeft}%`, width: `${bandWidth}%` }}
        />
        <div
          className={`absolute inset-y-0 left-0 rounded-full transition-[width,background-color] duration-300 ${
            out ? 'bg-crimson-container shadow-bloom-sm' : 'bg-oxy-container shadow-oxybloom-sm'
          }`}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="flex justify-between mt-1 font-mono text-[9px] readout text-ink/25">
        <span>{fmt(min)}</span>
        <span className={out ? 'text-crimson-container/80' : 'text-oxy/50'}>
          {fmt(safeLo)}–{fmt(safeHi)}
        </span>
        <span>{fmt(max)}</span>
      </div>
    </div>
  )
}

// ── Command button ────────────────────────────────────────────────────────────

interface CommandButtonProps {
  label: string
  blurb: string
  hotkey: string
  icon: ReactNode
  variant: 'primary' | 'ghost'
  /** 0 → ready, 1 → just fired. */
  cooldown: number
  disabled?: boolean
  onFire: () => void
}

export function CommandButton({
  label,
  blurb,
  hotkey,
  icon,
  variant,
  cooldown,
  disabled,
  onFire,
}: CommandButtonProps) {
  const busy = cooldown > 0
  const base =
    'group relative w-full overflow-hidden rounded-el px-4 py-3.5 text-left transition-all duration-200 disabled:opacity-40 disabled:cursor-not-allowed'
  const skin =
    variant === 'primary'
      ? 'bg-crimson-container text-white hover:shadow-bloom border-2 border-crimson-container'
      : 'border-2 border-oxy-container/70 text-oxy hover:bg-oxy-container/15 hover:shadow-oxybloom'

  return (
    <button
      type="button"
      onClick={onFire}
      disabled={disabled || busy}
      className={`${base} ${skin}`}
    >
      <span className="flex items-center gap-3">
        <span className="shrink-0 opacity-90">{icon}</span>
        <span className="min-w-0 flex-1">
          <span className="block font-mono text-[12px] font-bold readout uppercase truncate">
            {label}
          </span>
          {/* Wraps rather than truncates — the physiology is the point of the
              button, and clipping it to "↑rate, ↑pressure, va…" loses it. */}
          <span
            className={`block text-[11px] leading-snug mt-0.5 ${
              variant === 'primary' ? 'text-white/75' : 'text-oxy/60'
            }`}
          >
            {blurb}
          </span>
        </span>
        <kbd
          className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] font-bold ${
            variant === 'primary' ? 'border-white/40 text-white/80' : 'border-oxy/40 text-oxy/70'
          }`}
        >
          {hotkey}
        </kbd>
      </span>

      {/* Cooldown drains left-to-right along the bottom edge. */}
      {busy && (
        <span
          className="absolute bottom-0 left-0 h-[3px] bg-current opacity-70"
          style={{ width: `${cooldown * 100}%` }}
        />
      )}
    </button>
  )
}

// ── helpers ───────────────────────────────────────────────────────────────────

function clampPct(v: number) {
  return Math.max(0, Math.min(100, v))
}

function fmt(v: number) {
  return Number.isInteger(v) ? String(v) : v.toFixed(1)
}
