import type { DaySummary } from '../../twin/dayView'
import { groupColourIndex } from '../../twin/dayView'

interface Props {
  day: DaySummary
}

const GROUP_BG = [
  'bg-day-g0',
  'bg-day-g1',
  'bg-day-g2',
  'bg-day-g3',
] as const

function groupBackground(index: number): string {
  return index >= 0 && index < GROUP_BG.length ? GROUP_BG[index] : 'bg-day-other'
}

export function DayLegend({ day }: Props) {
  const sd = Number.isInteger(day.model.sd) ? String(day.model.sd) : day.model.sd.toFixed(1)

  return (
    <div className="flex flex-wrap items-center gap-x-[18px] gap-y-2 font-body text-[13px] text-ink/70">
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-0 w-[22px] border-t-[3px] border-day-measured align-middle" />
        Measured
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-0 w-[22px] border-t-[3px] border-dashed border-day-model align-middle" />
        Model
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-[22px] rounded-sm bg-day-band align-middle" />
        ±1 SD ({sd} {day.pair.unit})
      </span>
      {day.events.map((event, index) => (
        <span key={`${event.group}-${index}`} className="flex items-center gap-1.5">
          <span
            className={`inline-block h-3 w-[22px] rounded-sm align-middle ${groupBackground(groupColourIndex(day, event.group))}`}
          />
          {event.label}
        </span>
      ))}
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-[22px] rounded-sm bg-day-other align-middle" />
        Other
      </span>
      <span className="flex items-center gap-1.5">
        <span className="inline-block h-3 w-[22px] rounded-sm border border-ink/20 bg-day-gap align-middle" />
        No data
      </span>
    </div>
  )
}
