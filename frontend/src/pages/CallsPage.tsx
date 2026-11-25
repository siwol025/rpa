import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useCalls } from '../api/calls'
import { useBreakdown } from '../api/stats'
import { CATEGORIES, PAGE_MAX, Q_MAX_LENGTH, STATUSES, type CallListParams, type CallSort } from '../api/types'
import { CategoryChip } from '../components/CategoryChip'
import { EmptyState } from '../components/EmptyState'
import { ErrorState } from '../components/ErrorState'
import { PeriodInput } from '../components/PeriodInput'
import { StatusBadges } from '../components/StatusBadge'
import { formatDateTime, formatSeconds } from '../lib/format'
import { actionLabel, categoryLabel, STATUS_LABEL } from '../lib/status'
import { dateParam, oneOf, periodProblem, useUrlParams } from '../lib/useUrlParams'

const PAGE_SIZE = 20
const HEADERS = ['통화 일시', '담당자', '고객사', '유형', '질문 요약', '통화 시간', '조치 상태', '처리 상태']
// 서버 기본값은 등록순(-created_at)이라 통화 일시 정렬을 항상 보낸다
const SORTS: { value: CallSort; label: string }[] = [
  { value: '-call_datetime', label: '최신순' },
  { value: 'call_datetime', label: '오래된순' },
]
const KEYWORD_DELAY_MS = 300

interface SelectProps {
  label: string
  value: string | undefined
  options: { value: string; label: string }[]
  onChange: (v: string) => void
}

function FilterSelect({ label, value = '', options, onChange }: SelectProps) {
  // 선택지를 아직 못 받았거나 목록에 없는 값이어도 지금 걸린 필터는 보여준다
  const all = value && !options.some((o) => o.value === value) ? [...options, { value, label: value }] : options
  return (
    <select aria-label={label} className="field" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{label} 전체</option>
      {all.map((o) => (
        <option key={o.value} value={o.value}>
          {o.label}
        </option>
      ))}
    </select>
  )
}

/** 담당자·고객사 목록 API가 없어서 통계(담당자별·고객사별) 응답의 이름을 쓴다 */
function useNames(by: 'agent' | 'client') {
  const { data } = useBreakdown({}, by)
  const names = (data?.items ?? []).flatMap((i) => i.name ?? [])
  return names.map((n) => ({ value: n, label: n })).sort((a, b) => a.label.localeCompare(b.label))
}

