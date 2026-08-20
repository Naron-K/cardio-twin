/**
 * beatClock — one shared cardiac-cycle phase for the whole game view.
 *
 * Several views need to be on the *same* beat, so none of them owns the clock:
 * this module advances a single phase ∈ [0,1) at the live rate and each reads
 * it from its own rAF loop.  Phase 0 is the
 * start of the cardiac cycle; the QRS and ventricular ejection both live in
 * the SYSTOLE window below, which is what keeps the trace and the squeeze
 * visually locked together.
 *
 * Heart rate is ramped rather than snapped so a slider drag or a command
 * button doesn't make the beat jump a quarter cycle.
 */

/**
 * Fixed phase windows, the last consumer of which is the 16-bit sprite.
 * The anatomical stage no longer uses them: it derives its windows from the
 * model's `T_cycle` and `T_sys`, which is why a fast beat there spends a
 * larger share of the cycle in systole and these constants do not.
 */
export const SYSTOLE: [number, number] = [0.08, 0.42]
/** Atrial systole — the "atrial kick" just before the next cycle. */
export const ATRIAL_SYSTOLE: [number, number] = [0.8, 0.99]

const DEFAULT_CYCLE = 60 / 72

class BeatClock {
  phase = 0
  /** Effective cycle length in seconds, ramped toward `targetCycle`. */
  cycle = DEFAULT_CYCLE
  private targetCycle = DEFAULT_CYCLE
  private running = false
  private paused = false
  private last = 0
  private raf: number | null = null
  private refs = 0

  /** Effective rate, derived — nothing writes this directly any more. */
  get hr(): number {
    return 60 / this.cycle
  }

  /** Preferred entry point: cycle length straight from the model's `T_cycle`. */
  setCycle(seconds: number) {
    if (Number.isFinite(seconds) && seconds >= 0.2 && seconds <= 3) this.targetCycle = seconds
  }

  /** Legacy path for consumers that still think in bpm. */
  setHr(hr: number) {
    if (Number.isFinite(hr) && hr > 20 && hr < 260) this.setCycle(60 / hr)
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
      this.cycle += (this.targetCycle - this.cycle) * Math.min(1, dt * 3)
      if (!this.paused) {
        this.phase = (this.phase + dt / this.cycle) % 1
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
