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

/**
 * An objective names one of the model's *behavioural outcomes* and asks the
 * player to settle it.  It deliberately carries no band of its own: the band is
 * `target ± tolerance` as the outcome declares them, read live off the tick, so
 * an edit to `circulatory_lamina.xml` moves the goalposts here without a code
 * change.  A mission over a quantity the model does not evaluate would have no
 * band to check against, which is why every entry is an outcome id.
 */
export interface Mission {
  id: string
  brief: string
  /** Behavioural outcome id, as declared in the lamina XML. */
  outcomeId: string
  /** Seconds the outcome must stay inside its tolerance to complete. */
  holdSec: number
  reward: number
}

export const MISSIONS: Mission[] = [
  {
    id: 'perfusion',
    brief: 'Settle mean arterial pressure inside the tolerance the model sets for it',
    outcomeId: 'target_map',
    holdSec: 18,
    reward: 250,
  },
  {
    id: 'output',
    brief: 'Bring cardiac output back to its target and hold it there',
    outcomeId: 'target_co',
    holdSec: 18,
    reward: 300,
  },
  {
    id: 'filling',
    brief: 'Restore stroke volume — the heart pumps what it receives, so work on filling',
    outcomeId: 'target_sv',
    holdSec: 15,
    reward: 350,
  },
]
