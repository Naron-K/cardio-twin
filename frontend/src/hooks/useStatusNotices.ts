/**
 * useStatusNotices — the one place that decides what the dashboard tells the
 * reader about connection and model state, and in which words.
 *
 * The principle behind every notice below: say what happened, why, and what
 * the reader can do; never leave a frozen screen unexplained; never stack
 * duplicates; errors stay until they are resolved, confirmations leave by
 * themselves.
 *
 * Every notice this file can raise:
 *
 *   • 'connection', first connect slow — a cold host can take a minute, so a
 *     silent wait looks broken; the dashboard appears once the server answers.
 *   • 'connection', connection lost — frozen numbers need a reason and a way
 *     to hurry the retry, with the countdown kept current.
 *   • 'connection', refused — retrying cannot fix a refusal, so name it and
 *     point at a different model or a reload.
 *   • 'connection', data limit — the month's bandwidth is used and the server
 *     has stopped streaming on purpose; that must not read as an outage.
 *   • 'reconnected' — say the drop is over, and that the reader's inputs came
 *     back with it rather than being silently reset.
 *   • 'server:<code>:<id>' — a refused control change must not look accepted;
 *     the backend's code decides the words and its message supplies the detail.
 *   • 'update' — a tab left open on an old build should offer the new one
 *     without reloading under the reader's hands.
 *   • 'paused' — held values and locked inputs are a deliberate state, not a
 *     frozen screen, so name it and offer the way out.
 *   • 'diverged' — the safety limit firing is a fact about the last cycle that
 *     a reader can act on, but repeating it every tick would bury the screen.
 *   • 'reset' — confirm the loop reset so the warning above visibly clears.
 *   • 'tip-longpress' — the hold-to-explain gesture is invisible; teach it once
 *     per device without nagging.
 *
 * All returned callbacks are stable.  The action functions in `state` live in
 * a ref, so a parent that re-creates them on every render never re-fires any
 * effect here.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import type { NoticeApi } from '../components/notices/useNotices'
import { STREAM_LIMIT_CLOSE } from './useCardioStream'
import type { ServerNotice, StreamStatus } from './useCardioStream'

// ── Shared helpers ────────────────────────────────────────────────────────────

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

/** The words the backend's refusal code deserves on screen. */
function noticeTitle(code: string): string {
  switch (code) {
    case 'usage_warning':
      return 'Approaching the monthly data limit'
    case 'out_of_range':
      return 'Value outside the accepted range'
    case 'invalid_value':
      return 'That value is not a number'
    case 'unknown_input':
      return 'Not an input of this model'
    case 'bad_message':
      return 'Message not understood'
    case 'replay_end':
      return 'Recorded day finished'
    case 'measured_input':
      return 'Recorded input'
    case 'not_replaying':
      return 'Not replaying'
    case 'bad_speed':
      return 'Speed not available'
    case 'observed_input':
      return 'Measured input'
    case 'not_scenario':
      return 'Not a scenario'
    case 'unknown_preset':
      return 'Unknown preset'
    default:
      return 'Change not applied'
  }
}

/**
 * The running bundle's file name, or null on the dev server.
 *
 * The built page loads one module from /assets/, and its hashed name is the
 * build.  Development serves the entry from source instead, so there is no
 * asset name to compare and no update to offer.
 */
