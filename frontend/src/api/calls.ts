import { keepPreviousData, useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiGet, apiSend, apiUrl } from './client'
import type { CallDetail, CallListItem, CallListParams, CallPatch, CallStatus, Page } from './types'

export const fetchCalls = (p: CallListParams) => apiGet<Page<CallListItem>>('/calls', { ...p })
export const fetchCall = (id: number) => apiGet<CallDetail>(`/calls/${id}`)
export const updateCall = (id: number, patch: CallPatch) => apiSend<CallDetail>('PATCH', `/calls/${id}`, patch)
export const deleteCall = (id: number) => apiSend('DELETE', `/calls/${id}`)
export const retryCall = (id: number) => apiSend('POST', `/calls/${id}/retry`)
export const audioUrl = (id: number) => apiUrl(`/calls/${id}/audio`)

export function useCalls(p: CallListParams) {
  return useQuery({ queryKey: ['calls', p], queryFn: () => fetchCalls(p), placeholderData: keepPreviousData })
}

export function useCall(id: number, enabled = true) {
  return useQuery({ queryKey: ['call', id], queryFn: () => fetchCall(id), enabled })
}

/** 처리 중이거나 실패한 건. 목록 API는 상태를 하나씩만 받으므로 상태마다 조회한다 */
export const MONITOR_STATUSES: CallStatus[] = ['REGISTERED', 'QUEUED', 'STT_DONE', 'RETRY_REQUESTED', 'FAILED']
export const MONITOR_SIZE = 100
const POLL_MS = 5_000

export function useMonitor() {
  return useQueries({
    queries: MONITOR_STATUSES.map((status) => {
      const p: CallListParams = { status, page: 1, size: MONITOR_SIZE }
      return { queryKey: ['calls', p], queryFn: () => fetchCalls(p), refetchInterval: POLL_MS, staleTime: 0 }
    }),
  })
}

function useInvalidate() {
  const qc = useQueryClient()
  return async (id?: number) => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['calls'] }),
      qc.invalidateQueries({ queryKey: ['stats'] }),
      id === undefined ? undefined : qc.invalidateQueries({ queryKey: ['call', id] }),
    ])
  }
}

export function useUpdateCall(id: number) {
  const invalidate = useInvalidate()
  return useMutation({ mutationFn: (patch: CallPatch) => updateCall(id, patch), onSuccess: () => invalidate(id) })
}

export function useRetryCall() {
  const invalidate = useInvalidate()
  // 실패(409 등)해도 화면의 상태가 낡았다는 뜻이므로 다시 불러온다
  return useMutation({ mutationFn: retryCall, onSettled: (_data, _err, id) => invalidate(id) })
}

export function useDeleteCall() {
  const invalidate = useInvalidate()
  // 지운 상담의 상세는 다시 조회하지 않는다 (404)
  return useMutation({ mutationFn: deleteCall, onSuccess: () => invalidate() })
}
