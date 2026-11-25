import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { apiBlob, apiGet } from './client'
import type { BreakdownItem, Granularity, Period, StatsSummary, TrendItem } from './types'

const EXCEL_TIMEOUT_MS = 60_000

export const fetchSummary = (p: Period) => apiGet<StatsSummary>('/stats/summary', { ...p })
export const fetchTrend = (p: Period & { granularity: Granularity }) => apiGet<{ items: TrendItem[] }>('/stats/trend', { ...p })
export const fetchBreakdown = (p: Period & { by: 'agent' | 'client' }) => apiGet<{ items: BreakdownItem[] }>('/stats/breakdown', { ...p })
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
