import type { LaminaOption } from '../../utils/api'

/**
 * The lamina, as something you pick rather than something you restart into.
 *
 * The list is the backend's answer to "what can you serve", so a lamina that
 * exists shows up here without an edit. A lamina whose arithmetic nobody has
 * written is offered and marked, not hidden: it loads, draws its whole
 * structure and shows a dash on every computed node, which is a fair picture of
 * "declared but not implemented" and a reasonable thing to want to look at.
 *
 * Picking one is a single act upstream — the schema and the socket are both
 * reopened with that id, together or not at all. Falling back to a plain label
 * when the catalogue is unavailable keeps the header honest rather than
 * offering a choice that would not work.
 */
export function LaminaPicker({
  laminae,
  current,
  onPick,
}: {
  laminae: LaminaOption[]
  current: string
  onPick: (id: string) => void
}) {
  const name = laminae.find((l) => l.id === current)?.name ?? current

  if (laminae.length < 2) {
    return (
      <span className="font-display text-lg font-extrabold tracking-tight text-crimson-container truncate">
        {name}
      </span>
    )
  }

  return (
    <label className="relative flex items-baseline group" title="Switch lamina">
      <select
        value={current}
        onChange={(e) => onPick(e.target.value)}
        className="appearance-none cursor-pointer bg-transparent pr-4 font-display text-lg font-extrabold
                   tracking-tight text-crimson-container outline-none
                   focus-visible:ring-2 focus-visible:ring-crimson-container/50 rounded-el"
      >
        {laminae.map((l) => (
          <option key={l.id} value={l.id} className="bg-surface-low text-ink font-body">
            {l.name}
            {l.implemented ? '' : ' — structure only'}
          </option>
        ))}
      </select>
      <span
        aria-hidden
        className="pointer-events-none absolute right-0 bottom-1 font-mono text-[9px] text-ink/35
                   group-hover:text-ink/70 transition-colors"
      >
        ▼
      </span>
    </label>
  )
}
