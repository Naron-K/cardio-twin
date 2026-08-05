/**
 * protocol — what the player can *do* and what they're asked to achieve.
 *
 * Commands are deliberately not magic: each one nudges real sensor attributes
 * of the circulatory lamina and the resulting MAP / CO / SV come back through
 * the normal WebSocket tick, feedback loop and all.  Deltas are expressed as a
 * signed fraction of each sensor's physiological span so they stay sane no
 * matter what ranges the XML declares.
 */

export interface Command {
  id: string
  label: string
  blurb: string
  hotkey: string
  variant: 'primary' | 'ghost'
  cooldownMs: number
  /** sensor id → signed fraction of (physio_max − physio_min). */
  deltas: Record<string, number>
  /** Line written to the mission terminal when fired. */
  log: string
}

export const COMMANDS: Command[] = [
  {
    id: 'adrenaline',
    label: 'ADRENALINE BOOST',
    blurb: 'Sympathetic: ↑rate, ↑pressure, vasoconstriction',
    hotkey: '1',
    variant: 'primary',
    cooldownMs: 4500,
    deltas: { HR: +0.14, SBP: +0.11, r: -0.07 },
    log: 'Adrenaline pushed — sympathetic drive up, peripheral vessels constricted',
  },
  {
    id: 'exercise',
    label: 'EXERCISE REGIMEN',
    blurb: 'Exertion: ↑rate, ↑ventricular filling',
    hotkey: '2',
    variant: 'ghost',
    cooldownMs: 4500,
    deltas: { HR: +0.17, EDV: +0.14, SBP: +0.06 },
    log: 'Exertion started — venous return and preload raised',
  },
  {
    id: 'calm',
    label: 'CALM BREATHING',
    blurb: 'Parasympathetic: ↓rate, vasodilation',
    hotkey: '3',
    variant: 'ghost',
    cooldownMs: 4500,
    deltas: { HR: -0.14, SBP: -0.09, r: +0.07 },
    log: 'Slow breathing — vagal tone up, vessels dilated',
  },
]

export interface Mission {
  id: string
  brief: string
  metric: 'map' | 'co' | 'hr'
  lo: number
  hi: number
  unit: string
  /** Seconds the metric must stay inside the band to complete. */
  holdSec: number
  reward: number
}

export const MISSIONS: Mission[] = [
  {
    id: 'perfusion',
    brief: 'Hold mean arterial pressure inside the safe perfusion band',
    metric: 'map',
    lo: 70,
    hi: 100,
    unit: 'mmHg',
    holdSec: 18,
    reward: 250,
  },
  {
    id: 'output',
    brief: 'Bring cardiac output back to resting level and keep it there',
    metric: 'co',
    lo: 4.2,
    hi: 6.2,
    unit: 'L/min',
    holdSec: 18,
    reward: 300,
  },
  {
    id: 'rhythm',
    brief: 'Bring heart rate into the physiological band without dropping perfusion',
    metric: 'hr',
    lo: 60,
    hi: 85,
    unit: 'bpm',
    holdSec: 15,
    reward: 350,
  },
]

/** Display ranges for the vitals bars (game HUD, not model limits). */
export const VITAL_RANGE = {
  hr:  { min: 40,  max: 180, safeLo: 60,  safeHi: 100 },
  map: { min: 40,  max: 140, safeLo: 70,  safeHi: 100 },
  co:  { min: 1,   max: 12,  safeLo: 4.2, safeHi: 6.2 },
  sbp: { min: 70,  max: 200, safeLo: 100, safeHi: 130 },
  sv:  { min: 20,  max: 140, safeLo: 55,  safeHi: 95  },
} as const
