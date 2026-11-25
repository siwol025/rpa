import { DATE_MAX, DATE_MIN, type Period } from '../api/types'

export function PeriodInput({ value, onChange }: { value: Period; onChange: (key: 'from' | 'to', v: string) => void }) {
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <input type="date" aria-label="시작일" className="field" value={value.from ?? ''} min={DATE_MIN} max={value.to ?? DATE_MAX} onChange={(e) => onChange('from', e.target.value)} />
      <span className="text-muted">~</span>
      <input type="date" aria-label="종료일" className="field" value={value.to ?? ''} min={value.from ?? DATE_MIN} max={DATE_MAX} onChange={(e) => onChange('to', e.target.value)} />
    </span>
  )
}
