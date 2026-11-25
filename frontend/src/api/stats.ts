import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { fetchCalls } from './calls'
import { ApiError, apiBlob, apiGet } from './client'
import { CATEGORIES, type BreakdownItem, type CallListParams, type Granularity, type Period, type StatsSummary, type TrendItem } from './types'

const EXCEL_TIMEOUT_MS = 60_000

export const fetchTrend = (p: Period & { granularity: Granularity }) => apiGet<{ items: TrendItem[] }>('/stats/trend', { ...p })
export const fetchBreakdown = (p: Period & { by: 'agent' | 'client' }) => apiGet<{ items: BreakdownItem[] }>('/stats/breakdown', { ...p })

/** 통계 요약 API(W-09)가 없을 때 목록의 건수와 분류 통계로 센다. 미조치와 정체는 셀 방법이 없다 */
async function countSummary(p: Period): Promise<StatsSummary> {
  const count = async (filter: Partial<CallListParams>) => (await fetchCalls({ ...p, ...filter, page: 1, size: 1 })).total
  const [{ items }, needs_review, failed, metadata_incomplete] = await Promise.all([
    fetchBreakdown({ ...p, by: 'agent' }),
    count({ status: 'NEEDS_REVIEW' }),
    count({ status: 'FAILED' }),
    count({ metadata_incomplete: true }),
  ])
  return {
    total: items.reduce((n, i) => n + i.count, 0),
    by_category: Object.fromEntries(CATEGORIES.map((c) => [c, items.reduce((n, i) => n + i.by_category[c], 0)])),
    action_open: null,
    needs_review,
    metadata_incomplete,
    failed,
    stale: null,
  }
}

export async function fetchSummary(p: Period): Promise<StatsSummary> {
  try {
    return await apiGet<StatsSummary>('/stats/summary', { ...p })
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return countSummary(p)
    throw e
  }
}

export const fetchExcel = (p: Period) => apiBlob('/reports/excel', { ...p }, { timeoutMs: EXCEL_TIMEOUT_MS })

export function useSummary(p: Period) {
  return useQuery({ queryKey: ['stats', 'summary', p], queryFn: () => fetchSummary(p), placeholderData: keepPreviousData })
}

export function useTrend(p: Period, granularity: Granularity) {
  return useQuery({
    queryKey: ['stats', 'trend', p, granularity],
    // 단위를 바꾸는 동안 이전 단위의 막대를 새 단위로 그리지 않도록 결과에 단위를 함께 담는다
    queryFn: async () => ({ granularity, items: (await fetchTrend({ ...p, granularity })).items }),
    placeholderData: keepPreviousData,
  })
}

export function useBreakdown(p: Period, by: 'agent' | 'client') {
  return useQuery({ queryKey: ['stats', 'breakdown', p, by], queryFn: () => fetchBreakdown({ ...p, by }), placeholderData: keepPreviousData })
}
