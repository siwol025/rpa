import { useState, type ReactNode } from 'react'
import { useMutation, type UseQueryResult } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { hasValidationError } from '../api/client'
import { fetchExcel, useBreakdown, useSummary, useTrend } from '../api/stats'
import { CATEGORIES, type Granularity, type Period, type StatsSummary } from '../api/types'
import { BarList } from '../components/BarList'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PeriodInput } from '../components/PeriodInput'
import { TrendChart } from '../components/TrendChart'
import { saveBlob } from '../lib/saveBlob'
import { categoryLabel } from '../lib/status'
import { useToast } from '../lib/toast'
import { dateParam, periodProblem, useUrlParams } from '../lib/useUrlParams'

const KPIS: [label: string, value: (s: StatsSummary) => number | null][] = [
  ['총 건수', (s) => s.total],
  ['미조치', (s) => s.action_open],
  ['검토 필요', (s) => s.needs_review],
  ['메타데이터 확인 필요', (s) => s.metadata_incomplete],
  ['실패', (s) => s.failed],
  ['정체', (s) => s.stale],
]

const UNITS: { value: Granularity; label: string }[] = [
  { value: 'day', label: '일' },
  { value: 'week', label: '주' },
  { value: 'month', label: '월' },
]

/** 5대 유형은 0건이어도 보여주고, 나중에 추가된 유형은 뒤에 붙인다 */
function categoryRows(s: StatsSummary) {
  const codes = [...new Set<string>([...CATEGORIES, ...Object.keys(s.by_category)])]
  return codes.map((c) => ({ name: categoryLabel(c), count: s.by_category[c] ?? 0 }))
}

function Panel({ title, side, children }: { title: string; side?: ReactNode; children: ReactNode }) {
  return (
    <section aria-label={title} className="panel">
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-2.5">
        <h2 className="m-0 text-[15px] font-semibold">{title}</h2>
        {side}
      </div>
      {children}
    </section>
  )
}

/** 패널마다 따로 불러온다. 하나가 실패해도 나머지는 보인다 */
function Loaded<T>({ query, isEmpty, children }: { query: UseQueryResult<T>; isEmpty?: (data: T) => boolean; children: (data: T) => ReactNode }) {
  if (query.error) return <ErrorState error={query.error} onRetry={() => query.refetch()} retrying={query.isFetching} />
  if (query.data === undefined) return <div aria-label="불러오는 중" role="status" className="skeleton h-28" />
  if (isEmpty?.(query.data)) return <EmptyState title="이 기간에는 상담이 없어요" />
  return <div className={query.isPlaceholderData ? 'opacity-60' : ''}>{children(query.data)}</div>
}

function ExcelButton({ period, disabled }: { period: Period; disabled: boolean }) {
  const toast = useToast()
  const excel = useMutation({
    mutationFn: () => fetchExcel(period),
    onSuccess: (blob) => {
      const range = [period.from, period.to].map((d) => d?.replaceAll('-', '') ?? '').join('-')
      saveBlob(blob, period.from || period.to ? `report_${range}.xlsx` : 'report.xlsx')
    },
    onError: (e) => toast(e.message),
  })
  return (
    <button type="button" className="btn" disabled={disabled || excel.isPending} onClick={() => excel.mutate()}>
      {excel.isPending ? '만드는 중' : '엑셀 다운로드'}
    </button>
  )
}

function Stats({ period }: { period: Period }) {
  const [unit, setUnit] = useState<Granularity>('day')
  const summary = useSummary(period)
  const trend = useTrend(period, unit)
  const agents = useBreakdown(period, 'agent')
  const clients = useBreakdown(period, 'client')
  const stale = summary.data?.stale ?? 0

  return (
    <>
      {stale > 0 && !summary.error && (
        <div className="alert mb-3.5">
          <span>오래 처리가 멈춘 상담이 {stale}건 있어요</span>
          <Link to="/calls?stale=true" className="font-semibold text-inherit underline">
            정체 건 보기
          </Link>
        </div>
      )}

      <div className="mb-3">
        <Loaded query={summary}>
          {(s) => (
            <>
              <div className="kpis">
                {KPIS.map(([label, value]) => (
                  <div key={label} role="group" aria-label={label} className="flex flex-col gap-0.5 px-4 py-3.5">
                    <span className="text-xs font-medium text-fg-2">{label}</span>
                    <b className="num text-[26px] leading-tight tracking-tight">
                      {value(s) ?? '-'}
                      {value(s) !== null && <small className="ml-0.5 text-[13px] font-medium text-fg-2">건</small>}
                    </b>
                  </div>
                ))}
              </div>
              {s.stale === null && <p className="mt-2 mb-0 text-xs text-muted">미조치와 정체는 서버의 통계 요약이 준비되면 보여요</p>}
            </>
          )}
        </Loaded>
      </div>

      <div className="mb-3 grid grid-cols-1 gap-3 min-[900px]:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <Panel
          title="기간별 추이"
          side={
            <div role="group" aria-label="단위" className="inline-flex rounded-md border border-line p-0.5">
              {UNITS.map((u) => (
                <button
                  key={u.value}
                  type="button"
                  aria-pressed={unit === u.value}
                  onClick={() => setUnit(u.value)}
                  className="cursor-pointer rounded px-3 py-1 text-[13px] font-medium text-fg-2 aria-pressed:bg-accent aria-pressed:text-accent-fg"
                >
                  {u.label}
                </button>
              ))}
            </div>
          }
        >
          {/* 구간이 서버 한도(400개)를 넘음 (규약 §4.3) */}
          {hasValidationError(trend.error, 'range_too_large') ? (
            <EmptyState title="기간이 길어서 이 단위로는 볼 수 없어요. 주나 월로 바꾸거나 기간을 줄여 주세요" />
          ) : (
            <Loaded query={trend} isEmpty={(d) => d.items.length === 0}>
              {(d) => <TrendChart items={d.items} granularity={d.granularity} />}
            </Loaded>
          )}
        </Panel>
        <Panel title="유형별 건수">
          <Loaded query={summary}>{(s) => <BarList rows={categoryRows(s)} />}</Loaded>
        </Panel>
      </div>

      <div className="grid grid-cols-1 gap-3 min-[900px]:grid-cols-2">
        <Panel title="담당자별 현황">
          <Loaded query={agents} isEmpty={(d) => d.items.length === 0}>
            {(d) => <BarList rows={d.items} />}
          </Loaded>
        </Panel>
        <Panel title="고객사별 현황">
          <Loaded query={clients} isEmpty={(d) => d.items.length === 0}>
            {(d) => <BarList rows={d.items} />}
          </Loaded>
        </Panel>
      </div>
    </>
  )
}

export function DashboardPage() {
  const { sp, set } = useUrlParams()
  const period: Period = { from: dateParam(sp, 'from'), to: dateParam(sp, 'to') }
  const problem = periodProblem(period)

  return (
    <>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-x-5 gap-y-3">
        <h1 className="m-0 text-[22px] font-bold tracking-tight">대시보드</h1>
        <div className="flex flex-wrap items-center gap-2">
          <PeriodInput value={period} onChange={set} />
          <ExcelButton period={period} disabled={!!problem} />
        </div>
      </div>
      {problem ? <EmptyState title={problem} /> : <Stats period={period} />}
    </>
  )
}
