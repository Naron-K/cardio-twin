/**
 * Bottom-centred notice stack for the dashboard.
 *
 * Each tone has one job, and the component is written so that job stays
 * legible at a glance:
 *
 *   error   — something is broken and the screen cannot be trusted until it
 *             recovers.  It is sticky and should offer a recovery action.
 *   warning — a request was not carried out, and the body says why.
 *   info    — a state the reader should know about, such as being paused.
 *   success — confirms an action or a recovery; it disappears by itself.
 *
 * The newest notice sits nearest the bottom edge, so the reader's eye lands on
 * the latest thing that happened.  Every control keeps a 44px touch target:
 * this app runs on a touch display.
 */
import type { Notice, NoticeApi, NoticeTone } from './useNotices'

// ── Tone maps ─────────────────────────────────────────────────────────────────

const CARD_TONE: Record<NoticeTone, string> = {
  info:    'border-oxy-container/50',
  success: 'border-oxy-container/70 shadow-oxybloom-sm',
  warning: 'border-warn-strong/70',
  error:   'border-crimson-container/80 shadow-bloom-sm',
}

const DOT_TONE: Record<NoticeTone, string> = {
  info:    'bg-oxy-container',
  success: 'bg-oxy-container',
  warning: 'bg-warn-strong',
  error:   'bg-crimson-container animate-pulse',
}

const ACTION_TONE: Record<NoticeTone, string> = {
  info:    'border-oxy-container/60 bg-oxy-container/15 text-oxy',
  success: 'border-oxy-container/60 bg-oxy-container/15 text-oxy',
  warning: 'border-warn-strong/60 bg-warn-strong/15 text-warn',
  error:   'border-crimson-container/60 bg-crimson-container/15 text-crimson',
}

// ── Stack ─────────────────────────────────────────────────────────────────────

export function NoticeStack({ api }: { api: NoticeApi }) {
  // Newest first in the queue; the DOM paints oldest first so the newest card
  // ends up closest to the bottom edge.
  const ordered: Notice[] = [...api.notices].reverse()

  return (
    <section
      aria-label="Notifications"
      className="fixed inset-x-0 bottom-6 z-50 flex flex-col items-center gap-3 px-4 pointer-events-none"
    >
      {ordered.map((notice) => (
        <article
          key={notice.key}
          role={notice.tone === 'error' ? 'alert' : 'status'}
          aria-live={notice.tone === 'error' ? undefined : 'polite'}
          className={`pointer-events-auto w-[min(560px,100%)] rounded-card border-2 shadow-inset1 backdrop-blur-lg bg-surface-low/95 px-5 py-4 flex items-start gap-4 animate-log-in ${CARD_TONE[notice.tone]}`}
        >
          <span
            className={`mt-1.5 w-2.5 h-2.5 rounded-full shrink-0 ${DOT_TONE[notice.tone]}`}
          />

          <div className="flex-1 min-w-0">
            <h3 className="font-display text-[15px] font-semibold text-ink leading-snug">
              {notice.title}
            </h3>
            {notice.body && (
              <p className="mt-1 font-body text-[13px] leading-relaxed text-ink/70">
                {notice.body}
              </p>
            )}
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {notice.action && (
              <button
                type="button"
                onClick={notice.action.onAction}
                className={`min-h-[44px] px-4 rounded-full border-2 font-mono text-[11px] font-bold readout uppercase shrink-0 ${ACTION_TONE[notice.tone]}`}
              >
                {notice.action.label}
              </button>
            )}

            {notice.dismissible !== false && (
              <button
                type="button"
                onClick={() => api.dismiss(notice.key)}
                aria-label="Dismiss"
                className="min-w-[44px] min-h-[44px] rounded-full text-ink/45 hover:text-ink hover:bg-white/10 shrink-0"
              >
                ✕
              </button>
            )}
          </div>
        </article>
      ))}
    </section>
  )
}
