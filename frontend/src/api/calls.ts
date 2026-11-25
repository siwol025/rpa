import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiGet, apiSend, apiUrl, hasValidationError, toQueryString } from './client'
import { PAGE_SIZE_MAX, type CallDetail, type CallListItem, type CallListParams, type CallPatch, type Page, type RetryResult } from './types'

export const fetchCalls = (p: CallListParams) => apiGet<Page<CallListItem>>('/calls', { ...p })
export const fetchCall = (id: number) => apiGet<CallDetail>(`/calls/${id}`)
export const updateCall = (id: number, patch: CallPatch) => apiSend<CallDetail>('PATCH', `/calls/${id}`, patch)
export const deleteCall = (id: number, editor?: string) => apiSend('DELETE', `/calls/${id}${toQueryString({ editor })}`)
export const retryCall = (id: number) => apiSend<RetryResult>('POST', `/calls/${id}/retry`)
export const audioUrl = (id: number) => apiUrl(`/calls/${id}/audio`)

export function useCalls(p: CallListParams, enabled = true) {
  return useQuery({ queryKey: ['calls', p], queryFn: () => fetchCalls(p), placeholderData: keepPreviousData, enabled })
}

export function useCall(id: number, enabled = true) {
  return useQuery({ queryKey: ['call', id], queryFn: () => fetchCall(id), enabled })
}

const POLL_MS = 5_000
const MONITOR_PARAMS: CallListParams = {
  status: ['REGISTERED', 'QUEUED', 'STT_DONE', 'RETRY_REQUESTED', 'FAILED'],
  page: 1,
  size: PAGE_SIZE_MAX,
  sort: '-status_changed_at',
}

/** 처리 중이거나 실패한 건, 최근에 상태가 바뀐 순 */
export function useMonitor() {
  return useQuery({ queryKey: ['calls', MONITOR_PARAMS], queryFn: () => fetchCalls(MONITOR_PARAMS), refetchInterval: POLL_MS, staleTime: 0 })
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
  return useMutation({
    mutationFn: (patch: CallPatch) => updateCall(id, patch),
    onSuccess: () => invalidate(id),
    // 409는 화면의 상태가 낡았다는 뜻이므로 다시 불러온다
    onError: (e) => (e instanceof ApiError && e.status === 409 ? invalidate(id) : undefined),
  })
}

/** 서버 문구만으로는 무엇을 고칠지 알기 어려운 오류를 풀어 쓴다 */
export function updateProblem(e: Error): string {
  if (hasValidationError(e, 'datetime_range')) return '통화 일시는 2000년부터 2100년까지 입력할 수 있어요'
  return e.message
}

export function useRetryCall() {
  const invalidate = useInvalidate()
  // 실패(409 등)해도 화면의 상태가 낡았다는 뜻이므로 다시 불러온다
  return useMutation({ mutationFn: retryCall, onSettled: (_data, _err, id) => invalidate(id) })
}

export function useDeleteCall() {
  const invalidate = useInvalidate()
  // 지운 상담의 상세는 다시 조회하지 않는다 (404)
  return useMutation({ mutationFn: ({ id, editor }: { id: number; editor?: string }) => deleteCall(id, editor), onSuccess: () => invalidate() })
}