export function CallsPage() {
  const { sp, set } = useUrlParams()
  const { search } = useLocation()
  const page = Math.min(PAGE_MAX, Math.max(1, Math.floor(Number(sp.get('page'))) || 1))
  const urlQ = [...(sp.get('q') ?? '')].slice(0, Q_MAX_LENGTH).join('')
  const params = {
    from: dateParam(sp, 'from'),
    to: dateParam(sp, 'to'),
    category: oneOf(sp, 'category', CATEGORIES),
    agent: sp.get('agent') || undefined,
    client: sp.get('client') || undefined,
    status: oneOf(sp, 'status', STATUSES),
    q: urlQ || undefined,
    stale: sp.get('stale') === 'true' || undefined,
    metadata_incomplete: sp.get('metadata_incomplete') === 'true' || undefined,
    page,
    size: PAGE_SIZE,
    sort: oneOf(sp, 'sort', ['call_datetime']) ?? SORTS[0].value,
  } satisfies CallListParams
  const problem = periodProblem(params)
  const { data, error, isPending, isFetching, isPlaceholderData, refetch } = useCalls(params, !problem)
  const agents = useNames('agent')
  const clients = useNames('client')

  const [keyword, setKeyword] = useState(urlQ)
  // 뒤로 가기·메뉴 클릭으로 주소의 키워드가 바뀌면 입력칸도 따라간다
  useEffect(() => setKeyword((k) => (k.trim() === urlQ ? k : urlQ)), [urlQ])
  // 입력이 잠깐 멈추면 반영한다
  useEffect(() => {
    const next = keyword.trim()
    if (next === urlQ) return
    const t = setTimeout(() => set('q', next), KEYWORD_DELAY_MS)
    return () => clearTimeout(t)
    // urlQ가 바뀌면 위 effect가 keyword를 맞추므로 여기서는 입력에만 반응한다
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [keyword, set])

  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1
  const goPage = (p: number) => set('page', p > 1 ? String(p) : '', { keepPage: true })

  return (
    <section>
      <div className="mb-4 flex items-end justify-between gap-4">
        <h1 className="m-0 text-[22px] font-bold tracking-tight">상담 목록</h1>
        <output aria-label="검색 결과 수" className="num text-muted">
          {data && !error && !problem ? `${data.total}건` : ''}
        </output>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input type="search" aria-label="키워드" placeholder="키워드" maxLength={Q_MAX_LENGTH} className="field w-56 max-w-full" value={keyword} onChange={(e) => setKeyword(e.target.value)} />
        <PeriodInput value={params} onChange={set} />
        <FilterSelect label="유형" value={params.category} onChange={(v) => set('category', v)} options={CATEGORIES.map((c) => ({ value: c, label: categoryLabel(c) }))} />
        <FilterSelect label="담당자" value={params.agent} onChange={(v) => set('agent', v)} options={agents} />
        <FilterSelect label="고객사" value={params.client} onChange={(v) => set('client', v)} options={clients} />
        <FilterSelect label="처리 상태" value={params.status} onChange={(v) => set('status', v)} options={STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))} />
        <label className="inline-flex cursor-pointer items-center gap-1.5 px-1 py-1.5 text-[13px] text-fg-2">
          <input type="checkbox" checked={params.metadata_incomplete ?? false} onChange={(e) => set('metadata_incomplete', e.target.checked ? 'true' : '')} />
          메타데이터 확인 필요
        </label>
        <label className="inline-flex cursor-pointer items-center gap-1.5 px-1 py-1.5 text-[13px] text-fg-2">
          <input type="checkbox" checked={params.stale ?? false} onChange={(e) => set('stale', e.target.checked ? 'true' : '')} />
          정체
        </label>
        <select aria-label="정렬" className="field" value={params.sort} onChange={(e) => set('sort', e.target.value === SORTS[0].value ? '' : e.target.value)}>
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>

      {problem ? (
        <EmptyState title={problem} />
      ) : error ? (
        <ErrorState error={error} onRetry={() => refetch()} retrying={isFetching} />
      ) : (
        <div className="tablewrap">
          <table aria-busy={isPending || isPlaceholderData} className={`min-w-[960px] ${isPlaceholderData ? 'opacity-60' : ''}`}>
            <thead>
              <tr>
                {HEADERS.map((h) => (
                  <th key={h}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {isPending &&
                Array.from({ length: 5 }, (_, i) => (
                  <tr key={i} aria-hidden="true">
                    <td colSpan={HEADERS.length}>
                      <div className="skeleton h-4" />
                    </td>
                  </tr>
                ))}
              {data?.items.map((c) => (
                <tr key={c.id} className="hover:bg-surface-2">
                  <td className="num whitespace-nowrap">{formatDateTime(c.call_datetime)}</td>
                  <td className="whitespace-nowrap">{c.agent_name ?? '-'}</td>
                  <td className="whitespace-nowrap">{c.client_company ?? '-'}</td>
                  <td>
                    <CategoryChip category={c.category} />
                  </td>
                  <td className="max-w-[360px]">
                    <Link to={`/calls/${c.id}`} state={{ from: search }} className="block truncate font-medium text-fg no-underline hover:underline">
                      {c.question_summary ?? <span className="font-normal text-muted">{c.category ? '요약 없음' : '분석 결과 없음'}</span>}
                    </Link>
                  </td>
                  <td className="num">{formatSeconds(c.duration_sec)}</td>
                  <td className="whitespace-nowrap">{actionLabel(c.action_status)}</td>
                  <td>
                    <StatusBadges call={c} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.items.length === 0 && (
            <EmptyState
              title="조건에 맞는 상담이 없어요"
              action={
                page > 1 && (
                  <button type="button" className="btn text-fg" onClick={() => goPage(1)}>
                    첫 페이지로
                  </button>
                )
              }
            />
          )}
        </div>
      )}

      {data && !error && !problem && data.items.length > 0 && pages > 1 && (
        <nav aria-label="페이지" className="mt-3 flex items-center justify-center gap-2.5 text-[13px]">
          <button type="button" className="btn" disabled={page <= 1} onClick={() => goPage(page - 1)}>
            이전
          </button>
          <span className="num text-fg-2">
            {page} / {pages}
          </span>
          <button type="button" className="btn" disabled={page >= pages} onClick={() => goPage(page + 1)}>
            다음
          </button>
        </nav>
      )}
    </section>
  )
}
