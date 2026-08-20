/**
 * views — which panels this lamina earns.
 *
 * The dashboard does not decide what to show. Each view declares what it needs
 * out of the schema, and a view whose requirement the lamina does not meet is
 * not rendered at all: a lamina with no composites has no vector-space tab, a
 * lamina with no tags has no feedback tab, and neither case needs a special
 * case anywhere else. That is the difference between a dashboard that happens
 * to work for one model and a skeleton that reads whatever it is given.
 *
 * `applies` is deliberately a predicate over the schema rather than over the
 * data, so the set of tabs is stable from the moment the schema loads and does
 * not flicker as ticks arrive. A view that has structure but no numbers yet
 * says so inside itself.
 */
import type { ReactNode } from 'react'
import type { LaminaIndex } from './schema'
import type { StreamTick } from '../hooks/useCardioStream'
import { ConvergenceChart } from '../components/twin/ConvergenceChart'
import { OutcomePanel } from '../components/twin/OutcomePanel'
import { LoopPanel } from '../components/twin/LoopPanel'
import { FunctionPanel } from '../components/twin/FunctionPanel'
import { SegmentPanel } from '../components/twin/SegmentPanel'
import { CompositePanel } from '../components/twin/CompositePanel'
import { MachineryPanel } from '../components/twin/MachineryPanel'
import { TagPanel } from '../components/twin/TagPanel'

export interface ViewProps {
  index: LaminaIndex
  ticks: StreamTick[]
  latest: StreamTick | null
}

export interface TwinView {
  id: string
  label: string
  /** Panel header: where the numbers come from, then what they are. */
  eyebrow: string
  title: string
  /** Whether this lamina declares enough for the view to mean anything. */
  applies: (index: LaminaIndex) => boolean
  render: (props: ViewProps) => ReactNode
}

/** Outcome id → the model's own within-tolerance verdict on the latest tick. */
export function withinByOutcome(latest: StreamTick | null): Record<string, boolean> {
  const out: Record<string, boolean> = {}
  for (const [id, o] of Object.entries(latest?.beforeAfter ?? {})) out[id] = o.within_after
  return out
}

export const VIEWS: TwinView[] = [
  {
    id: 'functions',
    label: 'Functions',
    eyebrow: 'Declared computations',
    title: 'What the model calculates, with the numbers in it',
    applies: (i) => i.functions.length > 0,
    render: ({ index, latest }) => (
      <FunctionPanel
        index={index}
        computed={latest?.computed ?? {}}
        sensors={latest?.sensors ?? {}}
        external={latest?.computedExternal ?? {}}
        feedback={latest?.computedFeedback ?? {}}
      />
    ),
  },
  {
    id: 'segments',
    label: 'Segments',
    eyebrow: 'Declared subsystems',
    title: 'Every attribute on the range the model declares for it',
    applies: (i) => i.segments.length > 0,
    render: ({ index, latest }) => (
      <SegmentPanel
        index={index}
        computed={latest?.computed ?? {}}
        sensors={latest?.sensors ?? {}}
        outcomes={latest?.beforeAfter ?? {}}
      />
    ),
  },
  {
    id: 'outcomes',
    label: 'Outcomes',
    eyebrow: 'Behavioural outcomes',
    title: 'Each outcome on its own tolerance band',
    applies: (i) => i.outcomes.length > 0,
    render: ({ index, latest }) => (
      <OutcomePanel outcomes={latest?.beforeAfter ?? {}} index={index} />
    ),
  },
  {
    id: 'convergence',
    label: 'Convergence',
    eyebrow: 'Outcomes over time · with and without the loop',
    title: 'Total deviation from the model’s targets',
    applies: (i) => i.outcomes.length > 0,
    render: ({ ticks }) => <ConvergenceChart ticks={ticks} height={150} />,
  },
  {
    id: 'loop',
    label: 'Feedback loop',
    eyebrow: 'X = X′ + X″',
    title: 'What the loop is holding, and what wired it there',
    applies: (i) => i.tags.length > 0,
    render: ({ index, ticks, latest }) => (
      <div className="space-y-3">
        <LoopPanel ticks={ticks} latest={latest} index={index} />
        <div className="pt-3 border-t border-white/10">
          <TagPanel
            index={index}
            firing={latest?.tagsEmitted ?? []}
            deltas={latest?.deltasPerAttr ?? {}}
            withinByOutcome={withinByOutcome(latest)}
          />
        </div>
      </div>
    ),
  },
  {
    id: 'composites',
    label: 'Vector space',
    eyebrow: 'Composites',
    title: 'The addresses a correction is delivered to',
    applies: (i) => i.composites.length > 0,
    render: ({ index, latest }) => (
      <CompositePanel
        index={index}
        vectors={latest?.vectors ?? {}}
        absorption={latest?.absorption ?? {}}
      />
    ),
  },
  {
    id: 'machinery',
    label: 'Machinery',
    eyebrow: 'Model configuration',
    title: 'What this lamina selected, and what it selected from',
    applies: () => true,
    render: ({ index }) => <MachineryPanel index={index} />,
  },
]

export function viewsFor(index: LaminaIndex): TwinView[] {
  return VIEWS.filter((v) => v.applies(index))
}