function runningBuild(): string | null {
  try {
    if (typeof document === 'undefined') return null
    const src = document
      .querySelector<HTMLScriptElement>('script[type="module"][src*="/assets/"]')
      ?.getAttribute('src')
    if (!src) return null
    const path = src.split(/[?#]/)[0]
    const segment = path.split('/').pop() ?? ''
    return segment || null
  } catch {
    return null
  }
}

interface VersionGuard {
  /** The build this tab has already offered, if any. */
  build: string | null
  inFlight: boolean
}

/**
 * One guard per notice queue rather than per hook, because the reconnect path
 * and the fifteen-minute poll share the same 'update' key.  `push` is stable
 * for the life of a NoticeContext, which makes it a safe map key; the map
 * itself is weak so a provider that goes away leaves nothing behind.
 */
const versionGuards = new WeakMap<NoticeApi['push'], VersionGuard>()

/**
 * Ask /health whether the deployed build differs from this tab's, and offer a
 * reload when it does.
 *
 * Every failure mode is silent on purpose: /health may not exist, may answer
 * with something that is not JSON, or may never answer at all.  None of those
 * is worth a notice, and none of them may become an unhandled rejection.
 */
function checkVersion(push: NoticeApi['push']): void {
  const running = runningBuild()
  if (!running) return

  let guard = versionGuards.get(push)
  if (!guard) {
    guard = { build: null, inFlight: false }
    versionGuards.set(push, guard)
  }
  if (guard.inFlight) return

  const current = guard
  current.inFlight = true

  void (async () => {
    try {
      if (typeof fetch !== 'function') return
      const response = await fetch('/health', { cache: 'no-store' })
      const payload: unknown = await response.json()
      const build = isRecord(payload) && typeof payload.build === 'string'
        ? payload.build
        : ''
      if (!build || build === running || current.build === build) return

      current.build = build
      push({
        key: 'update',
        tone: 'info',
        sticky: true,
        title: 'A new version of the dashboard is available',
        body: "Reload to use it. The inputs you changed go back to the model's baselines.",
        action: {
          label: 'Reload',
          onAction: () => window.location.reload(),
        },
      })
    } catch {
      // A missing or broken /health is not something the reader can act on.
    } finally {
      current.inFlight = false
    }
  })()
}

// ── Stream event handlers ─────────────────────────────────────────────────────

export function useStreamNoticeHandlers(api: NoticeApi): {
  onNotice: (n: ServerNotice) => void
  onReconnect: (restored: number) => void
} {
  const { push, dismiss } = api

  const onNotice = useCallback(
    (n: ServerNotice) => {
      // Backend frames are untrusted input here: a notice with a number where
      // a string belongs must still surface instead of taking the socket down.
      const record = isRecord(n as unknown) ? (n as unknown as Record<string, unknown>) : {}
      const code = typeof record.code === 'string' ? record.code : ''
      const id = typeof record.id === 'string' ? record.id : ''
      const message = typeof record.message === 'string' ? record.message : ''

      push({
        key: `server:${code}:${id}`,
        tone: record.level === 'info' ? 'info' : 'warning',
        ttlMs: code === 'usage_warning' || code === 'replay_end' ? 15_000 : 8000,
        title: noticeTitle(code),
        body: message || 'The server did not apply the last change.',
      })
    },
    [push],
  )

  const onReconnect = useCallback(
    (restored: number) => {
      const count =
        typeof restored === 'number' && Number.isFinite(restored)
          ? Math.max(0, Math.floor(restored))
          : 0
      const suffix =
        count === 1
          ? ' Your input change was re-applied.'
          : count > 1
            ? ` Your ${count} input changes were re-applied.`
            : ''

      push({
        key: 'reconnected',
        tone: 'success',
        ttlMs: 5000,
        title: 'Reconnected',
        body: `Live data is flowing again.${suffix}`,
      })
      dismiss('connection')

      // A backend restart that changed the build is exactly the moment a
      // long-lived display should be told there is a new page to load.
      checkVersion(push)
    },
    [push, dismiss],
  )

  return { onNotice, onReconnect }
}

// ── Status notices ────────────────────────────────────────────────────────────

export interface StatusState {
  status: StreamStatus
  everOpened: boolean
  attempts: number
  retryAt: number | null
  online: boolean
  closeReason: string | null
  closeCode: number | null
  retryNow: () => void
  paused: boolean
  resume: () => void
  diverged: boolean
  resetLoop: () => void
}

/** How long a first connect may stay silent before it gets a notice. */
const SLOW_CONNECT_MS = 3_000

/** The shortest gap between two divergence warnings. */
const DIVERGE_REPEAT_MS = 30_000

/** How often an open dashboard asks whether a newer build was deployed. */
const VERSION_CHECK_MS = 15 * 60_000

/** Set on the first touch tip, so a storage-less browser only sees it once. */
let tipShownThisLoad = false

export function useStatusNotices(
  api: NoticeApi,
  state: StatusState,
): { confirmReset: () => void } {
  const { push, dismiss } = api
  const { status, everOpened, attempts, retryAt, online, closeReason, closeCode, paused, diverged } = state

  // Action functions are read through a ref so replacing them on every render
  // cannot re-run any of the effects below.
  const actionsRef = useRef({
    retryNow: state.retryNow,
    resume: state.resume,
    resetLoop: state.resetLoop,
  })
  useEffect(() => {
    actionsRef.current = {
      retryNow: state.retryNow,
      resume: state.resume,
      resetLoop: state.resetLoop,
    }
  })

  // ── 1. First connection is slow ────────────────────────────────────────────
  const slowShownRef = useRef(false)

  useEffect(() => {
    const slow = status === 'connecting' && !everOpened

    if (!slow) {
      // Only take the notice back if this effect is the one that raised it; a
      // reconnect raises the same key through the effect below.
      if (slowShownRef.current) {
        slowShownRef.current = false
        dismiss('connection')
      }
      return
    }

    const timer = setTimeout(() => {
      slowShownRef.current = true
      push({
        key: 'connection',
        tone: 'info',
        sticky: true,
        dismissible: false,
        title: 'Connecting to the server…',
        body: 'If the server is starting up, this can take up to a minute. The dashboard appears as soon as it answers.',
      })
    }, SLOW_CONNECT_MS)

    return () => clearTimeout(timer)
  }, [status, everOpened, push, dismiss])

  // ── 2. Connection lost ─────────────────────────────────────────────────────
  const lost = everOpened && (status === 'closed' || status === 'connecting') && !closeReason

  // A clock that only runs while the loss notice is due, so the countdown is
  // recomputed once a second without polling anyone else's state.
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!lost) return

    const id = setInterval(() => setNow(Date.now()), 1_000)
    return () => clearInterval(id)
  }, [lost])

  useEffect(() => {
    if (!lost) return

    // `now` is the one-second trigger; Date.now() keeps the first paint of the
    // notice current even when the previous loss ended some time ago.
    const measuredAt = Math.max(now, Date.now())
    const seconds = retryAt !== null
      ? Math.max(0, Math.ceil((retryAt - measuredAt) / 1_000))
      : null
    const tail =
      status === 'connecting'
        ? 'Reconnecting…'
        : seconds !== null
          ? `Retrying in ${seconds}s.`
          : 'Reconnecting…'

    if (!online) {
      push({
        key: 'connection',
        tone: 'error',
        title: 'This display is offline',
        body: 'The network connection is down, so the numbers on screen are frozen. The dashboard reconnects by itself when the network is back.',
      })
      return
    }

    const retry = { label: 'Retry now', onAction: () => actionsRef.current.retryNow() }

    if (attempts >= 3) {
      push({
        key: 'connection',
        tone: 'error',
        title: "Can't reach the server",
        body:
          'The server may be restarting, which can take about a minute. ' +
          tail,
        action: retry,
      })
      return
    }

    push({
      key: 'connection',
      tone: 'error',
      title: 'Connection to the server lost',
      body: 'The numbers on screen are frozen until it reconnects. ' + tail,
      action: retry,
    })
  }, [lost, now, status, attempts, online, retryAt, push])

  // ── 3. The server refused this model ──────────────────────────────────────
  useEffect(() => {
    if (!(status === 'closed' && closeReason)) return
    // Used up, not broken: say so plainly, and that it is deliberate.
    if (closeCode === STREAM_LIMIT_CLOSE) {
      push({
        key: 'connection',
        tone: 'error',
        title: 'Live data is off for this month',
        body: `${closeReason}. This keeps the hosting bill from growing.`,
        action: {
          label: 'Reload',
          onAction: () => window.location.reload(),
        },
      })
      return
    }

    push({
      key: 'connection',
      tone: 'error',
      title: 'The server refused this model',
      body: `${closeReason}. Pick another model from the list, or reload the page.`,
      action: {
        label: 'Reload',
        onAction: () => window.location.reload(),
      },
    })
  }, [status, closeReason, closeCode, push])

  // ── 4. An open or deliberately suspended stream has nothing to explain ────
  useEffect(() => {
    if (status === 'open' || status === 'suspended') dismiss('connection')
  }, [status, dismiss])

  // ── 5/7. Version check, both on reconnect and on a slow poll while open ────
  useEffect(() => {
    if (status !== 'open') return

    checkVersion(push)
    const id = setInterval(() => checkVersion(push), VERSION_CHECK_MS)
    return () => clearInterval(id)
  }, [status, push])

  // ── 8. Paused ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!(paused && status === 'open')) {
      dismiss('paused')
      return
    }

    push({
      key: 'paused',
      tone: 'info',
      sticky: true,
      title: 'The model is paused',
      body: 'Values are held where they were, and the inputs are locked until you resume.',
      action: {
        label: 'Resume',
        onAction: () => actionsRef.current.resume(),
      },
    })
  }, [paused, status, push, dismiss])

  // ── 9. Feedback loop hit its safety limit ─────────────────────────────────
  const wasDivergedRef = useRef(false)
  const divergedAtRef = useRef(0)

  useEffect(() => {
    const was = wasDivergedRef.current
    wasDivergedRef.current = diverged

    if (!diverged || was) return

    const nowMs = Date.now()
    if (nowMs - divergedAtRef.current < DIVERGE_REPEAT_MS) return
    divergedAtRef.current = nowMs

    push({
      key: 'diverged',
      tone: 'warning',
      ttlMs: 10_000,
      title: 'The feedback loop hit its safety limit',
      body:
        "Its correction grew past the allowed size, so that cycle's correction was rolled back. If this keeps happening, reset the loop.",
      action: {
        label: 'Reset loop',
        onAction: () => actionsRef.current.resetLoop(),
      },
    })
  }, [diverged, push])

  // ── 10. Explicit reset confirmation ───────────────────────────────────────
  const confirmReset = useCallback(() => {
    push({
      key: 'reset',
      tone: 'success',
      ttlMs: 4_000,
      title: 'Feedback loop reset',
      body: 'The correction it was holding is cleared. Inputs keep the values you set.',
    })
    dismiss('diverged')
  }, [push, dismiss])

  // ── 11. The hold-to-explain gesture, once per device ──────────────────────
  useEffect(() => {
    let storageAvailable = true
    try {
      if (window.localStorage.getItem('cardiotwin.tip.longpress') !== null) return
    } catch {
      storageAvailable = false
    }
    if (tipShownThisLoad) return

    let fired = false
    const onPointerDown = (event: PointerEvent) => {
      if (fired || event.pointerType !== 'touch') return
      fired = true
      tipShownThisLoad = true
      window.removeEventListener('pointerdown', onPointerDown)

      if (storageAvailable) {
        try {
          window.localStorage.setItem('cardiotwin.tip.longpress', '1')
        } catch {
          // Storage can disappear between the read and the write; the module
          // flag still keeps the tip to one showing this page load.
        }
      }

      push({
        key: 'tip-longpress',
        tone: 'info',
        ttlMs: 9_000,
        title: 'Tip: press and hold to read more',
        body: 'Press and hold a label, a chip or a box to see what it means.',
      })
    }

    window.addEventListener('pointerdown', onPointerDown)
    return () => window.removeEventListener('pointerdown', onPointerDown)
  }, [push])

  return { confirmReset }
}
