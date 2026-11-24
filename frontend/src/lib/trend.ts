import type { Granularity, TrendItem } from '../api/types'

const DAY_MS = 86_400_000
const DATE = /^\d{4}-\d{2}-\d{2}$/
const toDate = (period: string) => new Date(`${period}T00:00:00Z`)

function next(period: string, g: Granularity): string {
  const d = toDate(period)
  if (g === 'month') d.setUTCMonth(d.getUTCMonth() + 1)
  else d.setTime(d.getTime() + (g === 'week' ? 7 : 1) * DAY_MS)
  return d.toISOString().slice(0, 10)
}

/** 상담이 없어 빠진 구간을 0으로 채운다 (가로축 간격을 실제 시간에 맞춤) */
export function fillBuckets(items: TrendItem[], g: Granularity): TrendItem[] {
  if (items.length === 0) return []
  const counts = new Map(items.map((i) => [i.period.slice(0, 10), i.count]))
  // 예상과 다른 형식이면 채우지 않고 받은 그대로 그린다
  if (![...counts.keys()].every((k) => DATE.test(k))) return items
  const sorted = [...counts.keys()].sort()
  const out: TrendItem[] = []
  for (let p = sorted[0]; p <= sorted[sorted.length - 1]; p = next(p, g)) out.push({ period: p, count: counts.get(p) ?? 0 })
  return out
}

export function periodLabel(period: string, g: Granularity): string {
  if (!DATE.test(period)) return period
  const [y, m, d] = period.split('-').map(Number)
  if (g === 'month') return `${y}년 ${m}월`
  return g === 'week' ? `${m}/${d} 시작 주` : `${m}/${d}`
}

/** 가로축의 짧은 표시 */
export function axisLabel(period: string, g: Granularity): string {
  if (!DATE.test(period)) return period
  const [, m, d] = period.split('-').map(Number)
  return g === 'month' ? `${m}월` : `${m}/${d}`
}
