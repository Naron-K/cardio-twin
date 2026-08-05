/**
 * beatClock — one shared cardiac-cycle phase for the whole game view.
 *
 * The heart sprite and the ECG strip both need to be on the *same* beat, so
 * neither owns the clock: this module advances a single phase ∈ [0,1) at the
 * live heart rate and both read it from their own rAF loops.  Phase 0 is the
 * start of the cardiac cycle; the QRS and ventricular ejection both live in
 * the SYSTOLE window below, which is what keeps the trace and the squeeze
 * visually locked together.
 *
 * Heart rate is ramped rather than snapped so a slider drag or a command
 * button doesn't make the beat jump a quarter cycle.
 */

/** Ventricular systole: contraction + ejection. */
export const SYSTOLE: [number, number] = [0.08, 0.42]
/** Atrial systole — the "atrial kick" just before the next cycle. */
export const ATRIAL_SYSTOLE: [number, number] = [0.8, 0.99]

class BeatClock {
  phase = 0
  /** Displayed/effective rate, ramped toward `targetHr`. */
  hr = 72
  private targetHr = 72
  private running = false
  private paused = false
  private last = 0
  private raf: number | null = null
  private refs = 0

  setHr(hr: number) {
    if (Number.isFinite(hr) && hr > 20 && hr < 260) this.targetHr = hr
  }

  setPaused(paused: boolean) {
    this.paused = paused
  }

  /** Called by each consumer on mount; the loop stops when the last one leaves. */
  acquire(): () => void {
    this.refs++
    this.start()
    return () => {
      this.refs--
      if (this.refs <= 0) this.stop()
    }
  }

  private start() {
    if (this.running) return
    this.running = true
    this.last = performance.now()
    const tick = (now: number) => {
      // Clamp dt so a backgrounded tab doesn't fast-forward dozens of beats.
      const dt = Math.min(0.1, (now - this.last) / 1000)
      this.last = now
      this.hr += (this.targetHr - this.hr) * Math.min(1, dt * 3)
      if (!this.paused) {
        this.phase = (this.phase + (dt * this.hr) / 60) % 1
      }
      this.raf = requestAnimationFrame(tick)
    }
    this.raf = requestAnimationFrame(tick)
  }

  private stop() {
    this.running = false
    if (this.raf !== null) cancelAnimationFrame(this.raf)
    this.raf = null
  }
}

export const beatClock = new BeatClock()

/**
 * Raised-cosine bump over a phase window, wrapping across phase 1 → 0.
 * Returns 0 outside the window, peaking at 1 in the middle.
 */
export function bump(phase: number, [start, end]: [number, number]): number {
  const len = (end - start + 1) % 1 || 1
  const u = (phase - start + 1) % 1
  if (u > len) return 0
  return 0.5 - 0.5 * Math.cos(2 * Math.PI * (u / len))
}

/**
 * Idealised single-lead ECG as a function of cardiac phase, in arbitrary units
 * (R peak ≈ 1).  P–QRS–T built from gaussians.
 *
 * This is a *display* waveform derived from heart rate — the lamina model
 * computes lambda/CO/MAP, not a conduction waveform — so the UI labels it as
 * synthesised rather than measured.
 */
export function ecgAt(phase: number): number {
  const g = (centre: number, width: number, amp: number) => {
    let d = phase - centre
    if (d > 0.5) d -= 1
    if (d < -0.5) d += 1
    return amp * Math.exp(-(d * d) / (2 * width * width))
  }
  return (
    g(0.12, 0.022, 0.16) + // P
    g(0.194, 0.006, -0.1) + // Q
    g(0.21, 0.007, 1.0) + // R
    g(0.232, 0.008, -0.28) + // S
    g(0.4, 0.038, 0.3) // T
  )
}
