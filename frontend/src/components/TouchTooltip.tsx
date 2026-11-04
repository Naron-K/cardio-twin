/**
 * TouchTooltip — the `title` text, for a finger.
 *
 * Every description on the dashboard (what an input means, why a value is
 * stale, what a chip summarises) lives in a `title` attribute, and a touch
 * screen never hovers, so on the wall board all of it was unreachable.
 *
 * Rather than re-plumb a dozen components, this listens once, at the document,
 * for the long press Android already uses to ask "what is this?" — Chrome
 * reports it as a `contextmenu` event — finds the nearest element carrying a
 * title, and shows that text beside the finger. A mouse keeps its native
 * tooltip and its right-click menu: only a touch long-press is taken over.
 */
import { useEffect, useState } from 'react'

interface Tip {
  text: string
  x: number
  y: number
}

/** How long a tip stays up if nothing else dismisses it. */
const TIP_MS = 6_000
const TIP_WIDTH = 360
const EDGE = 12

function isTouchPress(e: MouseEvent): boolean {
  // Chrome dispatches contextmenu as a PointerEvent, so a long press says it
  // came from a finger; elsewhere, fall back to what the screen is.
  const type = (e as PointerEvent).pointerType
  if (type) return type === 'touch' || type === 'pen'
  return window.matchMedia?.('(pointer: coarse)').matches ?? false
}

/**
 * The nearest description above the pressed element: an HTML `title`
 * attribute, or the `<title>` child an SVG shape uses for the same job.
 */
function describe(start: Element): string | null {
  for (let el: Element | null = start; el; el = el.parentElement) {
    const attr = el.getAttribute('title')?.trim()
    if (attr) return attr
    if (el instanceof SVGElement) {
      const child = Array.from(el.children).find((c) => c.tagName.toLowerCase() === 'title')
      const text = child?.textContent?.trim()
      if (text) return text
    }
  }
  return null
}

export function TouchTooltip() {
  const [tip, setTip] = useState<Tip | null>(null)

  useEffect(() => {
    const onContextMenu = (e: MouseEvent) => {
      if (!isTouchPress(e)) return
      const text = e.target instanceof Element ? describe(e.target) : null
      if (!text) return
      e.preventDefault()
      setTip({ text, x: e.clientX, y: e.clientY })
    }
    const hide = () => setTip(null)

    document.addEventListener('contextmenu', onContextMenu)
    // The press that opened the tip ends with a pointerup, not a pointerdown,
    // so the next touch anywhere is what closes it.
    document.addEventListener('pointerdown', hide, true)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('resize', hide)
    return () => {
      document.removeEventListener('contextmenu', onContextMenu)
      document.removeEventListener('pointerdown', hide, true)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('resize', hide)
    }
  }, [])

  useEffect(() => {
    if (!tip) return
    const id = setTimeout(() => setTip(null), TIP_MS)
    return () => clearTimeout(id)
  }, [tip])

  if (!tip) return null

  // Above the finger, which covers whatever is below it, and kept on screen.
  const width = Math.min(TIP_WIDTH, window.innerWidth - EDGE * 2)
  const left = Math.min(Math.max(EDGE, tip.x - width / 2), window.innerWidth - width - EDGE)
  const above = tip.y > 160
  const style = above
    ? { left, width, bottom: window.innerHeight - tip.y + 28 }
    : { left, width, top: tip.y + 28 }

  return (
    <div
      role="tooltip"
      style={style}
      className="fixed z-[60] rounded-el border border-white/15 bg-surface-high/95 backdrop-blur-lg
                 shadow-inset1 px-4 py-3 font-body text-[13px] leading-relaxed text-ink
                 pointer-events-none animate-log-in whitespace-pre-line"
    >
      {tip.text}
    </div>
  )
}
