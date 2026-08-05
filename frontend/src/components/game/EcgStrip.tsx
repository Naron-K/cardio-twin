/**
 * EcgStrip — sweeping monitor trace, drawn on canvas with a glow-trace stroke
 * (DESIGN.md: line charts get a 2px same-colour bloom to read as an emissive
 * screen).
 *
 * The waveform is *synthesised* from the live heart rate — the lamina model
 * computes λ / CO / MAP, not a conduction waveform — so the panel labels it as
 * such rather than passing it off as measured data.  The sweep speed is fixed
 * (like a real monitor), so a faster HR genuinely packs more complexes into the
 * window instead of just animating quicker.
 */
import { useEffect, useRef } from 'react'
import { beatClock, ecgAt } from '../../game/beatClock'

interface Props {
  hr: number
  paused?: boolean
  /** Out-of-band vitals switch the trace from oxy-blue to crimson. */
  alert?: boolean
  height?: number
}

const SWEEP_PX_PER_SEC = 110
const ERASE_WIDTH = 26

export function EcgStrip({ hr, paused = false, alert = false, height = 96 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const wrapRef = useRef<HTMLDivElement | null>(null)
  const live = useRef({ alert, paused })
  useEffect(() => {
    live.current = { alert, paused }
  }, [alert, paused])

  useEffect(() => {
    beatClock.setHr(hr)
  }, [hr])

  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let w = 0
    let h = 0
    let dpr = 1
    let x = 0
    let prevY = height / 2

    const resize = () => {
      dpr = Math.min(2, window.devicePixelRatio || 1)
      w = wrap.clientWidth
      h = height
      canvas.width = Math.max(1, Math.floor(w * dpr))
      canvas.height = Math.max(1, Math.floor(h * dpr))
      canvas.style.width = `${w}px`
      canvas.style.height = `${h}px`
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, w, h)
      x = 0
      prevY = h / 2
    }
    resize()

    const ro = new ResizeObserver(resize)
    ro.observe(wrap)

    const release = beatClock.acquire()
    let raf = 0
    let last = performance.now()

    const frame = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000)
      last = now

      if (!live.current.paused && w > 0) {
        const colour = live.current.alert ? '#ff525f' : '#00e3fd'
        const step = SWEEP_PX_PER_SEC * dt
        const prevX = x
        x += step

        // Blank the strip just ahead of the cursor — the classic monitor gap.
        ctx.clearRect(x, 0, ERASE_WIDTH, h)
        if (x + ERASE_WIDTH > w) ctx.clearRect(0, 0, x + ERASE_WIDTH - w, h)

        const baseline = h * 0.62
        const amp = h * 0.42
        const y = baseline - ecgAt(beatClock.phase) * amp

        ctx.save()
        ctx.lineCap = 'round'
        ctx.lineJoin = 'round'
        ctx.strokeStyle = colour
        ctx.shadowColor = colour
        ctx.shadowBlur = 9
        ctx.lineWidth = 2
        ctx.beginPath()
        if (x >= w) {
          // Wrap without drawing a horizontal streak back across the strip.
          ctx.moveTo(prevX, prevY)
          ctx.lineTo(w, y)
          x -= w
        } else {
          ctx.moveTo(prevX, prevY)
          ctx.lineTo(x, y)
        }
        ctx.stroke()
        ctx.restore()

        // Leading dot.
        ctx.save()
        ctx.fillStyle = colour
        ctx.shadowColor = colour
        ctx.shadowBlur = 12
        ctx.beginPath()
        ctx.arc(x, y, 2.4, 0, Math.PI * 2)
        ctx.fill()
        ctx.restore()

        prevY = y
      }

      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)

    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
      release()
    }
  }, [height])

  return (
    <div
      ref={wrapRef}
      className="relative w-full overflow-hidden rounded-el bg-surface-lowest stage-grid scanlines"
      style={{ height }}
    >
      <canvas ref={canvasRef} className="block" />
    </div>
  )
}
